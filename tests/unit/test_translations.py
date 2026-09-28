"""Consistency checks for strings.json and the bundled translation files.

Custom integrations ship their translations as-is, so a key missing from a
language file silently falls back to English in that language.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_PKG_ROOT = Path(__file__).parents[2] / "custom_components" / "saxo_portfolio"
_TRANSLATIONS = sorted((_PKG_ROOT / "translations").glob("*.json"))
_NON_ENGLISH = [path for path in _TRANSLATIONS if path.stem != "en"]

# Entity names that are correctly spelled the same as in English.
_SAME_AS_ENGLISH: dict[str, set[str]] = {
    "da": {"entity.sensor.position.name"},
    "de": {"entity.sensor.name.name", "entity.sensor.position.name"},
    "fr": {"entity.sensor.position.name"},
    "sv": {"entity.sensor.position.name"},
}


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested translation dicts into dotted keys."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        else:
            flat[dotted] = value
    return flat


def _load(path: Path) -> dict[str, Any]:
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


_STRINGS = _load(_PKG_ROOT / "strings.json")


def test_english_translation_matches_strings() -> None:
    """en.json is the generated copy of strings.json."""
    assert _load(_PKG_ROOT / "translations" / "en.json") == _STRINGS


@pytest.mark.parametrize("path", _TRANSLATIONS, ids=lambda path: path.stem)
def test_translation_has_all_keys(path: Path) -> None:
    """Every language file has exactly the keys of strings.json."""
    keys = set(_load(path))
    assert sorted(set(_STRINGS) - keys) == [], "missing keys"
    assert sorted(keys - set(_STRINGS)) == [], "keys not in strings.json"


@pytest.mark.parametrize("path", _NON_ENGLISH, ids=lambda path: path.stem)
def test_entity_names_are_translated(path: Path) -> None:
    """Entity names are not left in English, apart from known cognates."""
    translation = _load(path)
    untranslated = sorted(
        key
        for key, value in _STRINGS.items()
        if key.startswith("entity.")
        and key.endswith(".name")
        and translation.get(key) == value
        and key not in _SAME_AS_ENGLISH.get(path.stem, set())
    )
    assert untranslated == []


@pytest.mark.parametrize("path", _NON_ENGLISH, ids=lambda path: path.stem)
def test_placeholders_are_kept(path: Path) -> None:
    """Translated strings keep the placeholders of the English original."""
    translation = _load(path)
    for key, value in _STRINGS.items():
        if key in translation and isinstance(value, str):
            expected = {part.split("}")[0] for part in value.split("{")[1:]}
            actual = {part.split("}")[0] for part in translation[key].split("{")[1:]}
            assert actual == expected, key
