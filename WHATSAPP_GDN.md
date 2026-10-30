# Continuous WhatsApp GDN monitoring

Open **WhatsApp** in the NEXUS sidebar. It contains **Browser** and **GDN Inbox**
tabs, **GRN Inbox**, and dedicated **WhatsApp Lane 1** / **WhatsApp Lane 2** tabs.
The GDN inbox buttons in Korber Automation open this same page.

The two WhatsApp lanes have their own forms, queues, progress, and isolated
Chrome profiles (`whatsapp_lane_1` and `whatsapp_lane_2`). Both inboxes offer only
these two destinations. Korber Automation keeps its existing Lane A / Lane B,
profiles, and jobs. Existing jobs are not moved; duplicate checks still include
all instantiated lanes. Creating/opening these tabs does not start a browser or
run a job. Scroll inside a lane tab to reach its queue and status controls.

## First setup

1. Choose **Open / Reconnect** on the WhatsApp page.
2. Link the internal browser using the QR code and WhatsApp on your phone.
3. Open the GDN group and move to its latest messages. At least one incoming
   text message must be visible to verify the selected name and supported page markup.
4. Choose **Use Open Group**. Existing visible requests are skipped unless you
   check **Also import messages currently visible** before selecting the group.
5. Confirm the saved group name and **Monitoring** state. Requests are saved in
   the inbox for review; they never create GDNs automatically.

The new Edge WebView2 profile requires its own initial QR login. The previous
Chrome profile is not imported. Existing inbox records and review edits survive.

## Monitoring lifetime

After a group is configured, monitoring starts automatically whenever NEXUS
starts. It continues while using other tools, switching Browser/Inbox tabs, or
minimizing NEXUS. Exiting NEXUS shuts down the helper. Windows must be awake and
connected. This does not install a Windows service, system tray app, or Windows
startup task.

**Pause** is explicit and persists across launches. **Resume** enables monitoring
again. To replace the monitored group, pause, open the replacement in the Browser
tab, and choose **Use Open Group**. The dedicated browser returns to the saved
group during active monitoring; use your normal WhatsApp app for other chats.

The sidebar shows status and the number of requests still marked New. Opening
or hiding the inbox does not own or stop capture. The application, not the page,
owns the browser process and monitoring controller.

## Review and mapping

Both inboxes show **Received** using the original WhatsApp message date/time
when the rendered message exposes it. Otherwise the value is explicitly marked
**Captured** using the saved local capture time. Legacy pending photos without
a saved time show **Time unavailable** until reliable metadata is observed.

**Clear List** hides the current GDN list and clears its review selection. The
GRN tab has its own independent button. History, photos, saved reviews, queued
actions, and duplicate protection remain; monitoring and new arrivals continue.
Cleared requests stay hidden after scans and restarts.

A quoted reply whose own body is exactly **DONE** (case-insensitive, surrounding
whitespace ignored) hides the corresponding request, including an existing inbox
row. This includes replies sent by the linked account. `NOT DONE`, `DONE ✅`,
and unquoted DONE messages do not qualify. Completion is retained for repeated
copies of the same deduplicated request/photo. It does not remove jobs already
in a Korber lane queue.

The adapter observes loaded replies only. In the verified WebView2 markup,
opening a quote highlights its original message. NEXUS follows that link, reads
the original row's message ID, and restores the view. It never matches completion
by quoted text or gate-pass number. Missing/ambiguous linkage leaves the request
visible with a notice; user interaction interrupts automated quote navigation.

Review a captured request, choose WhatsApp Lane 1 or WhatsApp Lane 2, then **Fill Form** or **Add to
Queue**. Queuing does not run the queue. Clipboard and single-message paste import
remain available on the GDN Inbox tab. Save edits before selecting another row;
background updates preserve edits to the currently selected request.

**Run Gatepass** validates and fills the selected lane, then starts its existing
**Create GDN** automation immediately, including opening the browser. It does
not add the request to the queue. The **State** column shows **New**, **Running**,
or **Completed**. Completed means the automation finished successfully, including
the report/print steps. You can run a completed request again; each click starts
a new attempt and returns its state to Running. Failed or stopped attempts return
to New after the worker stops (and any failure dialog is dismissed).
Starting another attempt closes that lane's previous browser session before
opening the fresh one, so two Chrome sessions do not compete for its profile.

Only a current run or waiting/running queue job blocks another simultaneous run
of the same warehouse/client/gate pass. Finished queue history and old launch
flags do not impose a permanent lock. Archived and WhatsApp-DONE requests stay
hidden. Attempts are retained in `gatepass_runs`; view closure does not lose their
outcomes. After restart, an interrupted attempt returns to New without claiming
that it completed. The first execution-state migration backs up an existing
database beside it as `inbox.before-gatepass-runs-<unique id>.sqlite3` and preserves
reviews, deduplication keys, and prior actions.

Mappings: WH ID to Warehouse ID; Client Code to Client Code; Gate pass to Gate
Pass No.; Seal numbers to Seal No.; **Note to Delivery Location**. Door Location
is retained separately and never replaces Note. Leading zeroes and seal slashes
are preserved. Multiline Note is retained in the inbox and joined with spaces
when filling Korber's single-line field.

Missing fields, control characters, and unknown warehouses block Fill/Queue.
Supply missing values explicitly, including N/A if appropriate. Conflicting
values and matching warehouse/client/gate-pass requests are flagged. Queued
requests with active lane jobs and duplicate active queue submissions across
lanes remain blocked.

## Recovery and status

Capture reads rendered incoming text every two seconds from a Python worker.
The WebView stays running when hidden. The browser is restored using an exact
saved sidebar title. The current WhatsApp page does not expose group IDs in
rendered HTML. As explicitly approved during implementation, this adapter uses
exact group-name binding: the header must match the selected sidebar chat and
visible matching names must be unambiguous. Keep the sidebar on All and use a unique group name; duplicates
outside the rendered sidebar cannot be ruled out. A changed or unavailable name
requires manual selection. This is not WhatsApp group-ID verification.

The helper writes requests directly to SQLite using WAL mode and atomic
insertion. A message is acknowledged only after classification/storage succeeds.
On reconnect, visible text is checked against the persisted checkpoint and inbox
deduplication. If continuity cannot be established, a possible capture gap stays
visible until you check recent group messages, import missing requests, and click
**Gap checked**. Complete offline history recovery is not provided.

A crashed or unresponsive helper is restarted after 2, 5, and 15 seconds. After
three unsuccessful retries, choose **Open / Reconnect**. A healthy monitoring
period resets the retry allowance. An expired login requires QR linking again.
If local storage fails, capture shows a storage error and retries unsaved text.

The GDN parser supports rendered incoming text. GRN document photos now have a
separate review inbox; see [WHATSAPP_GRN.md](WHATSAPP_GRN.md). Other attachments
and complete historical capture are unsupported. Incoming-tail markers establish sender signatures for
consecutive messages. Unclassified GDN-like text raises a capture-gap warning
instead of being assumed incoming. Quoted originals remain excluded from request
parsing; reply bodies are read separately for DONE completion. WhatsApp page selectors remain an experimental adapter;
the signed-in acceptance below records the remaining live scenarios. This is not
an official WhatsApp API integration and does not use a Meta API token.

## Local files and packaging

The database is at `%LOCALAPPDATA%/EFL_NEXUS/whatsapp_gdn/inbox.sqlite3`; the separate
persistent Edge profile is in `webview_profile` alongside it. `browser.log` holds
helper diagnostics. These runtime files are outside release bundles. Treat the
profile as signed-in account data; revoke it through WhatsApp Linked Devices
when needed. On systems without LOCALAPPDATA, the base is
`~/.local/share/EFL_NEXUS/whatsapp_gdn`.

The source helper runs through `whatsapp_monitor.py --whatsapp-browser`; frozen
builds use `EFL_NEXUS.exe --whatsapp-browser`. Both receive the database path, a
per-run identifier, and parent PID. Helper communication is local SQLite; no
remote debugging port or filesystem-capable page bridge is exposed.

## Validation

Local automated checks:

```powershell
python -m unittest discover -s tests -p test_whatsapp*.py -v
python -m unittest discover -s tests -p test_website_data_grabber.py -k WebsiteDataGrabberCreateGatepassTests -v
python -m unittest discover -s tests -p test_main_app_kpi_bridge.py -v
python -m py_compile main_app.py whatsapp_gdn.py whatsapp_monitor.py whatsapp_controller.py whatsapp_page.py whatsapp_inbox.py
```

State-machine snapshots in tests are explicitly labelled test doubles. They do
not prove live WhatsApp DOM compatibility. Real WebView2 smoke checks establish
browser startup, document evaluation while hidden, embedding, and shutdown only.

Inbox-feature artifacts are under `diagnostics/inbox-features` (ignored by Git),
including the pre-migration SQLite backup, test logs, window-specific UI previews,
and live quote-navigation evidence. The live check linked an existing outgoing
DONE reply to its actual original GDN message and persisted its exclusion.
Photo completion and ambiguous/missing linkage are covered by explicitly labelled
test doubles and real storage/UI checks; those do not establish additional live
WhatsApp markup compatibility.

Signed-in acceptance (requires the user to link the browser):

1. Confirm QR login, group identity, extraction, and saved-session restoration
   after exiting and reopening NEXUS.
2. Over 15 minutes, have participants send requests at random times while you
   use other tools, review the inbox, switch tabs, and minimize NEXUS. With a
   healthy connection, check that each appears within 10 seconds.
3. Check duplicate requests, corrections, Note mapping, leading zeroes, and
   preservation of unsaved review edits.
4. Pause/resume and restart NEXUS while paused. Confirm another group is never
   captured without pausing and selecting it explicitly.
5. Check browser failure, network interruption, login expiry, visible capture
   gaps, recovery, and shutdown. Check recent messages manually after gaps.
6. Repeat helper startup with the packaged executable; verify Pending Jobs and
   WhatsApp keep separate sessions and resize/hide independently.

### Verification in this implementation session (2026-10-20)

The linked WebView2 session verified the group header/sidebar selectors and
incoming-text structure. A 900.4-second minimized source-preview observation
recorded 450 healthy Monitoring samples, one helper run, and maximum heartbeat
age 2.02 seconds. No new requests arrived during that observation, so it does not
establish request-arrival latency. The local observation artifact is
`build/whatsapp-validation/live_check.json` (excluded from Git).

The packaged application subsequently restored the saved login and exact group
name automatically, without another QR login. Two GDN messages were captured
during recovery and their parsed fields were checked in the real review UI;
their arrival times were not measured. Browser/Inbox switching and navigation
to Pending Jobs kept the WhatsApp status active. Source-preview shutdown exited
cleanly. The real source/frozen WebView2 smoke checks covered hidden evaluation,
embedding, and shutdown; they do not establish full portal-session isolation.

All 36 WhatsApp unit/integration checks passed, along with 16 existing targeted
Pending Jobs/main-app regression checks. Random live arrivals within ten seconds,
real network interruption/login expiry, and simultaneous signed-in Pending Jobs
browsers remain live acceptance scenarios. Pause persistence, duplicate/storage
races, retry exhaustion, and review/lane behavior are covered by local tests.

Implementation references: [pywebview API](https://pywebview.flowrl.com/api/),
[WebView2 suspension](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2.trysuspendasync),
and [WhatsApp terms](https://www.whatsapp.com/legal/terms-of-service).
