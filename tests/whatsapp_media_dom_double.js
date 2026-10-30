// Minimal test-only DOM/MutationObserver double. This is not live WhatsApp evidence.
const fs = require('fs');
const {script, ack_script, scenario} = JSON.parse(fs.readFileSync(0, 'utf8'));
global.window = {};
global.location = {origin: 'https://web.whatsapp.com'};
Object.defineProperty(global, 'navigator', {value: {onLine: true}, configurable: true});
let callback, rows = [];
const panel = {};
const marker = {closest: () => null};
const title = {textContent: 'Test group'};
const match = {getAttribute: () => 'Test group', closest: () => match};
const selected = {contains: () => true};
const side = {querySelectorAll: selector => selector === 'span[title]' ? [match] : [selected]};
function photoRow(id, {incoming = true, outgoing = false, count = 1, author = 'Test author', quoted = false} = {}) {
    const thumbs = Array.from({length: count}, () => ({closest: () => quoted ? {} : null}));
    const row = {
        getAttribute: name => name === 'data-id' ? id : null,
        closest: () => row,
        querySelector: selector => selector.includes('tail-in') ? (incoming ? marker : null) :
            selector.includes('tail-out') ? (outgoing ? marker : null) : null,
        querySelectorAll: selector => selector.includes('image-thumb') ? thumbs :
            selector.includes('[data-testid="author"]') ? [{textContent: author, closest: () => null}] : [],
    };
    return row;
}
const main = {
    querySelector: selector => selector.includes('chat-title-name') ? title :
        selector.includes('conversation-panel-messages') ? panel : null,
    querySelectorAll: () => rows,
};
global.document = {querySelector: selector => selector === '#main' ? main :
    selector === '#pane-side' ? side : selector.includes('chat-title-name') ? title : null};
global.MutationObserver = class MutationObserverDouble {
    constructor(fn) {callback = fn;}
    observe() {}
    disconnect() {}
};
const read = new Function(script);
if (scenario === 'album') {
    rows = [photoRow('album', {count: 3})];
    process.stdout.write(JSON.stringify(read()));
} else if (scenario === 'directions') {
    rows = [photoRow('incoming'), photoRow('outgoing', {outgoing: true}),
            photoRow('quote', {quoted: true}), photoRow('uncertain', {incoming: false, author: 'Unverified author'})];
    process.stdout.write(JSON.stringify(read()));
} else {
    read(); // Install the observer before a transient photo arrives.
    const incoming = photoRow('transient-album', {count: 2});
    callback([{target: incoming, addedNodes: [incoming]}]);
    if (scenario === 'group_changed') title.textContent = 'Other group';
    const first = read(), repeated = read();
    new Function('snapshot', ack_script)(first);
    const second = read();
    process.stdout.write(JSON.stringify({first, repeated, second}));
}
