"""Experimental, read-only WhatsApp Web adapter.

DOM selectors below are compatibility assumptions, not a documented WhatsApp
API. They must be checked against a signed-in browser before deployment.
Unsupported markup suspends capture instead of reading an arbitrary chat.
"""

import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import queue

from whatsapp_gdn import GDNInboxStore, content_fingerprint, parse_gdn_message


# Read rendered incoming text only. No internal WhatsApp APIs, sends, or clicks.
# Bind the verified header to one exact, unambiguous rendered sidebar name.
# The signed-in page exposes no group JID; this limitation is user-approved.
READ_CONVERSATION_JS = r"""
if (location.origin !== 'https://web.whatsapp.com')
    return {error: 'Only WhatsApp Web can be monitored.', state: 'Unsupported page'};
if (!navigator.onLine) return {error: 'Waiting for the network.', state: 'Offline'};
const main = document.querySelector('#main');
const side = document.querySelector('#pane-side');
if (!main || !side) return {error: 'Sign in and open your GDN group.', state:
    side ? 'Group selection required' : 'Login or loading required'};
const title = main.querySelector('[data-testid="conversation-info-header-chat-title-name"]');
const name = title && title.textContent.trim();
if (!name) return {error: 'Cannot read the conversation title.', state: 'Unsupported markup'};
// The current page exposes message IDs, but not WhatsApp group JIDs. This
// explicit local binding key represents exact-name matching approved by user.
const matching = [...side.querySelectorAll('span[title]')]
    .filter(el => el.getAttribute('title') === name);
const rowsWithName = new Set(matching.map(el => el.closest('[aria-selected]') || el));
const selected = [...side.querySelectorAll('[aria-selected="true"]')];
if (rowsWithName.size !== 1 || selected.length !== 1 || !matching.some(el => selected[0].contains(el)))
    return {error: 'The group name is missing, duplicated, or does not match the selected sidebar chat.',
            state: 'Group selection required'};
if (!main.querySelector('[data-testid="conversation-panel-messages"]'))
    return {error: 'WhatsApp message markup is unsupported.', state: 'Unsupported markup'};
const groupKey = 'name:' + name;
const byGroup = window.__nexusGdnIncomingAuthors || (window.__nexusGdnIncomingAuthors = new Map());
if (!byGroup.has(groupKey)) byGroup.set(groupKey, new Set());
const incomingAuthors = byGroup.get(groupKey);
const messageRows = [...main.querySelectorAll('[data-id][data-testid^="conv-msg-"]')];
const isQuote = el => !!el.closest('[data-testid="quoted-message"]');
const metadata = row => [...row.querySelectorAll('[data-pre-plain-text]')].find(el => !isQuote(el));
const authorKey = el => {
    const value = el && el.getAttribute('data-pre-plain-text');
    const match = value && value.match(/^\[[^\]]+\]\s*(.+?):\s*$/s);
    return match ? match[1] : null;
};
// A sender is classified as incoming only after an explicit incoming-tail
// marker is observed. This also handles consecutive messages without a tail.
for (const row of messageRows) {
    const tail = row.querySelector('[data-testid="tail-in"]');
    const author = authorKey(metadata(row));
    if (tail && !isQuote(tail) && author) incomingAuthors.add(author);
}
const messages = [];
const unclassified = [];
const photos = [];
const unclassifiedPhotos = [];
for (const row of messageRows) {
    const texts = [...row.querySelectorAll('[data-pre-plain-text] .selectable-text')].filter(el => !isQuote(el));
    const roots = texts.filter(el => !texts.some(other => other !== el && other.contains(el)));
    const text = roots.map(el => el.innerText).join('\n').trim();
    const images = [...row.querySelectorAll('[data-testid="image-thumb"]')]
        .filter(el => !isQuote(el));
    const message = {id: row.getAttribute('data-id'), text};
    const incomingTail = row.querySelector('[data-testid="tail-in"]');
    const incoming = (incomingTail && !isQuote(incomingTail)) || incomingAuthors.has(authorKey(metadata(row)));
    if (text) {
        if (incoming) messages.push(message);
        else unclassified.push(message);
    }
    images.forEach((img,index) => (incoming ? photos : unclassifiedPhotos).push({message_id:message.id,index}));
}
return {group_id: groupKey, name, identity_method: 'exact_name', messages, unclassified, photos, unclassifiedPhotos};
"""


class CaptureSession:
    """Tracks the selected group and message revisions without storing chat history."""

    def __init__(self):
        self.group_id = None
        self.name = ""
        self.seen = set()

    @staticmethod
    def key(message):
        return message["id"], content_fingerprint(message["text"])

    def bind(self, snapshot, import_visible=False):
        if snapshot.get("error") or not snapshot.get("group_id"):
            raise ValueError(snapshot.get("error") or "No group identity available.")
        self.group_id, self.name = snapshot["group_id"], snapshot["name"]
        self.seen = set() if import_visible else {self.key(m) for m in snapshot["messages"]}
        return self.capture(snapshot)

    def capture(self, snapshot):
        if snapshot.get("error"):
            raise ValueError(f"Capture paused: {snapshot['error']}")
        if snapshot.get("group_id") != self.group_id:
            raise ValueError("Capture paused: return to the selected group, or select a new group in NEXUS.")
        found = []
        for message in snapshot["messages"]:
            key = self.key(message)
            if key not in self.seen:
                found.append(message)
        return found

    def acknowledge(self, message):
        self.seen.add(self.key(message))


def read_script():
    return "(() => {\n" + READ_CONVERSATION_JS + "\n})()"


def restore_group_script(name):
    # Exact sidebar title only; never navigate to an invented group URL.
    return """(() => {
        if (location.origin !== 'https://web.whatsapp.com') return false;
        const side = document.querySelector('#pane-side');
        if (!side) return false;
        const titles = [...side.querySelectorAll('span[title]')]
            .filter(el => el.getAttribute('title') === %s);
        if (titles.length !== 1) return false;
        titles[0].click(); return true;
    })()""" % json.dumps(name)


FOLLOW_LATEST_JS = """(() => {
    const rows = document.querySelectorAll('#main [data-id]');
    if (rows.length) rows[rows.length - 1].scrollIntoView({block: 'end', behavior: 'auto'});
})()"""


# Local diagnostics report structure only, never message text or account IDs.
PROBE_STRUCTURE_JS = r"""(() => {
    const main = document.querySelector('#main');
    const rows = [...document.querySelectorAll('#main [data-id]')];
    const incoming = [...document.querySelectorAll('#main .message-in')];
    return {
        origin: location.origin, main: !!main, data_rows: rows.length,
        mediaRows: rows.filter(r => r.querySelector('[data-testid="media-url-provider"]')).map(r => ({
            testid: r.getAttribute('data-testid'),
            metadata: !!r.querySelector('[data-pre-plain-text]'),
            tail: !!r.querySelector('[data-testid="tail-in"]'),
            testids: [...new Set([...r.querySelectorAll('[data-testid]')].map(e=>e.getAttribute('data-testid')))],
            thumbs: [...r.querySelectorAll('[data-testid="image-thumb"]')].map(t => ({
                icons: [...t.querySelectorAll('[data-icon]')].map(e=>e.getAttribute('data-icon')),
                controls: [...t.querySelectorAll('button,[role="button"]')].map(e=>({
                    tag:e.tagName, label:e.getAttribute('aria-label'), title:e.getAttribute('title'),
                    testid:e.getAttribute('data-testid'), disabled:e.getAttribute('aria-disabled')})),
                images: [...t.querySelectorAll('img')].map(e=>({
                    width:e.naturalWidth,height:e.naturalHeight,complete:e.complete,
                    scheme:(e.currentSrc||e.src).split(':')[0],
                    parents:[e,e.parentElement,e.parentElement?.parentElement].filter(Boolean).map(p=>({
                        testid:p.getAttribute('data-testid'),filter:getComputedStyle(p).filter,
                        display:getComputedStyle(p).display,visibility:getComputedStyle(p).visibility,
                        opacity:getComputedStyle(p).opacity,classes:p.className}))}))
            }))
        })),
        images: main ? [...main.querySelectorAll('img')].map(el => ({
            attributes: [...el.attributes].map(a => a.name),
            testid: el.getAttribute('data-testid'), role: el.getAttribute('role'),
            width: el.naturalWidth, height: el.naturalHeight,
            srcScheme: (el.currentSrc || el.src).split(':')[0],
            ancestors: [el.parentElement, el.parentElement?.parentElement].filter(Boolean)
                .map(p => ({tag: p.tagName, role: p.getAttribute('role'), testid: p.getAttribute('data-testid')}))
        })) : [],
        incoming: incoming.length,
        id_shapes: rows.slice(0, 4).map(el => el.getAttribute('data-id')
            .replace(/[0-9]/g, '0').replace(/[a-fA-F]/g, 'X')),
        header_titles: main ? [...main.querySelectorAll('header [title]')].map(el => el.tagName) : [],
        incoming_structure: incoming.slice(0, 2).map(el => {
            const structure = [];
            for (let i = 0; el && i < 4; i++, el = el.parentElement)
                structure.push({tag: el.tagName, attributes: [...el.attributes].map(a => a.name)});
            return structure;
        }),
        copyable: main ? main.querySelectorAll('[data-pre-plain-text]').length : 0,
        selectable: main ? main.querySelectorAll('.selectable-text').length : 0
        ,copyable_structure: main ? [...main.querySelectorAll('[data-pre-plain-text]')].slice(0, 2).map(el => {
            const structure = [];
            for (let i = 0; el && i < 6; i++, el = el.parentElement)
                structure.push({tag: el.tagName, attributes: [...el.attributes].map(a => a.name),
                    role: el.getAttribute('role'), align: getComputedStyle(el).alignSelf,
                    testid: el.getAttribute('data-testid'), display: getComputedStyle(el).display,
                    alignItems: getComputedStyle(el).alignItems, justify: getComputedStyle(el).justifyContent,
                    marginLeft: getComputedStyle(el).marginLeft, marginRight: getComputedStyle(el).marginRight,
                    classes: el.className});
            return structure;
        }) : [],
        selected_rows: [...document.querySelectorAll('#pane-side [aria-selected="true"]')].map(el => ({
            tag: el.tagName, attributes: [...el.attributes].map(a => a.name),
            ids: [...el.querySelectorAll('[data-id]')].map(item => item.getAttribute('data-id')
                .replace(/[0-9]/g, '0').replace(/[a-fA-F]/g, 'X'))
        })),
        jid_attributes: [...document.querySelectorAll('*')].flatMap(el => [...el.attributes]
            .filter(a => /@g\.us/.test(a.value)).map(a => ({tag: el.tagName, name: a.name,
                shape: a.value.replace(/[0-9]/g, '0').replace(/[a-fA-F]/g, 'X')}))).slice(0, 8),
        testids: main ? [...new Set([...main.querySelectorAll('[data-testid]')].map(el => el.getAttribute('data-testid')))] : [],
        bubble_layout: main ? [...main.querySelectorAll('[data-testid="msg-container"]')].slice(0, 8).map(el => {
            const s = getComputedStyle(el);
            return {float: s.cssFloat, background: s.backgroundColor, textAlign: s.textAlign,
                direction: s.direction, left: s.left, right: s.right, position: s.position,
                incomingTail: !!el.querySelector('[data-testid="tail-in"]'),
                outgoingTail: !!el.querySelector('[data-testid="tail-out"]')};
        }) : [],
        row_structure: rows.slice(-2).map(el => {
            const structure = [];
            for (let i = 0; el && i < 4; i++, el = el.parentElement) {
                const s = getComputedStyle(el);
                structure.push({tag: el.tagName, attributes: [...el.attributes].map(a => a.name),
                    testid: el.getAttribute('data-testid'), role: el.getAttribute('role'),
                    display: s.display, align: s.alignSelf, alignItems: s.alignItems,
                    justify: s.justifyContent, marginLeft: s.marginLeft, marginRight: s.marginRight,
                    paddingLeft: s.paddingLeft, paddingRight: s.paddingRight, width: s.width,
                    textAlign: s.textAlign, float: s.cssFloat});
            }
            return structure;
        })
    };
})()"""


class CaptureEngine:
    """Browser-independent state transitions, with durable acknowledgements."""

    def __init__(self, store, run_id):
        self.store, self.run_id = store, run_id
        self.session = CaptureSession()
        self.recovering = True

    def report(self, state, detail=""):
        self.store.report(self.run_id, state, detail, self.store.setting("capture_gap", False))

    def select(self, snapshot, import_visible=False):
        if not isinstance(snapshot, dict):
            raise ValueError("WhatsApp is not ready yet. Wait for the group to load, then select it again.")
        group = self.store.setting("group")
        if group and self.store.setting("enabled", False):
            raise ValueError("Pause monitoring before selecting or replacing the group.")
        self.session = CaptureSession()
        self.session.bind(snapshot, import_visible)
        self.store.set_settings(group={"id": snapshot["group_id"], "name": snapshot["name"],
                                       "identity_method": snapshot["identity_method"]},
                                enabled=True, checkpoint=None, capture_gap=False, unclassified_seen=[])
        self.recovering = False
        self.accept(snapshot, baseline=not import_visible)
        # Photos have their own durable sources and retry lifecycle.
        from whatsapp_grn import GRNInboxStore
        photos = GRNInboxStore(self.store.path)
        try:
            photos.discover(snapshot, baseline=not import_visible, import_visible=import_visible)
            photos.set_settings(grn_capture_initialized=snapshot["group_id"])
        finally:
            photos.close()

    def pause(self):
        self.store.set_settings(enabled=False)
        self.recovering = True
        self.report("Paused", "Monitoring is paused. Resume when ready.")

    def resume(self):
        self.store.set_settings(enabled=True)
        self.session = CaptureSession()
        self.recovering = True

    def accept(self, snapshot, baseline=False):
        group = self.store.setting("group")
        if not group or snapshot.get("group_id") != group["id"]:
            raise ValueError("Group selection required: the open chat does not match the saved group name.")
        messages = snapshot["messages"]
        unknown_history = self.store.setting("unclassified_seen", [])
        known_unknown = set(unknown_history)
        newly_unknown = []
        for message in snapshot.get("unclassified", []):
            fingerprint = content_fingerprint(message["text"])
            if fingerprint not in known_unknown and parse_gdn_message(message["text"]).candidate:
                newly_unknown.append(fingerprint)
                known_unknown.add(fingerprint)
        if newly_unknown:
            self.store.set_settings(unclassified_seen=(unknown_history + newly_unknown)[-1000:])
            if not baseline:
                self.store.set_settings(capture_gap=True)
        if self.recovering:
            self.session = CaptureSession()
            self.session.bind(snapshot, import_visible=True)
            checkpoint = self.store.setting("checkpoint")
            if checkpoint and checkpoint.get("group_id") == group["id"]:
                indices = [i for i, m in enumerate(messages) if m["id"] == checkpoint["message_id"]]
                if indices:
                    index = indices[-1]
                    unchanged = content_fingerprint(messages[index]["text"]) == checkpoint["fingerprint"]
                    for message in messages[:index + int(unchanged)]:
                        self.session.acknowledge(message)
                else:
                    self.store.set_settings(capture_gap=True)
            else:
                self.store.set_settings(capture_gap=True)
            self.recovering = False
        # Ignore baseline history only during explicit first-time group selection.
        if baseline:
            for message in messages:
                self.session.acknowledge(message)
        for message in self.session.capture(snapshot):
            # Includes non-GDN text: acknowledge only after the classification /
            # durable insert succeeds. Failure leaves the message retryable.
            self.store.add(message["text"], group["name"], message["id"])
            self.session.acknowledge(message)
        if messages:
            last = messages[-1]
            self.store.set_settings(checkpoint={"group_id": group["id"], "message_id": last["id"],
                                                "fingerprint": content_fingerprint(last["text"])})
        self.report("Monitoring", group["name"])


def run_whatsapp_browser(db_path, run_id, parent_pid):
    """WebView2 main loop lives in this process; a Python worker polls every 2s."""
    import webview

    # No filesystem-capable Python bridge is exposed to WhatsApp's document.
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    profile = Path(db_path).parent / "webview_profile"
    profile.mkdir(parents=True, exist_ok=True)
    window = webview.create_window("EFL NEXUS - WhatsApp Browser", "https://web.whatsapp.com/",
                                   width=1200, height=800, min_size=(600, 400),
                                   hidden=True, zoomable=True)
    loaded, stopping = threading.Event(), threading.Event()
    window.events.loaded += lambda: loaded.set()
    window.events.closed += lambda: stopping.set()

    def worker():
        store = GDNInboxStore(db_path)
        from whatsapp_grn import GRNInboxStore, GRNExtractionWorker, photo_read_script
        photos = GRNInboxStore(db_path)
        extraction_worker = GRNExtractionWorker(db_path, stopping)
        extraction_worker.thread.start()
        photo_results = queue.Queue()
        photo_inflight = None
        engine = CaptureEngine(store, run_id)
        last_restore = 0
        selection_error = None
        pending_selection = None
        parent_handle = None
        try:
            # Parent lifetime is independent of the embedded window's visibility.
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                parent_handle = kernel.OpenProcess(0x00100000, False, parent_pid)
                if not parent_handle:
                    raise RuntimeError("Cannot monitor the parent process lifetime")
            while not stopping.is_set():
                if parent_handle and kernel.WaitForSingleObject(parent_handle, 0) == 0:
                    break
                for action, payload in store.take_commands(run_id):
                    if action == "shutdown":
                        engine.report("Stopping", "Closing the internal WhatsApp browser.")
                        stopping.set()
                        break
                    if action == "pause":
                        engine.pause()
                    elif action == "resume":
                        engine.resume()
                    elif action == "retry_ocr" and not extraction_worker.thread.is_alive():
                        extraction_worker = GRNExtractionWorker(db_path, stopping)
                        extraction_worker.thread.start()
                    elif action == "acknowledge_gap":
                        store.set_settings(capture_gap=False)
                    elif action == "reload":
                        loaded.clear()
                        engine.recovering = True
                        window.load_url("https://web.whatsapp.com/")
                    elif action == "probe" and loaded.is_set():
                        store.set_settings(last_probe=window.evaluate_js(PROBE_STRUCTURE_JS))
                    elif action == "import_photos" and loaded.is_set():
                        current = window.evaluate_js(read_script())
                        if isinstance(current, dict) and current.get("group_id") == store.setting("group", {}).get("id"):
                            photos.discover(current, import_visible=True)
                            photos.set_settings(grn_capture_initialized=current["group_id"])
                        else:
                            store.set_settings(grn_capture_notice="Return to the selected group before importing photos.")
                    elif action == "select":
                        pending_selection = payload
                        selection_error = None
                if pending_selection is not None and loaded.is_set() and not stopping.is_set():
                    try:
                        engine.select(window.evaluate_js(read_script()), pending_selection.get("import_visible", False))
                    except ValueError as exc:
                        selection_error = str(exc)
                    pending_selection = None
                if stopping.is_set():
                    break
                while not photo_results.empty():
                    source_id, result = photo_results.get_nowait()
                    # Ignore late callbacks from a timed-out request.
                    if photo_inflight is None or source_id != photo_inflight[0]:
                        continue
                    try:
                        if not isinstance(result, dict) or result.get("error") or not result.get("data"):
                            photos.capture_failed(source_id, result.get("error", "Photo retrieval failed.") if isinstance(result, dict) else "Photo retrieval failed.")
                        else:
                            photos.save_image(source_id, result["data"])
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        photos.capture_failed(source_id, str(exc))
                    photo_inflight = None
                if photo_inflight and time.monotonic() - photo_inflight[1] > 20:
                    photos.capture_failed(photo_inflight[0], "Photo retrieval timed out. Retry capture.")
                    photo_inflight = None
                if not loaded.is_set():
                    engine.report("Starting", "Loading WhatsApp Web...")
                elif not store.setting("enabled", False):
                    if selection_error:
                        engine.report("Group selection required", selection_error)
                    else:
                        engine.report("Paused" if store.setting("group") else "Setup required",
                                      "Open the Browser tab, sign in, and select the group.")
                else:
                    snapshot = window.evaluate_js(read_script())
                    if not isinstance(snapshot, dict):
                        engine.recovering = True
                        engine.report("Reconnecting", "Waiting for a readable WhatsApp page.")
                    elif snapshot.get("error"):
                        engine.recovering = True
                        if time.monotonic() - last_restore > 10 and store.setting("group"):
                            window.evaluate_js(restore_group_script(store.setting("group")["name"]))
                            last_restore = time.monotonic()
                        engine.report(snapshot.get("state", "Group selection required"), snapshot["error"])
                    elif snapshot["group_id"] != store.setting("group", {}).get("id"):
                        engine.recovering = True
                        if time.monotonic() - last_restore > 10:
                            window.evaluate_js(restore_group_script(store.setting("group")["name"]))
                            last_restore = time.monotonic()
                        engine.report("Group selection required", "Return to the saved group, or pause to select a replacement.")
                    else:
                        try:
                            engine.accept(snapshot)
                            # Baseline existing photos on upgrade. Importing history is explicit.
                            initial = photos.setting("grn_capture_initialized") != snapshot["group_id"]
                            photos.discover(snapshot, baseline=initial)
                            if initial:
                                photos.set_settings(grn_capture_initialized=snapshot["group_id"])
                            notice = "Some photo senders could not be verified as incoming. Check the group for missing photos." if snapshot.get("unclassifiedPhotos") else ""
                            if store.setting("grn_capture_notice", "") != notice:
                                store.set_settings(grn_capture_notice=notice)
                            window.evaluate_js(FOLLOW_LATEST_JS)
                        except sqlite3.Error:
                            engine.report("Storage error", "Capture is waiting for local inbox storage; requests will be retried.")
                # Explicit imports can also complete while monitoring is paused for review.
                if loaded.is_set() and photo_inflight is None and store.setting("group"):
                    pending = photos.pending_capture(store.setting("group")["id"])
                    if pending:
                        source = pending[0]
                        photo_inflight = (source["id"], time.monotonic())
                        try:
                            window.evaluate_js(photo_read_script(source["group_id"], source["message_id"], source["photo_index"]),
                                callback=lambda result, source_id=source["id"]: photo_results.put((source_id, result)))
                        except Exception as exc:
                            photos.capture_failed(source["id"], f"Photo retrieval failed ({type(exc).__name__}). Retry capture.")
                            photo_inflight = None
                stopping.wait(2)
        except Exception as exc:
            try:
                engine.report("Failed", f"WhatsApp helper stopped ({type(exc).__name__}). Reconnect from NEXUS.")
            except sqlite3.Error:
                pass
        finally:
            if parent_handle:
                kernel.CloseHandle(parent_handle)
            store.close()
            photos.close()
            print("WhatsApp capture worker stopped; closing WebView2.", flush=True)
            window.destroy()
            print("WhatsApp browser window closed.", flush=True)

    webview.start(worker, gui="edgechromium", private_mode=False, storage_path=str(profile), debug=False)
    print("WhatsApp helper UI loop exited.", flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 5 and sys.argv[1] == "--whatsapp-browser":
        run_whatsapp_browser(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
