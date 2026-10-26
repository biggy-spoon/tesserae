"""Entries for the editor's cell widget picker (app/widget_picker.py)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.widget_picker import (
    CATEGORIES,
    category_for,
    display_name,
    first_sentence,
    picker_entries,
    split_name,
)

REPO = Path(__file__).resolve().parent.parent


@dataclass
class _W:
    id: str
    name: str
    manifest: dict[str, Any] = field(default_factory=dict)


def test_categories_match_the_schema_enum() -> None:
    schema = json.loads((REPO / "schema" / "plugin.schema.json").read_text(encoding="utf-8"))
    assert [c for c, _ in CATEGORIES] == schema["properties"]["category"]["enum"]


def test_every_bundled_widget_declares_a_category() -> None:
    ids = {c for c, _ in CATEGORIES}
    for manifest_path in sorted((REPO / "plugins").glob("*/plugin.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["kind"] != "widget":
            continue
        assert manifest.get("category") in ids, manifest_path.parent.name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Weather, Now", ("Weather", "Now")),
        ("Clock, Sunrise / Sunset", ("Clock", "Sunrise / Sunset")),
        ("Orbit: To-night", ("Orbit", "To-night")),
        ("Webpage", (None, "Webpage")),
        ("GTFS / GTFS-RT", (None, "GTFS / GTFS-RT")),
        ("topo_map", (None, "Topo map")),
    ],
)
def test_split_name(name: str, expected: tuple[str | None, str]) -> None:
    assert split_name(name, "x") == expected


def test_display_name_normalises_the_separator() -> None:
    assert display_name("Trackside: Photo", "trackside_photo") == "Trackside, Photo"
    assert display_name("glances_full", "glances_full") == "Glances full"


def test_category_prefers_the_manifest_then_family_then_id() -> None:
    assert category_for({"category": "sports"}, "github_streak", "GitHub") == "sports"
    assert category_for({"category": "nonsense"}, "github_streak", "GitHub") == "dev"
    assert category_for({}, "topo_map", None) == "places"
    assert category_for({}, "something_new", None) == "utility"


def test_first_sentence() -> None:
    assert first_sentence("Analog clock face. Pure SVG, no network.") == "Analog clock face."
    assert first_sentence("Single FX pair (e.g. AUD/USD).") == "Single FX pair (e.g. AUD/USD)."
    assert first_sentence("") == ""


def test_picker_entries_are_grouped_in_category_order() -> None:
    rows = picker_entries(
        [
            _W("webpage", "Webpage", {"icon": "ph-globe", "category": "utility"}),
            _W("clock_word", "Clock, Word", {"icon": "ph-text-aa", "category": "time"}),
            _W("clock_analog", "Clock, Analog", {"category": "time", "icon": "bad"}),
        ]
    )
    assert [r["id"] for r in rows] == ["clock_analog", "clock_word", "webpage"]
    assert rows[0] == {
        "id": "clock_analog",
        "family": "Clock",
        "item": "Analog",
        "category": "time",
        "icon": "ph-squares-four",
        "desc": "",
    }
