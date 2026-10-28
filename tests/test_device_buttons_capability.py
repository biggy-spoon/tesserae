"""``"buttons": false``: a device kind or hardware entry with no physical
buttons (or whose protocol forwards none). Its device page has no button map,
and Home Assistant gets no Input event entity for it. Absent means it may have
buttons, as every device always has."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import device_loader
from app.device_loader import has_buttons, has_touch, takes_input
from app.main import REPO_ROOT, create_app


def test_buttons_default_to_present_and_only_false_removes_them() -> None:
    assert has_buttons(SimpleNamespace(manifest={}))
    assert has_buttons(SimpleNamespace(manifest={"buttons": True}))
    assert has_buttons(SimpleNamespace(manifest={"buttons": "no"}))  # only a real false counts
    assert not has_buttons(SimpleNamespace(manifest={"buttons": False}))
    assert has_buttons(SimpleNamespace())  # no manifest at all
    assert not has_touch(SimpleNamespace(manifest={}))
    assert has_touch(SimpleNamespace(manifest={"touch": True}))


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ({}, True),
        ({"buttons": False}, False),
        ({"buttons": False, "touch": True}, True),
        ({"touch": True}, True),
    ],
)
def test_a_device_takes_input_through_buttons_or_touch(
    manifest: dict[str, bool], expected: bool
) -> None:
    assert takes_input(SimpleNamespace(manifest=manifest)) is expected


def test_a_hardware_entry_states_buttons_false_in_its_kind(tmp_path: Path) -> None:
    devices = tmp_path / "devices"
    proto = devices / "test_protocol"
    proto.mkdir(parents=True)
    (proto / "device.json").write_text(
        json.dumps(
            {
                "tesserae_compat": "1.x",
                "name": "test protocol",
                "version": "0.0.1",
                "renderers": ["pi_png"],
                "status_topic": "tesserae/test_protocol/status",
                "panel": {"w": 800, "h": 480, "orientation": "landscape"},
            }
        )
    )
    (proto / "device.py").write_text("def parse_status(payload):\n    return {}\n")
    hardware = tmp_path / "hardware" / "acme"
    hardware.mkdir(parents=True)
    for sku_id, extra in (("acme_plain", {"buttons": False}), ("acme_other", {})):
        (hardware / f"{sku_id}.json").write_text(
            json.dumps(
                {
                    "tesserae_compat": "1.x",
                    "id": sku_id,
                    "name": sku_id,
                    "vendor": "Acme",
                    "protocol": "test_protocol",
                    "panel": {"w": 800, "h": 480, "orientation": "landscape"},
                    **extra,
                }
            )
        )
    registry = device_loader.discover(
        devices,
        schema_path=REPO_ROOT / "schema" / "device.schema.json",
        data_root=tmp_path / "data",
        hardware_dir=tmp_path / "hardware",
        hardware_schema_path=REPO_ROOT / "schema" / "hardware.schema.json",
    )
    assert registry.errors == []
    assert registry.devices["acme_plain"].manifest["buttons"] is False
    assert not has_buttons(registry.devices["acme_plain"])
    assert "buttons" not in registry.devices["acme_other"].manifest
    assert has_buttons(registry.devices["acme_other"])


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    a = create_app(
        testing=False,
        data_root=tmp_path,
        plugins_dir=REPO_ROOT / "plugins",
        renderers_dir=REPO_ROOT / "renderers",
    )
    a.config["TESTING"] = True
    return a


def test_a_device_with_no_buttons_has_no_controls_section(app: Flask) -> None:
    client = app.test_client()
    client.post("/setup", data={"password": "abcdefgh", "password_confirm": "abcdefgh"})
    for device_id in ("plain", "buttoned"):
        client.post(
            "/settings/devices/add",
            data={"kind": "circuitpython_generic", "id": device_id, "name": device_id},
        )
    registry = app.config["DEVICE_REGISTRY"]
    registry.get("plain").manifest["buttons"] = False
    plain = client.get("/settings/devices/plain").get_data(as_text=True)
    other = client.get("/settings/devices/buttoned").get_data(as_text=True)
    assert 'id="controls"' not in plain and "Button map" not in plain
    assert 'href="#controls"' not in plain
    assert 'id="controls"' in other and "Button map" in other
    # A touch panel keeps the section (the touch monitor) even without buttons.
    registry.get("plain").manifest["touch"] = True
    tappable = client.get("/settings/devices/plain").get_data(as_text=True)
    assert 'id="controls"' in tappable and "Touch monitor" in tappable
    assert "Button map" not in tappable
