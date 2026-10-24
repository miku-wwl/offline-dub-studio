import shutil

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.subtitles import caption_cues, detect_boxes, filter_temporal_regions, readable_caption_margin, redact_video, write_ass, write_srt


def test_ass_keeps_times_and_escapes_markup(tmp_path):
    path = tmp_path / "captions.ass"
    write_ass(
        [{"id": "x", "start": 1.234, "end": 2.8, "translated_text": "Hello {quietly}, world"}],
        path,
        font_size=42,
        margin_v=50,
    )
    text = path.read_text(encoding="utf-8-sig")
    assert "0:00:01.23,0:00:02.80" in text
    assert r"Hello \{quietly\}, world" in text
    assert "Arial,42" in text


def test_manual_mask_creates_a_reviewable_repair_preview(tmp_path):
    source=tmp_path / "synthetic.mp4"
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"mp4v"),10,(160,90))
    assert writer.isOpened()
    for _ in range(10):
        frame=np.full((90,160,3),180,dtype=np.uint8)
        cv2.rectangle(frame,(20,65),(140,82),(10,10,10),-1)
        writer.write(frame)
    writer.release()
    destination=tmp_path / "repaired.mp4"
    preview=tmp_path / "previews"
    result=redact_video(source,destination,[{"start":0,"end":1,"boxes":[(18,63,125,22)]}],preview,"fast")
    assert result["mask_applied"] is True
    assert result["frames_processed"]==10
    assert destination.with_suffix(".mkv").is_file()
    assert (preview / "subtitle-original.png").is_file()
    assert (preview / "subtitle-mask.png").is_file()
    assert (preview / "subtitle-repaired.png").is_file()


def test_no_subtitles_reuses_source_without_encoding(tmp_path):
    source=tmp_path / "plain.avi"
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"FFV1"),10,(160,90))
    writer.write(np.full((90,160,3),120,dtype=np.uint8))
    writer.release()
    destination=tmp_path / "unused.mp4"
    report=redact_video(source,destination,[],tmp_path / "preview")
    assert report["output_video"]==str(source)
    assert report["frames_processed"]==0
    assert report["mask_applied"] is False
    assert not destination.exists()


@pytest.mark.skipif(not shutil.which("tesseract"),reason="Tesseract unavailable")
def test_real_ocr_temporal_masks_leave_absent_subtitles_and_scene_change_unchanged(tmp_path,monkeypatch):
    from pathlib import Path
    font_path=Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not font_path.exists():
        pytest.skip("Noto CJK font unavailable")
    fps=5
    source=tmp_path / "temporal.avi"
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"FFV1"),fps,(640,360))
    assert writer.isOpened()
    font=ImageFont.truetype(str(font_path),32)
    for i in range(30):
        t=i/fps
        frame=np.full((360,640,3),(60,80,100) if t<3.8 else (100,60,40),dtype=np.uint8)
        # A moving object crosses the same region while there is no subtitle.
        cv2.rectangle(frame,(i*13,302),(i*13+30,340),(0,100,240),-1)
        image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        if .8<=t<1.8 or 4.8<=t<5.8:
            ImageDraw.Draw(image).text((220,292),"你好世界" if t<2 else "这是测试",font=font,
                                      fill="white",stroke_width=2,stroke_fill="black")
        writer.write(cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR))
    writer.release()
    progress=[]
    regions,warnings=detect_boxes(source,[(180,288,280,65)],tmp_path / "ocr.json",progress=lambda done,total:progress.append((done,total)))
    assert progress[-1]==(30,30)
    assert regions, warnings
    assert any(r["start"]<=1<r["end"] for r in regions)
    assert any(r["start"]<=5<r["end"] for r in regions)
    assert not any(r["start"]<=3<r["end"] for r in regions)
    import app.subtitles as module
    def no_second_ocr(*_args):
        raise AssertionError("A hash-identical OCR cache must be reused")
    monkeypatch.setattr(module,"_frame_boxes",no_second_ocr)
    assert detect_boxes(source,[(180,288,280,65)],tmp_path / "ocr.json")[0]==regions
    report=redact_video(source,tmp_path / "clean.mkv",regions,tmp_path / "preview")
    original=cv2.VideoCapture(str(source))
    repaired=cv2.VideoCapture(report["output_video"])
    changed=0
    for i in range(30):
        ok,frame=original.read()
        ok2,clean=repaired.read()
        assert ok and ok2
        active=any(r["start_frame"]<=i<r["end_frame"] for r in regions)
        if not active:
            assert np.array_equal(frame,clean), f"Unmasked frame {i} was altered"
        else:
            changed+=int(not np.array_equal(frame,clean))
    original.release()
    repaired.release()
    assert changed>0
    assert report["fps"]==fps and report["width"]==640


def test_srt_preserves_intervals_and_literal_text(tmp_path):
    path=tmp_path / "captions.srt"
    write_srt([{"start":1.234,"end":2.8,"translated_text":"Hello {world}"}],path)
    assert "00:00:01,234 --> 00:00:02,800" in path.read_text(encoding="utf-8-sig")
    assert "Hello {world}" in path.read_text(encoding="utf-8-sig")


def test_long_caption_splits_into_readable_continuous_cues():
    cues=caption_cues([{"start":1,"end":9,"translated_text":"A readable caption with enough words. "*8}])
    assert len(cues)>1
    assert cues[0]["start"]==1 and cues[-1]["end"]==9
    assert all(len(cue["text"].splitlines())<=2 for cue in cues)
    assert all(max(map(len,cue["text"].splitlines()))<=54 for cue in cues)
    assert all(left["end"]==right["start"] for left,right in zip(cues,cues[1:]))


@pytest.mark.parametrize("start,end",[(-1,1),(2,1),(1,1),(float("nan"),2)])
def test_invalid_subtitle_intervals_are_rejected(start,end):
    with pytest.raises(ValueError,match="Invalid subtitle interval"):
        caption_cues([{"start":start,"end":end,"translated_text":"Invalid"}])


def test_ocr_thread_limit_does_not_leak_into_model_inference(tmp_path,monkeypatch):
    import os
    import app.subtitles as module
    source=tmp_path / "fixture.avi"
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"FFV1"),5,(160,90))
    writer.write(np.zeros((90,160,3),dtype=np.uint8))
    writer.release()
    monkeypatch.setattr(module.shutil,"which",lambda _name:"tesseract")
    monkeypatch.setenv("OMP_THREAD_LIMIT","8")
    def fail(_frame,_manual):
        assert os.environ["OMP_THREAD_LIMIT"]=="1"
        raise RuntimeError("OCR failed")
    monkeypatch.setattr(module,"_frame_boxes",fail)
    with pytest.raises(RuntimeError,match="OCR failed"):
        detect_boxes(source,[],tmp_path / "ocr.json")
    assert os.environ["OMP_THREAD_LIMIT"]=="8"


def test_boundary_blob_and_isolated_ocr_guess_cannot_damage_unsubtitled_frame():
    raw=[{"start":1,"end":1.04,"start_frame":25,"end_frame":26,"boxes":[(1650,960,50,85)]},
         {"start":2,"end":2.04,"start_frame":50,"end_frame":51,"boxes":[(500,980,100,50)]},
         {"start":3,"end":3.12,"start_frame":75,"end_frame":78,"boxes":[(700,980,160,50)]}]
    result=filter_temporal_regions(raw,[(220,960,1480,85)],100,25)
    assert len(result)==1
    assert result[0]["start_frame"]==75 and result[0]["end_frame"]==78


def test_english_captions_clear_the_source_band_and_preserve_higher_user_margin():
    regions=[{"boxes":[(630,973,140,68)]}]
    assert readable_caption_margin(1080,regions,40)==119
    assert readable_caption_margin(1080,regions,180)==180
    assert readable_caption_margin(1080,[],40)==40
