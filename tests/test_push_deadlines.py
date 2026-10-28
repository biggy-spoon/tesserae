"""Push manager deadlines: a caller can bound how long it waits for the
render lock (``lock_timeout_s``) and gets ``busy`` back instead of
blocking, a send that gave up never supersedes one still waiting, and the
deck-cache operations give up the same way. Home Assistant's command
worker passes these so a stuck render can't stall it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.state.page_store import Page, PageStore


def _real_push_manager(tmp_path: Path) -> tuple[Any, Any]:
    """A real PushManager over the bundled devices, one esp32 instance
    ``hallway`` and a page ``home`` bound to it."""

    from app import device_loader, device_service, renderer_loader
    from app.main import REPO_ROOT
    from app.push import PushManager
    from app.state.event_log import EventLog
    from app.state.settings_store import SettingsStore
    from app.transport import BrokerConfig, MqttTransport

    devices = device_loader.discover(
        REPO_ROOT / "devices",
        schema_path=REPO_ROOT / "schema" / "device.schema.json",
        data_root=tmp_path / "devices",
    )
    renderers = renderer_loader.discover(
        REPO_ROOT / "renderers",
        schema_path=REPO_ROOT / "schema" / "renderer.schema.json",
        data_root=tmp_path / "rdata",
    )
    device_service.create_instance(
        devices=devices,
        renderers=renderers,
        data_root=tmp_path / "devices",
        instance_id="hallway",
        kind_id="esp32_client",
    )
    pages = PageStore(tmp_path / "pages.json")
    pages.save(Page(id="home", name="Home", device_ids=["hallway"], cells=[]))

    class _Fake:
        def __init__(self, *a: Any, **kw: Any) -> None:
            self.on_connect = self.on_disconnect = self.on_message = None

        def username_pw_set(self, *a: Any, **kw: Any) -> None:
            pass

        def connect(self, *a: Any, **kw: Any) -> int:
            return 0

        def disconnect(self) -> int:
            return 0

        def loop_start(self) -> int:
            return 0

        def loop_stop(self) -> int:
            return 0

        def publish(self, *a: Any, **kw: Any) -> Any:
            return type("R", (), {"rc": 0})()

        def subscribe(self, *a: Any, **kw: Any) -> tuple[int, int]:
            return (0, 1)

    transport = MqttTransport(BrokerConfig(host="x"), client_factory=_Fake)
    transport.connect()
    events = EventLog(tmp_path / "events.db")
    manager = PushManager(
        registry=renderers,
        page_store=pages,
        transport=transport,
        settings=SettingsStore(tmp_path / "settings.json"),
        event_log=events,
        renders_dir=tmp_path / "renders",
        base_url_fn=lambda: "http://broker.local:8000",
        devices=devices,
    )
    return manager, events


def test_push_lock_wait_is_bounded_and_reports_busy(tmp_path: Path) -> None:
    import threading
    import time

    manager, _events = _real_push_manager(tmp_path)
    held, release = threading.Event(), threading.Event()

    def hog() -> None:  # another push holding the render lock
        with manager._lock:
            held.set()
            release.wait(5)

    thread = threading.Thread(target=hog)
    thread.start()
    assert held.wait(5)
    try:
        started = time.monotonic()
        result = manager.push("home", lock_timeout_s=0.2, settle=False)
        assert time.monotonic() - started < 2.0
    finally:
        release.set()
        thread.join(5)
    assert result.status == "busy"
    assert "busy" in (result.error or "")
    # The withdrawn ticket doesn't supersede anyone later.
    assert (
        manager._acquire_or_supersede(
            device_id=None, source="t", target="home", bypass_coalesce=False, lock_timeout_s=1.0
        )
        is None
    )
    manager._lock.release()


# ---------- coalescing tickets that time out ----------


def _hog(manager: Any):
    import threading

    held, release = threading.Event(), threading.Event()

    def run() -> None:
        with manager._lock:
            held.set()
            release.wait(5)

    thread = threading.Thread(target=run)
    thread.start()
    assert held.wait(5)
    return thread, release


def test_sends_that_gave_up_never_supersede_one_still_waiting(tmp_path: Path) -> None:
    # A waits normally, B and C queue behind it, B then C time
    # out; the ticket fell back to B's abandoned one and A came back
    # "superseded" although nothing newer was delivered.
    import threading

    manager, _events = _real_push_manager(tmp_path)
    hog, release = _hog(manager)
    outcome: dict[str, Any] = {}

    def a() -> None:
        outcome["a"] = manager._acquire_or_supersede(
            device_id="hallway", source="t", target="home", bypass_coalesce=False
        )

    waiter = threading.Thread(target=a)
    waiter.start()
    threading.Event().wait(0.1)  # A's ticket is issued and waiting
    results: dict[str, Any] = {}

    def give_up(name: str, wait: float) -> None:
        results[name] = manager._acquire_or_supersede(
            device_id="hallway",
            source="t",
            target="home",
            bypass_coalesce=False,
            lock_timeout_s=wait,
        )

    # B and C queue together behind A; B gives up first, then C.
    b = threading.Thread(target=give_up, args=("b", 0.3))
    b.start()
    threading.Event().wait(0.05)
    c = threading.Thread(target=give_up, args=("c", 0.5))
    c.start()
    b.join(5)
    c.join(5)
    assert results == {"b": "busy", "c": "busy"}
    release.set()
    hog.join(5)
    waiter.join(5)
    assert outcome["a"] is None  # A got the lock and proceeds
    manager._lock.release()


def test_a_newer_waiting_send_still_supersedes(tmp_path: Path) -> None:
    import threading

    manager, _events = _real_push_manager(tmp_path)
    hog, release = _hog(manager)
    outcome: dict[str, Any] = {}

    def send(name: str) -> None:
        got = manager._acquire_or_supersede(
            device_id="hallway", source="t", target="home", bypass_coalesce=False
        )
        outcome[name] = got
        if got is None:
            manager._lock.release()

    first = threading.Thread(target=send, args=("first",))
    first.start()
    threading.Event().wait(0.1)
    second = threading.Thread(target=send, args=("second",))
    second.start()
    threading.Event().wait(0.1)
    release.set()
    for thread in (hog, first, second):
        thread.join(5)
    assert outcome == {"first": "superseded", "second": None}


def test_an_older_send_yielding_to_a_timed_out_waiter_does_not_strand_both(
    tmp_path: Path,
) -> None:
    # The overlapping-timeout race: B (with a deadline) times out of the
    # lock wait, and before it takes the ticket lock to withdraw, older send
    # A is granted the lock, sees B's ticket still waiting and yields to it.
    # B then reports busy: neither delivered. B must take the lock it was
    # yielded to and deliver, and A (superseded by B) must not.
    import threading

    manager, _events = _real_push_manager(tmp_path)
    real = manager._lock
    a_done = threading.Event()
    gap_hit: list[bool] = []

    class GapLock:
        """The render lock, widening the gap between a waiter's timeout and
        its trip to the ticket lock until A has been through it."""

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            got = real.acquire(blocking, timeout)
            if not got and not gap_hit:
                gap_hit.append(True)
                real.release()  # the holder lets go in that very instant
                assert a_done.wait(5)
            return got

        def release(self) -> None:
            real.release()

        def __enter__(self) -> bool:
            return self.acquire()

        def __exit__(self, *exc: object) -> None:
            self.release()

    manager._lock = GapLock()
    assert manager._lock.acquire()  # the render in flight
    outcome: dict[str, Any] = {}

    def send(name: str, lock_timeout_s: float | None) -> None:
        outcome[name] = manager._acquire_or_supersede(
            device_id="hallway",
            source="t",
            target="home",
            bypass_coalesce=False,
            lock_timeout_s=lock_timeout_s,
        )
        if name == "a":
            a_done.set()

    a = threading.Thread(target=send, args=("a", None))
    a.start()
    threading.Event().wait(0.1)  # A's ticket is older and waiting
    b = threading.Thread(target=send, args=("b", 0.3))
    b.start()
    for thread in (a, b):
        thread.join(10)
    assert not a.is_alive() and not b.is_alive()
    assert outcome == {"a": "superseded", "b": None}  # one of them delivers
    real.release()


def test_deck_cache_operations_give_up_when_the_renderer_stays_busy(tmp_path: Path) -> None:
    import time

    manager, _events = _real_push_manager(tmp_path)
    hog, release = _hog(manager)
    try:
        started = time.monotonic()
        assert manager.promote_deck_page("hallway", "home", lock_timeout_s=0.1) is False
        assert manager.warm_deck_page("home", "hallway", lock_timeout_s=0.1) is False
        assert manager.clear_deck_cache("hallway", lock_timeout_s=0.1) is False
        assert time.monotonic() - started < 2.0
    finally:
        release.set()
        hog.join(5)
    assert manager.clear_deck_cache("hallway", lock_timeout_s=1.0) is True
