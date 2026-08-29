"""Language detection and English-only index policy (review R34)."""

from __future__ import annotations

from repair_assistant.parsing.language import detect_language, is_index_language


def test_detect_language_spanish_and_french() -> None:
    assert detect_language("Desenchufe la lavadora. Advertencia: boletín técnico.") == "es"
    assert detect_language("Débrancher la laveuse. Avertissement: bulletin technique.") == "fr"
    assert detect_language("Unplug the washer and check the door lock switch.") == "en"


def test_index_language_keeps_english_and_undecided() -> None:
    assert is_index_language("en")
    assert is_index_language("en-US")
    assert is_index_language(None)
    assert not is_index_language("es")
    assert not is_index_language("fr-CA")
