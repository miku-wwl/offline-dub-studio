from __future__ import annotations

import json
import hashlib
import math
import os
import shutil
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .config import settings


def _ts(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hour, rem = divmod(total_ms, 3_600_000)
    minute, rem = divmod(rem, 60_000)
    second, ms = divmod(rem, 1000)
    return f"{hour}:{minute:02d}:{second:02d}.{ms // 10:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", r"\N")


def caption_cues(segments: list[dict]) -> list[dict]:
    cues=[]
    for seg in sorted(segments,key=lambda row:float(row["start"])):
        start,end=float(seg["start"]),float(seg["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:
            raise ValueError(f"Invalid subtitle interval for {seg.get('id','unknown')}")
        text=" ".join(str(seg.get('short_translation') or seg.get("translated_text","")).split())
        if not text:
            continue
        lines=textwrap.wrap(text,width=54,break_long_words=True,break_on_hyphens=False)
        groups=["\n".join(lines[index:index+2]) for index in range(0,len(lines),2)]
        weights=[len(group) for group in groups]
        total=sum(weights)
        elapsed=0
        for group,weight in zip(groups,weights):
            cue_start=start+(end-start)*elapsed/total
            elapsed+=weight
            cues.append({"start":cue_start,"end":start+(end-start)*elapsed/total,"text":group})
    return cues


def write_ass(segments: list[dict], output: Path, font_size: int = 44, margin_v: int = 44) -> None:
    lines = ["[Script Info]", "ScriptType: v4.00+", "WrapStyle: 2", "ScaledBorderAndShadow: yes",
             "PlayResX: 1920", "PlayResY: 1080", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
             "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00111111,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,70,70,{margin_v},1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for cue in caption_cues(segments):
        text=_escape(cue["text"])
        lines.append(f"Dialogue: 0,{_ts(cue['start'])},{_ts(cue['end'])},Default,,0,0,0,,{text}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def write_srt(segments: list[dict], output: Path) -> None:
    def stamp(value):
        ms=max(0,round(float(value)*1000))
        seconds,ms=divmod(ms,1000)
        minutes,seconds=divmod(seconds,60)
        hours,minutes=divmod(minutes,60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"
    rows=[]
    for cue in caption_cues(segments):
        rows.append(f"{len(rows)+1}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}\n")
    output.write_text("\n".join(rows),encoding="utf-8-sig")


def readable_caption_margin(height:int,regions:list[dict],requested:int) -> int:
    if not regions or height<=0:
        return requested
    top=min(box[1] for row in regions for box in row["boxes"])
    # ASS coordinates use PlayResY=1080 regardless of source resolution.
    return max(requested,math.ceil((height-top)*1080/height+12))


def _frame_boxes(frame, manual):
    """Manual rectangles constrain the search; they do not force a permanent mask."""
    import pytesseract
    from pytesseract import Output
    height,width=frame.shape[:2]
    search=manual or [(int(width*.1),int(height*.8),int(width*.8),height-int(height*.8))]
    boxes=[]
    for rx,ry,rw,rh in search:
        x0,y0=max(0,rx),max(0,ry)
        x1,y1=min(width,rx+rw),min(height,ry+rh)
        if x1<=x0 or y1<=y0:
            continue
        crop=cv2.cvtColor(frame[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
        # White, outlined dialogue captions remain readable over moving scenery.
        # Colour/stylized captions require review; do not erase uncertain regions.
        crop=cv2.threshold(crop,200,255,cv2.THRESH_BINARY_INV)[1]
        data=pytesseract.image_to_data(crop,lang="chi_sim+eng",
                                       config="--psm 6",output_type=Output.DICT)
        for i,raw in enumerate(data.get("text",[])):
            try:
                confidence=float(data["conf"][i])
            except (ValueError,TypeError):
                continue
            if confidence<35 or not any("\u3400"<=char<="\u9fff" for char in raw):
                continue
            x=max(x0,int(data["left"][i])+x0-5)
            y=max(y0,int(data["top"][i])+y0-5)
            right=min(x1,int(data["left"][i])+x0+int(data["width"][i])+5)
            bottom=min(y1,int(data["top"][i])+y0+int(data["height"][i])+5)
            boxes.append((x,y,right-x,bottom-y))
    return boxes


def _source_digest(path:Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda:source.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def filter_temporal_regions(intervals:list[dict],search:list,total:int,fps:float) -> list[dict]:
    """Discard boundary blobs/isolated guesses; never invent a missing detection."""
    frames={}
    for row in intervals:
        boxes=[]
        for x,y,w,h in row["boxes"]:
            inside=any(x>rx and y>ry and x+w<rx+rw and y+h<ry+rh
                       and h<rh*.9 for rx,ry,rw,rh in search)
            if inside and w>=3 and h>=6:
                boxes.append(tuple([x,y,w,h]))
        # At least a pair of glyphs or a wide word is needed for a reliable line.
        if len(boxes)<2 and not any(w>h*1.3 for _x,_y,w,h in boxes):
            continue
        for frame in range(int(row.get("start_frame",round(row["start"]*fps))),
                           min(total,int(row.get("end_frame",round(row["end"]*fps))))):
            frames[frame]=boxes
    result=[]
    def nearby(left,right):
        return any(abs(y-ny)<max(h,nh)*.3 and x<nx+nw+8 and nx<x+w+8
                   for x,y,w,h in left for nx,ny,nw,nh in right)
    for frame,boxes in sorted(frames.items()):
        if not any(nearby(boxes,frames.get(neighbor,[])) for neighbor in (frame-1,frame+1)):
            continue
        if result and result[-1]["end_frame"]==frame and result[-1]["boxes"]==boxes:
            result[-1]["end_frame"]=frame+1
            result[-1]["end"]=(frame+1)/fps
        else:
            result.append({"start":frame/fps,"end":(frame+1)/fps,"start_frame":frame,"end_frame":frame+1,"boxes":boxes})
    return result


def detect_boxes(video_path: Path, manual: list[tuple[int,int,int,int]], trace_path: Path,
                 checkpoint: Callable[[],None] | None=None,
                 progress: Callable[[int,int],None] | None=None) -> tuple[list[dict],list[str]]:
    """OCR each frame independently: no mask survives a subtitle or scene change.

    A bounded batch keeps decoded frames out of whole-video memory. Each result
    covers precisely one frame; only identical adjacent results are coalesced.
    """
    intervals=[]
    warnings=[]
    signature=_source_digest(video_path)
    metadata_cap=cv2.VideoCapture(str(video_path))
    width=int(metadata_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height=int(metadata_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps=metadata_cap.get(cv2.CAP_PROP_FPS) or 25.0
    total=int(metadata_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    metadata_cap.release()
    search=manual or [(int(width*.1),int(height*.8),int(width*.8),height-int(height*.8))]
    cached={}
    if trace_path.exists():
        try:
            cached=json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):
            pass
    cache_valid=(cached.get("source_sha256")==signature
                 and cached.get("strategy")=="per-frame-white-caption-ocr"
                 and cached.get("manual_search_regions")==[list(box) for box in manual])
    if cache_valid:
        raw=cached.get("raw_intervals",cached.get("intervals",[]))
        intervals=filter_temporal_regions(raw,search,total,fps)
        cached.update({"raw_intervals":raw,"intervals":intervals,"cache_reused":True,
                       "filter_strategy":"boundary-and-adjacent-frame-validation"})
        trace_path.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding="utf-8")
        if progress:
            progress(total,total)
        return intervals,warnings
    if not shutil.which(settings.tesseract):
        warnings.append("Tesseract is unavailable; no automatic subtitle mask was applied.")
    else:
        cap=cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError("OpenCV could not open the video for subtitle detection")
        fps=cap.get(cv2.CAP_PROP_FPS) or 25.0
        total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_no=0
        old_thread_limit=os.environ.get("OMP_THREAD_LIMIT")
        os.environ["OMP_THREAD_LIMIT"]="1"
        try:
            # Tesseract itself may use OpenMP. Keep a small, bounded pool.
            with ThreadPoolExecutor(max_workers=2) as pool:
                while True:
                    if checkpoint:
                        checkpoint()
                    batch=[]
                    for _ in range(4):
                        ok,frame=cap.read()
                        if not ok:
                            break
                        batch.append(frame)
                    if not batch:
                        break
                    results=pool.map(lambda frame:_frame_boxes(frame,manual),batch)
                    for boxes in results:
                        if boxes:
                            if intervals and intervals[-1]["end_frame"]==frame_no and intervals[-1]["boxes"]==boxes:
                                intervals[-1]["end_frame"]=frame_no+1
                                intervals[-1]["end"]=(frame_no+1)/fps
                            else:
                                intervals.append({"start":frame_no/fps,"end":(frame_no+1)/fps,
                                                  "start_frame":frame_no,"end_frame":frame_no+1,"boxes":boxes})
                        frame_no+=1
                    if progress:
                        progress(frame_no,total)
        except Exception as exc:
            # Cancellation must propagate, never become an apparent successful OCR.
            from .pipeline import JobCancelled
            if isinstance(exc,JobCancelled):
                raise
            raise RuntimeError(f"Subtitle OCR failed ({type(exc).__name__}): {exc}. Check Tesseract chi_sim data or choose no hard-subtitle processing.") from exc
        finally:
            cap.release()
            if old_thread_limit is None:
                os.environ.pop("OMP_THREAD_LIMIT",None)
            else:
                os.environ["OMP_THREAD_LIMIT"]=old_thread_limit
        if not intervals:
            warnings.append("OCR found no high-confidence Chinese subtitles in the search region; review the source preview.")
    raw=intervals
    intervals=filter_temporal_regions(raw,search,total,fps)
    trace_path.write_text(json.dumps({"strategy":"per-frame-white-caption-ocr","manual_search_regions":manual,
                                      "source_sha256":signature,"raw_intervals":raw,"intervals":intervals,
                                      "cache_reused":False,"filter_strategy":"boundary-and-adjacent-frame-validation"},ensure_ascii=False,indent=2),encoding="utf-8")
    return intervals,warnings


def active_boxes(intervals: list[dict], frame_no: int, fps: float) -> list[tuple]:
    return [box for interval in intervals
            if int(interval.get("start_frame",round(interval["start"]*fps)))<=frame_no
            <int(interval.get("end_frame",round(interval["end"]*fps)))
            for box in interval["boxes"]]


def _inpaint_roi(frame,mask,radius,algorithm):
    x,y,w,h=cv2.boundingRect(mask)
    pad=max(16,radius*3)
    height,width=frame.shape[:2]
    x0,y0=max(0,x-pad),max(0,y-pad)
    x1,y1=min(width,x+w+pad),min(height,y+h+pad)
    repaired=frame.copy()
    repaired[y0:y1,x0:x1]=cv2.inpaint(frame[y0:y1,x0:x1],mask[y0:y1,x0:x1],radius,algorithm)
    return repaired


def redact_video(source: Path, destination: Path, regions: list[dict], preview_dir: Path,
                 mode: str="fast",checkpoint: Callable[[],None] | None=None,
                 progress: Callable[[int,int],None] | None=None) -> dict:
    cap=cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not open the video for subtitle processing")
    width,height=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps=cap.get(cv2.CAP_PROP_FPS) or 25.0
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if regions and not isinstance(regions[0],dict):
        cap.release()
        raise ValueError("Subtitle masks require timed intervals. Pass manual rectangles to detect_boxes() as search regions.")
    preview_dir.mkdir(parents=True,exist_ok=True)
    frames=masked_frames=0
    writer=None
    if regions:
        # FFV1 is lossless: unmasked decoded frames remain pixel-identical before
        # the single final H.264 encode. MKV is required for this intermediate.
        destination=destination.with_suffix(".mkv")
        writer=cv2.VideoWriter(str(destination),cv2.VideoWriter_fourcc(*"FFV1"),fps,(width,height))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError("OpenCV could not create the lossless subtitle intermediate")
    first=None
    preview_saved=False
    try:
        while True:
            if checkpoint and frames%10==0:
                checkpoint()
            ok,frame=cap.read()
            if not ok:
                break
            if first is None:
                first=frame.copy()
            if not regions:
                break  # No masks: use the original video without processing it.
            mask=np.zeros((height,width),dtype=np.uint8)
            for x,y,w,h in active_boxes(regions,frames,fps):
                x0,y0=max(0,x),max(0,y)
                x1,y1=min(width,x+w),min(height,y+h)
                if x1>x0 and y1>y0:
                    mask[y0:y1,x0:x1]=255
            algorithm=cv2.INPAINT_NS if mode=="balanced" else cv2.INPAINT_TELEA
            repaired=_inpaint_roi(frame,mask,7 if mode=="balanced" else 5,algorithm) if mask.any() else frame
            if mask.any():
                masked_frames+=1
                if not preview_saved:
                    marked=frame.copy()
                    marked[mask>0]=(0,0,255)
                    for name,value in [("original",frame),("mask",marked),("repaired",repaired)]:
                        cv2.imwrite(str(preview_dir / f"subtitle-{name}.png"),value)
                    preview_saved=True
            writer.write(repaired)
            frames+=1
            if progress and (frames%25==0 or frames==total):
                progress(frames,total)
    finally:
        cap.release()
        if writer:
            writer.release()
    if not preview_saved and first is not None:
        for name in ("original","mask","repaired"):
            cv2.imwrite(str(preview_dir / f"subtitle-{name}.png"),first)
    return {"width":width,"height":height,"fps":fps,"frames_processed":frames,
            "masked_frames":masked_frames,"unmasked_frames":frames-masked_frames,
            "regions":regions,"mask_applied":bool(masked_frames),
            "output_video":str(destination if writer else source),
            "technique":"opencv-navier-stokes" if mode=="balanced" else "opencv-telea"}
