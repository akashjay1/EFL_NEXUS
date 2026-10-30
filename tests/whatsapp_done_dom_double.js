// Minimal, explicitly labelled DOM test double for the live-verified quote
// highlight protocol. This does not establish WhatsApp markup compatibility.
const fs = require('fs');
const {script, scenario} = JSON.parse(fs.readFileSync(0, 'utf8'));
const animations = [];
const nodes = new Map();
let restored = false;
function row(id) {
    const node = {
        parentElement: null,
        getAttribute: key => key === 'data-id' ? id : null,
        closest: () => node,
        scrollIntoView: () => { restored = true; },
        querySelectorAll: () => [],
        querySelector: () => null
    };
    nodes.set(id, node);
    return node;
}
const original = row('test-original');
const reply = row('test-reply');
const highlight = target => ({effect: {
    target,
    getKeyframes: () => [
        {offset: 0, backgroundColor: 'transparent'},
        {offset: .5, backgroundColor: 'green'},
        {offset: 1, backgroundColor: 'transparent'}
    ]
}});
reply.querySelector = () => ({click() {
    if (scenario === 'ready' || scenario === 'ambiguous' || scenario === 'interrupted') animations.push(highlight(original));
    if (scenario === 'ambiguous') animations.push(highlight(row('test-other')));
    if (scenario === 'unrelated-animation') animations.push({effect: {target: original, getKeyframes: () => [{offset: 0, opacity: 0}]}});
}});
global.window = {};
global.document = {
    querySelectorAll: () => [...nodes.values()],
    querySelector: () => null,
    getAnimations: () => animations,
    addEventListener: () => {}
};
global.getComputedStyle = () => ({overflowY: 'visible'});
const run = new Function('snapshot', script);
const snapshot = () => ({group_id: 'test-group', messages: [], photos: [], replies: [
    {id: 'test-reply', text: 'DONE', reply_to: null}
]});
const first = run(snapshot());
if (window.__nexusDoneNavigation) {
    window.__nexusDoneNavigation.started -= 2500;
    if (scenario === 'interrupted') window.__nexusDoneNavigation.interrupted = true;
}
const second = run(snapshot());
process.stdout.write(JSON.stringify({first, second, restored}));
