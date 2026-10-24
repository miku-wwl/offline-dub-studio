import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.config import Settings
from app.providers import ASRProvider, TranslationProvider, configure_local_argos_splitter


def test_argos_translation_uses_language_api(monkeypatch):
    requested = []

    class FakeLanguage:
        def __init__(self, code):
            self.code = code

        def get_translation(self, target):
            requested.append((self.code, target.code))
            return SimpleNamespace(translate=lambda text: "Hello, world.")

    argos = ModuleType("argostranslate")
    translate = ModuleType("argostranslate.translate")
    translate.get_installed_languages = lambda: [FakeLanguage("zh"), FakeLanguage("en")]
    argos.translate = translate
    monkeypatch.setitem(sys.modules, "argostranslate", argos)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", translate)

    segments = [{"source_text": "你好，世界。"}]
    result = TranslationProvider().translate(segments, "zh", "en")

    assert requested == [("zh", "en")]
    assert segments[0]["translated_text"] == "Hello, world."
    assert result["provider"] == "argos-translate"
    assert result["translated"] == 1


def test_local_argos_sentence_splitter_keeps_punctuation():
    translation = SimpleNamespace(underlying=SimpleNamespace(sentencizer=object()))

    configure_local_argos_splitter(translation)

    assert translation.underlying.sentencizer.split_sentences("你好。再见！") == ["你好。", "再见！"]
    assert translation.underlying.sentencizer.split_sentences("3.14 is pi. 你好。") == ["3.14 is pi.", "你好。"]


@pytest.mark.parametrize("empty",[False,True])
def test_asr_respects_openmp_limit_and_rejects_empty_success(tmp_path,monkeypatch,empty):
    import app.providers as module
    config=Settings(models_dir=tmp_path / "models")
    directory=config.models_dir / "asr" / "small"
    directory.mkdir(parents=True)
    (directory / "model.bin").write_bytes(b"test model sentinel")
    monkeypatch.setattr(module,"settings",config)
    monkeypatch.setattr(module,"effective_cpu_count",lambda:8)
    monkeypatch.setenv("OMP_THREAD_LIMIT","1")
    requested=[]
    class Whisper:
        def __init__(self,_path,**kwargs):
            requested.append(kwargs["cpu_threads"])
        def transcribe(self,*_args,**_kwargs):
            row=SimpleNamespace(text="你好",start=0,end=1,avg_logprob=-.1)
            return iter([] if empty else [row]),SimpleNamespace(language="zh",language_probability=1,duration_after_vad=60)
    whisper=ModuleType("faster_whisper")
    whisper.WhisperModel=Whisper
    monkeypatch.setitem(sys.modules,"faster_whisper",whisper)
    if empty:
        with pytest.raises(RuntimeError,match="ASR returned no speech segments.*VAD retained 60"):
            ASRProvider().transcribe(tmp_path / "speech.wav","asr-small","zh")
    else:
        assert ASRProvider().transcribe(tmp_path / "speech.wav","asr-small","zh")["cpu_threads"]==1
    assert requested==[1]
