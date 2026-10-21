"""#1297: compare the confined HTTP source reader with the existing placement reader.

These fixtures use real pack/sidecar producers and synthetic task stores. The
benchmark counts work, not just time; timings are observations, never a threshold.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from hashlib import sha256
from pathlib import Path

import pytest

from ouroboros import artifacts, confined_files, evidence_packs as packs
from ouroboros.task_results import write_task_result


def _packed(root, task="wanted"):
    raw = b"exact checkpoint bytes"
    ref = artifacts.store_actor_source_bytes(root, task, category="context_checkpoints", source_id="record",
                                             data=raw, extension="json")
    loose = artifacts.task_artifact_dir_path(root, task) / ref["path"]
    pack, sidecar = packs.write_pack(root, task, 1, [{"sha256": ref["sha256"], "size": len(raw),
        "kind": packs.CHECKPOINT, "path": ref["path"], "source": loose}])
    loose.unlink()
    return ref, raw, loose, pack, sidecar


def _outcome(call):
    try:
        return ("value", call())
    except (OSError, ValueError) as exc:
        return (type(exc).__name__, exc.errno if isinstance(exc, OSError) else None)


def _placement(anchor, placement, task="wanted"):
    if placement == "canonical":
        return anchor
    root = (anchor / "task_drives" / task if placement == "legacy"
            else anchor / "state/headless_tasks" / task / "data")
    write_task_result(anchor, task, "completed", headless_child_drive_root=str(root))
    return root


@pytest.mark.parametrize("fault", ["none", "loose_good", "loose_bad", "pack_bad", "pack_missing", "sidecar_bad",
                                   "unrelated_bad", "absent", "absent_with_unrelated_bad", "bad_loose_missing_pack",
                                   "index_bad"])
@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("placement", ["canonical", "headless", "legacy"])
def test_confined_and_existing_source_fallback_outcomes(tmp_path, fault, metadata, warm, placement):
    # Independent roots ensure the original reader does not warm the candidate's
    # cache before its cold lookup. Both use real producers and SQLite indexes.
    reader = packs.handle_info if metadata else packs.handle_bytes
    outcomes = []
    for confined in (False, True):
        anchor = tmp_path / ("candidate" if confined else "original")
        root = _placement(anchor, placement)
        ref, raw, loose, pack, _ = _packed(root)
        kwargs = {"anchor": anchor} if confined else {}
        if warm:
            reader(root, "wanted", ref["path"], **kwargs)
        if fault == "loose_good":
            loose.write_bytes(raw)
        if fault in {"loose_bad", "bad_loose_missing_pack"}:
            loose.write_bytes(b"wrong")
        if fault == "pack_bad":
            pack.write_bytes(b"broken stream")
        if fault in {"pack_missing", "bad_loose_missing_pack"}:
            pack.unlink()
        if fault == "sidecar_bad":
            (packs.packs_dir(root) / "wanted.members.json").write_text("{")
        if fault in {"unrelated_bad", "absent_with_unrelated_bad"}:
            (packs.packs_dir(root) / "other.members.json").write_text("{")
        if fault == "index_bad":
            (packs.packs_dir(root) / packs.INDEX_NAME).write_bytes(b"damaged optional index")
        relative = ref["path"] if not fault.startswith("absent") else ref["path"].replace("record-", "absent-")
        outcomes.append(_outcome(lambda: reader(root, "wanted", relative, **kwargs)))
    assert outcomes[0] == outcomes[1]


def test_confined_source_handles_canonical_child_and_reciprocal_retry(tmp_path):
    root, old, new = tmp_path / "data", "before", "after"
    child = root / "task_drives" / old
    ref, raw, _loose, _pack, _ = _packed(child, old)
    write_task_result(root, old, "completed", retry_task_id=new)
    write_task_result(root, new, "completed", timeout_retry_from=old, original_task_id=old)
    assert artifacts.read_actor_source_bytes(root, new, ref, anchor=root) == raw
    write_task_result(root, old, "completed", retry_task_id="another")
    with pytest.raises(FileNotFoundError):
        artifacts.read_actor_source_bytes(root, new, ref, anchor=root)


@pytest.mark.parametrize("count", [20, 2000])
@pytest.mark.parametrize("placement", ["canonical", "headless", "legacy"])
def test_confined_placement_work_stays_constant(tmp_path, monkeypatch, record_property, count, placement):
    anchor = tmp_path / "data"
    root = _placement(anchor, placement, "zz-target")
    ref, raw, _loose, _pack, sidecar = _packed(root, "zz-target")
    directory = packs.packs_dir(root)
    # A real sidecar per unrelated historical task; none of its packs is read by
    # either target lookup. Keep enough metadata for the real index builder.
    for number in range(count):
        task = f"history-{number:05d}"
        (directory / packs.sidecar_name(task, 1)).write_text(json.dumps({**sidecar, "task_id": task}))
    assert packs.handle_bytes(root, "zz-target", ref["path"]) == raw  # warm existing SQLite cache
    reads, enumerated, scans = [], [], []
    real_open, real_entries, real_sidecar = confined_files.ConfinedDirectory.open, confined_files.ConfinedDirectory.entries, packs.read_sidecar

    def opened(self, name):
        reads.append(name)
        return real_open(self, name)

    def entries(self, **kwargs):
        found = real_entries(self, **kwargs)
        enumerated.append(len(found))
        return found

    real_names = packs._sidecar_names
    def names(root):
        scans.append(str(root))
        return real_names(root)

    monkeypatch.setattr(packs, "_sidecar_names", names)
    decoded = []
    def sidecar_read(path, **kwargs):
        decoded.append(path.name)
        return real_sidecar(path, **kwargs)

    monkeypatch.setattr(confined_files.ConfinedDirectory, "open", opened)
    monkeypatch.setattr(confined_files.ConfinedDirectory, "entries", entries)
    monkeypatch.setattr(packs, "read_sidecar", sidecar_read)
    measurements = []
    for mode in ("cached", "cached_absent", "confined_found", "confined_absent"):
        reads.clear()
        enumerated.clear()
        decoded.clear()
        scans.clear()
        times = []
        for _ in range(3):
            relative = ref["path"].replace("record-", "absent-") if mode.endswith("absent") else ref["path"]
            start = time.perf_counter()
            outcome = _outcome(lambda: packs.handle_bytes(root, "zz-target", relative,
                                                         **({} if mode.startswith("cached") else {"anchor": anchor})))
            times.append(time.perf_counter() - start)
            assert outcome == (("FileNotFoundError", None) if mode.endswith("absent") else ("value", raw))
        measurements.append({"mode": mode, "unrelated_tasks": count, "placement": placement, "trials": 3,
                             "median_seconds": statistics.median(times), "sidecars_decoded_total": len(decoded),
                             "enumerated_entries_total": sum(enumerated), "sidecar_scans_total": len(scans),
                             "confined_open_calls_total": len(reads)})
        assert decoded == []
        assert enumerated == []
        assert scans == []
    record_property("placement_cost", json.dumps(measurements))
    print("PLACEMENT_COST " + json.dumps(measurements))
    evidence = os.environ.get("OUROBOROS_TEST_EVIDENCE_ROOT")
    if evidence:
        target = Path(evidence) / f"placement-cost-{placement}-{count}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(measurements, indent=2) + "\n")


@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("placement", ["canonical", "headless", "legacy"])
def test_warm_cache_corruption_preserves_existing_authority(tmp_path, record_property, metadata, placement):
    anchor = tmp_path / "data"
    root = _placement(anchor, placement)
    ref, raw, _loose, _pack, _ = _packed(root)
    reader = packs.handle_info if metadata else packs.handle_bytes
    expected = {"size": len(raw), "sha256": ref["sha256"], "loose": False} if metadata else raw
    assert reader(root, "wanted", ref["path"]) == expected
    (packs.packs_dir(root) / "wanted.members.json").write_text("{")
    cached = _outcome(lambda: reader(root, "wanted", ref["path"]))
    confined = _outcome(lambda: reader(root, "wanted", ref["path"], anchor=anchor))
    record_property("warm_cache_contract", json.dumps({"metadata": metadata, "placement": placement,
                    "cached": cached[0], "confined": confined[0]}))
    assert cached == confined == ("value", expected)


def test_trusted_placement_selection_cannot_reopen_swapped_pack_directory(tmp_path, monkeypatch):
    from tests.test_task_download_confinement import _junction_or_link

    root = tmp_path / "data"
    ref, _raw, _loose, pack, _ = _packed(root)
    original = packs._locate
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / pack.name).write_bytes(b"external canary")
    selected = []
    def swap(*args, **kwargs):
        located = original(*args, **kwargs)
        selected.append(located[0])
        pack.parent.rename(pack.parent.with_name("packs-held"))
        _junction_or_link(pack.parent, outside)
        return located
    monkeypatch.setattr(packs, "_locate", swap)
    with pytest.raises(OSError):
        packs.handle_bytes(root, "wanted", ref["path"], anchor=root)
    assert selected == [pack]
