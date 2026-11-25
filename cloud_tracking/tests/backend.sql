-- Live PostgreSQL verification with explicitly synthetic test fixtures.
-- Every fixture and mutation is inside a subtransaction deliberately rolled back.
-- No real administrator, enrollment, device or session is modified.
create or replace function pg_temp.check_true(ok boolean,label text) returns jsonb language plpgsql as $$
begin
  if not coalesce(ok,false) then raise exception 'FAILED: %',label; end if;
  return jsonb_build_array(label);
end $$;
create or replace function pg_temp.expect_error(statement text,expected text,label text) returns jsonb language plpgsql as $$
declare code text;
begin
  begin execute statement; exception when others then get stacked diagnostics code=returned_sqlstate; end;
  if code is distinct from expected then raise exception 'FAILED: %, expected %, got %',label,expected,coalesce(code,'success'); end if;
  return jsonb_build_array(label);
end $$;
create or replace function pg_temp.verify_monitoring() returns jsonb language plpgsql as $$
<<fixture>>
declare
  checks jsonb:='[]'; owner_id uuid:=gen_random_uuid(); owner_session uuid:=gen_random_uuid();
  nonadmin_id uuid:=gen_random_uuid(); nonadmin_session uuid:=gen_random_uuid();
  device_uuid uuid:=gen_random_uuid(); device_uuid2 uuid:=gen_random_uuid(); device_id uuid; device_id2 uuid;
  enrollment_id uuid:=gen_random_uuid(); enrollment2 uuid:=gen_random_uuid(); enrollment3 uuid:=gen_random_uuid();
  credential_id uuid:=gen_random_uuid(); credential2 uuid:=gen_random_uuid(); credential3 uuid:=gen_random_uuid();
  session_id uuid:=gen_random_uuid(); session2 uuid:=gen_random_uuid(); session3 uuid:=gen_random_uuid();
  start_id uuid:=gen_random_uuid(); event2 uuid:=gen_random_uuid(); event3 uuid:=gen_random_uuid(); event4 uuid:=gen_random_uuid();
  events jsonb; result jsonb; snapshot jsonb; stamp timestamptz:=now()-interval '10 minutes';
  test_owner_email text:='owner-'||gen_random_uuid()||'@example.invalid';
begin
  begin
    -- Test doubles: non-deliverable email addresses and fixed, unenrolled hex secrets.
    insert into nexus_private.admin_invitations(email,role,slot) values(test_owner_email,'owner',5);
    insert into auth.users(id,email,email_confirmed_at) values(owner_id,test_owner_email,now());
    insert into auth.sessions(id,user_id,aal,created_at,updated_at) values(owner_session,owner_id,'aal2',now(),now());
    checks:=checks||pg_temp.check_true(exists(select 1 from public.admin_profiles where user_id=owner_id),'reserved verified owner activates');
    checks:=checks||pg_temp.expect_error(format('insert into auth.users(id,email) values(%L,%L)',gen_random_uuid(),'not-invited@example.invalid'),'42501','uninvited signup rejected');
    insert into nexus_private.admin_invitations(email,role,slot) values('pending-'||nonadmin_id||'@example.invalid','admin',4);
    insert into auth.users(id,email) values(nonadmin_id,'pending-'||nonadmin_id||'@example.invalid');
    insert into auth.sessions(id,user_id,aal) values(nonadmin_session,nonadmin_id,'aal2');
    update nexus_private.admin_invitations set revoked_at=now(),slot=null where email='pending-'||nonadmin_id||'@example.invalid';
    checks:=checks||pg_temp.check_true(not exists(select 1 from public.admin_profiles where user_id=nonadmin_id),'unverified email cannot activate administrator');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_admin_action(%L,%L,%L,%L)',nonadmin_id,nonadmin_session,'list_admins','{}'),'42501','authenticated nonadministrator denied');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_admin_action(%L,%L,%L,%L)',owner_id,owner_session,'revoke_admin',jsonb_build_object('user_id',owner_id)),'23514','final owner removal rejected');
    for i in 1..3 loop
      perform public.nexus_admin_action(owner_id,owner_session,'reserve_admin',jsonb_build_object('email','slot-'||i||'-'||owner_id||'@example.invalid','role','admin'));
    end loop;
    checks:=checks||pg_temp.expect_error(format('select public.nexus_admin_action(%L,%L,%L,%L)',owner_id,owner_session,'reserve_admin',jsonb_build_object('email','overflow@example.invalid','role','admin')),'23514','five active and pending administrator slots enforced');
    checks:=checks||pg_temp.check_true(not has_function_privilege('anon','public.nexus_ingest(uuid,text,uuid,jsonb,jsonb)','execute'),'anonymous role cannot invoke privileged ingestion');
    checks:=checks||pg_temp.check_true(not has_function_privilege('authenticated','public.nexus_admin_action(uuid,uuid,text,jsonb)','execute'),'browser cannot impersonate an admin actor via service RPC');
    checks:=checks||pg_temp.check_true(not has_table_privilege('authenticated','nexus_private.device_credentials','select'),'device hashes not readable by authenticated clients');

    result:=public.nexus_admin_action(owner_id,owner_session,'create_enrollment',jsonb_build_object('enrollment_id',enrollment_id,'installation_uuid',device_uuid,'device_name','TEST-PC','account_label','Test account A','code_hash',encode(sha256(convert_to(repeat('b',64),'UTF8')),'hex')));
    device_id:=(result->>'device_id')::uuid;
    result:=public.nexus_claim_enrollment(enrollment_id,repeat('b',64),device_uuid,credential_id,repeat('a',64));
    checks:=checks||pg_temp.check_true(result->>'replayed'='false','one-time enrollment claim accepted');
    result:=public.nexus_claim_enrollment(enrollment_id,repeat('b',64),device_uuid,credential_id,repeat('a',64));
    checks:=checks||pg_temp.check_true(result->>'replayed'='true','lost enrollment response can be retried safely');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_claim_enrollment(%L,%L,%L,%L,%L)',enrollment_id,repeat('b',64),device_uuid,gen_random_uuid(),repeat('a',64)),'42501','consumed code cannot enroll a second credential');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_claim_enrollment(%L,%L,null,%L,%L)',enrollment_id,repeat('b',64),credential_id,repeat('a',64)),'42501','missing installation identity rejected');
    perform public.nexus_admin_action(owner_id,owner_session,'create_enrollment',jsonb_build_object('enrollment_id',enrollment2,'installation_uuid',device_uuid,'device_name','TEST-PC','account_label','Test account B','code_hash',encode(sha256(convert_to(repeat('c',64),'UTF8')),'hex')));
    perform public.nexus_claim_enrollment(enrollment2,repeat('c',64),device_uuid,credential2,repeat('d',64));
    checks:=checks||pg_temp.check_true((select count(*) from public.devices where installation_uuid=device_uuid)=1,'Windows accounts share one installation device');
    checks:=checks||pg_temp.check_true((select count(*) from nexus_private.device_credentials dc where dc.device_id=fixture.device_id)=2,'Windows accounts retain separate credentials');

    events:=jsonb_build_array(jsonb_build_object('id',start_id,'sequence',1,'type','started','timestamp',stamp,'payload',jsonb_build_object('device_name','TEST-PC','operator_name','Test Operator A','identity_source','KPI Profile','module','Dashboard','app_version','test-only')));
    result:=public.nexus_ingest(credential_id,repeat('a',64),session_id,events,null);
    checks:=checks||pg_temp.check_true(result->>'accepted_events'='1','offline session start recorded');
    checks:=checks||pg_temp.check_true((select last_seen_at is null from public.sessions where id=session_id),'offline replay does not mark a session online');
    result:=public.nexus_ingest(credential_id,repeat('a',64),session_id,events,null);
    checks:=checks||pg_temp.check_true(result->>'accepted_events'='0','duplicate event delivery is idempotent');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential_id,repeat('a',64),session_id,jsonb_set(events,'{0,payload,operator_name}','"Tampered Test Name"')),'23505','event id cannot be reused with modified data');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential_id,repeat('f',64),session_id,events),'42501','invalid device credential denied');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential2,repeat('d',64),session_id,'[]'),'42501','another account on same device cannot mutate session');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential_id,repeat('a',64),session_id,jsonb_build_array(jsonb_build_object('id',gen_random_uuid(),'sequence',3,'type','closed','timestamp',stamp,'payload','{}'::jsonb))),'P0409','out-of-order event batch rejected atomically');
    perform public.nexus_ingest(credential_id,repeat('a',64),session_id,jsonb_build_array(jsonb_build_object('id',event2,'sequence',2,'type','operator_changed','timestamp',stamp+interval '1 second','payload',jsonb_build_object('operator_name','Test Operator B','identity_source','KPI Profile'))),null);
    checks:=checks||pg_temp.check_true((select operator_name_snapshot='Test Operator A' from public.sessions where id=session_id),'initial operator snapshot remains immutable');
    checks:=checks||pg_temp.check_true((select count(*) from public.session_identity_periods ip where ip.session_id=fixture.session_id)=2,'operator change adds history interval');
    perform public.nexus_ingest(credential_id,repeat('a',64),session_id,jsonb_build_array(jsonb_build_object('id',event3,'sequence',3,'type','module_changed','timestamp',stamp+interval '2 seconds','payload',jsonb_build_object('module','User KPI'))),jsonb_build_object('sequence',1,'sent_at',now(),'idle_seconds',350));
    checks:=checks||pg_temp.check_true((select active_module='User KPI' and last_seen_at is not null and idle_seconds=350 from public.sessions where id=session_id),'live heartbeat tracks module, receipt and idle state');
    checks:=checks||pg_temp.check_true((select count(*) from public.session_events ev where ev.session_id=fixture.session_id)=3,'ordinary heartbeat adds no history event');
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential_id,repeat('a',64),session_id,jsonb_build_array(
      jsonb_build_object('id',gen_random_uuid(),'sequence',4,'type','recording_gap','timestamp',stamp+interval '3 seconds','payload',jsonb_build_object('dropped_events',1)),
      jsonb_build_object('id',gen_random_uuid(),'sequence',6,'type','closed','timestamp',stamp+interval '4 seconds','payload','{}'::jsonb))),'P0409','partially invalid event batch rolls back');
    checks:=checks||pg_temp.check_true((select event_sequence=3 from public.sessions where id=session_id) and (select count(*) from public.session_events ev where ev.session_id=fixture.session_id)=3,'failed batch preserves prior projection and history');
    update nexus_private.device_credentials set request_count=60,request_window=now() where id=credential_id;
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential_id,repeat('a',64),session_id,'[]'),'P0429','per-credential request quota enforced');
    update nexus_private.device_credentials set request_count=0 where id=credential_id;
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,%L)',credential_id,repeat('a',64),session_id,'[]',jsonb_build_object('sequence',2,'sent_at',now()-interval '5 minutes','idle_seconds',0)),'22023','stale replayed heartbeat cannot establish liveness');
    perform public.nexus_ingest(credential2,repeat('d',64),gen_random_uuid(),jsonb_build_array(jsonb_build_object('id',gen_random_uuid(),'sequence',1,'type','started','timestamp',stamp,
      'payload',jsonb_build_object('device_name','TEST-PC','operator_name','TEST-PC','identity_source','Device Fallback','module','Dashboard','app_version','test-only'))),null);
    checks:=checks||pg_temp.check_true(exists(select 1 from public.sessions s where s.credential_id=credential2 and s.identity_source='Device Fallback' and s.operator_name_snapshot='TEST-PC'),'missing KPI profile records device fallback explicitly');

    -- Another machine with the same operator name remains distinct.
    result:=public.nexus_admin_action(owner_id,owner_session,'create_enrollment',jsonb_build_object('enrollment_id',enrollment3,'installation_uuid',device_uuid2,'device_name','TEST-PC','account_label','Test account C','code_hash',encode(sha256(convert_to(repeat('e',64),'UTF8')),'hex')));
    device_id2:=(result->>'device_id')::uuid;
    perform public.nexus_claim_enrollment(enrollment3,repeat('e',64),device_uuid2,credential3,repeat('f',64));
    events:=jsonb_build_array(jsonb_build_object('id',gen_random_uuid(),'sequence',1,'type','started','timestamp',stamp,'payload',jsonb_build_object('device_name','TEST-PC','operator_name','Test Operator A','identity_source','KPI Profile','module','Dashboard','app_version','test-only')));
    perform public.nexus_ingest(credential3,repeat('f',64),session2,events,jsonb_build_object('sequence',1,'sent_at',now(),'idle_seconds',0));
    checks:=checks||pg_temp.check_true(device_id<>device_id2,'identical hostname and operator do not merge devices');
    perform public.nexus_ingest(credential_id,repeat('a',64),session3,jsonb_set(events,'{0,id}',to_jsonb(gen_random_uuid())),null);
    checks:=checks||pg_temp.check_true((select count(*) from public.sessions ss where ss.device_id=fixture.device_id and ss.credential_id=fixture.credential_id)=2,'new launch creates a separate application session');

    -- RLS tested under actual database roles and synthetic JWT session claims.
    perform set_config('request.jwt.claims',jsonb_build_object('sub',owner_id,'session_id',owner_session,'aal','aal2')::text,true);
    set local role authenticated;
    snapshot:=public.nexus_current_snapshot();
    reset role;
    checks:=checks||pg_temp.check_true(exists(select 1 from jsonb_array_elements(snapshot->'sessions') s where s->>'id'=session_id::text and s->>'status'='idle' and s->>'operator_name'='Test Operator B'),'authorized MFA administrator sees current identity and idle status');
    perform set_config('request.jwt.claims',jsonb_build_object('sub',owner_id,'session_id',owner_session,'aal','aal1')::text,true);
    set local role authenticated;
    begin perform public.nexus_current_snapshot(); raise exception 'MFA was not enforced'; exception when insufficient_privilege then null; end;
    reset role;
    checks:=checks||pg_temp.check_true(true,'MFA required for dashboard records');
    perform set_config('request.jwt.claims',jsonb_build_object('sub',nonadmin_id,'session_id',nonadmin_session,'aal','aal2','user_metadata',jsonb_build_object('role','owner'))::text,true);
    set local role authenticated;
    begin perform public.nexus_current_snapshot(); raise exception 'Nonadministrator was allowed'; exception when insufficient_privilege then null; end;
    reset role;
    checks:=checks||pg_temp.check_true(true,'editable user metadata grants no monitoring access');
    perform set_config('request.jwt.claims',jsonb_build_object('sub',owner_id,'session_id',gen_random_uuid(),'aal','aal2')::text,true);
    set local role authenticated;
    begin perform public.nexus_current_snapshot(); raise exception 'Revoked Auth session was allowed'; exception when insufficient_privilege then null; end;
    reset role;
    checks:=checks||pg_temp.check_true(true,'missing or revoked Auth session denied');

    update public.sessions set last_seen_at=now()-interval '4 minutes' where id=session_id;
    perform nexus_private.maintenance(); perform nexus_private.maintenance();
    checks:=checks||pg_temp.check_true((select count(*) from public.session_events ev where ev.session_id=fixture.session_id and event_type='disconnected')=1,'crash or outage records one disconnection transition');
    perform public.nexus_ingest(credential_id,repeat('a',64),session_id,'[]',jsonb_build_object('sequence',2,'sent_at',now(),'idle_seconds',0));
    checks:=checks||pg_temp.check_true((select count(*) from public.session_events ev where ev.session_id=fixture.session_id and event_type='reconnected')=1,'reconnection reuses session and emits one transition');
    perform public.nexus_ingest(credential_id,repeat('a',64),session_id,jsonb_build_array(jsonb_build_object('id',event4,'sequence',4,'type','closed','timestamp',stamp+interval '3 seconds','payload','{}'::jsonb)),null);
    checks:=checks||pg_temp.check_true((select ended_at is not null and end_reason='closed' and not end_is_estimated from public.sessions where id=session_id),'normal close ends session explicitly');
    perform public.nexus_ingest(credential_id,repeat('a',64),session_id,'[]',jsonb_build_object('sequence',3,'sent_at',now(),'idle_seconds',0));
    checks:=checks||pg_temp.check_true((select ended_at is not null and live_sequence=2 from public.sessions where id=session_id),'late heartbeat cannot resurrect closed session');
    perform public.nexus_admin_action(owner_id,owner_session,'revoke_credential',jsonb_build_object('credential_id',credential_id));
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential_id,repeat('a',64),session3,'[]'),'42501','revoked credential denied');
    perform public.nexus_admin_action(owner_id,owner_session,'revoke_device',jsonb_build_object('device_id',device_id2));
    checks:=checks||pg_temp.expect_error(format('select public.nexus_ingest(%L,%L,%L,%L,null)',credential3,repeat('f',64),session2,'[]'),'42501','device revocation denies all its credentials');
    raise exception 'Deliberate test fixture rollback' using errcode='ZX001';
  exception when sqlstate 'ZX001' then null;
  end;
  return jsonb_build_object('passed',jsonb_array_length(checks),'checks',checks,'fixtures_rolled_back',true);
end $$;
select pg_temp.verify_monitoring() as verification;
