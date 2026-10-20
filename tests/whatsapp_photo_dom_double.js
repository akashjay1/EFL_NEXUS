// Minimal DOM/media test double. No real WhatsApp DOM or network is used.
const fs = require('fs'), vm = require('vm');
const {script, scenario} = JSON.parse(fs.readFileSync(0, 'utf8'));
let opened=0,closed=0,fetches=0,modal=scenario==='user_viewer'?makeModal():null;
const window={};
const title={textContent:scenario==='wrong_group'?'Other group':'Test group'};
const match={getAttribute:()=> 'Test group'};
const selected={contains:()=>true};
const side={querySelectorAll:s=>s==='span[title]'?[match]:[selected]};
const image={complete:scenario!=='incomplete',naturalWidth:1200,naturalHeight:1600,
 currentSrc:'blob:https://web.whatsapp.com/test-double',parentElement:null};
const thumb={closest:()=>null,click:()=>{opened++;modal=makeModal();}};
const row={getAttribute:()=> 'test-message',querySelectorAll:()=>[thumb]};
function makeModal(){return {isConnected:true,contains:()=>false,querySelectorAll:s=>{
 if(s.includes('media-image')){if(scenario==='thumbnail_only')return [];image.parentElement=modal;return [image];}
 return [{getAttribute:()=> 'Close',click:()=>{closed++;modal.isConnected=false;modal=null;}}];
}};}
const document={addEventListener:()=>{},querySelector:s=>s==='#pane-side'?side:s.includes('chat-title-name')?title:modal,
 querySelectorAll:()=>[row]};
class FileReaderDouble {readAsDataURL(){this.result='data:image/jpeg;base64,dGVzdC1kb3VibGU=';this.onload();}}
const context={window,document,location:{origin:'https://web.whatsapp.com'},AbortController,
 getComputedStyle:el=>({filter:scenario==='blurred'&&el===image?'blur(8px)':'none',display:'block',visibility:'visible',opacity:'1'}),
 fetch:async()=>{fetches++;return {ok:scenario!=='fetch_error',blob:async()=>({size:20})};},
 FileReader:FileReaderDouble,setTimeout,clearTimeout,Date};
(async()=>{
 const first=await vm.runInNewContext(script,context);
 const result=first.waiting&&scenario!=='user_viewer'?await vm.runInNewContext(script,context):first;
 process.stdout.write(JSON.stringify({first:{waiting:first.waiting,error:first.error},result,opened,closed,fetches}));
})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1;});
