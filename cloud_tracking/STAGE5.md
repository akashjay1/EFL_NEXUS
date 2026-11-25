# Stage 5 implementation status — incomplete

The new integration is deliberately disabled by `cloud_monitoring.READY_FOR_DEVICE_PILOT` until the remaining correctness and Windows checks pass. Do not enable it for operators yet. Stage 6 has not started. No backend schema, Edge Function or production settings were changed.

Created: `cloud_monitoring/__init__.py`, `cloud_client.py`, `device_identity.py`, `operator_identity.py`, `heartbeat_service.py`, `session_manager.py`, `offline_queue.py`, `security.py`; `tests/test_cloud_monitoring.py`.

Modified: monitoring hooks in `main_app.py`, enrollment dialog in `operator_presence_settings.py`, hidden imports in `EFL_NEXUS.spec`, required module list in `build_release.py`. Existing unrelated working-tree edits were retained. `operator_presence.py` validation helpers are reused; its old RPC tracker is no longer selected by the new integration.

Implemented foundations: exact Edge URLs/headers; Credential Manager records per Windows account; locally persisted pending enrollment credentials before submission; SQLite FULL/WAL outbox; stable event IDs/sequences; validated KPI identity via the active ConfigStore path; heartbeat coalescing; high-water validation; overflow counters followed by a contiguous recording-gap event; process lease files for crash recovery; background worker, timeouts and jitter; optional ProgramData identity provisioning helper.

Machine identity is outside application folders at `%PROGRAMDATA%/EFL_NEXUS_Monitoring/installation.json`. Intended ACL: System/Administrators full access, Users read/execute. A local Windows MachineGuid binding is not transmitted and rejects identity files copied from another Windows installation. Full OS image cloning still requires deployment-time identity reset; this is not hardware attestation.

Executed: 2 new outbox tests, 4 existing presence tests, 4 packaging tests, 6 launcher/KPI bridge tests and 18 KPI profile tests passed (34 total). KPI suite emitted Tk callback teardown errors despite passing assertions; these need investigation before compatibility signoff. Monitoring/integration Python files parsed successfully. A Python 3.12 frozen build, installer execution, Credential Manager integration and cross-account ACL enforcement have NOT been verified. Packaging unit tests do not establish release compatibility.

Remaining required work:

- Implement and test seven-day expiry with explicit server-compatible recording-gap reconciliation; the current queue retains expired events and surfaces backend rejection rather than silently dropping them.
- Guarantee terminal-close recording at queue capacity and persistence across a process exit during an in-flight request. Current 1.5-second launcher grace can expire before a network request returns; recovery exists but clean-close delivery is not guaranteed.
- Bound and clean historical launch/lease metadata; isolate failing/revoked historical credentials from healthy sessions; reconcile conflicts automatically where safe.
- Provision machine identity through the installer/setup UI with elevation, safe concurrent creation and verified reparse-point handling. The helper exists but installer automation is not wired.
- Complete enrollment/re-enrollment UI, provisioning UX, and first-run recovery after absent machine identity. Existing active enrollment replacement currently requires restarting.
- Add required worker/transport/identity/Windows integration tests, including real credentials stored and removed in isolated test targets, using explicitly labeled network test doubles where necessary.
- Run full relevant regressions and the actual supported 64-bit Python 3.12 packaging checks. Keep AuditShip/updater behavior unchanged.

Next physical-device test, after these blockers are resolved: provision UUID once with administrator approval on each of two computers; verify standard users cannot edit the identity file; verify two Windows accounts on one computer read the same UUID and hold different Credential Manager targets; use an MFA-authorized administrator to create installation-bound enrollment JSON (`url`, `key`, `enrollment_id`, `code`, `installation_uuid`); enroll each account; test same KPI name across devices, profile/module changes, inactivity, disconnect/reconnect, forced termination, normal close and revocation. Administrator passwords/MFA codes must remain private. No real administrator enrollment or physical-device telemetry test has been performed.
