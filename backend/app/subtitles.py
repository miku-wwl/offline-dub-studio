from __future__ import annotations

import json
import shutil
from pathlib import Path

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


def write_ass(segments: list[dict], output: Path, font_size: int = 44, margin_v: int = 44) -> None:
    lines = ["[Script Info]", "ScriptType: v4.00+", "WrapStyle: 2", "ScaledBorderAndShadow: yes",
             "PlayResX: 1920", "PlayResY: 1080", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
             "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00111111,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,70,70,{margin_v},1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for seg in sorted(segments, key=lambda s: float(s["start"])):
        text = _escape(str(seg.get("translated_text", "")).strip())
        if not text:
            continue
        lines.append(f"Dialogue: 0,{_ts(float(seg['start']))},{_ts(float(seg['end']))},Default,,0,0,0,,{text}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def detect_boxes(video_path: Path, manual: list[tuple[int, int, int, int]], trace_path: Path) -> tuple[list[tuple[int,int,int,int]], list[str]]:
    boxes = [tuple(map(int, box)) for box in manual]
    warnings: list[str] = []
    if shutil.which(settings.tesseract):
        try:
            import pytesseract
            from pytesseract import Output
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            interval = max(1, round(fps))
            samples = []
            frame_no = 0
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_no % interval == 0:
                    h, w = frame.shape[:2]
                    crop_y = int(h * 0.55)
                    data = pytesseract.image_to_data(frame[crop_y:, :], lang="chi_sim+eng", config="--psm 6", output_type=Output.DICT)
                    current = []
                    for i, raw in enumerate(data.get("text", [])):
                        word = raw.strip()
                        try:
                            confidence = float(data["conf"][i])
                        except (ValueError, TypeError):
                            confidence = -1
                        if confidence < 35 or not any("\u3400" <= c <= "\u9fff" for c in word):
                            continue
                        x, y = int(data["left"][i]), int(data["top"][i]) + crop_y
                        bw, bh = int(data["width"][i]), int(data["height"][i])
                        if y > h * 0.55:
                            current.append((max(0,x-6), max(0,y-6), min(w,bw+12), min(h,bh+12)))
                    if current:
                        boxes.extend(current)
                        samples.append({"time": round(frame_no / fps, 2), "boxes": current})
                        original_preview=trace_path.parent / "subtitle-original.png"
                        if not original_preview.exists():
                            cv2.imwrite(str(original_preview), frame)
                frame_no += 1
            cap.release()
            trace_path.write_text(json.dumps({"sampled_regions": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
            if not samples:
                warnings.append("OCR found no high-confidence Chinese text in the lower video region; review the preview or add a manual region.")
        except Exception as exc:
            warnings.append(f"Chinese OCR could not run ({type(exc).__name__}); use manual subtitle regions.")
    else:
        warnings.append("Tesseract is unavailable; no automatic hard-subtitle regions were detected.")
    # Merge overlapping/touching detections so words in the same subtitle line form one stable mask.
    merged: list[tuple[int,int,int,int]] = []
    for x,y,w,h in sorted(boxes, key=lambda b:(b[1],b[0])):
        match = next((i for i,(mx,my,mw,mh) in enumerate(merged)
                      if abs(y-my) < max(h,mh)*1.5 and x <= mx+mw+80 and mx <= x+w+80), None)
        if match is None:
            merged.append((x,y,w,h))
        else:
            mx,my,mw,mh = merged[match]
            left, top, right, bottom = min(x,mx), min(y,my), max(x+w,mx+mw), max(y+h,my+mh)
            merged[match] = (left,top,right-left,bottom-top)
    return merged, warnings


def redact_video(source: Path, destination: Path, regions: list[tuple[int,int,int,int]], preview_dir: Path, mode: str="fast") -> dict:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not open the video for subtitle processing")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width,height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("OpenCV could not create an inpainted preview video")
    mask = np.zeros((height,width), dtype=np.uint8)
    for x,y,w,h in regions:
        x0,y0 = max(0,x),max(0,y)
        x1,y1 = min(width,x+w),min(height,y+h)
        if x1>x0 and y1>y0:
            cv2.rectangle(mask,(x0,y0),(x1,y1),255,-1)
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_saved = False
    sample = cv2.imread(str(preview_dir / "subtitle-original.png"))
    if sample is not None:
        sample_mask=mask
        sample_height,sample_width=sample.shape[:2]
        if (sample_width,sample_height)!=(width,height):
            sample_mask=cv2.resize(mask,(sample_width,sample_height),interpolation=cv2.INTER_NEAREST)
        marked=sample.copy()
        marked[sample_mask>0]=(0,0,255)
        cv2.imwrite(str(preview_dir / "subtitle-mask.png"),marked)
        algorithm=cv2.INPAINT_NS if mode=="balanced" else cv2.INPAINT_TELEA
        radius=7 if mode=="balanced" else 5
        repaired_sample=cv2.inpaint(sample,sample_mask,radius,algorithm) if sample_mask.any() else sample
        cv2.imwrite(str(preview_dir / "subtitle-repaired.png"),repaired_sample)
        preview_saved=True
    frames = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if not preview_saved:
            cv2.imwrite(str(preview_dir / "subtitle-original.png"), frame)
            masked = frame.copy()
            masked[mask > 0] = (0,0,255)
            cv2.imwrite(str(preview_dir / "subtitle-mask.png"), masked)
            algorithm=cv2.INPAINT_NS if mode=="balanced" else cv2.INPAINT_TELEA
            radius=7 if mode=="balanced" else 5
            repaired = cv2.inpaint(frame, mask, radius, algorithm) if mask.any() else frame
            cv2.imwrite(str(preview_dir / "subtitle-repaired.png"), repaired)
            preview_saved = True
        algorithm=cv2.INPAINT_NS if mode=="balanced" else cv2.INPAINT_TELEA
        radius=7 if mode=="balanced" else 5
        clean = cv2.inpaint(frame, mask, radius, algorithm) if mask.any() else frame
        writer.write(clean)
        frames += 1
    cap.release()
    writer.release()
    technique="opencv-navier-stokes" if mode=="balanced" else "opencv-telea"
    return {"width":width,"height":height,"fps":fps,"frames_processed":frames,
            "regions":regions,"mask_applied":bool(mask.any()),"technique":technique}
