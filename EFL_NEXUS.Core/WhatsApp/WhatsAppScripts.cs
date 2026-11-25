using System.Text.Json;

namespace EflNexus.Core.WhatsApp;

/// <summary>
/// Verified WhatsApp Web DOM &amp; media scripts (1:1 parity with whatsapp_media.py, whatsapp_monitor.py, whatsapp_grn.py).
/// </summary>
public static class WhatsAppScripts
{
    public const int MaxImageBytes = 20 * 1024 * 1024;
    public const int MaxImagePixels = 30_000_000;
    public const int GrnScanWindowSeconds = 60 * 60;

    public static readonly IReadOnlyDictionary<string, string> MediaSelectors =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["rows"] = "[data-id][data-testid^=\"conv-msg-\"]",
            ["thumbnail"] = "[data-testid=\"image-thumb\"]",
            ["quote"] = "[data-testid=\"quoted-message\"]",
            ["viewer"] = "[data-testid=\"media-viewer-modal\"]",
            ["original"] = "[data-testid=\"media-image\"] img"
        };

    public static readonly string MediaAdapterJs =
        "const nexusMedia = " + JsonSerializer.Serialize(MediaSelectors) + @";
const nexusPhotoThumbs = row => [...row.querySelectorAll(nexusMedia.thumbnail)]
    .filter(el => !el.closest(nexusMedia.quote));
";

    public static readonly string ReadConversationJs = MediaAdapterJs + @"
if (location.origin !== 'https://web.whatsapp.com')
    return {error: 'Only WhatsApp Web can be monitored.', state: 'Unsupported page'};
if (!navigator.onLine) return {error: 'Waiting for the network.', state: 'Offline'};
const main = document.querySelector('#main');
const side = document.querySelector('#pane-side');
if (!main || !side) return {error: 'Sign in and open your GDN group.', state:
    side ? 'Group selection required' : 'Login or loading required'};
const title = main.querySelector('[data-testid=""conversation-info-header-chat-title-name""]');
const name = title && title.textContent.trim();
if (!name) return {error: 'Cannot read the conversation title.', state: 'Unsupported markup'};
const matching = [...side.querySelectorAll('span[title]')]
    .filter(el => el.getAttribute('title') === name);
const rowsWithName = new Set(matching.map(el => el.closest('[aria-selected]') || el));
const selected = [...side.querySelectorAll('[aria-selected=""true""]')];
if (rowsWithName.size !== 1 || selected.length !== 1 || !matching.some(el => selected[0].contains(el)))
    return {error: 'The group name is missing, duplicated, or does not match the selected sidebar chat.',
            state: 'Group selection required'};
if (!main.querySelector('[data-testid=""conversation-panel-messages""]'))
    return {error: 'WhatsApp message markup is unsupported.', state: 'Unsupported markup'};
const groupKey = 'name:' + name;
const byGroup = window.__nexusGdnIncomingAuthors || (window.__nexusGdnIncomingAuthors = new Map());
if (!byGroup.has(groupKey)) byGroup.set(groupKey, new Set());
const incomingAuthors = byGroup.get(groupKey);
const messageRows = [...main.querySelectorAll(nexusMedia.rows)];
if(!messageRows.length && main.querySelector(nexusMedia.thumbnail))
    return {error:'Photo message markup is unsupported. Reconnect or reopen the group.',state:'Unsupported markup'};
const isQuote = el => !!el.closest('[data-testid=""quoted-message""]');
const metadata = row => [...row.querySelectorAll('[data-pre-plain-text]')].find(el => !isQuote(el));
const authorKey = row => {
    const el=metadata(row);
    const value = el && el.getAttribute('data-pre-plain-text');
    const match = value && value.match(/^\[[^\]]+\]\s*(.+?):\s*$/s);
    if(match) return match[1];
    const author=[...row.querySelectorAll('[data-testid=""author""]')].find(e=>!isQuote(e));
    return author?.textContent.trim() || null;
};
for (const row of messageRows) {
    const tail = row.querySelector('[data-testid=""tail-in""]');
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
    if (text.toUpperCase()==='DONE' && row.querySelector('[data-testid=""quoted-message""]'))
        replies.push({...message,reply_to:null});
    const incomingTail = row.querySelector('[data-testid=""tail-in""]');
    const outgoingTail = row.querySelector('[data-testid=""tail-out""]');
    const outgoing = outgoingTail && !isQuote(outgoingTail);
    const incoming = !outgoing && ((incomingTail && !isQuote(incomingTail)) || incomingAuthors.has(authorKey(row)));
    if (text) {
        if (incoming) messages.push(message);
        else unclassified.push(message);
    }
    if (!outgoing) images.forEach((img,index) => (incoming ? photos : unclassifiedPhotos).push({message_id:message.id,index,message_time:message.message_time}));
}
const panel=main.querySelector('[data-testid=""conversation-panel-messages""]');
let observer=window.__nexusGrnPhotoObserver;
if(observer && (observer.panel!==panel || observer.group!==groupKey)) {
    observer.watcher.disconnect(); delete window.__nexusGrnPhotoObserver; observer=null;
}
const visible_photos=[...photos,...unclassifiedPhotos].map(p=>p.message_id);
if(typeof MutationObserver!=='undefined' && !observer) {
    observer={panel,group:groupKey,pending:new Map(),sequence:0,overflow:false};
    observer.watcher=new MutationObserver(records=>{
        if(document.querySelector('#main [data-testid=""conversation-info-header-chat-title-name""]')?.textContent.trim()!==name) return;
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
            const tail=row.querySelector('[data-testid=""tail-out""]');
            if(tail && !isQuote(tail)) continue;
            const incoming=row.querySelector('[data-testid=""tail-in""]');
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
";

    public static readonly string AckPhotosJs = @"
const observer=window.__nexusGrnPhotoObserver;
if(observer && observer.group===snapshot.group_id) {
    for(const [key,token] of snapshot.photo_observations || []) {
        if(observer.pending.get(key)?.observation===token) observer.pending.delete(key);
    }
    observer.overflow=false;
}
";

    public static string PhotoAckScript(WhatsAppSnapshot snapshot)
    {
        var payload = new
        {
            group_id = snapshot.GroupId,
            photo_observations = snapshot.PhotoObservations
        };
        return "(() => {const snapshot=" + JsonSerializer.Serialize(payload) + ";" + AckPhotosJs + "})()";
    }

    public static readonly string ResolveDoneJs = @"
if (snapshot.error) return snapshot;
const caches=window.__nexusDoneLinks || (window.__nexusDoneLinks=new Map());
if(!caches.has(snapshot.group_id)) caches.set(snapshot.group_id,new Map());
const cache=caches.get(snapshot.group_id), now=Date.now();
const rowFor=id=>[...document.querySelectorAll('#main [data-id][data-testid^=""conv-msg-""]')]
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
        const target=animation.effect.target?.closest('#main [data-id][data-testid^=""conv-msg-""]');
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
            .filter(e=>!e.closest('[data-testid=""quoted-message""]'));
        const roots=textNodes.filter(e=>!textNodes.some(other=>other!==e && other.contains(e)));
        const meta=[...row.querySelectorAll('[data-pre-plain-text]')].find(e=>!e.closest('[data-testid=""quoted-message""]'));
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
if(window.__nexusGrnOriginal || document.querySelector('[data-testid=""media-viewer-modal""]'))
    return {...snapshot,reply_scan_pending:true};
const row=rowFor(pending.id), button=row?.querySelector('[data-testid=""quoted-message""] [aria-label=""Quoted message""]');
if(!button){cache.set(pending.id,{target:null,retry:now+30000});return snapshot;}
let scroller=row.parentElement;
while(scroller && !(scroller.scrollHeight>scroller.clientHeight && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller=scroller.parentElement;
owner={group:snapshot.group_id,reply:pending.id,started:now,snapshot,
    before:new Set(document.getAnimations()),
    scroller,scrollTop:scroller?.scrollTop,events:new AbortController(),interrupted:false};
owner.anchor=[...document.querySelectorAll('#main [data-id][data-testid^=""conv-msg-""]')].at(-1)?.getAttribute('data-id');
window.__nexusDoneNavigation=owner;
const interrupt=e=>{if(e.isTrusted) owner.interrupted=true;};
document.addEventListener('pointerdown',interrupt,{capture:true,signal:owner.events.signal});
document.addEventListener('keydown',interrupt,{capture:true,signal:owner.events.signal});
button.click();
return {...snapshot,reply_scan_pending:true};
";

    public static string ReadScript(string? expectedGroup = null, Dictionary<string, Dictionary<string, string>>? knownDone = null)
    {
        var guard = !string.IsNullOrEmpty(expectedGroup)
            ? "if(snapshot.group_id!==" + JsonSerializer.Serialize(expectedGroup) + ") return snapshot;\n"
            : "";
        var remembered = "";
        if (knownDone is { Count: > 0 })
        {
            remembered = "const remembered=" + JsonSerializer.Serialize(knownDone) + ";" +
                "const savedLinks=window.__nexusDoneLinks || (window.__nexusDoneLinks=new Map());" +
                "if(!savedLinks.has(snapshot.group_id)) savedLinks.set(snapshot.group_id,new Map());" +
                "for(const [reply,target] of Object.entries(remembered[snapshot.group_id] || {}))" +
                "savedLinks.get(snapshot.group_id).set(reply,{target,retry:Infinity});\n";
        }
        return "(() => {const snapshot=(()=>{\n" + ReadConversationJs + "\n})();\nif(snapshot.error) return snapshot;\n" + guard + remembered + ResolveDoneJs + "\n})()";
    }

    public static string RestoreGroupScript(string name)
    {
        return @"(() => {
        if (location.origin !== 'https://web.whatsapp.com') return false;
        const side = document.querySelector('#pane-side');
        if (!side) return false;
        const titles = [...side.querySelectorAll('span[title]')]
            .filter(el => el.getAttribute('title') === " + JsonSerializer.Serialize(name) + @");
        if (titles.length !== 1) return false;
        const target=titles[0];
        target.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true,button:0,buttons:1,pointerType:'mouse',isPrimary:true}));
        target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true,button:0,buttons:1}));
        target.dispatchEvent(new PointerEvent('pointerup', {bubbles:true,button:0,buttons:0,pointerType:'mouse',isPrimary:true}));
        target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true,button:0}));
        target.click(); return true;
    })()";
    }

    public const string FollowLatestJs = @"(() => {
    const rows = document.querySelectorAll('#main [data-id]');
    if (rows.length) rows[rows.length - 1].scrollIntoView({block: 'end', behavior: 'auto'});
})()";

    public const string ProbeStructureJs = @"(() => {
    const main = document.querySelector('#main');
    const rows = [...document.querySelectorAll('#main [data-id]')];
    const incoming = [...document.querySelectorAll('#main .message-in')];
    return {
        origin: location.origin, main: !!main, data_rows: rows.length,
        done_links: [...(window.__nexusDoneLinks?.get('name:'+main?.querySelector('[data-testid=""conversation-info-header-chat-title-name""]')?.textContent.trim()) || new Map())]
            .map(([reply,info])=>({reply,target:info.target})),
        done_scan_pending: !!window.__nexusDoneNavigation,
        quoted_structure: rows.filter(r=>r.querySelector('[data-testid=""quoted-message""]')).slice(-12).map(r=>({
            id:r.getAttribute('data-id'),
            done:[...r.querySelectorAll('[data-pre-plain-text] .selectable-text')]
                .filter(e=>!e.closest('[data-testid=""quoted-message""]')).map(e=>e.innerText).join('\n').trim().toUpperCase()==='DONE',
            outgoing:!!r.querySelector('[data-testid=""tail-out""]'),
            quoted_photo:!!r.querySelector('[data-testid=""quoted-message""] [data-testid=""image-thumb""]')
        })),
        mediaRows: rows.filter(r => r.querySelector('[data-testid=""media-url-provider""]')).map(r => ({
            testid: r.getAttribute('data-testid'),
            metadata: !!r.querySelector('[data-pre-plain-text]'),
            tail: !!r.querySelector('[data-testid=""tail-in""]'),
            testids: [...new Set([...r.querySelectorAll('[data-testid]')].map(e=>e.getAttribute('data-testid')))],
            thumbs: [...r.querySelectorAll('[data-testid=""image-thumb""]')].map(t => ({
                icons: [...t.querySelectorAll('[data-icon]')].map(e=>e.getAttribute('data-icon')),
                controls: [...t.querySelectorAll('button,[role=""button""]')].map(e=>({
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
        selectable: main ? main.querySelectorAll('.selectable-text').length : 0,
        copyable_structure: main ? [...main.querySelectorAll('[data-pre-plain-text]')].slice(0, 2).map(el => {
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
        selected_rows: [...document.querySelectorAll('#pane-side [aria-selected=""true""]')].map(el => ({
            tag: el.tagName, attributes: [...el.attributes].map(a => a.name),
            ids: [...el.querySelectorAll('[data-id]')].map(item => item.getAttribute('data-id')
                .replace(/[0-9]/g, '0').replace(/[a-fA-F]/g, 'X'))
        })),
        jid_attributes: [...document.querySelectorAll('*')].flatMap(el => [...el.attributes]
            .filter(a => /@g\.us/.test(a.value)).map(a => ({tag: el.tagName, name: a.name,
                shape: a.value.replace(/[0-9]/g, '0').replace(/[a-fA-F]/g, 'X')}))).slice(0, 8),
        testids: main ? [...new Set([...main.querySelectorAll('[data-testid]')].map(el => el.getAttribute('data-testid')))] : [],
        bubble_layout: main ? [...main.querySelectorAll('[data-testid=""msg-container""]')].slice(0, 8).map(el => {
            const s = getComputedStyle(el);
            return {float: s.cssFloat, background: s.backgroundColor, textAlign: s.textAlign,
                direction: s.direction, left: s.left, right: s.right, position: s.position,
                incomingTail: !!el.querySelector('[data-testid=""tail-in""]'),
                outgoingTail: !!el.querySelector('[data-testid=""tail-out""]')};
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
})()";

    public static string PhotoReadScript(string groupId, string messageId, int index)
    {
        return $@"(async () => {{
        {MediaAdapterJs}
        const groupId={JsonSerializer.Serialize(groupId)}, messageId={JsonSerializer.Serialize(messageId)}, photoIndex={index};
        const waiting=error=>({{error,waiting:true}});
        if(window.__nexusDoneNavigation) return waiting('Checking DONE reply links before opening photos.');
        const title=()=>document.querySelector('#main [data-testid=""conversation-info-header-chat-title-name""]');
        const validGroup=()=>{{
            const header=title(),side=document.querySelector('#pane-side');
            if(!header || 'name:'+header.textContent.trim()!==groupId || !side) return false;
            const matches=[...side.querySelectorAll('span[title]')].filter(e=>e.getAttribute('title')===header.textContent.trim());
            const selected=[...side.querySelectorAll('[aria-selected=""true""]')];
            return matches.length===1 && selected.length===1 && selected[0].contains(matches[0]);
        }};
        if(location.origin!=='https://web.whatsapp.com' || !validGroup())
            return {{error:'Return to the selected group to load the original photo.'}};
        const row=[...document.querySelectorAll('#main '+nexusMedia.rows)]
            .find(e=>e.getAttribute('data-id')===messageId);
        const thumb=row && nexusPhotoThumbs(row)[photoIndex];
        let owner=window.__nexusGrnOriginal;
        if(!thumb && !owner) return {{error:row?'Photo markup is unsupported or this album item is not loaded. Reopen the message and retry capture.':'Photo message is outside the rendered history. Open its message to complete capture.'}};
        let modal=document.querySelector(nexusMedia.viewer);
        const finish=close=>{{
            if(!owner || window.__nexusGrnOriginal!==owner) return;
            owner.events.abort();
            if(close && !owner.interrupted && owner.modal?.isConnected && validGroup()) {{
                const buttons=[...owner.modal.querySelectorAll('button,[role=""button""]')]
                    .filter(e=>e.getAttribute('aria-label')==='Close');
                if(buttons.length===1) buttons[0].click();
            }}
            delete window.__nexusGrnOriginal;
        }};
        if(owner && owner.interrupted){{finish(false);return waiting('Photo loading paused while you use the WhatsApp viewer. Close it to continue.');}}
        if(owner && Date.now()-owner.started>12000){{finish(true);return {{error:'Original photo did not finish loading. Capture will retry.'}};}}
        if(owner && (owner.messageId!==messageId || owner.photoIndex!==photoIndex || owner.groupId!==groupId))
            return waiting('Waiting for another original photo to finish loading.');
        if(!owner){{
            if(modal) return waiting('Close WhatsApp\u2019s photo viewer to let automatic original-photo capture continue.');
            owner={{groupId,messageId,photoIndex,started:Date.now(),events:new AbortController(),modal:null,interrupted:false}};
            window.__nexusGrnOriginal=owner;
            const interrupt=e=>{{if(e.isTrusted && document.querySelector(nexusMedia.viewer)?.contains(e.target)) owner.interrupted=true;}};
            document.addEventListener('pointerdown',interrupt,{{capture:true,signal:owner.events.signal}});
            document.addEventListener('keydown',interrupt,{{capture:true,signal:owner.events.signal}});
            thumb.click();
            modal=document.querySelector(nexusMedia.viewer);
            owner.modal=modal;
            return waiting('Loading the original photo from WhatsApp.');
        }}
        if(!modal){{finish(false);return waiting('Opening original photo. Capture will retry.');}}
        if(owner.modal && owner.modal!==modal){{finish(false);return waiting('WhatsApp\u2019s photo viewer changed. Close it to continue capture.');}}
        owner.modal=modal;
        const full=[...modal.querySelectorAll(nexusMedia.original)].filter(img=>{{
            if(!img.complete || img.naturalWidth<300 || img.naturalHeight<300 || !(img.currentSrc||img.src).startsWith('blob:https://web.whatsapp.com/')) return false;
            for(let e=img;e && e!==modal;e=e.parentElement){{
                const s=getComputedStyle(e);
                if(s.filter!=='none' || s.visibility==='hidden' || s.display==='none' || Number(s.opacity)===0) return false;
            }}
            return true;
        }});
        if(full.length!==1) return waiting('Waiting for WhatsApp to load the full photo, rather than its blurred preview.');
        const img=full[0],src=img.currentSrc||img.src;
        const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
        try {{
            const response=await fetch(src,{{signal:abort.signal}});
            if(!response.ok) throw Error('Original photo could not be retrieved.');
            const blob=await response.blob();
            if(blob.size>{MaxImageBytes}) throw Error('Photo exceeds the 20 MB capture limit.');
            const data=await new Promise((resolve,reject)=>{{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('Photo read failed.'));r.readAsDataURL(blob);}});
            if(!validGroup() || owner.interrupted || !modal.isConnected || (img.currentSrc||img.src)!==src)
                throw Error('The group or photo changed during capture. Retry in the selected group.');
            return {{data:data.slice(data.indexOf(',')+1),width:img.naturalWidth,height:img.naturalHeight,quality:'full_viewer'}};
        }} catch(e){{return {{error:String(e.message||e)}};}}
        finally{{clearTimeout(timer);finish(true);}}
    }})()";
    }
}
