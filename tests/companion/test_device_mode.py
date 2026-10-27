"""Confirmed mode reports are durable advisory metadata, not device commands."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from flask import Flask

from app.state.device_facts import DeviceFactsStore

from .test_companion_api import _CLIENT, _issue_companion_code, _pair, _seed_device, _validate
from .test_companion_api import app as app

_OBSERVATION = {"mode": "bluetooth", "observed_at": "2026-01-02T03:04:05Z", "source": "ios_ble"}
_PATH = "/api/app/v1/devices/kitchen/mode-observation"


def _headers(app: Flask) -> dict[str, str]:
    token = _pair(app.test_client(), _issue_companion_code(app)).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_mode_is_persisted_readable_and_does_not_change_device_behavior(app: Flask) -> None:
    _seed_device(app)
    client = app.test_client()
    headers = _headers(app)
    manifest = copy.deepcopy(app.config["DEVICE_REGISTRY"].get("kitchen").manifest)
    status = copy.deepcopy(app.config["DEVICE_STATUS"])
    before = client.get("/api/app/v1/devices", headers=headers).get_json()["devices"][0]
    assert "mode_observation" not in before
    assert client.put(_PATH, headers=headers, json=_OBSERVATION).status_code == 204

    store = app.config["DEVICE_FACTS"]
    persisted = DeviceFactsStore(store._path).get("kitchen")
    assert persisted is not None
    assert persisted["mode_observation"]["mode"] == "bluetooth"
    assert persisted["mode_observation"]["token_id"]
    body = client.get("/api/app/v1/devices", headers=headers).get_json()
    _validate(body, "DevicesResponse")
    observation = body["devices"][0]["mode_observation"]
    assert observation == {**_OBSERVATION, "received_at": observation["received_at"]}
    assert app.config["DEVICE_STATUS"] == status
    assert app.config["DEVICE_REGISTRY"].get("kitchen").manifest == manifest


def test_old_and_identical_retries_cannot_replace_newer_mode(app: Flask) -> None:
    _seed_device(app)
    client = app.test_client()
    headers = _headers(app)
    latest = {**_OBSERVATION, "mode": "wifi", "observed_at": "2026-01-02T11:04:06+08:00"}
    assert client.put(_PATH, headers=headers, json=_OBSERVATION).status_code == 204
    assert client.put(_PATH, headers=headers, json=latest).status_code == 204
    store = app.config["DEVICE_FACTS"]
    contents = store._path.read_bytes()
    assert client.put(_PATH, headers=headers, json=latest).status_code == 204
    assert client.put(_PATH, headers=headers, json=_OBSERVATION).status_code == 204
    assert store._path.read_bytes() == contents
    observation = store.get("kitchen")["mode_observation"]
    assert observation["mode"] == "wifi"
    assert observation["observed_at"] == "2026-01-02T03:04:06Z"
    store.record("kitchen", fw_version="new-firmware")
    assert store.get("kitchen")["mode_observation"] == observation


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {**_OBSERVATION, "mode": "unknown"},
        {**_OBSERVATION, "source": "advertisement"},
        {**_OBSERVATION, "observed_at": "2026-01-02T03:04:05"},
        {**_OBSERVATION, "observed_at": "20260102T030405Z"},
        {**_OBSERVATION, "observed_at": "9999-01-01T00:00:00Z"},
        {**_OBSERVATION, "photo_key": "must-not-upload"},
    ],
)
def test_invalid_mode_reports_are_not_stored(app: Flask, body: Any) -> None:
    _seed_device(app)
    before = app.config["DEVICE_FACTS"].get("kitchen")
    assert app.test_client().put(_PATH, headers=_headers(app), json=body).status_code == 400
    assert app.config["DEVICE_FACTS"].get("kitchen") == before


def test_mode_reporting_requires_auth_scope_and_registered_instance(app: Flask) -> None:
    _seed_device(app)
    client = app.test_client()
    assert client.put(_PATH, json=_OBSERVATION).status_code == 401
    token, _ = app.config["COMPANION_TOKENS"].issue(client=_CLIENT, scopes=["devices:read"])
    assert (
        client.put(
            _PATH, headers={"Authorization": f"Bearer {token}"}, json=_OBSERVATION
        ).status_code
        == 403
    )
    assert (
        client.put(
            _PATH.replace("kitchen", "missing"), headers=_headers(app), json=_OBSERVATION
        ).status_code
        == 404
    )


def test_status_merges_independently_without_replacing_mode_or_erasing_readings(app: Flask) -> None:
    _seed_device(app)
    client = app.test_client()
    headers = _headers(app)
    report = {
        **_OBSERVATION,
        "battery": {"percent": 65, "observed_at": "2026-01-02T03:04:06Z"},
        "firmware": {"version": "0.9.11", "observed_at": _OBSERVATION["observed_at"]},
    }
    assert client.put(_PATH, headers=headers, json=report).status_code == 204
    newer_mode = {**_OBSERVATION, "mode": "wifi", "observed_at": "2026-01-02T03:04:09Z"}
    assert client.put(_PATH, headers=headers, json=newer_mode).status_code == 204
    newer_battery = {**report, "battery": {"percent": 63, "observed_at": "2026-01-02T03:04:10Z"}}
    assert client.put(_PATH, headers=headers, json=newer_battery).status_code == 204
    # Delayed mode-only and telemetry retries cannot erase or roll back any field.
    for old in (_OBSERVATION, report):
        assert client.put(_PATH, headers=headers, json=old).status_code == 204
    store = app.config["DEVICE_FACTS"]
    saved = DeviceFactsStore(store._path).get("kitchen")["mode_observation"]
    assert saved["mode"] == "wifi"
    assert saved["observed_at"] == newer_mode["observed_at"]
    assert saved["battery"] == newer_battery["battery"]
    assert saved["firmware"] == report["firmware"]
    body = client.get("/api/app/v1/devices", headers=headers).get_json()
    _validate(body, "DevicesResponse")
    exposed = body["devices"][0]["mode_observation"]
    assert exposed["battery"] == saved["battery"] and exposed["firmware"] == saved["firmware"]
    assert "token_id" not in exposed


@pytest.mark.parametrize(
    "field,reading",
    [
        ("battery", {"percent": True, "observed_at": _OBSERVATION["observed_at"]}),
        ("battery", {"percent": -1, "observed_at": _OBSERVATION["observed_at"]}),
        ("battery", {"percent": 101, "observed_at": _OBSERVATION["observed_at"]}),
        ("battery", {"percent": 65.5, "observed_at": _OBSERVATION["observed_at"]}),
        ("battery", {"percent": 65}),
        ("battery", None),
        ("firmware", {"version": "", "observed_at": _OBSERVATION["observed_at"]}),
        ("firmware", {"version": "—", "observed_at": _OBSERVATION["observed_at"]}),
        ("firmware", {"version": "x" * 129, "observed_at": _OBSERVATION["observed_at"]}),
        ("firmware", {"version": "bad\nvalue", "observed_at": _OBSERVATION["observed_at"]}),
        ("firmware", {"version": "0.9", "observed_at": "9999-01-01T00:00:00Z"}),
        ("firmware", {"version": "0.9", "observed_at": "2026-01-02T03:04:05"}),
        (
            "firmware",
            {"version": "0.9", "observed_at": _OBSERVATION["observed_at"], "key": "secret"},
        ),
    ],
)
def test_invalid_status_readings_reject_the_whole_report(
    app: Flask, field: str, reading: Any
) -> None:
    _seed_device(app)
    before = app.config["DEVICE_FACTS"].get("kitchen")
    response = app.test_client().put(
        _PATH, headers=_headers(app), json={**_OBSERVATION, field: reading}
    )
    assert response.status_code == 400
    assert app.config["DEVICE_FACTS"].get("kitchen") == before
