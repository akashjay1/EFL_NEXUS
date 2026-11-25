-- Monitoring backend. All device secrets stay behind service-only RPCs.
create schema nexus_private;
revoke all on schema nexus_private from public, anon, authenticated;
grant usage on schema nexus_private to service_role;

create table public.monitoring_settings (
  id boolean primary key default true check (id),
  heartbeat_seconds integer not null default 60 check (heartbeat_seconds between 30 and 600),
  disconnected_seconds integer not null default 180,
  idle_seconds integer not null default 300 check (idle_seconds between 60 and 3600),
  dashboard_refresh_seconds integer not null default 15 check (dashboard_refresh_seconds between 10 and 300),
  history_days integer not null default 90 check (history_days between 7 and 365),
  check (disconnected_seconds >= heartbeat_seconds * 3)
);
insert into public.monitoring_settings default values;

create table public.admin_profiles (
  user_id uuid primary key references auth.users(id) on delete restrict,
  role text not null check (role in ('owner','admin')),
  slot smallint check (slot between 1 and 5),
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  check ((revoked_at is null) = (slot is not null))
);
create unique index admin_active_slot on public.admin_profiles(slot) where revoked_at is null;

create table public.devices (
  id uuid primary key default gen_random_uuid(),
  installation_uuid uuid not null unique,
  device_name text not null check (length(btrim(device_name)) between 1 and 120 and device_name !~ '[[:cntrl:]]'),
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);
create table nexus_private.device_credentials (
  id uuid primary key,
  device_id uuid not null references public.devices(id),
  credential_hash bytea not null check (octet_length(credential_hash)=32),
  account_label text not null check (length(btrim(account_label)) between 1 and 120 and account_label !~ '[[:cntrl:]]'),
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  request_window timestamptz not null default now(),
  request_count integer not null default 0
);
create index credential_device on nexus_private.device_credentials(device_id);
create table nexus_private.device_enrollments (
  id uuid primary key,
  device_id uuid not null references public.devices(id),
  code_hash bytea not null check (octet_length(code_hash)=32),
  account_label text not null check (length(btrim(account_label)) between 1 and 120 and account_label !~ '[[:cntrl:]]'),
  created_by uuid not null references public.admin_profiles(user_id),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '10 minutes',
  consumed_at timestamptz,
  credential_id uuid references nexus_private.device_credentials(id),
  revoked_at timestamptz,
  check ((consumed_at is null) = (credential_id is null))
);
create index enrollment_device on nexus_private.device_enrollments(device_id);
create index enrollment_creator on nexus_private.device_enrollments(created_by);

create table public.sessions (
  id uuid primary key,
  device_id uuid not null references public.devices(id),
  credential_id uuid not null references nexus_private.device_credentials(id),
  device_name_snapshot text not null,
  operator_name_snapshot text not null,
  identity_source text not null check (identity_source in ('KPI Profile','Device Fallback')),
  app_version text not null,
  active_module text not null,
  started_at timestamptz not null,
  received_at timestamptz not null default now(),
  last_event_at timestamptz not null,
  last_seen_at timestamptz,
  idle_seconds integer not null default 0 check (idle_seconds between 0 and 604800),
  ended_at timestamptz,
  end_reason text check (end_reason in ('closed','unclean','revoked')),
  end_is_estimated boolean not null default false,
  event_sequence bigint not null default 0 check (event_sequence between 0 and 9007199254740991),
  live_sequence bigint not null default 0 check (live_sequence between 0 and 9007199254740991),
  disconnected_at timestamptz,
  check (ended_at is null or ended_at >= started_at),
  check ((ended_at is null) = (end_reason is null))
);
create index sessions_device_started on public.sessions(device_id, started_at desc, id desc);
create index sessions_recent on public.sessions(started_at desc, id desc);
create index sessions_live on public.sessions(last_seen_at) where ended_at is null;
create index sessions_credential on public.sessions(credential_id);
create table public.session_identity_periods (
  session_id uuid not null references public.sessions(id) on delete cascade,
  start_sequence bigint not null,
  operator_name_snapshot text not null,
  identity_source text not null check (identity_source in ('KPI Profile','Device Fallback')),
  started_at timestamptz not null,
  primary key(session_id,start_sequence)
);
create table public.session_events (
  id uuid primary key,
  session_id uuid not null references public.sessions(id) on delete cascade,
  sequence bigint not null,
  event_type text not null check (event_type in ('started','operator_changed','module_changed','closed','unclean','recording_gap','disconnected','reconnected')),
  event_timestamp timestamptz not null,
  received_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata)='object' and octet_length(metadata::text)<=2048),
  unique(session_id,sequence)
);
create index events_recent on public.session_events(received_at desc,id desc);

create table nexus_private.admin_invitations (
  id uuid primary key default gen_random_uuid(),
  email text not null check (email=lower(btrim(email)) and length(email) between 3 and 254 and position('@' in email)>1),
  role text not null check (role in ('owner','admin')),
  slot smallint check (slot between 1 and 5),
  created_at timestamptz not null default now(),
  created_by uuid references public.admin_profiles(user_id),
  claimed_user_id uuid references auth.users(id),
  revoked_at timestamptz
);
create unique index invitation_pending_email on nexus_private.admin_invitations(email) where revoked_at is null and claimed_user_id is null;
create unique index invitation_pending_slot on nexus_private.admin_invitations(slot) where revoked_at is null and claimed_user_id is null;
create index invitation_creator on nexus_private.admin_invitations(created_by);
create index invitation_claimant on nexus_private.admin_invitations(claimed_user_id);
create table nexus_private.admin_audit_events (
  id bigint generated always as identity primary key,
  actor_id uuid,
  action text not null,
  target_id uuid,
  created_at timestamptz not null default now()
);

-- The only definer helpers live in an unexposed schema, with fixed search paths.
-- Session checks make revoked Auth sessions fail immediately, including stale JWTs.
create function nexus_private.has_live_auth_session() returns boolean
language sql stable security definer set search_path='' as $$
  select auth.uid() is not null and exists (
    select 1 from auth.sessions s where s.user_id=auth.uid()
    and s.id::text=auth.jwt()->>'session_id' and (s.not_after is null or s.not_after>now())
  )
$$;
revoke all on function nexus_private.has_live_auth_session() from public,anon;
grant usage on schema nexus_private to authenticated;
grant execute on function nexus_private.has_live_auth_session() to authenticated;

create function public.nexus_is_admin() returns boolean
language sql stable security invoker set search_path='' as $$
  select exists(select 1 from public.admin_profiles where user_id=auth.uid() and revoked_at is null)
    and coalesce(auth.jwt()->>'aal'='aal2',false)
$$;
revoke all on function public.nexus_is_admin() from public,anon;
grant execute on function public.nexus_is_admin() to authenticated;

alter table public.admin_profiles enable row level security;
create policy admin_own_profile on public.admin_profiles for select to authenticated
  using (user_id=(select auth.uid()) and (select nexus_private.has_live_auth_session()));
do $$ declare t text; begin
  foreach t in array array['monitoring_settings','devices','sessions','session_identity_periods','session_events'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
    execute format('create policy admin_read on public.%I for select to authenticated using ((select public.nexus_is_admin()))',t);
  end loop;
  foreach t in array array['device_credentials','device_enrollments','admin_invitations','admin_audit_events'] loop
    execute format('alter table nexus_private.%I enable row level security',t);
    execute format('revoke all on nexus_private.%I from public,anon,authenticated',t);
  end loop;
end $$;
revoke all on public.admin_profiles from public,anon,authenticated;
grant select on public.admin_profiles to authenticated;
grant all on all tables in schema nexus_private to service_role;
grant usage,select on all sequences in schema nexus_private to service_role;
grant all on public.admin_profiles,public.monitoring_settings,public.devices,public.sessions,public.session_identity_periods,public.session_events to service_role;

create function nexus_private.require_admin(p_actor uuid,p_session uuid,p_owner boolean default false) returns void
language plpgsql security invoker set search_path='' as $$
begin
  if not exists(select 1 from public.admin_profiles a join auth.sessions s on s.user_id=a.user_id
      where a.user_id=p_actor and a.revoked_at is null and s.id=p_session
      and s.aal='aal2' and (s.not_after is null or s.not_after>now()) and (not p_owner or a.role='owner')) then
    raise exception 'Administrator access required' using errcode='42501';
  end if;
end $$;
-- Server-only role needs session validity for management; no client grants.
grant select on auth.sessions to service_role;

create function public.nexus_bootstrap_owner(p_email text) returns void
language plpgsql security invoker set search_path='' as $$
begin
  perform pg_advisory_xact_lock(71024001);
  if exists(select 1 from public.admin_profiles) or exists(select 1 from nexus_private.admin_invitations) then
    raise exception 'Owner bootstrap already reserved' using errcode='23505';
  end if;
  insert into nexus_private.admin_invitations(email,role,slot) values(lower(btrim(p_email)),'owner',1);
  insert into nexus_private.admin_audit_events(action) values('owner_reserved');
end $$;

-- Closed registration: only an explicitly reserved address may become an Auth user.
-- Verification or an authenticated project-owner action is required before granting access.
create function nexus_private.gate_auth_user() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if not exists(select 1 from nexus_private.admin_invitations where email=lower(new.email)
      and revoked_at is null and claimed_user_id is null) then
    raise exception 'Account has not been invited' using errcode='42501';
  end if;
  return new;
end $$;
create trigger nexus_invitation_gate before insert on auth.users for each row execute function nexus_private.gate_auth_user();
create function nexus_private.activate_invited_admin() returns trigger
language plpgsql security definer set search_path='' as $$
declare v nexus_private.admin_invitations%rowtype;
begin
  if new.email_confirmed_at is null then return new; end if;
  perform pg_advisory_xact_lock(71024001);
  select * into v from nexus_private.admin_invitations where email=lower(new.email)
    and revoked_at is null and claimed_user_id is null for update;
  if found then
    insert into public.admin_profiles(user_id,role,slot) values(new.id,v.role,v.slot);
    update nexus_private.admin_invitations set claimed_user_id=new.id where id=v.id;
    insert into nexus_private.admin_audit_events(action,target_id) values('admin_activated',new.id);
  end if;
  return new;
end $$;
create trigger nexus_activate_admin after insert or update of email_confirmed_at on auth.users
for each row execute function nexus_private.activate_invited_admin();

create function public.nexus_admin_action(p_actor uuid,p_auth_session uuid,p_action text,p_args jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare v_slot smallint; v_target uuid; v_device uuid; v_role text; v_email text;
begin
  perform pg_advisory_xact_lock(71024001);
  perform nexus_private.require_admin(p_actor,p_auth_session,p_action in ('reserve_admin','revoke_admin','list_admins'));
  if p_action='reserve_admin' then
    v_role:=p_args->>'role'; v_email:=lower(btrim(p_args->>'email'));
    if v_role not in ('admin','owner') or v_role is null or v_email is null then raise exception 'Invalid invitation' using errcode='22023'; end if;
    if exists(select 1 from auth.users where lower(email)=v_email) then
      raise exception 'Use an address without an existing account' using errcode='23505';
    end if;
    select n::smallint into v_slot from generate_series(1,5) n where n not in (
      select slot from public.admin_profiles where revoked_at is null
      union all select slot from nexus_private.admin_invitations where revoked_at is null and claimed_user_id is null
    ) order by n limit 1;
    if v_slot is null then raise exception 'Five administrator slots are already reserved' using errcode='23514'; end if;
    insert into nexus_private.admin_invitations(email,role,slot,created_by) values(v_email,v_role,v_slot,p_actor) returning id into v_target;
  elsif p_action='revoke_admin' then
    v_target:=(p_args->>'user_id')::uuid;
    if not exists(select 1 from public.admin_profiles where user_id=v_target and revoked_at is null) then raise exception 'Administrator not found' using errcode='22023'; end if;
    if (select role from public.admin_profiles where user_id=v_target)='owner' and
      (select count(*) from public.admin_profiles where role='owner' and revoked_at is null)<=1 then
      raise exception 'The final owner cannot be removed' using errcode='23514';
    end if;
    update public.admin_profiles set revoked_at=now(),slot=null where user_id=v_target;
    update nexus_private.admin_invitations set revoked_at=now(),slot=null where claimed_user_id=v_target;
  elsif p_action='cancel_invitation' then
    perform nexus_private.require_admin(p_actor,p_auth_session,true);
    v_target:=(p_args->>'invitation_id')::uuid;
    update nexus_private.admin_invitations set revoked_at=now(),slot=null where id=v_target and claimed_user_id is null;
    if not found then raise exception 'Pending invitation not found' using errcode='22023'; end if;
  elsif p_action='list_admins' then
    return jsonb_build_object('admins',(select coalesce(jsonb_agg(jsonb_build_object('user_id',a.user_id,'email',u.email,'role',a.role,'revoked_at',a.revoked_at)),'[]') from public.admin_profiles a join auth.users u on u.id=a.user_id),
      'pending',(select coalesce(jsonb_agg(jsonb_build_object('id',id,'email',email,'role',role)),'[]') from nexus_private.admin_invitations where revoked_at is null and claimed_user_id is null));
  elsif p_action='create_enrollment' then
    v_target:=(p_args->>'enrollment_id')::uuid;
    insert into public.devices(installation_uuid,device_name) values((p_args->>'installation_uuid')::uuid,p_args->>'device_name')
      on conflict(installation_uuid) do update set device_name=excluded.device_name returning id into v_device;
    if exists(select 1 from public.devices where id=v_device and revoked_at is not null) then raise exception 'Device revoked' using errcode='42501'; end if;
    -- A fresh code invalidates outstanding, unconsumed codes for the same account label.
    update nexus_private.device_enrollments set revoked_at=now() where device_id=v_device
      and account_label=p_args->>'account_label' and consumed_at is null and revoked_at is null;
    insert into nexus_private.device_enrollments(id,device_id,code_hash,account_label,created_by)
      values(v_target,v_device,decode(p_args->>'code_hash','hex'),p_args->>'account_label',p_actor);
  elsif p_action='revoke_device' then
    v_target:=(p_args->>'device_id')::uuid;
    perform 1 from public.devices where id=v_target for update;
    if not found then raise exception 'Device not found' using errcode='22023'; end if;
    update public.devices set revoked_at=coalesce(revoked_at,now()) where id=v_target;
    update nexus_private.device_credentials set revoked_at=coalesce(revoked_at,now()) where device_id=v_target;
    update nexus_private.device_enrollments set revoked_at=coalesce(revoked_at,now()) where device_id=v_target;
    update public.sessions set ended_at=greatest(started_at,now()),end_reason='revoked',end_is_estimated=true where device_id=v_target and ended_at is null;
  elsif p_action='revoke_credential' then
    v_target:=(p_args->>'credential_id')::uuid;
    select device_id into v_device from nexus_private.device_credentials where id=v_target;
    perform 1 from public.devices where id=v_device for update;
    update nexus_private.device_credentials set revoked_at=coalesce(revoked_at,now()) where id=v_target;
    if not found then raise exception 'Credential not found' using errcode='22023'; end if;
    update public.sessions set ended_at=greatest(started_at,now()),end_reason='revoked',end_is_estimated=true where credential_id=v_target and ended_at is null;
  elsif p_action='device_credentials' then
    return (select coalesce(jsonb_agg(jsonb_build_object('id',id,'account_label',account_label,'created_at',created_at,'revoked_at',revoked_at)),'[]') from nexus_private.device_credentials where device_id=(p_args->>'device_id')::uuid);
  else raise exception 'Unknown administrator action' using errcode='22023';
  end if;
  insert into nexus_private.admin_audit_events(actor_id,action,target_id) values(p_actor,p_action,v_target);
  return jsonb_build_object('id',v_target,'device_id',v_device);
end $$;
grant select on auth.users to service_role;

create function public.nexus_claim_enrollment(p_enrollment_id uuid,p_code text,p_installation_uuid uuid,p_credential_id uuid,p_secret text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare v nexus_private.device_enrollments%rowtype; v_device public.devices%rowtype;
begin
  if p_code is null or p_secret is null or p_installation_uuid is null or p_code !~ '^[0-9a-f]{64}$' or p_secret !~ '^[0-9a-f]{64}$' or p_credential_id is null then
    raise exception 'Enrollment rejected' using errcode='42501';
  end if;
  select d.* into v_device from public.devices d join nexus_private.device_enrollments e on e.device_id=d.id where e.id=p_enrollment_id for update of d;
  select * into v from nexus_private.device_enrollments where id=p_enrollment_id for update;
  if v.id is null or v.revoked_at is not null or v_device.revoked_at is not null or v_device.installation_uuid<>p_installation_uuid
    or v.code_hash<>sha256(convert_to(p_code,'UTF8')) then raise exception 'Enrollment rejected' using errcode='42501'; end if;
  if v.consumed_at is not null then
    if v.credential_id=p_credential_id and exists(select 1 from nexus_private.device_credentials where id=p_credential_id and device_id=v.device_id
      and revoked_at is null and credential_hash=sha256(convert_to(p_secret,'UTF8'))) then
      return jsonb_build_object('device_id',v.device_id,'credential_id',p_credential_id,'replayed',true);
    end if;
    raise exception 'Enrollment rejected' using errcode='42501';
  end if;
  if v.expires_at<now() then raise exception 'Enrollment rejected' using errcode='42501'; end if;
  insert into nexus_private.device_credentials(id,device_id,credential_hash,account_label)
    values(p_credential_id,v.device_id,sha256(convert_to(p_secret,'UTF8')),v.account_label);
  update nexus_private.device_enrollments set consumed_at=now(),credential_id=p_credential_id where id=v.id;
  return jsonb_build_object('device_id',v.device_id,'credential_id',p_credential_id,'replayed',false);
end $$;

create function nexus_private.checked_text(p_value text,p_max integer) returns text
language plpgsql immutable security invoker set search_path='' as $$
begin
  if p_value is null or length(btrim(p_value)) not between 1 and p_max or p_value ~ '[[:cntrl:]]' then
    raise exception 'Invalid telemetry text' using errcode='22023'; end if;
  return btrim(p_value);
end $$;
create function nexus_private.check_identity(p jsonb) returns void
language plpgsql immutable security invoker set search_path='' as $$
begin
  perform nexus_private.checked_text(p->>'operator_name',120);
  if p->>'identity_source' is null or p->>'identity_source' not in ('KPI Profile','Device Fallback') then
    raise exception 'Invalid identity source' using errcode='22023'; end if;
end $$;

create function public.nexus_ingest(p_credential_id uuid,p_secret text,p_session_id uuid,p_events jsonb,p_live jsonb default null) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare c nexus_private.device_credentials%rowtype; s public.sessions%rowtype; d public.devices%rowtype;
  e jsonb; old_e public.session_events%rowtype; payload jsonb; ev_id uuid; seq bigint; kind text; stamp timestamptz;
  live_seq bigint; sent timestamptz; accepted integer:=0; live_changed boolean:=false; conf public.monitoring_settings%rowtype;
begin
  if p_secret is null or p_secret !~ '^[0-9a-f]{64}$' or p_session_id is null then raise exception 'Device credential rejected' using errcode='42501'; end if;
  select * into c from nexus_private.device_credentials where id=p_credential_id;
  select * into d from public.devices where id=c.device_id for update;
  select * into c from nexus_private.device_credentials where id=p_credential_id for update;
  if c.id is null or c.revoked_at is not null or d.revoked_at is not null or c.credential_hash<>sha256(convert_to(p_secret,'UTF8')) then
    raise exception 'Device credential rejected' using errcode='42501'; end if;
  if jsonb_typeof(p_events) is distinct from 'array' or jsonb_array_length(p_events)>50 then raise exception 'Invalid event batch' using errcode='22023'; end if;
  if c.request_window<now()-interval '1 minute' then c.request_window:=now(); c.request_count:=0; end if;
  if c.request_count>=60 then raise exception 'Device request limit reached' using errcode='P0429'; end if;
  update nexus_private.device_credentials set request_window=c.request_window,request_count=c.request_count+1 where id=c.id;
  select * into conf from public.monitoring_settings;
  select * into s from public.sessions where id=p_session_id for update;
  if s.id is not null and (s.device_id<>d.id or s.credential_id<>c.id) then raise exception 'Session ownership rejected' using errcode='42501'; end if;
  for e in select value from jsonb_array_elements(p_events) loop
    if jsonb_typeof(e) is distinct from 'object' or (e - array['id','sequence','type','timestamp','payload'])<>'{}'::jsonb then raise exception 'Invalid event envelope' using errcode='22023'; end if;
    ev_id:=(e->>'id')::uuid; seq:=(e->>'sequence')::bigint; kind:=e->>'type'; stamp:=(e->>'timestamp')::timestamptz; payload:=e->'payload';
    if ev_id is null or seq is null or seq not between 1 and 9007199254740991 or stamp is null or not isfinite(stamp)
      or stamp>now()+interval '5 minutes' or stamp<now()-interval '7 days' or jsonb_typeof(payload) is distinct from 'object' or octet_length(payload::text)>2048
      or kind is null or kind not in ('started','operator_changed','module_changed','closed','unclean','recording_gap') then
      raise exception 'Invalid telemetry event' using errcode='22023'; end if;
    select * into old_e from public.session_events where id=ev_id;
    if found then
      if old_e.session_id<>p_session_id or old_e.sequence<>seq or old_e.event_type<>kind or old_e.event_timestamp<>stamp or old_e.metadata<>payload then
        raise exception 'Event id conflicts with stored event' using errcode='23505'; end if;
      continue;
    end if;
    if s.id is null then
      if seq<>1 or kind<>'started' then raise exception 'Session start required' using errcode='P0409'; end if;
      perform nexus_private.check_identity(payload);
      if (payload-array['operator_name','identity_source','device_name','module','app_version'])<>'{}'::jsonb then raise exception 'Unexpected start fields' using errcode='22023'; end if;
      if payload->>'identity_source'='Device Fallback' and payload->>'operator_name'<>payload->>'device_name' then raise exception 'Invalid fallback identity' using errcode='22023'; end if;
      insert into public.sessions(id,device_id,credential_id,device_name_snapshot,operator_name_snapshot,identity_source,app_version,active_module,started_at,last_event_at)
      values(p_session_id,d.id,c.id,nexus_private.checked_text(payload->>'device_name',120),payload->>'operator_name',payload->>'identity_source',
        nexus_private.checked_text(payload->>'app_version',40),nexus_private.checked_text(payload->>'module',80),stamp,stamp) returning * into s;
    elsif s.ended_at is not null then raise exception 'Session is terminal' using errcode='P0409';
    elsif kind='started' then raise exception 'Session already started' using errcode='P0409';
    end if;
    if seq<>s.event_sequence+1 or stamp<s.last_event_at then raise exception 'Events must be ordered and contiguous' using errcode='P0409'; end if;
    if kind in ('started','operator_changed') then
      perform nexus_private.check_identity(payload);
      if kind='operator_changed' and (payload-array['operator_name','identity_source'])<>'{}'::jsonb then raise exception 'Unexpected identity fields' using errcode='22023'; end if;
      if payload->>'identity_source'='Device Fallback' and payload->>'operator_name'<>s.device_name_snapshot then raise exception 'Invalid fallback identity' using errcode='22023'; end if;
      insert into public.session_identity_periods(session_id,start_sequence,operator_name_snapshot,identity_source,started_at)
        values(s.id,seq,payload->>'operator_name',payload->>'identity_source',stamp);
    elsif kind='module_changed' then
      if (payload-'module')<>'{}'::jsonb then raise exception 'Unexpected module fields' using errcode='22023'; end if;
      s.active_module:=nexus_private.checked_text(payload->>'module',80);
    elsif kind in ('closed','unclean') then
      if payload<>'{}'::jsonb then raise exception 'Unexpected shutdown fields' using errcode='22023'; end if;
      s.ended_at:=stamp; s.end_reason:=kind; s.end_is_estimated:=kind='unclean';
    elsif kind='recording_gap' then
      if (payload-'dropped_events')<>'{}'::jsonb or (payload->>'dropped_events')::integer<1 or payload->>'dropped_events' is null then raise exception 'Invalid gap' using errcode='22023'; end if;
    end if;
    insert into public.session_events(id,session_id,sequence,event_type,event_timestamp,metadata) values(ev_id,s.id,seq,kind,stamp,payload);
    s.event_sequence:=seq; s.last_event_at:=stamp; accepted:=accepted+1;
  end loop;
  if s.id is null then raise exception 'Session start required' using errcode='P0409'; end if;
  if p_live is not null and p_live<>'null'::jsonb then
    if jsonb_typeof(p_live) is distinct from 'object' or (p_live-array['sequence','sent_at','idle_seconds'])<>'{}'::jsonb then raise exception 'Invalid live update' using errcode='22023'; end if;
    live_seq:=(p_live->>'sequence')::bigint; sent:=(p_live->>'sent_at')::timestamptz;
    if live_seq is null or live_seq not between 1 and 9007199254740991 or sent is null or not isfinite(sent)
      or sent<now()-interval '2 minutes' or sent>now()+interval '5 minutes'
      or p_live->>'idle_seconds' is null or (p_live->>'idle_seconds')::integer not between 0 and 604800 then raise exception 'Invalid live update' using errcode='22023'; end if;
    if s.ended_at is null and live_seq>s.live_sequence and (s.last_seen_at is null or s.last_seen_at<=now()-make_interval(secs=>conf.heartbeat_seconds/2)) then
      if s.disconnected_at is not null or s.last_seen_at<now()-make_interval(secs=>conf.disconnected_seconds) then
        insert into public.session_events(id,session_id,sequence,event_type,event_timestamp) values(gen_random_uuid(),s.id,-(live_seq*2),'reconnected',now());
      end if;
      s.last_seen_at:=now(); s.live_sequence:=live_seq; s.idle_seconds:=(p_live->>'idle_seconds')::integer; s.disconnected_at:=null; live_changed:=true;
    end if;
  end if;
  if accepted>0 or live_changed then
  update public.sessions set event_sequence=s.event_sequence,last_event_at=s.last_event_at,active_module=s.active_module,
    ended_at=s.ended_at,end_reason=s.end_reason,end_is_estimated=s.end_is_estimated,
    last_seen_at=s.last_seen_at,live_sequence=s.live_sequence,idle_seconds=s.idle_seconds,disconnected_at=s.disconnected_at where id=s.id;
  end if;
  return jsonb_build_object('accepted_events',accepted,'event_sequence',s.event_sequence,'live_sequence',s.live_sequence,'server_time',now());
end $$;

-- Dashboard reads retain RLS; no privileged aggregate view.
create function public.nexus_current_snapshot() returns jsonb
language plpgsql stable security invoker set search_path='' as $$
declare conf public.monitoring_settings%rowtype;
begin
  if not public.nexus_is_admin() then raise exception 'Administrator access required' using errcode='42501'; end if;
  select * into conf from public.monitoring_settings;
  return jsonb_build_object('server_time',now(),'settings',to_jsonb(conf),
    'devices',(select coalesce(jsonb_agg(to_jsonb(d)),'[]') from public.devices d),
    'sessions',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from (
      select s.id,s.device_id,s.device_name_snapshot,s.active_module,s.app_version,s.started_at,s.last_seen_at,s.idle_seconds,
        p.operator_name_snapshot as operator_name,p.identity_source,
        case when d.revoked_at is not null then 'revoked'
          when s.ended_at is not null then 'offline'
          when s.last_seen_at is null or s.last_seen_at<now()-make_interval(secs=>conf.disconnected_seconds) then 'disconnected'
          when s.idle_seconds>=conf.idle_seconds then 'idle' else 'online' end as status
      from public.sessions s join public.devices d on d.id=s.device_id
      left join lateral(select operator_name_snapshot,identity_source from public.session_identity_periods where session_id=s.id order by start_sequence desc limit 1) p on true
      where s.ended_at is null or s.id=(select s2.id from public.sessions s2 where s2.device_id=s.device_id order by s2.started_at desc,s2.id desc limit 1)
    ) x));
end $$;
revoke all on function public.nexus_current_snapshot() from public,anon;
grant execute on function public.nexus_current_snapshot() to authenticated;

-- Only important events emit invalidations. Payloads contain no operator records.
create function nexus_private.broadcast_change() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  perform realtime.send(jsonb_build_object('refresh',true),'refresh','nexus:monitoring',true);
  return null;
end $$;
create trigger nexus_event_refresh after insert on public.session_events for each statement execute function nexus_private.broadcast_change();
create trigger nexus_device_refresh after insert or update of revoked_at on public.devices for each statement execute function nexus_private.broadcast_change();
create policy nexus_realtime_read on realtime.messages for select to authenticated
  using (extension='broadcast' and (select realtime.topic())='nexus:monitoring' and (select public.nexus_is_admin()));

create function nexus_private.maintenance() returns void
language plpgsql security invoker set search_path='' as $$
declare s public.sessions%rowtype; conf public.monitoring_settings%rowtype;
begin
  select * into conf from public.monitoring_settings;
  for s in select * from public.sessions where ended_at is null and disconnected_at is null
    and last_seen_at<now()-make_interval(secs=>conf.disconnected_seconds) for update skip locked loop
    update public.sessions set disconnected_at=now() where id=s.id;
    -- Disconnection and reconnection share the negative namespace, separated by parity.
    insert into public.session_events(id,session_id,sequence,event_type,event_timestamp)
      values(gen_random_uuid(),s.id,-(s.live_sequence*2+1),'disconnected',now()) on conflict(session_id,sequence) do nothing;
  end loop;
  delete from public.sessions where ended_at is not null and ended_at<now()-make_interval(days=>conf.history_days);
  delete from nexus_private.device_enrollments where coalesce(consumed_at,expires_at)<now()-interval '7 days';
end $$;

-- Explicit EXECUTE grants. No default PUBLIC access to any privileged RPC/helper.
do $$ declare f record; begin
  for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='nexus_private' loop
    execute format('revoke all on function %s from public,anon,authenticated',f.signature);
    execute format('grant execute on function %s to service_role',f.signature);
  end loop;
  for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname in ('nexus_bootstrap_owner','nexus_admin_action','nexus_claim_enrollment','nexus_ingest') loop
    execute format('revoke all on function %s from public,anon,authenticated',f.signature);
    execute format('grant execute on function %s to service_role',f.signature);
  end loop;
end $$;
grant execute on function nexus_private.has_live_auth_session() to authenticated;
notify pgrst,'reload schema';
