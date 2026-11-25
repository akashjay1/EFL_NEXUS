// Synthetic protocol fixtures only. No cloud accounts/devices or production credentials.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {adminAction,databaseError,enrollment,readBody,telemetry,screenVerify,deviceStatus,fingerprint} from '../supabase/functions/_shared/protocol.ts';
const id='10000000-0000-4000-8000-000000000001';
const secret='a'.repeat(64);
const event={id,sequence:1,type:'started',timestamp:'2026-11-02T00:00:00Z',payload:{operator_name:'TEST-PC',identity_source:'Device Fallback',device_name:'TEST-PC',module:'Dashboard',app_version:'test-only'}};
test('fallback and validated profile labels have explicit identity sources',()=>{
  assert.equal(telemetry({session_id:id,events:[event]},id,secret).p_events[0].payload.identity_source,'Device Fallback');
  assert.equal(telemetry({session_id:id,events:[{...event,payload:{...event.payload,operator_name:'Test Operator',identity_source:'KPI Profile'}}]},id,secret).p_events[0].payload.operator_name,'Test Operator');
  assert.throws(()=>telemetry({session_id:id,events:[{...event,payload:{...event.payload,operator_name:'Wrong fallback'}}]},id,secret));
});
test('unexpected business fields and user metadata cannot enter telemetry',()=>{
  for(const key of ['kpi_user_code','password','document','user_metadata']) {
    assert.throws(()=>telemetry({session_id:id,events:[{...event,payload:{...event.payload,[key]:'test-only'}}]},id,secret));
  }
  assert.throws(()=>telemetry({session_id:id,events:[event],secret},id,secret));
});
test('bounded batches, safe sequences, explicit UTC and finite idle values',()=>{
  assert.throws(()=>telemetry({session_id:id,events:Array(51).fill(event)},id,secret));
  for(const sequence of [0,-1,1.5,Number.MAX_SAFE_INTEGER+1,null]) assert.throws(()=>telemetry({session_id:id,events:[{...event,sequence}]},id,secret));
  assert.throws(()=>telemetry({session_id:id,events:[{...event,timestamp:'2026-11-02 00:00'}]},id,secret));
  assert.throws(()=>telemetry({session_id:id,events:[],live:{sequence:1,sent_at:event.timestamp,idle_seconds:Infinity}},id,secret));
});
test('enrollment retries retain the same locally saved credential identity',()=>{
  const input={enrollment_id:id,installation_uuid:id,credential_id:id,code:secret,secret};
  assert.deepEqual(enrollment(input),enrollment(input));
  assert.throws(()=>enrollment({...input,installation_uuid:null}));
  assert.throws(()=>enrollment({...input,secret:'sb_secret_TEST_DOUBLE'}));
});
test('admin requests cannot set credential hashes or grant arbitrary roles',()=>{
  assert.throws(()=>adminAction({action:'reserve_admin',args:{email:'test@example.invalid',role:'superuser'}}));
  assert.throws(()=>adminAction({action:'create_enrollment',args:{enrollment_id:id,installation_uuid:id,device_name:'Test',account_label:'Test',code_hash:'injected'}}));
  assert.equal(adminAction({action:'reserve_admin',args:{email:'TEST@EXAMPLE.INVALID',role:'admin'}}).args.email,'test@example.invalid');
});
test('database errors reveal neither stored records nor secret values',()=>{
  for(const [sql,state] of [['42501',403],['23505',409],['P0409',409],['P0429',429],['22P02',400],['XX000',503]]) assert.equal(databaseError(sql).status,state);
});
test('request reader enforces method, content type, JSON and actual streamed size',async()=>{
  await assert.rejects(()=>readBody(new Request('https://test.invalid',{method:'GET'})));
  await assert.rejects(()=>readBody(new Request('https://test.invalid',{method:'POST',body:'{}'})));
  await assert.rejects(()=>readBody(new Request('https://test.invalid',{method:'POST',headers:{'content-type':'application/json'},body:'not-json'})));
  await assert.rejects(()=>readBody(new Request('https://test.invalid',{method:'POST',headers:{'content-type':'application/json'},body:' '.repeat(65537)})));
  assert.deepEqual(await readBody(new Request('https://test.invalid',{method:'POST',headers:{'content-type':'application/json'},body:'{}'})),{});
});
test('screen views need a device, a real reason and an exact SHA-256 fingerprint',()=>{
  const fp=Array(32).fill('ab').join(':');
  const ok=adminAction({action:'start_screen_view',args:{device_id:id,reason:'Operator asked for help',fingerprint:fp}});
  assert.equal(ok.args.fingerprint,fp.toUpperCase());
  assert.throws(()=>adminAction({action:'start_screen_view',args:{device_id:id,reason:'x',fingerprint:fp}}));
  assert.throws(()=>adminAction({action:'start_screen_view',args:{device_id:id,reason:'help please',fingerprint:'AB:CD'}}));
  assert.throws(()=>adminAction({action:'start_screen_view',args:{device_id:id,reason:'help please',fingerprint:fp,extra:1}}));
  assert.throws(()=>fingerprint(fp.replace('ab','zz')));
});
test('device screen verification and status require the device credential',()=>{
  const fp=Array(32).fill('0F').join(':');
  assert.equal(screenVerify({view_id:id,fingerprint:fp},id,secret).p_view,id);
  assert.throws(()=>screenVerify({view_id:id,fingerprint:fp},id,'bad'));
  assert.throws(()=>screenVerify({view_id:id,fingerprint:fp,sdp:'x'},id,secret));
  assert.deepEqual(deviceStatus({},id,secret),{p_credential_id:id,p_secret:secret});
  assert.throws(()=>deviceStatus({},null,secret));
});
test('uninstall is an explicit boolean admin action',()=>{
  assert.equal(adminAction({action:'set_device_uninstall',args:{device_id:id,uninstall:true}}).args.uninstall,true);
  assert.throws(()=>adminAction({action:'set_device_uninstall',args:{device_id:id,uninstall:'yes'}}));
});
