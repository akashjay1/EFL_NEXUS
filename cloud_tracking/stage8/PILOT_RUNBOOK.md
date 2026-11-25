# Controlled two-computer pilot — activation not authorized

The regular application remains disabled by `cloud_monitoring.READY_FOR_DEVICE_PILOT = False`.
No desktop update, installer, updater manifest, or monitoring activation has been deployed.
The two designated computers and their actual installation UUIDs are still required.
Existing Stage 7 seeded device names/UUIDs must not be reused as physical pilot evidence.

## Inventory and provisioning before activation

1. Record each real computer name, installation folder, two Windows account names,
   and the actual ConfigStore file path used by that installation.
2. If machine identity is missing, the Windows administrator can run the existing
   executable with `--provision-monitoring` without a bundle. This writes machine
   identity; it does not enable the application monitoring gates. Do not generate
   a different UUID in the dashboard for an already provisioned machine.
3. Read the real UUID from `%PROGRAMDATA%\EFL_NEXUS_Monitoring\installation.json`
   using the existing diagnostics/read_identity path. Never copy machine binding
   or credentials into chat.
4. After owner AAL2 verification, create enrollment in Devices using that exact
   UUID. Download `provisioning.json` directly to a protected local location.
   Use the existing elevated `EFL_NEXUS.exe --provision-monitoring <absolute-bundle-path>`
   workflow. Enrollment codes expire after 600 seconds; recreate only if needed.
   Do not log or commit the bundle. Confirm successful provisioning before
   removing any leftover bundle through the normal approved process.
5. Run `python -m cloud_tracking.pilot_preflight --config <actual-config-path>
   --expected-installation-uuid <actual-uuid>` from this repository on each
   machine/account. The command performs no provisioning or network calls and
   never starts monitoring. It reports credential decryption as a boolean only.
6. Verify the same UUID and credential decryption in both Windows accounts.
   Review actual ProgramData directory/file ACLs: SYSTEM and Administrators may
   write; ordinary users should only read/execute. DPAPI LOCAL_MACHINE is machine
   bound; it does not isolate credentials from other users on that machine.
7. In the owner AAL2 dashboard, match the exact UUID to an unrevoked device and
   its active credential. Local decryption alone does not prove server enrollment.
8. Confirm a valid KPI profile resolves to `KPI Profile`; an absent/invalid profile
   resolves to the computer name with `Device Fallback`. Never share the KPI code.

## Prepared activation mechanism — do not activate yet

`pilot_runtime_hook.py` is a dormant PyInstaller runtime-hook template. It is not
referenced by the ordinary `EFL_NEXUS.spec`, has `OWNER_AUTHORIZED = False`, and
has no installation UUIDs. Therefore it cannot enable monitoring as delivered.

After separate owner authorization and successful provisioning of both computers:

1. Prepare an isolated pilot source/build directory using the reviewed desktop
   revision; preserve all unrelated current checkout work.
2. In that isolated build only, put exactly the two verified machine UUIDs in
   `PILOT_INSTALLATION_UUIDS` and set `OWNER_AUTHORIZED = True`. Do not embed device
   secrets, passwords, TOTP material, or enrollment codes.
3. Add this hook to `Analysis(runtime_hooks=[...])` in the isolated copy of the
   existing spec, preserving its other packaging settings. Include the existing
   monitoring modules; build with the existing Python 3.12 release prerequisites.
4. The hook permits the monitoring gate only for an allowed machine with a
   readable, matching machine credential, existing-project URL, and completed
   enrollment fields. It enables the gate only in that pilot process. The actual
   app config must also explicitly request `cloud_monitoring_enabled = true`.
5. Verify the pilot binary fails closed on an unlisted machine or missing/mismatched
   credential. Verify the normal build still has its False gate.
6. Record pilot binary SHA-256 and distribute directly to only those two computers.
   Do not publish it through the company-wide updater or change the ordinary spec.

The hook is a prepared mechanism, not an executed pilot build. Authorized runtime
behavior and physical device checks have not yet been validated.

## Acceptance evidence after separate activation authorization

Record timestamps and session IDs for each designated computer/account. Verify:

- Background worker runs without blocking the application; heartbeat interval is
  60 seconds. Module changes, idle detection and identity changes reach the dashboard.
- SQLite queue is at `%LOCALAPPDATA%\EFL_NEXUS\Monitoring\outbox.sqlite3` for each
  Windows account. Check queued event count, acknowledgments, and blocked launches.
- Each launch receives a separate session. Normal closure produces `closed`;
  forced termination is recovered as `unclean` on the next launch.
- Controlled offline usage preserves ordered events through an application restart.
  Reconnection acknowledges queued events without duplicate history. Do not delete
  queues to obtain a passing result. History older than seven days remains archived.
- Snapshot, Live Operators, Devices, Session History and events reflect actual
  records. Confirm private Realtime delivery separately from the 15-second poll.
- Device revocation is an irreversible acceptance action: obtain approval for the
  exact disposable pilot enrollment before revoking. Observe telemetry HTTP 403,
  then use a fresh owner-authorized enrollment if the device is to resume.

Stop acceptance if any identity, credential, provisioning, AAL2, or routing check
fails. Leave monitoring disabled until the owner authorizes the corrected pilot.
