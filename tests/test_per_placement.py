"""``ctx["placement_id"]`` and the ``render.per_placement`` manifest key.

A widget's ``fetch()`` is told which placement it is rendering for (page, cell
and device), and a widget that declares ``render.per_placement`` is not handed
another placement's fetch from the canvas memo or the last-good fallback.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from app import composer
from app.main import REPO_ROOT, create_app
from app.state.page_store import Cell, Page
from app.state.panel_store import Element


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    a = create_app(
        testing=False,
        data_root=tmp_path,
        plugins_dir=REPO_ROOT / "plugins",
        renderers_dir=REPO_ROOT / "renderers",
        devices_dir=REPO_ROOT / "devices",
    )
    a.config["TESTING"] = True
    return a


def _probe(
    app: Flask, monkeypatch: pytest.MonkeyPatch, per_placement: bool
) -> list[dict[str, Any]]:
    """Give the analog clock widget a fetch() that records its ctx."""
    seen: list[dict[str, Any]] = []

    def fetch(
        options: dict[str, Any], settings: dict[str, Any], ctx: dict[str, Any]
    ) -> dict[str, Any]:
        seen.append(dict(ctx))
        return {"n": len(seen)}

    plugin = app.config["PLUGIN_REGISTRY"].get("clock_analog")
    assert plugin is not None
    render = {**plugin.manifest.get("render", {})}
    if per_placement:
        render["per_placement"] = True
    else:
        render.pop("per_placement", None)
    monkeypatch.setattr(plugin, "server_module", types.SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(plugin, "manifest", {**plugin.manifest, "render": render})
    return seen


def _canvas(app: Flask, page_id: str, device: str = "") -> list[dict[str, Any]]:
    els = [
        Element(id="a", kind="widget", widget="clock_analog", x=0, y=0, w=200, h=100),
        Element(id="b", kind="widget", widget="clock_analog", x=0, y=120, w=200, h=100),
    ]
    with app.test_request_context("/compose/cv"):
        return composer._build_canvas_els(els, 400, 300, target_device_id=device, page_id=page_id)


def test_canvas_fetch_ctx_names_page_element_and_device(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _probe(app, monkeypatch, per_placement=False)
    _canvas(app, "pg", device="dev_a")
    assert [c["placement_id"] for c in seen] == ["pg/a@dev_a"]


def test_canvas_without_a_page_falls_back_to_the_element_id(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _probe(app, monkeypatch, per_placement=False)
    _canvas(app, "")
    assert seen[0]["placement_id"] == "a"


def test_ordinary_widget_still_shares_one_fetch(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _probe(app, monkeypatch, per_placement=False)
    _canvas(app, "pg")
    assert len(seen) == 1


def test_per_placement_widget_fetches_once_per_element(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _probe(app, monkeypatch, per_placement=True)
    out = _canvas(app, "pg", device="dev_a")
    assert [c["placement_id"] for c in seen] == ["pg/a@dev_a", "pg/b@dev_a"]
    assert [e["data"]["n"] for e in out] == [1, 2]


def test_grid_fetch_ctx_names_page_cell_and_device(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _probe(app, monkeypatch, per_placement=False)
    page = Page(
        id="pg",
        name="PG",
        cells=[
            Cell(id="c1", plugin="clock_analog", x=0, y=0, w=400, h=300),
            Cell(id="c2", plugin="clock_analog", x=400, y=0, w=400, h=300),
        ],
    )
    page_dict = page.model_dump(mode="json", exclude_none=True)
    page_dict["panel"] = {"w": 800, "h": 300}
    page_dict["target_device_id"] = "dev_b"
    with app.test_request_context("/compose/pg"):
        composer._hydrate_page(page_dict, preview=True)
    assert sorted(c["placement_id"] for c in seen) == ["pg/c1@dev_b", "pg/c2@dev_b"]


def test_grid_without_a_page_id_adds_no_placement(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _probe(app, monkeypatch, per_placement=False)
    cells = [Cell(id="c1", plugin="clock_analog", x=0, y=0, w=400, h=300)]
    page_dict = {
        "name": "x",
        "cells": [c.model_dump(mode="json", exclude_none=True) for c in cells],
    }
    page_dict["panel"] = {"w": 400, "h": 300}
    with app.test_request_context("/compose/x"):
        composer._hydrate_page(page_dict, preview=True)
    assert seen and "placement_id" not in seen[0]


def test_last_good_key_only_splits_on_placement_when_given() -> None:
    plain = composer._last_good_key("w", {"a": 1}, 800, 480)
    assert composer._last_good_key("w", {"a": 1}, 800, 480, "") == plain
    assert composer._last_good_key("w", {"a": 1}, 800, 480, "pg/c1") != plain
    assert composer._last_good_key("w", {"a": 1}, 800, 480, "pg/c1") != composer._last_good_key(
        "w", {"a": 1}, 800, 480, "pg/c2"
    )


def test_schema_types_render_per_placement() -> None:
    import json

    import jsonschema

    schema = json.loads((REPO_ROOT / "schema" / "plugin.schema.json").read_text())
    manifest = json.loads((REPO_ROOT / "plugins" / "clock_analog" / "plugin.json").read_text())
    jsonschema.validate({**manifest, "render": {"per_placement": True}}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**manifest, "render": {"per_placement": "yes"}}, schema)
