"""Create a short non-copyrighted structural fixture; this is not movie-quality evidence."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def run(args: list[str]) -> None:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit((result.stderr or result.stdout)[-2000:])


def main() -> int:
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "/data/inbox/synthetic-mandarin-30s.mp4")
    destination.parent.mkdir(parents=True, exist_ok=True)
    font = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not font.is_file():
        raise SystemExit(f"Fixture font is missing: {font}")
    with tempfile.TemporaryDirectory(prefix="dub-studio-fixture-") as directory:
        root = Path(directory)
        first, second, audio = root / "speaker-a.wav", root / "speaker-b.wav", root / "mixed.wav"
        run(["espeak-ng", "-v", "zh", "-s", "125", "-p", "38", "-w", str(first),
             "你好，我叫小林。今天我们来测试本地中文配音。"])
        run(["espeak-ng", "-v", "zh", "-s", "132", "-p", "72", "-w", str(second),
             "天气很好，我们检查字幕和背景声音。"])
        run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(first),
             "-stream_loop", "-1", "-i", str(second), "-f", "lavfi", "-i", "sine=frequency=196:sample_rate=44100",
             "-filter_complex",
             "[0:a]atrim=duration=15,adelay=0:all=1[a];"
             "[1:a]atrim=duration=15,adelay=15000:all=1[b];"
             "[2:a]volume=0.025[m];[a][b][m]amix=inputs=3:duration=longest:normalize=0,atrim=duration=30[out]",
             "-map", "[out]", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(audio)])
        text = "你好，今天是离线字幕测试。"
        vf = ("drawbox=x=0:y=285:w=iw:h=55:color=black@0.7:t=fill,"
              f"drawtext=fontfile={font}:text='{text}':fontcolor=white:fontsize=30:x=(w-text_w)/2:y=h-48")
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x43524a:s=640x360:r=15:d=30",
             "-i", str(audio), "-vf", vf, "-map", "0:v:0", "-map", "1:a:0", "-t", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destination)])
    print(f"Created synthetic 30-second Mandarin fixture: {destination}")
    print("It contains two espeak-ng Chinese voices, a sine-wave bed, and burned Chinese text; it is structural test media only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
