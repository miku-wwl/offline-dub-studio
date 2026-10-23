from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import effective_cpu_count, settings


MODEL_PACKS = {
    "asr-tiny": {
        "name": "Faster-Whisper Tiny (CPU Lite)", "kind": "asr", "repo": "Systran/faster-whisper-tiny",
        "revision": "d90ca5fe260221311c53c58e660288d3deb8d356", "license": "MIT",
        "approx_size": "75 MB", "access": "public", "path": "asr/tiny",
    },
    "asr-small": {
        "name": "Faster-Whisper Small (Balanced)", "kind": "asr", "repo": "Systran/faster-whisper-small",
        "revision": "536b0662742c02347bc0e980a01041f333bce120", "license": "MIT",
        "approx_size": "500 MB", "access": "public", "path": "asr/small",
    },
    "translation-zh-en": {
        "name": "Argos Chinese to English", "kind": "translation", "repo": "argosopentech/argospm-index",
        "revision": "translate-zh_en 1.9", "license": "package metadata", "approx_size": "50-200 MB",
        "access": "public language package", "path": "argos",
    },
    "tts-kokoro-en": {
        "name": "Kokoro 82M English voices", "kind": "tts", "repo": "hexgrad/Kokoro-82M",
        "revision": "f3ff3571791e39611d31c381e3a41a3af07b4987", "license": "Apache-2.0",
        "approx_size": "363 MB", "access": "public", "path": "huggingface",
    },
    "separation-htdemucs": {
        "name": "Demucs htdemucs vocals split", "kind": "separation", "repo": "facebookresearch/demucs",
        "revision": "4.0.1", "license": "MIT code; model terms follow upstream", "approx_size": "80-300 MB",
        "access": "public", "path": "torch",
    },
}


def _manifest_path(pack_id: str) -> Path:
    return settings.models_dir / MODEL_PACKS[pack_id]["path"] / "pack-manifest.json"


def list_packs() -> list[dict[str, Any]]:
    result = []
    for pack_id, meta in MODEL_PACKS.items():
        manifest_path = _manifest_path(pack_id)
        manifest = {}
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
        ready = _ready(pack_id, manifest)
        result.append({"id":pack_id, **meta, "ready":ready,
                       "initialized_at":manifest.get("initialized_at"),
                       "verified_files":manifest.get("verified_files", []),
                       "note":_note(pack_id)})
    return result


def _ready(pack_id: str, manifest: dict) -> bool:
    if pack_id.startswith("asr-"):
        return bool(manifest.get("initialized_at")) and (settings.models_dir / MODEL_PACKS[pack_id]["path"] / "model.bin").is_file()
    if pack_id == "translation-zh-en":
        try:
            os.environ["ARGOS_CHUNK_TYPE"] = "ARGOSTRANSLATE"
            os.environ["ARGOS_DEVICE_TYPE"] = "cpu"
            os.environ["ARGOS_PACKAGES_DIR"] = str(settings.models_dir / "argos")
            import argostranslate.translate as tr
            languages = {lang.code: lang for lang in tr.get_installed_languages()}
            source, target = languages.get("zh"), languages.get("en")
            return bool(manifest.get("initialized_at")) and bool(source and target and source.get_translation(target))
        except ImportError:
            return False
    if pack_id == "tts-kokoro-en":
        return bool(manifest.get("initialized_at")) and _hf_cache_has_kokoro() and importlib.util.find_spec("en_core_web_sm") is not None
    if pack_id == "separation-htdemucs":
        # torch.hub stores pretrained checkpoints under <TORCH_HOME>/hub/checkpoints.
        cache=settings.models_dir / "torch" / "hub" / "checkpoints"
        return bool(manifest.get("initialized_at")) and cache.exists() and any(p.stat().st_size>1_000_000 for p in cache.glob("*.th"))
    return False


def _hf_cache_has_kokoro() -> bool:
    hub = settings.models_dir / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"
    return hub.exists() and any(hub.glob("snapshots/*/kokoro-v1_0.pth"))


def _note(pack_id: str) -> str | None:
    if pack_id == "separation-htdemucs":
        return "Music-vocal separation only; not a film-dialogue separator. Upstream repository is archived."
    if pack_id == "translation-zh-en":
        return "The exact package version and checksum are written to the model manifest after install."
    return None


def _write_manifest(pack_id: str, extra: dict[str, Any] | None = None) -> None:
    meta = MODEL_PACKS[pack_id]
    path = _manifest_path(pack_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    files = []
    if path.parent.exists():
        for item in sorted(path.parent.rglob("*")):
            if item.is_file() and item.name != "pack-manifest.json":
                digest = hashlib.sha256()
                with item.open("rb") as f:
                    for chunk in iter(lambda:f.read(1024*1024), b""):
                        digest.update(chunk)
                files.append({"path":str(item.relative_to(path.parent)), "sha256":digest.hexdigest(), "bytes":item.stat().st_size})
    document = {"id":pack_id,"repo":meta["repo"],"revision":meta["revision"],"license":meta["license"],
                "initialized_at":datetime.now(timezone.utc).isoformat(),
                "verified_files":files,**(extra or {})}
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def initialize(pack_id: str) -> dict:
    if pack_id not in MODEL_PACKS:
        raise ValueError("Unknown model pack")
    current = next((item for item in list_packs() if item["id"] == pack_id), None)
    if current and current["ready"]:
        return current
    if settings.offline:
        raise RuntimeError("OFFLINE_INFERENCE=true; model download/initialization is disabled")
    meta = MODEL_PACKS[pack_id]
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(settings.models_dir / "huggingface")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(settings.models_dir / "huggingface" / "hub")
    os.environ["TORCH_HOME"] = str(settings.models_dir / "torch")
    os.environ["ARGOS_PACKAGES_DIR"] = str(settings.models_dir / "argos")
    os.environ["ARGOS_DEVICE_TYPE"] = "cpu"
    os.environ["ARGOS_CHUNK_TYPE"] = "ARGOSTRANSLATE"
    if pack_id.startswith("asr-"):
        import numpy as np
        import soundfile as sf
        from huggingface_hub import snapshot_download
        target = settings.models_dir / meta["path"]
        target.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=meta["repo"], revision=meta["revision"], local_dir=str(target))
        if not (target / "model.bin").exists():
            raise RuntimeError("Downloaded Faster-Whisper snapshot does not contain model.bin")
        from faster_whisper import WhisperModel
        model=WhisperModel(str(target),device="cpu",compute_type="int8",cpu_threads=effective_cpu_count())
        with tempfile.TemporaryDirectory(prefix="dub-studio-asr-smoke-") as folder:
            sample=Path(folder) / "silent-zh.wav"
            sf.write(sample,np.zeros(32000,dtype=np.float32),16000)
            started=time.perf_counter()
            segments,info=model.transcribe(str(sample),language="zh",beam_size=1,vad_filter=False)
            list(segments)
            inference={"device":"cpu","compute":"int8","sample":"2s synthetic silence",
                       "language":getattr(info,"language","zh"),"seconds":round(time.perf_counter()-started,3)}
        del model
        _write_manifest(pack_id,{"smoke_inference":inference})
    elif pack_id == "translation-zh-en":
        import argostranslate.package as package
        package.update_package_index()
        available = [p for p in package.get_available_packages()
                     if p.from_code == "zh" and p.to_code == "en" and str(getattr(p,"package_version","")) == "1.9"]
        if not available:
            raise RuntimeError("The official Argos package index no longer lists the pinned zh-en 1.9 language package")
        chosen = available[0]
        path = chosen.download()
        if not Path(path).is_file() or Path(path).stat().st_size == 0:
            raise RuntimeError("Argos language package download is empty")
        package.install_from_path(path)
        import argostranslate.translate as translate
        languages = {lang.code: lang for lang in translate.get_installed_languages()}
        source, target = languages.get("zh"), languages.get("en")
        translator = source.get_translation(target) if source and target else None
        if translator is None:
            raise RuntimeError("Argos package installed but the local zh-en translator is not available")
        from .providers import configure_local_argos_splitter
        configure_local_argos_splitter(translator)
        sample_translation=translator.translate("你好，世界。")
        if not sample_translation.strip():
            raise RuntimeError("Argos returned an empty output for its local inference check")
        info = {"package_version":getattr(chosen,"package_version",None),
                "package_checksum":getattr(chosen,"package_checksum",None),
                "from_code":chosen.from_code,"to_code":chosen.to_code,
                "package_license":getattr(chosen,"package_license",None) or "not stated in the official package index; review package metadata",
                "sentence_splitter":"local punctuation-based; no SBD model download",
                "smoke_inference":{"input":"你好，世界。","output":sample_translation,"provider":"argos-translate"}}
        _write_manifest(pack_id, info)
    elif pack_id == "tts-kokoro-en":
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=meta["repo"], revision=meta["revision"])
        cache = settings.models_dir / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"
        ref = cache / "refs" / "main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(meta["revision"], encoding="ascii")
        from kokoro import KPipeline
        import numpy as np
        pipeline = KPipeline(lang_code="a", repo_id=meta["repo"], device="cpu")
        generated = list(pipeline("Local model initialization check.", voice="af_heart"))
        if not generated or not any(np.asarray(item[2]).size for item in generated):
            raise RuntimeError("Kokoro did not synthesize the initialization phrase")
        _write_manifest(pack_id)
    elif pack_id == "separation-htdemucs":
        import numpy as np
        import soundfile as sf
        os.environ["OMP_NUM_THREADS"]=str(effective_cpu_count())
        os.environ["MKL_NUM_THREADS"]=str(effective_cpu_count())
        import torch
        torch.set_num_threads(effective_cpu_count())
        from demucs.pretrained import get_model
        model = get_model("htdemucs").to("cpu").eval()
        if model is None:
            raise RuntimeError("Demucs did not load the htdemucs CPU model")
        env=os.environ.copy()
        with tempfile.TemporaryDirectory(prefix="dub-studio-separation-smoke-") as folder:
            root=Path(folder)
            sample=root / "tone.wav"
            rate=44100
            t=np.arange(rate*10,dtype=np.float32)/rate
            stereo=np.stack((0.15*np.sin(2*np.pi*220*t),0.15*np.sin(2*np.pi*330*t)),axis=1)
            sf.write(sample,stereo,rate,subtype="PCM_16")
            output=root / "separated"
            started=time.perf_counter()
            result=subprocess.run([sys.executable,"-m","app.demucs_runner","-d","cpu","-n","htdemucs",
                                   "--two-stems","vocals","-o",str(output),str(sample)],
                                  capture_output=True,text=True,encoding="utf-8",errors="replace",env=env,timeout=900)
            stems=output / "htdemucs" / "tone"
            if result.returncode or not (stems / "vocals.wav").is_file() or not (stems / "no_vocals.wav").is_file():
                raise RuntimeError("Demucs CPU inference check failed: "+(result.stderr or result.stdout)[-1200:])
            smoke={"device":"cpu","model":"htdemucs","sample":"10s synthetic stereo tones",
                   "seconds":round(time.perf_counter()-started,3),"outputs":["vocals.wav","no_vocals.wav"]}
        del model
        _write_manifest(pack_id,{"smoke_inference":smoke})
    entry = next(p for p in list_packs() if p["id"] == pack_id)
    if not entry["ready"]:
        raise RuntimeError("Model initialization returned, but readiness verification failed")
    return entry
