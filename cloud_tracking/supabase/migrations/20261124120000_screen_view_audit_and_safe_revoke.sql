-- Screen-view authorization + audit, and explicit (opt-in) uninstall on revoke.
--
-- Screen viewing: an MFA admin must start a view with a reason. The row stores the
-- DTLS fingerprint of the admin browser's WebRTC offer. The desktop verifies the view
-- (device credential + view id + the fingerprint it actually received) before it
-- answers, so an offer injected on the signalling channel by anyone else is ignored.
--
-- Revoke: revoking a device no longer implies uninstalling it. Uninstall is a
-- separate, explicit admin request that the desktop reads via nexus_device_status.

create table nexus_private.screen_views (
  id uuid primary key default gen_random_uuid(),
  device_id uuid not null references public.devices(id) on delete cascade,
  admin_user uuid not null references public.admin_profiles(user_id),
  reason text not null check (length(btrim(reason)) between 3 and 200 and reason !~ '[[:cntrl:]]'),
  offer_fingerprint text not null check (offer_fingerprint ~ '^[0-9A-F]{2}(:[0-9A-F]{2}){31}$'),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '60 seconds',
  verified_at timestamptz,
  ended_at timestamptz
);
create index screen_views_device on nexus_private.screen_views(device_id, created_at desc);
create index screen_views_admin on nexus_private.screen_views(admin_user);

create table nexus_private.device_decommissions (
  device_id uuid primary key references public.devices(id) on delete cascade,
  requested_by uuid not null references public.admin_profiles(user_id),
  requested_at timestamptz not null default now()
);
create index device_decommissions_admin on nexus_private.device_decommissions(requested_by);

revoke all on nexus_private.screen_views, nexus_private.device_decommissions from public, anon, authenticated;
grant all on nexus_private.screen_views, nexus_private.device_decommissions to service_role;
alter table nexus_private.screen_views enable row level security;
alter table nexus_private.device_decommissions enable row level security;
create policy no_client_access on nexus_private.screen_views for all to anon, authenticated using (false) with check (false);
create policy no_client_access on nexus_private.device_decommissions for all to anon, authenticated using (false) with check (false);

-- Validates a device credential WITHOUT requiring the device to be active.
-- Returns the device id, or raises P0401.
create function nexus_private.device_for_credential(p_credential_id uuid, p_secret text) returns uuid
language plpgsql security definer set search_path='' as $$
declare v_device uuid;
begin
  if p_credential_id is null or p_secret is null or p_secret !~ '^[0-9a-f]{64}$' then
    raise exception 'Device credential rejected' using errcode='P0401';
  end if;
  select c.device_id into v_device from nexus_private.device_credentials c
    where c.id=p_credential_id and c.credential_hash=sha256(convert_to(p_secret,'UTF8'));
  if v_device is null then raise exception 'Device credential rejected' using errcode='P0401'; end if;
  return v_device;
end $$;

-- Admin: start a screen view (called by admin-control with the verified actor + auth session).
create function public.nexus_start_screen_view(p_actor uuid, p_auth_session uuid, p_device uuid, p_reason text, p_fingerprint text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_id uuid; v_recent integer;
begin
  perform nexus_private.require_admin(p_actor, p_auth_session);
  if not exists(select 1 from public.devices where id=p_device and revoked_at is null) then
    raise exception 'Device not available' using errcode='22023';
  end if;
  select count(*) into v_recent from nexus_private.screen_views where admin_user=p_actor and created_at>now()-interval '1 minute';
  if v_recent>=10 then raise exception 'Too many screen views' using errcode='P0429'; end if;
  insert into nexus_private.screen_views(device_id, admin_user, reason, offer_fingerprint)
    values (p_device, p_actor, btrim(p_reason), upper(p_fingerprint)) returning id into v_id;
  return jsonb_build_object('view_id', v_id);
end $$;

-- Admin: mark a view as ended (best effort, for the audit duration).
create function public.nexus_end_screen_view(p_actor uuid, p_auth_session uuid, p_view uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
  perform nexus_private.require_admin(p_actor, p_auth_session);
  update nexus_private.screen_views set ended_at=coalesce(ended_at, now()) where id=p_view and admin_user=p_actor;
  return jsonb_build_object('ok', true);
end $$;

-- Admin: audit log of screen views (newest first).
create function public.nexus_screen_view_log(p_actor uuid, p_auth_session uuid, p_limit integer default 100)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
  perform nexus_private.require_admin(p_actor, p_auth_session);
  return (select coalesce(jsonb_agg(row_to_json(x) order by x.created_at desc), '[]'::jsonb) from (
    select v.id, v.device_id, d.device_name, u.email as admin_email, v.reason, v.created_at, v.verified_at, v.ended_at
    from nexus_private.screen_views v
    join public.devices d on d.id=v.device_id
    join auth.users u on u.id=v.admin_user
    order by v.created_at desc
    limit least(greatest(coalesce(p_limit,100),1),500)) x);
end $$;

-- Device: verify an incoming view request before answering it. Single use.
create function public.nexus_verify_screen_view(p_credential_id uuid, p_secret text, p_view uuid, p_fingerprint text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_device uuid; v nexus_private.screen_views%rowtype; v_email text;
begin
  v_device := nexus_private.device_for_credential(p_credential_id, p_secret);
  if exists(select 1 from public.devices where id=v_device and revoked_at is not null)
     or exists(select 1 from nexus_private.device_credentials where id=p_credential_id and revoked_at is not null) then
    raise exception 'Device revoked' using errcode='42501';
  end if;
  select * into v from nexus_private.screen_views where id=p_view for update;
  if v.id is null or v.device_id<>v_device or v.verified_at is not null or v.expires_at<now()
     or v.offer_fingerprint<>upper(coalesce(p_fingerprint,'')) then
    return jsonb_build_object('ok', false);
  end if;
  update nexus_private.screen_views set verified_at=now() where id=v.id;
  select email into v_email from auth.users where id=v.admin_user;
  return jsonb_build_object('ok', true, 'admin', coalesce(v_email,'Administrator'), 'reason', v.reason);
end $$;

-- Admin: request (or cancel) uninstall of a device. Revoke stays a separate action.
create function public.nexus_set_device_uninstall(p_actor uuid, p_auth_session uuid, p_device uuid, p_uninstall boolean)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
  perform nexus_private.require_admin(p_actor, p_auth_session);
  if not exists(select 1 from public.devices where id=p_device) then raise exception 'Device not found' using errcode='22023'; end if;
  if p_uninstall then
    insert into nexus_private.device_decommissions(device_id, requested_by) values (p_device, p_actor)
      on conflict (device_id) do nothing;
  else
    delete from nexus_private.device_decommissions where device_id=p_device;
  end if;
  return jsonb_build_object('ok', true);
end $$;

-- Device: after a 403 the desktop asks what to do. Only an explicit uninstall request
-- makes it remove itself; anything else just stops monitoring.
create function public.nexus_device_status(p_credential_id uuid, p_secret text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_device uuid; v_revoked boolean;
begin
  v_device := nexus_private.device_for_credential(p_credential_id, p_secret);
  select (d.revoked_at is not null) or (c.revoked_at is not null) into v_revoked
    from public.devices d join nexus_private.device_credentials c on c.device_id=d.id
    where d.id=v_device and c.id=p_credential_id;
  return jsonb_build_object(
    'revoked', coalesce(v_revoked,true),
    'uninstall', exists(select 1 from nexus_private.device_decommissions where device_id=v_device));
end $$;

do $$ declare f text; begin
  foreach f in array array[
    'nexus_private.device_for_credential(uuid,text)',
    'public.nexus_start_screen_view(uuid,uuid,uuid,text,text)',
    'public.nexus_end_screen_view(uuid,uuid,uuid)',
    'public.nexus_screen_view_log(uuid,uuid,integer)',
    'public.nexus_verify_screen_view(uuid,text,uuid,text)',
    'public.nexus_set_device_uninstall(uuid,uuid,uuid,boolean)',
    'public.nexus_device_status(uuid,text)'] loop
    execute format('revoke all on function %s from public, anon, authenticated', f);
    execute format('grant execute on function %s to service_role', f);
  end loop;
end $$;

-- Audit rows are kept indefinitely. Extend nexus_private.maintenance if a retention limit is required.
