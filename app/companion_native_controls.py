"""Validation and bounded place lookup for Companion's native form controls."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, TypeGuard
from urllib.parse import urlencode

from PIL import ImageColor

from app.location_time import is_iana_zone

_LOCATION_KEYS = frozenset(("name", "country", "admin1", "latitude", "longitude", "timezone"))
_THEME_COLOR = re.compile(r"var\(--[a-zA-Z_][a-zA-Z0-9_-]*(?:,\s*(.+))?\)")
_FUNCTION_COLOR = re.compile(r"(rgba?|hsla?)\(([^()]*)\)", re.IGNORECASE)


def _channel(value: str, maximum: float, *, percent_only: bool = False) -> bool:
    percent = value.endswith("%")
    if percent_only and not percent:
        return False
    try:
        number = float(value[:-1] if percent else value)
    except ValueError:
        return False
    return math.isfinite(number) and 0 <= number <= (100 if percent else maximum)


def _functional_color(kind: str, body: str) -> bool:
    if "," in body:
        parts = [part.strip() for part in body.split(",")]
        if any(not part or "/" in part for part in parts):
            return False
    else:
        parts = body.replace("/", " / ").split()
        if "/" in parts:
            if len(parts) != 5 or parts[3] != "/":
                return False
            parts = parts[:3] + parts[4:]
        elif len(parts) != 3:
            return False
    if len(parts) not in (3, 4):
        return False
    if len(parts) == 4 and not _channel(parts[3], 1):
        return False
    if kind.lower().startswith("rgb"):
        return all(_channel(part, 255) for part in parts[:3])
    hue = re.sub(r"(?:deg|grad|rad|turn)$", "", parts[0], flags=re.IGNORECASE)
    try:
        valid_hue = math.isfinite(float(hue))
    except ValueError:
        return False
    return valid_hue and all(_channel(part, 100, percent_only=True) for part in parts[1:3])


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


def condition_matches(actual: Any, expected: Any) -> bool:
    """The browser's primitive text comparison, including integral JSON floats."""
    if isinstance(expected, dict) and "not" in expected:
        return not condition_matches(actual, expected["not"])

    def text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, dict):
            return "[object Object]"
        if type(value) in (int, float) and finite_number(value):
            number = float(value)
            if number == 0:
                return "0"
            shortest = repr(number)
            if 1e-6 <= abs(number) < 1e21:
                fixed = format(Decimal(shortest), "f")
                return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
            coefficient, exponent = shortest.lower().split("e")
            if "." in coefficient:
                coefficient = coefficient.rstrip("0").rstrip(".")
            return f"{coefficient}e{int(exponent):+d}"
        return str(value)

    wanted = {text(v) for v in expected} if isinstance(expected, list) else {text(expected)}
    return (
        any(text(v) in wanted for v in actual)
        if isinstance(actual, list)
        else text(actual) in wanted
    )


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
    """CSS colors and theme variables, without URLs or declarations."""
    if not isinstance(value, str) or len(value) > 200:
        return False
    color = value.strip()
    if not color:
        return True
    if variable := _THEME_COLOR.fullmatch(color):
        return not variable[1] or valid_color(variable[1])
    if functional := _FUNCTION_COLOR.fullmatch(color):
        return _functional_color(functional[1], functional[2])
    if color.casefold() in {"transparent", "currentcolor", "inherit", "initial", "unset", "revert"}:
        return True
    try:
        channels = ImageColor.getrgb(color)
        if any(not 0 <= component <= 255 for component in channels):
            return False
    except (ValueError, TypeError, OverflowError):
        return False
    return True


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
