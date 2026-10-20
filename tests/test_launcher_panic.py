"""Tray Panic races and installation custody, with all process/HTTP effects replaced."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from ouroboros import launcher_background as background
from ouroboros import launcher_readiness as readiness


def disarm_emergency_owners(monkeypatch, events):
    """Keep the real emergency coordinator and persistence; replace native stop effects."""
    from ouroboros import server_control

    monkeypatch.setattr(server_control, "_restart_stop_requested", False)
    for path in ("ouroboros.startup_historical_audit.audit.stop", "ouroboros.maintenance.child.stop",
                 "ouroboros.storage.count.stop", "ouroboros.storage_free.free.stop"):
        monkeypatch.setattr(path, lambda: None)
    for path in ("ouroboros.tools.shell.kill_all_tracked_subprocesses", "ouroboros.workspace_executor.kill_all_foreground",
                 "ouroboros.tools.services.kill_all_services", "ouroboros.extension_companion.panic_kill_all"):
        monkeypatch.setattr(path, lambda *a, **kw: [])
    monkeypatch.setattr("ouroboros.local_model.get_manager", lambda **kw: None)
    monkeypatch.setattr("ouroboros.claudexor_daemon.get_owned_daemon", lambda **kw: None if kw.get("create") is False
                        else SimpleNamespace(stop_outcome=lambda: "nothing_to_stop"))
    monkeypatch.setattr("ouroboros.process_custody.stop_ledgered_processes", lambda *a, **kw: [])
    monkeypatch.setattr("multiprocessing.active_children", lambda: [])
    monkeypatch.setattr("ouroboros.process_scope.panic_scope_census", lambda root: events.append("census"))
    monkeypatch.setattr(server_control, "stop_restart_successor", lambda: [])
    monkeypatch.setattr(server_control, "_persist_panic_controls", lambda root: None)


@pytest.fixture
def stopped_world(monkeypatch, tmp_path):
    from ouroboros import config, server_control

    events, exited = [], threading.Event()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(background, "indicator_class", lambda: None)
    monkeypatch.setattr(background, "_active", None)
    disarm_emergency_owners(monkeypatch, events)
    monkeypatch.setattr(server_control.os, "_exit", lambda code: (events.append(("exit", code)), exited.set()))
    bg = background.Background(lambda: (events.append("ordinary exit"), exited.set()), lambda: 1, threading.Event())
    yield bg, events, exited
    for thread in threading.enumerate():
        if thread.name.startswith(("panic-", "ouroboros-indicator-panic")):
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_panic_latches_before_starting_any_post_thread(stopped_world, monkeypatch):
    bg, _, _ = stopped_world
    threads = []
    monkeypatch.setattr(background.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: threads.append(kw)))
    bg.request_panic()
    assert bg.shutdown.is_set() and bg.quit.is_set(), "click must fence handoff before the POST thread runs"
    assert len(threads) == 1 and threads[0]["daemon"] is False


def test_early_panic_never_posts_to_the_stale_or_default_port(stopped_world, monkeypatch):
    bg, events, exited = stopped_world
    posts = []

    class AcceptingForeignServer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(background.urllib.request, "urlopen",
                        lambda request, **kw: posts.append(request.full_url) or AcceptingForeignServer())
    bg.request_panic()
    assert exited.wait(5), "a foreign server accepting /panic cannot keep this bootstrap alive"
    assert posts == [], "a port file/default is not this generation's endpoint authority"
    assert "census" in events and "ordinary exit" not in events


@pytest.mark.parametrize("state", ["absent", "dead", "foreign", "wrong-port", "reused-pid", "owned"])
def test_panic_endpoint_requires_the_live_current_generation(monkeypatch, tmp_path, state):
    from ouroboros import server_process

    proc = SimpleNamespace(pid=41, poll=lambda: 0 if state == "dead" else None)
    binding = {"pid": 42 if state == "foreign" else 41, "port": 9001 if state == "wrong-port" else 9000}
    monkeypatch.setattr(server_process, "read_service_bindings", lambda root: {"main": binding})
    monkeypatch.setattr(server_process, "service_binding_is_live", lambda value: state != "reused-pid")
    port = readiness.owned_server_port(None if state == "absent" else proc, 9000, tmp_path)
    assert port == (9000 if state == "owned" else None)


def test_early_panic_stops_retained_daemon_custody_and_its_work(stopped_world, monkeypatch, tmp_path):
    from ouroboros import claudexor_daemon as daemon, process_custody as custody, platform_layer

    bg, events, exited = stopped_world
    manager = daemon.OwnedClaudexorDaemon()
    retained = {"daemon": True, "work": True}
    written, settlement = [], threading.Event()
    row = {"pid": 444, "purpose": daemon.CUSTODY_PURPOSE}
    monkeypatch.setattr(daemon, "get_owned_daemon", lambda **kw: None if kw.get("create") is False else manager)
    monkeypatch.setattr(daemon, "verify_owned_home", lambda **kw: "")
    def classify(**kwargs):
        settlement.wait(3)  # asynchronous settlement must not be the first physical stop
        return None, daemon._TRANSPORT_UNREACHABLE, ""

    monkeypatch.setattr(manager, "_classify_liveness", classify)
    monkeypatch.setattr(manager, "_settle_exited_child", lambda: None)
    monkeypatch.setattr(manager, "_terminate_child", lambda: False)
    monkeypatch.setattr(custody, "process_stop_snapshot", lambda root, purposes: [row])
    monkeypatch.setattr(custody, "pending_process_stops", lambda root, purposes: [] if not any(retained.values()) else [row])
    monkeypatch.setattr(platform_layer, "collect_descendant_pids", lambda pid: {445})

    def stop(root, purposes, *, unconfirmed=None, expected_entries=None, timeout_sec=None):
        assert root == tmp_path and purposes == {daemon.CUSTODY_PURPOSE}
        assert expected_entries == [row] or timeout_sec == 0
        retained.update(daemon=False, work=False)
        events.append("retained custody stopped")
        return [444]

    monkeypatch.setattr(custody, "stop_ledgered_processes", stop)
    # Persistence is fast: a stop cannot rely on disk writes incidentally giving
    # the asynchronously started daemon settlement time to reach its kill.
    from ouroboros import server_control
    write_flag = server_control._write_panic_flag

    def persist(root):
        written.append(dict(retained))
        settlement.set()
        write_flag(root)

    monkeypatch.setattr(server_control, "_write_panic_flag", persist)
    bg.request_panic()
    assert exited.wait(5)
    assert retained == {"daemon": False, "work": False}, "ordinary launcher teardown deliberately retains these"
    assert written == [{"daemon": False, "work": False}], "request retained roots before persistence, not during async settlement"
    assert "retained custody stopped" in events and "census" in events and "ordinary exit" not in events
    assert (tmp_path / "state/panic_stop.flag").read_text() == "panic"
