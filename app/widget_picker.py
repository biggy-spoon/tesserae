"""Entries for the dashboard editor's cell widget picker.

The picker is a search box over every installed widget, grouped by subject.
A widget names its subject with the optional ``category`` key in
``plugin.json`` (one of ``CATEGORIES``). Catalog widgets published before
that key existed don't carry it, so the category falls back to the family in
the widget's name ("GitHub, Streak" is dev), then to a short list of known
standalone widgets, then to Utility.

Names are shown split into family and item: "Weather, Now" reads as a muted
"Weather," and a bold "Now". Some catalog widgets use "Family: Item" or left
the manifest name as their snake_case id; both are tidied for display here so
the list reads consistently until those manifests are renamed.
"""

from __future__ import annotations

import re
from typing import Any

# (id, label), in picker order. Mirrors the ``category`` enum in
# schema/plugin.schema.json; tests/test_widget_picker.py keeps the two in step.
CATEGORIES: list[tuple[str, str]] = [
    ("time", "Time & dates"),
    ("plans", "Plans & tasks"),
    ("weather", "Weather & sky"),
    ("home-assistant", "Home Assistant"),
    ("reading", "News & reading"),
    ("art", "Art & photos"),
    ("places", "Nature & places"),
    ("media", "Music & TV"),
    ("sports", "Sports"),
    ("transport", "Transport"),
    ("dev", "Dev & servers"),
    ("finance", "Finance"),
    ("utility", "Utility"),
]
CATEGORY_IDS = frozenset(c for c, _ in CATEGORIES)

# Family (the part of the name before the separator) -> category, for widgets
# whose manifest has no ``category``.
_FAMILY_CATEGORY: dict[str, str] = {
    "Clock": "time",
    "Countdown": "time",
    "Year": "time",
    "Calendar": "plans",
    "Todoist": "plans",
    "Apple": "plans",
    "Weather": "weather",
    "Sky": "weather",
    "Orbit": "weather",
    "Home Assistant": "home-assistant",
    "News": "reading",
    "Comics": "reading",
    "Picture": "art",
    "AI": "art",
    "Map": "places",
    "Melbourne": "places",
    "Spotify": "media",
    "Plex": "media",
    "Recently Added": "media",
    "AFL": "sports",
    "F1": "sports",
    "Football": "sports",
    "Transit": "transport",
    "Flights": "transport",
    "Overhead": "transport",
    "Trackside": "transport",
    "Underway": "transport",
    "GitHub": "dev",
    "Glances": "dev",
    "OctoPrint": "dev",
    "YouTube": "dev",
    "Dev Reference": "dev",
    "Terminal": "dev",
    "Finance": "finance",
    "Tesserae": "utility",
}

# Catalog widgets without a family in their name, by id.
_ID_CATEGORY: dict[str, str] = {
    "ai_brief": "art",
    "ai_image": "art",
    "ai_scene": "art",
    "apple_mail_inbox": "utility",
    "apple_reminders": "plans",
    "arr_recently_added": "media",
    "backyard_birds": "places",
    "climate_history": "weather",
    "development_activity": "places",
    "flight_status": "transport",
    "flights_overhead": "transport",
    "fractal_tile": "art",
    "front_page": "reading",
    "fugleramme": "places",
    "glances_full": "dev",
    "goodreads_shelf": "reading",
    "koi_pond": "art",
    "map_poster": "places",
    "markdown_note": "utility",
    "paperlesspaper_art": "art",
    "plex_recently_added": "media",
    "pokedex": "art",
    "poorly_drawn_lines": "reading",
    "poster": "art",
    "posthog_metric": "dev",
    "public_holiday_countdown": "time",
    "public_transport_times": "transport",
    "recipes": "reading",
    "room_status": "plans",
    "sky_tonight": "weather",
    "specimen_sheet": "places",
    "topo_map": "places",
    "trmnl_proxy": "utility",
    "urban_forest": "places",
    "wildlife_nearby": "places",
    "world_time": "time",
    "xkcd_comic": "reading",
}

_SEPARATOR = re.compile(r",\s+|:\s+")
# A sentence ends at ". " before a capital, except after "e.g." / "i.e.".
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-Z0-9])")


def split_name(name: str, widget_id: str) -> tuple[str | None, str]:
    """``(family, item)`` for display. ``family`` is None for a standalone name.

    A name left as the snake_case id ("topo_map") is shown in words ("Topo
    map") rather than as a key.
    """
    name = name.strip()
    if "_" in name and " " not in name:
        words = name.replace("_", " ").strip()
        return None, words[:1].upper() + words[1:]
    parts = _SEPARATOR.split(name, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None, name or widget_id


def category_for(manifest: dict[str, Any], widget_id: str, family: str | None) -> str:
    declared = manifest.get("category")
    if isinstance(declared, str) and declared in CATEGORY_IDS:
        return declared
    if family and family in _FAMILY_CATEGORY:
        return _FAMILY_CATEGORY[family]
    return _ID_CATEGORY.get(widget_id, "utility")


def first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    return _SENTENCE_END.split(text, maxsplit=1)[0]


def display_name(name: str, widget_id: str) -> str:
    family, item = split_name(name, widget_id)
    return f"{family}, {item}" if family else item


def picker_entries(widgets: list[Any]) -> list[dict[str, Any]]:
    """One JSON-ready row per widget, in category order then by name."""
    order = {c: i for i, (c, _) in enumerate(CATEGORIES)}
    rows = []
    for w in widgets:
        manifest = w.manifest if isinstance(w.manifest, dict) else {}
        family, item = split_name(w.name, w.id)
        icon = manifest.get("icon")
        rows.append(
            {
                "id": w.id,
                "family": family,
                "item": item,
                "category": category_for(manifest, w.id, family),
                "icon": icon
                if isinstance(icon, str) and icon.startswith("ph-")
                else "ph-squares-four",
                "desc": first_sentence(str(manifest.get("description") or "")),
            }
        )
    rows.sort(
        key=lambda r: (order[r["category"]], (r["family"] or r["item"]).lower(), r["item"].lower())
    )
    return rows
