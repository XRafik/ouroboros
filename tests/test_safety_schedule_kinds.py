"""Schedule writer provenance is host-authored and freezes with an accepted occurrence."""
from copy import deepcopy

from tests.test_schedule_occurrence import q as queue_fixture
q = queue_fixture
from ouroboros.task_results import load_task_result


def row():
    return {"id": "schedule", "name": "test", "enabled": True,
            "trigger": {"type": "once", "run_at": "2000-01-01T00:00:00+00:00"},
            "task": {"text": "Do work", "metadata": {"work_kind": "owner", "resource_intent": {"kind": "system_repo"}}}}


def test_writer_overrides_payload_and_accepted_occurrence_freezes(q):
    from supervisor.queue_schedules import _task_from_schedule
    record = q.queue.upsert_scheduled_task(row(), drive_root=q.root, writer_kind="owner", actor="owner:gateway")
    assert record["writer_kind"] == "owner"
    assert "work_kind" not in record["task"]["metadata"]
    assert _task_from_schedule(record)["metadata"]["work_kind"] == "owner"
    # Agent editing the same record owns its new occasion; payload cannot retain owner-kind.
    record = q.queue.upsert_scheduled_task(row(), drive_root=q.root, writer_kind="consciousness", actor="agent",
        writer_metadata={"initiator": "consciousness", "consciousness_autonomy": "act", "origin_wake_task_id": "wake"})
    assert record["writer_kind"] == "consciousness"
    q.queue.check_scheduled_tasks()
    [accepted] = q.pending
    assert accepted["metadata"]["work_kind"] == "consciousness"
    assert accepted["metadata"]["origin_wake_task_id"] == "wake"
    receipt = deepcopy(load_task_result(q.root, accepted["id"])["schedule_admission"])
    changed = row()
    changed["enabled"] = False  # edit consumed row without asking to rearm it
    q.queue.upsert_scheduled_task(changed, drive_root=q.root, writer_kind="owner", actor="owner:gateway")
    assert load_task_result(q.root, accepted["id"])["schedule_admission"] == receipt
    assert accepted["metadata"]["work_kind"] == "consciousness"


def test_legacy_forged_stamp_is_not_a_host_fact(q):
    from supervisor.queue_schedules import _task_from_schedule
    record = row()
    assert _task_from_schedule(record)["metadata"]["work_kind"] == "consciousness"
    record["source"] = "owner"
    assert _task_from_schedule(record)["metadata"]["work_kind"] == "owner"
    record["task"]["metadata"]["initiator"] = "consciousness"
    assert _task_from_schedule(record)["metadata"]["work_kind"] == "consciousness"


def test_schedule_lifecycle_edit_changes_writer(q):
    q.queue.upsert_scheduled_task(row(), drive_root=q.root, writer_kind="owner", actor="owner:gateway")
    outcome = q.queue.mutate_scheduled_task("disable", "schedule", reason="later", actor="agent", drive_root=q.root,
                                          writer_kind="consciousness")
    assert outcome["changed"]
    [stored] = q.queue.list_scheduled_tasks(q.root)["tasks"]
    assert stored["writer_kind"] == "consciousness"
    q.queue.mutate_scheduled_task("restore", "schedule", reason="resume", actor="owner:gateway", drive_root=q.root,
                                  writer_kind="owner")
    [stored] = q.queue.list_scheduled_tasks(q.root)["tasks"]
    assert stored["writer_kind"] == "owner"


def test_manifest_edit_replaces_writer_but_readiness_does_not():
    from ouroboros.consciousness_authority import stamp_manifest_schedule
    previous = {"writer_kind": "owner", "task": {"text": "old"}, "skill_content_hash": "one"}
    resync = {**previous, "enabled": False}
    stamp_manifest_schedule(previous, resync)
    assert resync["writer_kind"] == "owner"
    changed = {**previous, "skill_content_hash": "two"}
    stamp_manifest_schedule(previous, changed)
    assert changed["writer_kind"] == "consciousness"


def test_legacy_owner_origin_at_admission_is_positive_provenance(q):
    for task_id, origin, metadata, expected in [
        ("owner", {"message_id": "owner-message"}, {}, "owner"),
        ("unknown", None, {}, "consciousness"),
        ("presence", {"message_id": "owner-message"}, {"presence": {}}, "consciousness"),
    ]:
        task = q.queue.enqueue_task({"id": task_id, "type": "task", "text": "work",
                                    "origin_message_ref": origin, "metadata": metadata}, restoring_snapshot=True)
        assert task["metadata"]["work_kind"] == expected
