"""Validation and bounded place lookup for Companion's native form controls."""

from __future__ import annotations

import math
import re
from typing import Any, TypeGuard
from urllib.parse import urlencode

from app.location_time import is_iana_zone

_LOCATION_KEYS = frozenset(("name", "country", "admin1", "latitude", "longitude", "timezone"))


def same_json(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        # JSON numbers round-trip through Swift as Double and integral values
        # may re-encode as integers. Booleans remain a distinct JSON kind.
        return type(a) in (int, float) and type(b) in (int, float) and a == b
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same_json(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def finite_number(value: Any) -> TypeGuard[int | float]:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def valid_location(value: Any, *, previous: list[Any] | None = None) -> bool:
    """A selected place or a manually entered, finite coordinate pair."""
    if not isinstance(value, dict):
        return False
    for key in set(value) - _LOCATION_KEYS:
        if not previous or any(
            not isinstance(old, dict) or key not in old or not same_json(old[key], value[key])
            for old in previous
        ):
            return False
    if not value:
        return True
    for name, limit in (("latitude", 90), ("longitude", 180)):
        coordinate = value.get(name)
        if not finite_number(coordinate):
            return False
        if not -limit <= coordinate <= limit:
            return False
    if any(
        not isinstance(value[k], str) or len(value[k]) > 200
        for k in ("name", "country", "admin1")
        if k in value
    ):
        return False
    return "timezone" not in value or is_iana_zone(value["timezone"])


def valid_color(value: Any) -> bool:
    """New colors use the web editor's six-digit RGB hex representation."""
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def location_choices(query: str) -> tuple[list[dict[str, Any]], bool]:
    """Only a fixed upstream is queried; failures never disclose its exception."""
    query = query.strip()
    if len(query) < 2:
        return [], True
    if len(query) > 200:
        return [], False
    # A coordinate pair works without a geocoding service or credentials.
    pair = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*", query)
    if pair:
        place: dict[str, Any] = {
            "name": query,
            "latitude": float(pair[1]),
            "longitude": float(pair[2]),
        }
        return ([{"value": place, "label": query}], True) if valid_location(place) else ([], True)
    from app.net_guard import fetch_json

    try:
        payload = fetch_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urlencode({"name": query, "count": 10, "language": "en", "format": "json"}),
            timeout=5,
            max_bytes=256 * 1024,
        )
        if not isinstance(payload, dict):
            return [], False
        if payload.get("error"):
            return [], False
        results = payload.get("results", [])
        if not isinstance(results, list):
            return [], False
        choices: list[dict[str, Any]] = []
        for result in results[:10]:
            if not isinstance(result, dict):
                continue
            place = {k: result[k] for k in _LOCATION_KEYS if k in result}
            if not valid_location(place) or not place:
                continue
            label = ", ".join(
                dict.fromkeys(str(place[k]) for k in ("name", "admin1", "country") if place.get(k))
            )
            choices.append(
                {
                    "value": place,
                    "label": label or str(place["latitude"]) + ", " + str(place["longitude"]),
                }
            )
        return choices, True
    except Exception:
        return [], False
