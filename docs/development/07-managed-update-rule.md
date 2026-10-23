# Managed Update Rule

Managed updates rewrite the live tree under owner authority. Persist target, writer/local-work custody and resolver/recovery authority before mutation for replay.

- Separate the local work branch from the official feed (`ouroboros/update_channels.py`; ARCHITECTURE §8).
- Preflight selects an exact target and binds description and qualification to it; missing checks and accepted FAILs are disclosed without a veto (`tests/test_update_qualification.py`). Apply binds base and target. Smart, replace and Restore observe the effective index lock before work stops; an existing lock stays untouched and returns typed not-applied. Apply closes writers, drains direct turns, stops workers/services and re-plans. Reopen only after verified abort/rollback or healthy restart. Evolution cleanup shares lock/admission.
- Destructive apply, replace, rollback and materialization refuse turns; in `assisted_resolution`/`committing_assisted`, Main answers but other tasks’ repo tools stay refused (`worker_chat_lane.conversation_admitted_during_update`); steer through `tell_task`.
- Stash dirty work outside merge history, then restore. Never automatically drop an update stash, even on success: `rescue-local-*` pins it for Git cleanup. Only Git conflicts invoke the reviewed resolver; filenames create no policy.
- Persist restoration intent before apply; consume it on completion (restored, preserved or incomplete). Failed persistence keeps the marker; interrupted replay never resets/reapplies over returned or later work (`supervisor/update_merge.py`).
- Schema 1 is default; stash restoration and rollback with stashed work need schema 2 before checkout: older strict readers refuse interrupted new state without resetting. `stash_restored` records successful apply, never intent. Restart the desktop app, Docker/service or direct server, not its tab; in-app Restart refuses pending restoration.
- The resolver stages the merge, binaries included; review needs exact staged mode/blob/size and parent ids. Missing metadata blocks.
- Managed merge commits need a green full suite on the exact candidate (“The tiered commit and CI gates”). Non-commit resolver terminals roll back and best-effort preserve the failed-update branch; recovery requires fresh rescue. Boot holds Paused commits (`postcommit_resume`); Stop rolls back.
- Fresh rescue precedes destructive rollback and boot re-materialization; capture failure is fail-open, durably disclosed with a transaction pointer (ARCHITECTURE §2).
- `git_ops.host_git_env` disables optional locks/diff refresh; reads never repair. Writers retain mandatory locks/repair. Refusals retain stderr; no tree effect means not-applied, never restored.
- Manual Restore fences writers, pins HEAD, never pushes, and interrupts without restart handoffs. Promotion binds one development SHA for local QA and push. After-update facts reach panel and mind; the host never decides whether to tell the owner (`tests/test_update_generation_facts.py`).
- Apply shows engine transition/work (unreadable means unknown), installed Python/SQLite versus target bundle documentation, and forward-only data. `engine_pin_policy` also drives restart; in-app Update keeps the interpreter/SQLite.
- `git_bootstrap.json` needs identical clean checkout/dependency fingerprints; checkout/rollback invalidates it, successful smoke recreates it (ARCHITECTURE §2). Test zero-reset/zero-smoke repeats and change/transaction invalidation.

Enforcement: `tests/test_update_merge_policy.py`, `tests/test_update_dirty_stash.py`, `tests/test_update_stash_recovery.py` (real Git, crash/replay, Restart), `tests/test_update_hardening.py`, `tests/test_update_tx_corrupt_quarantine.py`.

Native hosts add no source updater: launcher hooks verify the artifact before core start and read back adoption before finalizing boot. Failure rolls back; worker self-restart cannot complete native adoption even when core SHA matches.
