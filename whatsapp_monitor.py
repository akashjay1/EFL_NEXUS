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


# Capture rendered incoming requests only; no internal WhatsApp APIs or sends.
# The separate DONE resolver follows quote links using rendered page controls.
# Bind the verified header to one exact, unambiguous rendered sidebar name.
# The signed-in page exposes no group JID; this limitation is user-approved.
from whatsapp_media import MEDIA_ADAPTER_JS


READ_CONVERSATION_JS = MEDIA_ADAPTER_JS + r"""
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
const messageRows = [...main.querySelectorAll(nexusMedia.rows)];
if(!messageRows.length && main.querySelector(nexusMedia.thumbnail))
    return {error:'Photo message markup is unsupported. Reconnect or reopen the group.',state:'Unsupported markup'};
const isQuote = el => !!el.closest('[data-testid="quoted-message"]');
const metadata = row => [...row.querySelectorAll('[data-pre-plain-text]')].find(el => !isQuote(el));
const authorKey = row => {
    const el=metadata(row);
    const value = el && el.getAttribute('data-pre-plain-text');
    const match = value && value.match(/^\[[^\]]+\]\s*(.+?):\s*$/s);
    if(match) return match[1];
    // Photos without captions may omit copyable-text metadata. The author
    // marker is also rendered on incoming media rows in the verified page.
    const author=[...row.querySelectorAll('[data-testid="author"]')].find(e=>!isQuote(e));
    return author?.textContent.trim() || null;
};
// A sender is classified as incoming only after an explicit incoming-tail
// marker is observed. This also handles consecutive messages without a tail.
for (const row of messageRows) {
    const tail = row.querySelector('[data-testid="tail-in"]');
    const author = authorKey(row);
    if (tail && !isQuote(tail) && author) incomingAuthors.add(author);
}
const messages = [];
const unclassified = [];
const photos = [];
const unclassifiedPhotos = [];
const replies = [];
const messageTime = row => {
    const value=metadata(row)?.getAttribute('data-pre-plain-text') || '';
    const stamp=value.match(/^\[([^\]]+)\]/);
    return stamp ? stamp[1] : '';
};
for (const row of messageRows) {
    const texts = [...row.querySelectorAll('[data-pre-plain-text] .selectable-text')].filter(el => !isQuote(el));
    const roots = texts.filter(el => !texts.some(other => other !== el && other.contains(el)));
    const text = roots.map(el => el.innerText).join('\n').trim();
    const images = nexusPhotoThumbs(row);
    const message = {id: row.getAttribute('data-id'), text, message_time:messageTime(row)};
    if (text.toUpperCase()==='DONE' && row.querySelector('[data-testid="quoted-message"]'))
        replies.push({...message,reply_to:null});
    const incomingTail = row.querySelector('[data-testid="tail-in"]');
    const outgoingTail = row.querySelector('[data-testid="tail-out"]');
    const outgoing = outgoingTail && !isQuote(outgoingTail);
    const incoming = !outgoing && ((incomingTail && !isQuote(incomingTail)) || incomingAuthors.has(authorKey(row)));
    if (text) {
        if (incoming) messages.push(message);
        else unclassified.push(message);
    }
    if (!outgoing) images.forEach((img,index) => (incoming ? photos : unclassifiedPhotos).push({message_id:message.id,index,message_time:message.message_time}));
}
// Observe messages that can be virtualized out of the DOM between Python polls.
// Retain lightweight photo metadata, never image bytes or detached message trees.
const panel=main.querySelector('[data-testid="conversation-panel-messages"]');
let observer=window.__nexusGrnPhotoObserver;
if(observer && (observer.panel!==panel || observer.group!==groupKey)) {
    observer.watcher.disconnect(); delete window.__nexusGrnPhotoObserver; observer=null;
}
const visible_photos=[...photos,...unclassifiedPhotos].map(p=>p.message_id);
if(typeof MutationObserver!=='undefined' && !observer) {
    observer={panel,group:groupKey,pending:new Map(),sequence:0,overflow:false};
    observer.watcher=new MutationObserver(records=>{
        if(document.querySelector('#main [data-testid="conversation-info-header-chat-title-name"]')?.textContent.trim()!==name) return;
        const changed=new Set();
        for(const record of records) {
            const target=record.target?.closest?.(nexusMedia.rows);
            if(target) changed.add(target);
            for(const node of record.addedNodes || []) {
                const row=node.closest?.(nexusMedia.rows);
                if(row) changed.add(row);
                for(const child of node.querySelectorAll?.(nexusMedia.rows) || []) changed.add(child);
            }
        }
        for(const row of changed) {
            const tail=row.querySelector('[data-testid="tail-out"]');
            if(tail && !isQuote(tail)) continue;
            const incoming=row.querySelector('[data-testid="tail-in"]');
            const author=authorKey(row);
            if(incoming && !isQuote(incoming) && author) incomingAuthors.add(author);
            const verified=!!((incoming && !isQuote(incoming)) || incomingAuthors.has(author));
            nexusPhotoThumbs(row).forEach((img,index)=>{
                const message_id=row.getAttribute('data-id');
                if(!message_id) return;
                const key=message_id+':'+index;
                observer.pending.set(key,{message_id,index,message_time:messageTime(row),verified,observation:++observer.sequence});
                if(observer.pending.size>2000) {observer.pending.delete(observer.pending.keys().next().value);observer.overflow=true;}
            });
        }
    });
    observer.watcher.observe(panel,{childList:true,subtree:true,attributes:true,attributeFilter:['data-pre-plain-text','data-testid']});
    window.__nexusGrnPhotoObserver=observer;
}
if(observer) {
    const known=new Set([...photos,...unclassifiedPhotos].map(p=>p.message_id+':'+p.index));
    for(const [key,photo] of observer.pending) {
        if(!known.has(key)) (photo.verified?photos:unclassifiedPhotos).push(photo);
    }
}
const photo_notice=observer?.overflow?'Photo observation buffer filled. Compare the group and use Scan GRN for missing loaded messages.':'';
const photo_observations=observer?[...observer.pending].map(([key,photo])=>[key,photo.observation]):[];
return {group_id: groupKey, name, identity_method: 'exact_name', messages, unclassified, photos, unclassifiedPhotos, replies, visible_photos, photo_notice, photo_observations};
"""

ACK_PHOTOS_JS = r"""
const observer=window.__nexusGrnPhotoObserver;
if(observer && observer.group===snapshot.group_id) {
    for(const [key,token] of snapshot.photo_observations || []) {
        if(observer.pending.get(key)?.observation===token) observer.pending.delete(key);
    }
    observer.overflow=false;
}
"""


def photo_ack_script(snapshot):
    acknowledged = {key: snapshot.get(key) for key in ('group_id', 'photo_observations')}
    return '(() => {const snapshot=' + json.dumps(acknowledged) + ';' + ACK_PHOTOS_JS + '})()'


# In the verified WebView2 page quotes expose no message ID. Following a quote
# starts a three-keyframe background highlight on the original message row.
# Resolve that row's data-id, never the quote's text, author or screen position.
RESOLVE_DONE_JS = r"""
if (snapshot.error) return snapshot;
const caches=window.__nexusDoneLinks || (window.__nexusDoneLinks=new Map());
if(!caches.has(snapshot.group_id)) caches.set(snapshot.group_id,new Map());
const cache=caches.get(snapshot.group_id), now=Date.now();
const rowFor=id=>[...document.querySelectorAll('#main [data-id][data-testid^="conv-msg-"]')]
    .find(r=>r.getAttribute('data-id')===id);
const finish=s=>{
    s.replies=(s.replies||[]).map(r=>({...r,reply_to:cache.get(r.id)?.target || null}));
    s.unresolved_done=s.replies.filter(r=>!r.reply_to).map(r=>r.id);
    return s;
};
let owner=window.__nexusDoneNavigation;
if(owner){
    if(owner.group!==snapshot.group_id){owner.events.abort();delete window.__nexusDoneNavigation;return finish(snapshot);}
    const targets=new Set();
    if(!owner.interrupted) for(const animation of document.getAnimations()){
        if(owner.before.has(animation)) continue;
        const frames=animation.effect?.getKeyframes() || [];
        if(frames.length!==3 || frames[0].offset!==0 || frames[1].offset!==0.5 || frames[2].offset!==1 ||
           !frames.every(f=>typeof f.backgroundColor==='string') ||
           frames[0].backgroundColor!==frames[2].backgroundColor || frames[0].backgroundColor===frames[1].backgroundColor) continue;
        const target=animation.effect.target?.closest('#main [data-id][data-testid^="conv-msg-"]');
        const id=target?.getAttribute('data-id');
        if(id && id!==owner.reply) targets.add(id);
    }
    if(targets.size!==1 && !owner.interrupted && now-owner.started<2000)
        return {...finish(owner.snapshot),reply_scan_pending:true};
    const original=targets.size===1 && !owner.interrupted ? [...targets][0] : null;
    cache.set(owner.reply,{target:original,retry:now+30000});
    const saved=owner.snapshot;
    if(original){
        const row=rowFor(original), textNodes=[...row.querySelectorAll('[data-pre-plain-text] .selectable-text')]
            .filter(e=>!e.closest('[data-testid="quoted-message"]'));
        const roots=textNodes.filter(e=>!textNodes.some(other=>other!==e && other.contains(e)));
        const meta=[...row.querySelectorAll('[data-pre-plain-text]')].find(e=>!e.closest('[data-testid="quoted-message"]'));
        const stamp=(meta?.getAttribute('data-pre-plain-text') || '').match(/^\[([^\]]+)\]/);
        saved.observed_originals=[{id:original,text:roots.map(e=>e.innerText).join('\n').trim(),message_time:stamp?.[1] || ''}];
    }
    owner.events.abort();
    if(!owner.interrupted){
        const anchor=rowFor(owner.anchor);
        if(anchor) anchor.scrollIntoView({block:'end',behavior:'instant'});
        else if(owner.scroller?.isConnected) owner.scroller.scrollTop=owner.scrollTop;
    }
    delete window.__nexusDoneNavigation;
    finish(saved);
    if(saved.replies.some(r=>!r.reply_to && (!cache.has(r.id) || cache.get(r.id).retry<=now))) saved.reply_scan_pending=true;
    return saved;
}
finish(snapshot);
const pending=snapshot.replies.find(r=>!r.reply_to && (!cache.has(r.id) || cache.get(r.id).retry<=now));
if(!pending) return snapshot;
if(window.__nexusGrnOriginal || document.querySelector('[data-testid="media-viewer-modal"]'))
    return {...snapshot,reply_scan_pending:true};
const row=rowFor(pending.id), button=row?.querySelector('[data-testid="quoted-message"] [aria-label="Quoted message"]');
if(!button){cache.set(pending.id,{target:null,retry:now+30000});return snapshot;}
let scroller=row.parentElement;
while(scroller && !(scroller.scrollHeight>scroller.clientHeight && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller=scroller.parentElement;
owner={group:snapshot.group_id,reply:pending.id,started:now,snapshot,
    before:new Set(document.getAnimations()),
    scroller,scrollTop:scroller?.scrollTop,events:new AbortController(),interrupted:false};
// Use the final rendered row as a viewport anchor; it is not reply evidence.
owner.anchor=[...document.querySelectorAll('#main [data-id][data-testid^="conv-msg-"]')].at(-1)?.getAttribute('data-id');
window.__nexusDoneNavigation=owner;
const interrupt=e=>{if(e.isTrusted) owner.interrupted=true;};
document.addEventListener('pointerdown',interrupt,{capture:true,signal:owner.events.signal});
document.addEventListener('keydown',interrupt,{capture:true,signal:owner.events.signal});
button.click();
return {...snapshot,reply_scan_pending:true};
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


def read_script(expected_group=None, known_done=None):
    guard = ("if(snapshot.group_id!==" + json.dumps(expected_group) + ") return snapshot;\n") if expected_group else ""
    remembered = ""
    if known_done:
        remembered = ("const remembered=" + json.dumps(known_done) + ";"
            "const savedLinks=window.__nexusDoneLinks || (window.__nexusDoneLinks=new Map());"
            "if(!savedLinks.has(snapshot.group_id)) savedLinks.set(snapshot.group_id,new Map());"
            "for(const [reply,target] of Object.entries(remembered[snapshot.group_id] || {}))"
            "savedLinks.get(snapshot.group_id).set(reply,{target,retry:Infinity});\n")
    return "(() => {const snapshot=(()=>{\n" + READ_CONVERSATION_JS + "\n})();\nif(snapshot.error) return snapshot;\n" + guard + remembered + RESOLVE_DONE_JS + "\n})()"


def restore_group_script(name):
    # Exact sidebar title only; never navigate to an invented group URL.
    return """(() => {
        if (location.origin !== 'https://web.whatsapp.com') return false;
        const side = document.querySelector('#pane-side');
        if (!side) return false;
        const titles = [...side.querySelectorAll('span[title]')]
            .filter(el => el.getAttribute('title') === %s);
        if (titles.length !== 1) return false;
        // The live WhatsApp chat list responds to pointer-down selection;
        // click() alone did not restore the conversation in this version.
        const target=titles[0];
        target.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true,button:0,buttons:1,pointerType:'mouse',isPrimary:true}));
        target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true,button:0,buttons:1}));
        target.dispatchEvent(new PointerEvent('pointerup', {bubbles:true,button:0,buttons:0,pointerType:'mouse',isPrimary:true}));
        target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true,button:0}));
        target.click(); return true;
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
        done_links: [...(window.__nexusDoneLinks?.get('name:'+main?.querySelector('[data-testid="conversation-info-header-chat-title-name"]')?.textContent.trim()) || new Map())]
            .map(([reply,info])=>({reply,target:info.target})),
        done_scan_pending: !!window.__nexusDoneNavigation,
        quoted_structure: rows.filter(r=>r.querySelector('[data-testid="quoted-message"]')).slice(-12).map(r=>({
            id:r.getAttribute('data-id'),
            done:[...r.querySelectorAll('[data-pre-plain-text] .selectable-text')]
                .filter(e=>!e.closest('[data-testid="quoted-message"]')).map(e=>e.innerText).join('\n').trim().toUpperCase()==='DONE',
            outgoing:!!r.querySelector('[data-testid="tail-out"]'),
            quoted_photo:!!r.querySelector('[data-testid="quoted-message"] [data-testid="image-thumb"]')
        })),
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
            photos.discover(snapshot, baseline=not import_visible, import_visible=import_visible, recent_only=True)
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
        self.store.observe_messages(snapshot)
        if snapshot.get("reply_scan_pending"):
            self.report("Monitoring", "Checking DONE reply links...")
            return
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
            self.store.add(message["text"], group["name"], message["id"],
                           group_id=group["id"], message_time=message.get("message_time", ""))
            self.session.acknowledge(message)
        if messages:
            last = messages[-1]
            self.store.set_settings(checkpoint={"group_id": group["id"], "message_id": last["id"],
                                                "fingerprint": content_fingerprint(last["text"])})
        self.report("Monitoring", group["name"])


def run_whatsapp_browser(db_path, run_id, parent_pid):
    """WebView2 runs here; Python polls independently of hidden-page timers."""
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
        from whatsapp_grn import GRNInboxStore, GRNExtractionWorker, photo_read_script, grn_photo_is_recent
        from grn_cloud_ocr import GRNCloudWorker
        photos = GRNInboxStore(db_path)
        extraction_worker = GRNExtractionWorker(db_path, stopping)
        extraction_worker.thread.start()
        cloud_worker = GRNCloudWorker(db_path, stopping)
        cloud_worker.thread.start()
        photo_results = queue.Queue()
        photo_inflight = {}
        photo_owner_id = None
        photo_wake = threading.Event()
        scan_requested = False

        def photo_done(source_id, token, result):
            photo_results.put((source_id, token, result))
            photo_wake.set()
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
                    elif action == 'retry_cloud' and not cloud_worker.thread.is_alive():
                        cloud_worker = GRNCloudWorker(db_path, stopping)
                        cloud_worker.thread.start()
                    elif action == "acknowledge_gap":
                        store.set_settings(capture_gap=False)
                    elif action == "reload":
                        loaded.clear()
                        engine.recovering = True
                        window.load_url("https://web.whatsapp.com/")
                    elif action == "probe" and loaded.is_set():
                        store.set_settings(last_probe=window.evaluate_js(PROBE_STRUCTURE_JS))
                    elif action == "import_photos" and loaded.is_set():
                        current = window.evaluate_js(read_script(store.setting("group", {}).get("id"), store.known_done_replies()))
                        if isinstance(current, dict) and current.get("group_id") == store.setting("group", {}).get("id"):
                            if photos.default_warehouse(current["group_id"]):
                                scan_requested = True
                            else:
                                store.set_settings(grn_capture_notice="Choose and save the default GRN warehouse before scanning photos.")
                        else:
                            store.set_settings(grn_capture_notice="Return to the selected group before importing photos.")
                    elif action == "select":
                        pending_selection = payload
                        selection_error = None
                if pending_selection is not None and loaded.is_set() and not stopping.is_set():
                    selection_snapshot = window.evaluate_js(read_script(known_done=store.known_done_replies()))
                    if not isinstance(selection_snapshot, dict) or not selection_snapshot.get("reply_scan_pending"):
                        try:
                            engine.select(selection_snapshot, pending_selection.get("import_visible", False))
                        except ValueError as exc:
                            selection_error = str(exc)
                        pending_selection = None
                if stopping.is_set():
                    break
                while not photo_results.empty():
                    source_id, token, result = photo_results.get_nowait()
                    # Ignore late callbacks from a timed-out request.
                    if photo_inflight.get(source_id) != token:
                        continue
                    try:
                        if isinstance(result, dict) and result.get("waiting"):
                            photos.capture_waiting(source_id, result.get("error", "Loading original photo."))
                        elif not isinstance(result, dict) or result.get("error") or not result.get("data"):
                            photos.capture_failed(source_id, result.get("error", "Photo retrieval failed.") if isinstance(result, dict) else "Photo retrieval failed.")
                        else:
                            photos.save_image(source_id, result["data"])
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        photos.capture_failed(source_id, str(exc))
                    if not isinstance(result, dict) or not result.get('waiting'):
                        photo_owner_id = None
                    photo_inflight.pop(source_id, None)
                for source_id, started in tuple(photo_inflight.items()):
                    if time.monotonic() - started > 15:
                        photos.capture_failed(source_id, "Photo retrieval timed out. Capture will retry.")
                        photo_inflight.pop(source_id, None)
                        photo_owner_id = None
                snapshot = None
                if not loaded.is_set():
                    engine.report("Starting", "Loading WhatsApp Web...")
                elif not store.setting("enabled", False):
                    if selection_error:
                        engine.report("Group selection required", selection_error)
                    else:
                        engine.report("Paused" if store.setting("group") else "Setup required",
                                      "Open the Browser tab, sign in, and select the group.")
                else:
                    snapshot = window.evaluate_js(read_script(store.setting("group", {}).get("id"), store.known_done_replies()))
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
                            if not snapshot.get("reply_scan_pending"):
                                recency = photos.discover(snapshot, baseline=initial, recent_only=True)
                                window.evaluate_js(photo_ack_script(snapshot))
                                if initial:
                                    photos.set_settings(grn_capture_initialized=snapshot["group_id"])
                            notice = snapshot.get('photo_notice', '') or ("Some photo senders could not be verified as incoming. Check the group for missing photos." if snapshot.get("unclassifiedPhotos") else "")
                            if not snapshot.get('reply_scan_pending') and recency['unknown_time']:
                                notice = (notice + ' ' if notice else '') + f"Skipped {recency['unknown_time']} photo(s): received time unavailable or unsupported. Only the last hour is scanned."
                            if store.setting("grn_capture_notice", "") != notice:
                                store.set_settings(grn_capture_notice=notice)
                            if not snapshot.get("reply_scan_pending"):
                                window.evaluate_js(FOLLOW_LATEST_JS)
                        except sqlite3.Error:
                            engine.report("Storage error", "Capture is waiting for local inbox storage; requests will be retried.")
                # Explicit imports can also complete while monitoring is paused for review.
                if loaded.is_set() and len(photo_inflight) < 1 and store.setting("group"):
                    if snapshot is None:
                        snapshot = window.evaluate_js(read_script(store.setting("group", {}).get("id"), store.known_done_replies()))
                    valid = (isinstance(snapshot, dict) and not snapshot.get("error")
                             and snapshot.get("group_id") == store.setting("group", {}).get("id"))
                    if valid:
                        photos.observe_messages(snapshot)
                        if scan_requested and not snapshot.get("reply_scan_pending"):
                            recency = photos.discover(snapshot, import_visible=True, recent_only=True)
                            window.evaluate_js(photo_ack_script(snapshot))
                            photos.set_settings(grn_capture_initialized=snapshot["group_id"],
                                                grn_scan_status=f"Scan complete: {recency['eligible']} photo(s) within the last hour; {recency['outside_window']} outside the window and {recency['unknown_time']} with unverified times skipped. Cleared and DONE items stay hidden.")
                            scan_requested = False
                    visible_ids = {p['message_id'] for key in ('photos', 'unclassifiedPhotos')
                                   for p in snapshot.get(key, [])} if valid and not snapshot.get("reply_scan_pending") else set()
                    if valid and 'visible_photos' in snapshot:
                        visible_ids.intersection_update(snapshot['visible_photos'])
                    if photo_owner_id is not None:
                        active = photos.db.execute("SELECT group_id,message_id,message_time,hidden_reason,capture_refresh,document_id FROM grn_sources WHERE id=?", (photo_owner_id,)).fetchone()
                        if not active or active['hidden_reason'] or active['group_id'] != store.setting('group')['id'] or (active['document_id'] and not active['capture_refresh']):
                            photo_owner_id = None
                        elif not grn_photo_is_recent(active['message_time']):
                            photos.capture_waiting(photo_owner_id, 'Outside the last-hour scan window; capture skipped.')
                            photo_owner_id = None
                        elif valid and not snapshot.get('reply_scan_pending') and active['message_id'] not in visible_ids:
                            photos.capture_waiting(photo_owner_id, 'Photo message is outside the rendered history. Open its message to complete capture.')
                            photo_owner_id = None
                    pending = photos.pending_capture(store.setting("group")["id"],
                        limit=1-len(photo_inflight), exclude_ids=photo_inflight, visible_ids=visible_ids, owner_id=photo_owner_id, recent_only=True)
                    for source in pending:
                        photo_owner_id = source['id']
                        token = time.monotonic()
                        photo_inflight[source["id"]] = token
                        try:
                            window.evaluate_js(photo_read_script(source["group_id"], source["message_id"], source["photo_index"]),
                                callback=lambda result, source_id=source["id"], token=token: photo_done(source_id, token, result))
                        except Exception as exc:
                            photos.capture_failed(source["id"], f"Photo retrieval failed ({type(exc).__name__}). Retry capture.")
                            photo_inflight.pop(source["id"], None)
                            photo_owner_id = None
                photo_wake.wait(.5)
                photo_wake.clear()
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
