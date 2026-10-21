"""Production gateway/transport replay of exact offline engine HTTP responses.

No engine schemas are reconstructed here. Guard mutations are named explicitly;
their starting problems, continuation envelopes and catalogs are recorded wire.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
import json
from pathlib import Path
import queue
from types import SimpleNamespace

import httpx
import pytest

from ouroboros import llm_claudexor as transport, model_wait, usage_accounting as ua
from ouroboros.gateways import claudexor as wire
from ouroboros.llm import LLMClient
from ouroboros.llm_substitution import CapabilityRetry
from tests._usage_store_testing import ledger_rows
from tests.claudexor_capability_wire import read_capture
from tests.test_claudexor_capability_engine import OLDER_TREE, TASK, TREE, call, notices

FIXTURES = Path(__file__).parent / "fixtures/llm_wire/claudexor_capability"


def capture(name):
    value = read_capture(FIXTURES / f"{name}.json")
    assert value["engine_tree"] == (OLDER_TREE if name == "older" else TREE)
    return value


def results(name):
    return [json.loads(row["body_utf8"]) for row in capture(name)["wire"]
            if row["path"].endswith("/result") and row["status"] == 200]


@pytest.fixture
def replay(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("OUROBOROS_DATA_DIR", str(root))
    monkeypatch.setenv("OUROBOROS_SETTINGS_PATH", str(root / "settings.json"))
    monkeypatch.setenv("OUROBOROS_MODEL_ACCOUNTS", "{}")
    monkeypatch.setenv("TOTAL_BUDGET", "100")
    monkeypatch.setattr(transport.config, "CLAUDEXOR_MODEL_POLL_INTERVAL_SEC", 0)
    uploads, ids, reads = [], [], []
    frames = defaultdict(deque)

    def respond(request):
        key = (request.method, request.url.raw_path.decode())
        reads.append(key)
        assert frames[key], f"Unrecorded engine request: {key}"
        row = frames[key].popleft()
        return httpx.Response(row["status"], content=row["body_utf8"].encode())

    original = wire.ClaudexorGateway.__init__

    def initialize(gateway, endpoint):
        original(gateway, endpoint)
        gateway._client.close()
        gateway._client = httpx.Client(base_url="http://127.0.0.1:1", transport=httpx.MockTransport(respond))

    monkeypatch.setattr(wire.ClaudexorGateway, "__init__", initialize)
    upload = wire.ClaudexorGateway.upload_model_request

    def upload_record(gateway, payload, *, idempotency_key):
        uploads.append(deepcopy(payload))
        ids.append(idempotency_key)
        return upload(gateway, payload, idempotency_key=idempotency_key)

    monkeypatch.setattr(wire.ClaudexorGateway, "upload_model_request", upload_record)

    def gateway(*_args, **_kwargs):
        instance = wire.ClaudexorGateway(wire.DaemonEndpoint("127.0.0.1", 1, "offline"))
        instance.handshake()
        return instance

    monkeypatch.setattr(transport, "ensure_owned_gateway", gateway)
    monkeypatch.setattr(transport, "read_owned_gateway", gateway)
    # Every Accounts read in these stories is answered by the recorded wire, never an engine.
    from ouroboros import claudexor_daemon as owned
    monkeypatch.setattr(owned, "owned_config_dir", lambda: root)
    monkeypatch.setattr(owned, "get_owned_daemon", lambda: SimpleNamespace(status_dict=lambda: {"state": "running"}))
    monkeypatch.setattr(wire, "discover_daemon_at", lambda *_: wire.DaemonEndpoint("127.0.0.1", 1, "offline"))
    monkeypatch.setattr(owned.OwnedClaudexorDaemon, "ensure_running", lambda *_: pytest.fail("passive read woke engine"))
    events = queue.Queue()
    from ouroboros.task_results import write_task_result
    write_task_result(root, TASK["id"], "running")

    def start(name, *, mutate=None):
        records = capture(name)["wire"]
        for row in records:
            if mutate:
                mutate(row)
            frames[(row["method"], row["path"])].append(row)
        return SimpleNamespace(root=root, home=root, scenario=name, client=LLMClient(), gateway=gateway,
                               events=events, uploads=uploads, ids=ids, reads=reads, records=records)

    with ua.usage_scope(ua.UsageScope(drive_root=root, task_id=TASK["id"], root_task_id=TASK["id"])), \
            model_wait.task_model_wait_scope(task=TASK, drive_root=root, event_queue=events, worker_slot_held=False):
        yield start


def status_payload(monkeypatch, f):
    from ouroboros.gateway.claudexor_accounts import _read_status_payload
    return _read_status_payload(False)


EXPECT = {  # scenario: (uploads, notices, final error code or None)
    "serve": (2, 0, None), "both": (2, 1, "model_capability_refused"), "pin": (1, 1, "model_capability_refused"),
    "no_alternative": (1, 1, "model_capability_refused"), "retry_invalid": (2, 0, "model_capability_refused"),
    "generic_serve": (2, 0, None), "generic_both": (2, 0, "invalid_request"), "older": (1, 0, "invalid_request"),
}


@pytest.mark.parametrize("name", list(EXPECT))
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_real_wire_transport(replay, monkeypatch, name, asynchronous):
    f = replay(name)
    uploads, delivered, code = EXPECT[name]
    kwargs = {"model_account_override": "a"} if name == "pin" else {}
    if code is None:
        answer, usage = call(f, asynchronous, **kwargs)
        assert answer["content"] == "served by b" and len(usage["ledger_attempt_ids"]) == 2
    else:
        with pytest.raises(transport.ClaudexorModelError) as raised:
            call(f, asynchronous, **kwargs)
        assert raised.value.code == code
    assert len(f.uploads) == len(set(f.ids)) == uploads
    assert len(ledger_rows(f.root)) == uploads
    if uploads == 2:
        assert {**f.uploads[0], "account": {"mode": "auto"},
                "retryOfOperationId": f.uploads[1]["retryOfOperationId"]} == f.uploads[1]
    else:
        assert all("retryOfOperationId" not in request for request in f.uploads)
    rows = notices(f, monkeypatch)
    assert len(rows) == delivered
    if rows:
        from ouroboros.llm_substitution import capability_notice
        notice_id, text = capability_notice(raised.value.problem)
        assert rows[0]["text"] == text + "\nFirst seen in Helper call."
        context = raised.value.problem["context"]
        assert context["nextStep"] in rows[0]["text"] and context["retryOnOtherAccount"] is False


@pytest.mark.parametrize("scenario", ["continuation", "preferred", "third", "returns"])
def test_real_wire_engine_stories(replay, monkeypatch, scenario):
    from tests import test_claudexor_capability_engine as engine
    story = {"continuation": engine.test_bound_continuation_and_next_call,
             "preferred": engine.test_preferred_account_yields_to_mark,
             "third": engine.test_double_refusal_leaves_a_third_account,
             "returns": engine.test_one_notice_per_episode}[scenario]
    f = replay(scenario)
    if scenario == "returns":
        f.home = f.root / "home"  # the recorded provider steering is already in the wire
        f.home.mkdir(parents=True, exist_ok=True)
    story(f, monkeypatch)


@pytest.mark.parametrize("guard", ["pin", "unknown", "unsettled", "generation_started",
                                   "no_typed_permission", "second_retry", "granted"])
def test_typed_guards_from_recorded_facts(guard, monkeypatch, tmp_path):
    fact = results("serve")[0]
    payload = deepcopy(capture("serve")["uploads"][0])
    context = fact["problem"]["context"]
    state = "unresolved" if guard == "unsettled" else "settled"
    if guard == "generation_started":
        context["generationStarted"] = True
    if guard == "no_typed_permission":
        context.pop("retryOnOtherAccount")
    if guard == "pin":
        payload["account"] = {"mode": "pin", "profileId": "a"}
    error = transport.ClaudexorModelError(fact["problem"], unknown=guard == "unknown",
                                         operation_id=context["operationId"], route=fact["route"])
    error.physical_attempt_capture = SimpleNamespace(state=state, attempt_id="captured-first")
    invocation = SimpleNamespace(payload=payload, operation_id=context["operationId"], root=tmp_path)
    policy = CapabilityRetry()
    if guard == "second_retry":
        policy.original = error
    monkeypatch.setattr(policy, "announce", lambda *_: None)
    assert (policy.refused(invocation, error) is not None) is (guard == "granted")


def test_older_engine_is_not_asked_for_marks(replay, monkeypatch):
    f = replay("older")
    status = status_payload(monkeypatch, f)
    assert status["reads"]["accounts"] == "ok"
    assert "routing_evidence" not in status["profiles"] and "routing_evidence_read" not in status["profiles"]
    assert ("GET", "/v2/accounts/routing-evidence?includeCapabilities=true") not in f.reads


def test_a_failed_marks_read_is_one_dated_fact(replay, monkeypatch):
    def fail(row):
        if row["path"].startswith("/v2/accounts/routing-evidence"):
            row.update(status=500, body_utf8=json.dumps({"code": "internal", "message": "store", "retryable": True}))
    f = replay("both", mutate=fail)
    with pytest.raises(transport.ClaudexorModelError):
        call(f)
    status = status_payload(monkeypatch, f)
    assert status["reads"]["accounts"] == "ok"
    assert "routing_evidence" not in status["profiles"]
    assert status["profiles"]["routing_evidence_read"]["state"] == "failed"


def test_marks_ride_a_successful_account_read(replay, monkeypatch):
    f = replay("both")
    with pytest.raises(transport.ClaudexorModelError):
        call(f)
    evidence = status_payload(monkeypatch, f)["profiles"]["routing_evidence"]
    assert [row["profile_id"] for row in evidence["capabilities"]] == ["a", "b"]
    assert ("GET", "/v2/accounts/routing-evidence?includeCapabilities=true") in f.reads
