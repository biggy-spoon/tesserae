"""Instance files (``devices/<id>.json``) are read, patched and written back
whole. Request threads and background ones (TRMNL size adoption, a
firmware-driven renderer switch) both do it, so every such writer, and every
delete, holds ``device_service.INSTANCE_FILE_LOCK``: two writers can't drop
each other's change, and a writer that read the file before a delete can't
write the device back."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from flask import Flask

from app import device_service, trmnl_api
from app.main import REPO_ROOT, create_app
from app.settings import devices_routes


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


def _add_kitchen(app: Flask) -> None:
    client = app.test_client()
    client.post("/setup", data={"password": "abcdefgh", "password_confirm": "abcdefgh"})
    client.post(
        "/settings/devices/add",
        data={"kind": "circuitpython_generic", "id": "kitchen", "name": "Kitchen"},
    )


def test_every_instance_file_writer_holds_the_lock() -> None:
    for fn in (
        device_service.update_instance_panel,
        device_service.update_instance_gamut,
        device_service.update_instance_renderer,
        device_service.set_instance_renderer_id,
        device_service.update_advertised_gamuts,
        device_service.set_grey_prompt_dismissed,
        device_service.sync_renderer_for_firmware,
        device_service.restore_rest_only_transports,
        device_service.refine_inherited_gamuts,
        device_service.update_instance_kind,
        device_service.update_instance_quiet_hours,
        device_service.update_instance_locale,
        device_service.update_instance_battery_offset,
        device_service.delete_instance,
        devices_routes._apply_rename,
        devices_routes._make_rest_instance,
        devices_routes.devices_set_transport,
        devices_routes.devices_regenerate_token,
    ):
        assert "INSTANCE_FILE_LOCK" in fn.__code__.co_names, fn.__name__
    assert "INSTANCE_FILE_LOCK" in trmnl_api._adopt_reported_panel.__code__.co_names


def test_a_save_waits_for_a_writer_holding_the_lock_and_keeps_its_change(
    app: Flask, tmp_path: Path
) -> None:
    _add_kitchen(app)
    devices = app.config["DEVICE_REGISTRY"]
    renderers = app.config["RENDERER_REGISTRY"]
    path = devices.get("kitchen").path
    done = threading.Event()

    def _save_locale() -> None:
        device_service.update_instance_locale(
            devices=devices,
            renderers=renderers,
            data_root=tmp_path,
            instance_id="kitchen",
            locale="de",
        )
        done.set()

    with device_service.INSTANCE_FILE_LOCK:
        worker = threading.Thread(target=_save_locale)
        worker.start()
        assert not done.wait(0.3), "saved while another writer held the instance file"
        raw = json.loads(path.read_text())
        raw["name"] = "Renamed"  # the other writer's change, mid-flight
        path.write_text(json.dumps(raw), encoding="utf-8")
    assert done.wait(10)
    worker.join()
    stored = json.loads(path.read_text())
    assert stored["name"] == "Renamed"
    assert stored["locale"] == "de"


def test_a_delete_waits_for_a_writer_holding_the_lock(app: Flask) -> None:
    _add_kitchen(app)
    devices = app.config["DEVICE_REGISTRY"]
    renderers = app.config["RENDERER_REGISTRY"]
    path = devices.get("kitchen").path
    done = threading.Event()

    def _delete() -> None:
        device_service.delete_instance(devices=devices, renderers=renderers, instance_id="kitchen")
        done.set()

    with device_service.INSTANCE_FILE_LOCK:
        worker = threading.Thread(target=_delete)
        worker.start()
        assert not done.wait(0.3), "deleted while another writer held the instance file"
        assert path.exists()
    assert done.wait(10)
    worker.join()
    assert not path.exists()
