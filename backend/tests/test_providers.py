import sys
from types import ModuleType, SimpleNamespace

from app.providers import TranslationProvider, configure_local_argos_splitter


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
