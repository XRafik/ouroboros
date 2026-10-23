# Managed Update Rule

Managed updates preserve target, admission, local work and recovery. Persist before mutation so interruption replays without guessing.

- Separate the local work branch from the official feed (`ouroboros/update_channels.py`; ARCHITECTURE §8).
- Bind description and qualification to preflight's exact base/target; disclose missing checks and accepted FAILs without a veto (`tests/test_update_qualification.py`). Apply binds those pins, fences writers and re-plans before mutation; reopen after verified abort/rollback or healthy restart. Evolution shares admission.
- Conversation and repo-writing differ: destructive apply, replace, rollback and materialization refuse turns; while the authorized resolver owns the transaction (`assisted_resolution`/`committing_assisted`), Main answers but other tasks' repo tools stay refused (`worker_chat_lane.conversation_admitted_during_update`); steering uses `tell_task`.
- Keep dirty work out of merge history: stash, then restore it. Never drop an update stash automatically, even after success — `rescue-local-*` pins the exact object and explicit Git cleanup exists. Only a real Git conflict invokes the reviewed resolver; filenames create no policy.
- Record restoration intent in the existing transaction before apply and consume it on every completion (restored, preserved or incomplete); failed persistence keeps the marker, and an interrupted replay never resets or reapplies over returned or later work (`supervisor/update_merge.py`).
- Schema 1 is the default; stash restoration and a rollback carrying stashed work need schema 2 before old code is checked out: an older strict reader refuses an interrupted new state without a reset. `stash_restored` means a recorded successful apply, never intent. Restart the actual desktop app, Docker/service or direct server, not its browser tab; in-app Restart refuses while a restoration is pending.
- The resolver stages the full merge, tracked binaries included; review gets exact staged mode/blob/size and parent object ids, and missing metadata blocks.
- A managed merge commit requires a green full suite on the exact candidate (“The tiered commit and CI gates”). Any non-commit resolver terminal rolls back and best-effort preserves the attempt on its failed-update branch; recovery needs the fresh rescue, not that branch. Boot holds a Paused commit (`postcommit_resume`); its Stop rolls back.
- Fresh rescue precedes every destructive rollback and boot re-materialization; a capture failure is fail-open but durably disclosed with a transaction pointer (the choke point: ARCHITECTURE §2).
- Restore fences writers and pins HEAD; promotion binds one SHA for QA/push. Retain after-update facts for panel and mind; the host never decides whether to tell the owner (`tests/test_update_generation_facts.py`).
- `git_bootstrap.json` is reused only for an identical clean checkout and dependency fingerprint; every checkout or rollback invalidates it, only a successful smoke recreates it (ARCHITECTURE §2). Test the zero-reset/zero-smoke repeat and invalidation by changes or transactions.

Enforcement: `tests/test_update_merge_policy.py`, `tests/test_update_dirty_stash.py`, `tests/test_update_stash_recovery.py` (real Git, crash/replay, Restart), `tests/test_update_hardening.py`, `tests/test_update_tx_corrupt_quarantine.py`.

Native hosts add no source updater: the launcher hook verifies its installed artifact before core start and reads it back after boot before finalization; failure rolls back, and a worker self-restart keeps an incomplete native adoption incomplete even when the core SHA matches.
