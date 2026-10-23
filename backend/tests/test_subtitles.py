import cv2
import numpy as np

from app.subtitles import redact_video, write_ass


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
    result=redact_video(source,destination,[(18,63,125,22)],preview,"fast")
    assert result["mask_applied"] is True
    assert result["frames_processed"]==10
    assert destination.is_file()
    assert (preview / "subtitle-original.png").is_file()
    assert (preview / "subtitle-mask.png").is_file()
    assert (preview / "subtitle-repaired.png").is_file()
