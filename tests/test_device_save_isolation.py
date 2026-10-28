"""A device card save changes only its own keys in ``settings.devices.<id>``.

The button map, the update-delivery mode and wake alignment are saved outside
the kind's config schema. They used to read the device's whole entry, change
a key and write the copy back, which undid anything another request (a
background writer, a second browser tab) saved on that entry in between.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from app.main import REPO_ROOT, create_app


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


@pytest.mark.parametrize(
    ("fields", "stored_key"),
    [
        ({"refresh_mode": "full"}, "refresh_mode"),
        ({"button_map_json": '{"left": "refresh"}'}, "button_map"),
        ({"wake_align_mode": "interval", "wake_align_anchor": "06:00"}, "wake_align_mode"),
    ],
    ids=["refresh mode", "button map", "wake alignment"],
)
def test_a_save_keeps_a_key_another_request_wrote_meanwhile(
    app: Flask, fields: dict[str, str], stored_key: str
) -> None:
    client = app.test_client()
    client.post("/setup", data={"password": "abcdefgh", "password_confirm": "abcdefgh"})
    client.post(
        "/settings/devices/add",
        data={"kind": "circuitpython_generic", "id": "kitchen", "name": "Kitchen"},
    )
    store = app.config["SETTINGS_STORE"]
    wrote: list[bool] = []

    def _other_request() -> None:
        if not wrote:
            wrote.append(True)
            store.update_item("devices", "kitchen", {"written_meanwhile": "kept"})

    real_update, real_patch = store.update_item, store.patch_section

    def _update_item(namespace: str, item_id: str, values: dict[str, Any], **kw: Any) -> None:
        if namespace == "devices" and item_id == "kitchen":
            _other_request()
        real_update(namespace, item_id, values, **kw)

    def _patch_section(name: str, values: dict[str, Any]) -> None:
        if name == "devices" and "kitchen" in values:
            _other_request()
        real_patch(name, values)

    store.update_item, store.patch_section = _update_item, _patch_section
    try:
        resp = client.post("/settings/devices/kitchen/save", data=fields)
    finally:
        store.update_item, store.patch_section = real_update, real_patch
    assert resp.status_code == 302 and wrote
    entry = store.get_section("devices")["kitchen"]
    assert stored_key in entry
    assert entry["written_meanwhile"] == "kept"


def test_removing_a_device_drops_only_its_own_settings_entry(app: Flask) -> None:
    client = app.test_client()
    client.post("/setup", data={"password": "abcdefgh", "password_confirm": "abcdefgh"})
    for device_id in ("kitchen", "hall"):
        client.post(
            "/settings/devices/add",
            data={"kind": "circuitpython_generic", "id": device_id, "name": device_id},
        )
    store = app.config["SETTINGS_STORE"]
    store.update_item("devices", "kitchen", {"refresh_mode": "full"})
    store.update_item("devices", "hall", {"refresh_mode": "full"})
    from app import device_cleanup

    device_cleanup._wipe_settings_for_device(store, "kitchen")
    assert set(store.get_section("devices")) == {"hall"}
