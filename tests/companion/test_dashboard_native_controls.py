"""Native controls retain web semantics and never drop hidden or legacy values."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from app.companion_component_settings import Schema
from app.companion_dashboard_settings import InvalidSettings
from app.companion_native_controls import (
    condition_matches,
    location_choices,
    valid_color,
    valid_location,
)
from app.state.page_store import Page

from ._schema import schema_for
from .test_companion_dashboard_settings import _headers
from .test_dashboard_components import app as _app_fixture
from .test_dashboard_components import field, page, patch, registry


@pytest.fixture
def app(tmp_path):
    return _app_fixture.__wrapped__(tmp_path)


def test_shared_condition_cases_match_browser_number_and_primitive_text():
    cases = json.loads(
        (
            Path(__file__).parent / "contract/Fixtures/dashboard-native-condition-cases.json"
        ).read_text()
    )
    for case in cases:
        assert condition_matches(case["actual"], case["expected"]) is case["matches"]


def native_registry():
    reg = registry()
    reg["qa"].manifest["cell_options"] += [
        {
            "name": "size",
            "label": "Size",
            "type": "slider",
            "default": 1,
            "min": 0.05,
            "max": 3,
            "step": 0.05,
            "unit": "×",
        },
        {"name": "place", "label": "Place", "type": "location_search", "default": ""},
        {"name": "ink", "label": "Ink", "type": "color", "default": "var(--fg)"},
        {
            "name": "child",
            "type": "boolean",
            "default": True,
            "show_if": {"conditional": {"not": ""}},
        },
    ]
    return reg


def native(page_value: Page | None = None, reg: Any = None) -> Schema:
    return Schema(page_value or page(), reg or native_registry(), native_controls=True)


def test_legacy_opt_in_metadata_and_typed_roundtrip():
    reg = native_registry()
    old, current = Schema(page(), reg), native(reg=reg)
    for name in ("size", "place", "ink", "conditional"):
        assert not field(old, name).view["editable"]
        assert field(current, name).view["editable"]
    size = field(current, "size")
    assert {k: size.view[k] for k in ("minimum", "maximum", "step", "unit")} == {
        "minimum": 0.05,
        "maximum": 3,
        "step": 0.05,
        "unit": "×",
    }
    place = {
        "name": "Shanghai",
        "latitude": 31.23,
        "longitude": 121.47,
        "timezone": "Asia/Shanghai",
    }
    updated = patch(
        current,
        {
            size.id: 1.15,
            field(current, "place").id: place,
            field(current, "ink").id: "rebeccapurple",
        },
    )
    again = native(updated, reg)
    assert field(again, "place").view["value"] == place
    assert field(again, "ink").view["value"] == "rebeccapurple"
    assert field(again, "size").view["value"] == 1.15
    assert again.doc["canvas"]["els"][0]["options"]["unknown"] == {"keep": 1}


def test_conditional_combined_patch_and_hidden_value_preservation():
    s = native()
    conditional, controller = field(s, "conditional"), field(s, "title")
    assert conditional.view["visibility_conditions"] == [
        {"field_id": controller.id, "expected": "yes"}
    ]
    assert not conditional.view["visible"]
    with pytest.raises(InvalidSettings, match="hidden"):
        patch(native(), {conditional.id: "new"})
    shown = native(patch(native(), {conditional.id: "kept", controller.id: "yes"}))
    assert field(shown, "conditional").view["visible"]
    assert field(shown, "child").view["visible"]
    hidden = native(patch(shown, {controller.id: "no"}))
    assert not field(hidden, "conditional").view["visible"]
    assert not field(hidden, "child").view["visible"]
    assert field(hidden, "conditional").view["value"] == "kept"
    with pytest.raises(InvalidSettings, match="hidden"):
        patch(
            native(patch(native(), {controller.id: "yes"})),
            {controller.id: "no", conditional.id: "discard"},
        )
    with pytest.raises(InvalidSettings, match="hidden"):
        patch(native(), reset_fields=[conditional.id])


@pytest.mark.parametrize(
    ("actual", "expected", "visible"),
    [
        (True, "true", True),
        (8, "8", True),
        (8.0, "8", True),
        (8, 8.0, True),
        (None, "", True),
        (["a", "b"], ["b", "c"], True),
        (["a"], {"not": ["b", "c"]}, True),
        (False, True, False),
        (["a"], ["b"], False),
        (["a"], {"not": "a"}, False),
    ],
)
def test_visibility_uses_existing_web_text_matching(actual, expected, visible):
    reg = native_registry()
    reg["qa"].manifest["cell_options"][7]["show_if"] = {"title": expected}
    p = page().model_dump(mode="json")
    p["canvas"]["els"][0]["options"]["title"] = actual
    assert field(native(Page.model_validate(p), reg), "conditional").view["visible"] is visible


def test_declared_controller_resolves_public_input_id_and_scopes_instances():
    p = page().model_dump(mode="json")
    p["canvas"]["inputs"] = [
        {"name": "mode", "label": "Mode", "targets": [{"el": "one", "key": "title"}]}
    ]
    s = native(Page.model_validate(p))
    dependency = field(s, "conditional").view["visibility_conditions"][0]
    assert dependency["field_id"] == s.inputs[0].id
    updated = native(patch(s, {field(s, "conditional").id: "new"}, inputs={"mode": "yes"}))
    assert field(updated, "conditional").view["visible"]
    assert not field(updated, "conditional", 1).view["visible"]


@pytest.mark.parametrize("kind", ["missing", "cycle", "secret"])
def test_unresolvable_dependencies_remain_visible_readonly_without_secrets(kind):
    reg = native_registry()
    specs = reg["qa"].manifest["cell_options"]
    if kind == "missing":
        specs[7]["show_if"] = {"absent": "x"}
    elif kind == "cycle":
        specs[0]["show_if"] = {"conditional": "x"}
    else:
        specs[7]["show_if"] = {"token": "PRIVATE-EXPECTED"}
    s = native(reg=reg)
    f = field(s, "conditional")
    assert not f.view["editable"] and f.view["visible"]
    assert f.view["visibility_conditions"] == []
    assert "PRIVATE-EXPECTED" not in json.dumps(s.response())


@pytest.mark.parametrize("value", [0, 1.12, 3.1, True, float("nan"), float("inf"), 10**400])
def test_slider_rejects_range_step_bool_and_nonfinite(value):
    s = native()
    with pytest.raises(InvalidSettings):
        patch(s, {field(s, "size").id: value})


def test_slider_defaults_and_incompatible_shared_constraints():
    reg = native_registry()
    reg["qa"].manifest["cell_options"][-4] = {"name": "size", "label": "Size", "type": "slider"}
    f = field(native(reg=reg), "size")
    assert [f.view[k] for k in ("minimum", "maximum", "step")] == [0, 100, 1]
    p = page().model_dump(mode="json")
    reg["other"] = copy.deepcopy(reg["qa"])
    reg["other"].manifest["cell_options"][-4]["step"] = 0.3
    reg["qa"].manifest["cell_options"][-4]["step"] = 0.2
    p["canvas"]["els"][1]["sources"][0]["key"] = "other"
    p["canvas"]["inputs"] = [
        {
            "name": "size",
            "label": "Size",
            "type": "slider",
            "targets": [
                {"el": "one", "key": "size"},
                {"el": "two", "slot": "source_options", "index": 0, "key": "size"},
            ],
        }
    ]
    shared = native(Page.model_validate(p), reg).inputs[0]
    assert not shared.view["editable"]


@pytest.mark.parametrize(
    "value",
    [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": True, "longitude": 0},
        {"latitude": float("nan"), "longitude": 0},
        {"latitude": 10**400, "longitude": 0},
        {"latitude": 0},
        {"latitude": 0, "longitude": 0, "timezone": "../private"},
        {"latitude": 0, "longitude": 0, "unrecognized": "value"},
        "new legacy text",
    ],
)
def test_location_rejects_invalid_changed_value(value):
    assert not valid_location(value)
    s = native()
    with pytest.raises(InvalidSettings):
        patch(s, {field(s, "place").id: value})


@pytest.mark.parametrize(
    "value",
    [
        "#123",
        "#11223344",
        "red",
        "rebeccapurple",
        "rgb(1, 2, 3)",
        "rgba(1, 2, 3, 0.5)",
        "rgb(10% 20% 30% / 50%)",
        "hsl(120, 50%, 25%)",
        "hsla(120deg, 50%, 25%, .5)",
        "var(--accent)",
        "var(--ink, #fff)",
        "var(--ink, rgba(1, 2, 3, .5))",
        "transparent",
        "currentColor",
    ],
)
def test_color_accepts_css_colors_and_theme_values(value):
    assert valid_color(value)
    s = native()
    assert field(native(patch(s, {field(s, "ink").id: value})), "ink").view["value"] == value


@pytest.mark.parametrize(
    "value",
    [
        "url(https://example.com/a)",
        "red;background:black",
        "rgb(999,0,0)",
        "rgba(1,2,3,128)",
        "rgb(1,,2,3)",
        {"red": 2},
        "not-a-css-color",
    ],
)
def test_color_rejects_invalid_changed_values(value):
    assert not valid_color(value)
    s = native()
    with pytest.raises(InvalidSettings):
        patch(s, {field(s, "ink").id: value})


def test_location_and_color_legacy_values_survive_other_edits_and_resets():
    p = page().model_dump(mode="json")
    p["canvas"]["els"][0]["options"].update(place="Old place name", ink="old-theme-token")
    s = native(Page.model_validate(p))
    updated = native(patch(s, {field(s, "title").id: "New title"}))
    assert field(updated, "place").view["value"] == "Old place name"
    assert field(updated, "ink").view["value"] == "old-theme-token"
    unchanged = native(patch(updated, {field(updated, "place").id: "Old place name"}))
    reset = native(
        patch(unchanged, reset_fields=[field(unchanged, "place").id, field(unchanged, "ink").id])
    )
    assert not field(reset, "place").view["has_override"]
    assert field(reset, "ink").view["value"] == "var(--fg)"


def test_coordinate_edit_retains_unchanged_legacy_metadata_but_cannot_add_or_change_it():
    p = page().model_dump(mode="json")
    prior = {"name": "Old", "latitude": 1, "longitude": 2, "elevation": 50, "timezone": "UTC"}
    p["canvas"]["els"][0]["options"]["place"] = prior
    s = native(Page.model_validate(p))
    edited = {**prior, "latitude": 3}
    result = native(patch(s, {field(s, "place").id: edited}))
    assert field(result, "place").view["value"] == edited
    for unknown_edit in ({"elevation": 51}, {"new_metadata": 2}):
        s = native(Page.model_validate(p))
        with pytest.raises(InvalidSettings):
            patch(s, {field(s, "place").id: {**edited, **unknown_edit}})


def test_location_choices_empty_coordinates_provider_and_failure(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("No upstream expected")

    monkeypatch.setattr("app.net_guard.fetch_json", no_network)
    assert location_choices("") == ([], True)
    rows, ready = location_choices("31.23, 121.47")
    assert ready and rows[0]["value"]["latitude"] == 31.23
    assert location_choices("91, 0") == ([], True)

    def fetch(url, **kwargs):
        assert url.startswith("https://geocoding-api.open-meteo.com/v1/search?")
        assert kwargs["timeout"] == 5
        return {
            "results": [
                {
                    "name": "Test",
                    "latitude": 1,
                    "longitude": 2,
                    "timezone": "UTC",
                    "country": "Testland",
                    "id": 2,
                }
            ]
        }

    monkeypatch.setattr("app.net_guard.fetch_json", fetch)
    rows, ready = location_choices("test")
    assert ready and rows[0]["value"]["timezone"] == "UTC" and "id" not in rows[0]["value"]
    monkeypatch.setattr(
        "app.net_guard.fetch_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PRIVATE"))
    )
    assert location_choices("test") == ([], False)


def test_http_native_header_location_choices_and_atomic_rejection(app, monkeypatch):
    reg = native_registry()
    app.config["PLUGIN_REGISTRY"].plugins.update(reg)
    app.config["PAGE_STORE"].save(page())
    client, headers = app.test_client(), {**_headers(app), "X-Tesserae-Dashboard-Controls": "1"}
    url = "/api/app/v1/dashboards/component-qa/settings"
    initial = client.get(url, headers=headers).get_json()
    jsonschema.validate(initial, schema_for("DashboardSettingsResponse"))
    fields = {f["name"]: f for f in initial["components"][0]["fields"]}
    assert fields["conditional"]["editable"] and not fields["conditional"]["visible"]
    old = client.get(url, headers=_headers(app)).get_json()
    assert not next(f for f in old["components"][0]["fields"] if f["name"] == "conditional")[
        "editable"
    ]
    choices_url = url + "/fields/" + fields["place"]["field_id"] + "/choices"
    choices = client.get(choices_url + "?q=1,2", headers=headers).get_json()
    assert choices["status"] == "ready" and choices["choices"][0]["value"]["latitude"] == 1
    jsonschema.validate(choices, schema_for("DashboardSettingsChoicesResponse"))
    monkeypatch.setattr(
        "app.net_guard.fetch_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PRIVATE"))
    )
    failed = client.get(choices_url + "?q=test", headers=headers).get_json()
    assert failed["status"] == "unavailable" and "PRIVATE" not in json.dumps(failed)
    body = {
        "revision": initial["revision"],
        "schema_revision": initial["schema_revision"],
        "settings": {"name": "Must not save"},
        "component_values": {fields["conditional"]["field_id"]: "hidden"},
    }
    result = client.patch(url, headers=headers, json=body)
    assert result.status_code == 400 and app.config["PAGE_STORE"].get("component-qa").name == "QA"


def test_legacy_location_metadata_keeps_json_number_kind_but_not_boolean_alias():
    reg = native_registry()
    doc = page().model_dump(mode="json")
    doc["canvas"]["els"][0]["options"]["place"] = {
        "latitude": 1.0,
        "longitude": 2.0,
        "legacy": {"enabled": True, "scale": 1.0},
    }
    current = native(Page.model_validate(doc), reg)
    place = field(current, "place")
    bad = {"latitude": 1, "longitude": 2, "legacy": {"enabled": 1, "scale": 1}}
    with pytest.raises(InvalidSettings):
        patch(current, {place.id: bad})
    good = {"latitude": 3, "longitude": 2, "legacy": {"enabled": True, "scale": 1}}
    updated = native(patch(current, {place.id: good}), reg)
    assert field(updated, "place").view["value"] == good
