// Explicitly opt-in negative HTTP tests against the configured Supabase project.
// Synthetic credentials are never enrolled. Tests create no users or telemetry.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const config=JSON.parse(await readFile(new URL('../dashboard/public-config.json',import.meta.url),'utf8'));
const enabled=process.env.NEXUS_LIVE_TESTS==='true';
const uuid='10000000-0000-4000-8000-000000000001';
const fixtureSecret='a'.repeat(64); // TEST DOUBLE, no enrolled credential has this value.
async function request(path,body,extra={},withKey=true) {
  const result=await fetch(config.supabaseUrl+path,{method:body===undefined?'GET':'POST',redirect:'error',
    headers:{...(withKey?{apikey:config.supabasePublishableKey}:{}),'content-type':'application/json',...extra},
    ...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(20000)});
  return {status:result.status,body:await result.json()};
}
test('deployed enrollment rejects a syntactically valid unenrolled code',{skip:!enabled},async()=>{
  const r=await request('/functions/v1/device-enroll',{enrollment_id:uuid,code:fixtureSecret,installation_uuid:uuid,credential_id:uuid,secret:fixtureSecret});
  assert.equal(r.status,403,JSON.stringify(r.body)); assert.equal(r.body.error,'access_denied');
});
test('deployed telemetry rejects an unknown device credential',{skip:!enabled},async()=>{
  const r=await request('/functions/v1/device-telemetry',{session_id:uuid,events:[]},{'x-device-id':uuid,'x-device-secret':fixtureSecret});
  assert.equal(r.status,403,JSON.stringify(r.body)); assert.equal(r.body.error,'access_denied');
});
test('device API also requires the application key',{skip:!enabled},async()=>{
  const r=await request('/functions/v1/device-telemetry',{session_id:uuid,events:[]},{'x-device-id':uuid,'x-device-secret':fixtureSecret},false);
  assert.equal(r.status,401,JSON.stringify(r.body));
});
test('browser origins are rejected by desktop endpoints',{skip:!enabled},async()=>{
  const r=await request('/functions/v1/device-telemetry',{session_id:uuid,events:[]},{origin:'https://test-only.example.invalid'});
  assert.equal(r.status,403); assert.equal(r.body.error,'desktop_only');
});
test('anonymous clients cannot read device records',{skip:!enabled},async()=>{
  const r=await request('/rest/v1/devices?select=id'); assert.ok([401,403].includes(r.status),JSON.stringify(r.body));
});
test('anonymous clients cannot bypass Edge credential checks through RPC',{skip:!enabled},async()=>{
  const r=await request('/rest/v1/rpc/nexus_ingest',{p_credential_id:uuid,p_secret:fixtureSecret,p_session_id:uuid,p_events:[]});
  assert.ok([401,403].includes(r.status),JSON.stringify(r.body));
});
test('anonymous clients cannot reserve the bootstrap owner',{skip:!enabled},async()=>{
  const r=await request('/rest/v1/rpc/nexus_bootstrap_owner',{p_email:'test-only@example.invalid'});
  assert.ok([401,403].includes(r.status),JSON.stringify(r.body));
});
test('administrator endpoint denies calls without a user session',{skip:!enabled},async()=>{
  const r=await request('/functions/v1/admin-control',{action:'list_admins',args:{}});
  assert.equal(r.status,401,JSON.stringify(r.body));
});
