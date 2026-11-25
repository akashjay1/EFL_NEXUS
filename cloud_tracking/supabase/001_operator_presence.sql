-- SUPERSEDED DRAFT: do not apply. Use the reviewed migrations/ backend instead.
-- The earlier RPC-only prototype does not preserve identity history.
-- Idempotent initial migration. No credentials or seeded operators are included.
begin;

create schema if not exists nexus_tracking;
revoke all on schema nexus_tracking from public, anon, authenticated;

create table if not exists nexus_tracking.admins (
    user_id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);
create table if not exists nexus_tracking.devices (
    id uuid primary key default gen_random_uuid(),
    label text not null check (length(label) between 1 and 120),
    token_hash bytea not null,
    created_at timestamptz not null default now(),
    revoked_at timestamptz
);
create table if not exists nexus_tracking.sessions (
    id uuid primary key,
    device_id uuid not null references nexus_tracking.devices(id),
    operator_name text check (length(operator_name) between 1 and 120),
    device_name text not null check (length(device_name) between 1 and 120),
    current_tool text not null check (length(current_tool) between 1 and 80),
    app_version text not null check (length(app_version) between 1 and 40),
    started_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    ended_at timestamptz,
    end_reason text check (end_reason in ('closed', 'revoked')),
    sequence bigint not null check (sequence > 0)
);
create index if not exists nexus_sessions_seen on nexus_tracking.sessions(last_seen_at desc);
create index if not exists nexus_sessions_device on nexus_tracking.sessions(device_id);
alter table nexus_tracking.admins enable row level security;
alter table nexus_tracking.devices enable row level security;
alter table nexus_tracking.sessions enable row level security;
-- Access is exclusively through the narrowly scoped functions below.
revoke all on all tables in schema nexus_tracking from public, anon, authenticated;

create or replace function nexus_tracking.require_admin()
returns void language plpgsql stable set search_path = '' as $$
begin
    if not exists (select 1 from nexus_tracking.admins where user_id = auth.uid()) then
        raise exception 'Administrator access required' using errcode = '42501';
    end if;
end;
$$;
revoke all on function nexus_tracking.require_admin() from public, anon, authenticated;

create or replace function public.nexus_register_device(p_label text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_id uuid;
    -- Two independent UUIDs provide 244 random bits. Only a SHA-256 hash is stored.
    v_token text := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
begin
    perform nexus_tracking.require_admin();
    if p_label is null or length(btrim(p_label)) not between 1 and 120
       or p_label ~ '[[:cntrl:]]' then
        raise exception 'Enter a device label of 1 to 120 characters' using errcode = '22023';
    end if;
    insert into nexus_tracking.devices(label, token_hash)
    values (btrim(p_label), sha256(convert_to(v_token, 'UTF8'))) returning id into v_id;
    return jsonb_build_object('device_id', v_id, 'device_token', v_token);
end;
$$;

create or replace function public.nexus_revoke_device(p_device_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
    perform nexus_tracking.require_admin();
    update nexus_tracking.devices set revoked_at = coalesce(revoked_at, now()) where id = p_device_id;
    if not found then
        raise exception 'Device not found' using errcode = '22023';
    end if;
    update nexus_tracking.sessions set ended_at = now(), end_reason = 'revoked'
    where device_id = p_device_id and ended_at is null;
end;
$$;

create or replace function public.nexus_heartbeat(
    p_device_id uuid, p_device_token text, p_session_id uuid, p_sequence bigint,
    p_operator_name text, p_device_name text, p_current_tool text, p_app_version text,
    p_closed boolean default false
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_device nexus_tracking.devices%rowtype;
    v_session nexus_tracking.sessions%rowtype;
    v_now timestamptz := now();
    v_name text := nullif(btrim(p_operator_name), '');
begin
    if p_device_token is null or p_device_token !~ '^[0-9a-f]{64}$' then
        raise exception 'Device enrollment rejected' using errcode = '42501';
    end if;
    -- Serialize writes with revocation and other launches on this enrollment.
    select * into v_device from nexus_tracking.devices where id = p_device_id for update;
    if not found or v_device.revoked_at is not null
       or v_device.token_hash <> sha256(convert_to(p_device_token, 'UTF8')) then
        raise exception 'Device enrollment rejected' using errcode = '42501';
    end if;
    if p_session_id is null or p_sequence is null or p_sequence not between 1 and 2147483647
       or p_device_name is null or length(btrim(p_device_name)) not between 1 and 120
       or p_current_tool is null or length(btrim(p_current_tool)) not between 1 and 80
       or p_app_version is null or length(btrim(p_app_version)) not between 1 and 40
       or length(v_name) > 120
       or (coalesce(v_name, '') || p_device_name || p_current_tool || p_app_version) ~ '[[:cntrl:]]'
       or p_closed is null then
        raise exception 'Invalid presence update' using errcode = '22023';
    end if;
    select * into v_session from nexus_tracking.sessions where id = p_session_id;
    if found then
        if v_session.device_id <> p_device_id then
            raise exception 'Device enrollment rejected' using errcode = '42501';
        end if;
        -- Delayed, duplicated, or post-close requests cannot resurrect a session.
        if v_session.ended_at is not null or p_sequence <= v_session.sequence then
            return jsonb_build_object('accepted', false, 'server_time', v_now);
        end if;
        -- Throttle ordinary updates; a close can always be reported immediately.
        if not p_closed and v_session.last_seen_at > v_now - interval '10 seconds' then
            return jsonb_build_object('accepted', false, 'server_time', v_now);
        end if;
        update nexus_tracking.sessions set operator_name = v_name,
            device_name = btrim(p_device_name), current_tool = btrim(p_current_tool),
            app_version = btrim(p_app_version), last_seen_at = v_now, sequence = p_sequence,
            ended_at = case when p_closed then v_now else null end,
            end_reason = case when p_closed then 'closed' else null end
        where id = p_session_id;
    else
        -- Starts/ends are retained for 30 days; heartbeats only update one row.
        delete from nexus_tracking.sessions where last_seen_at < v_now - interval '30 days';
        insert into nexus_tracking.sessions(id, device_id, operator_name, device_name, current_tool,
            app_version, started_at, last_seen_at, sequence, ended_at, end_reason)
        values (p_session_id, p_device_id, v_name, btrim(p_device_name), btrim(p_current_tool),
            btrim(p_app_version), v_now, v_now, p_sequence,
            case when p_closed then v_now else null end, case when p_closed then 'closed' else null end);
    end if;
    return jsonb_build_object('accepted', true, 'server_time', v_now);
end;
$$;

create or replace function public.nexus_admin_snapshot(p_include_history boolean default false)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_now timestamptz := now();
    v_sessions jsonb;
    v_devices jsonb;
begin
    perform nexus_tracking.require_admin();
    select coalesce(jsonb_agg(to_jsonb(s) order by s.last_seen_at desc), '[]'::jsonb)
    into v_sessions from (
        select s.id, s.device_id, s.operator_name, s.device_name, s.current_tool, s.app_version,
               s.started_at, s.last_seen_at, s.ended_at, s.end_reason,
               case when d.revoked_at is not null then 'revoked'
                    when s.ended_at is not null then 'closed'
                    when s.last_seen_at < v_now - interval '90 seconds' then 'connection_lost'
                    else 'online' end as status
        from nexus_tracking.sessions s join nexus_tracking.devices d on d.id = s.device_id
        where s.last_seen_at >= v_now - interval '30 days'
          and (p_include_history or (s.ended_at is null and s.last_seen_at >= v_now - interval '1 day'))
        order by (s.ended_at is null and s.last_seen_at >= v_now - interval '90 seconds') desc,
                 s.last_seen_at desc limit 200
    ) s;
    select coalesce(jsonb_agg(to_jsonb(d) order by d.created_at desc), '[]'::jsonb)
    into v_devices from (
        select d.id, d.label, d.created_at, d.revoked_at, max(s.last_seen_at) as last_seen_at
        from nexus_tracking.devices d left join nexus_tracking.sessions s on s.device_id = d.id
        group by d.id
    ) d;
    return jsonb_build_object('server_time', v_now, 'sessions', v_sessions, 'devices', v_devices);
end;
$$;

revoke all on function public.nexus_heartbeat(uuid, text, uuid, bigint, text, text, text, text, boolean)
    from public, anon, authenticated;
grant execute on function public.nexus_heartbeat(uuid, text, uuid, bigint, text, text, text, text, boolean) to anon;

revoke all on function public.nexus_admin_snapshot(boolean) from public, anon, authenticated;
revoke all on function public.nexus_register_device(text) from public, anon, authenticated;
revoke all on function public.nexus_revoke_device(uuid) from public, anon, authenticated;
grant execute on function public.nexus_admin_snapshot(boolean) to authenticated;
grant execute on function public.nexus_register_device(text) to authenticated;
grant execute on function public.nexus_revoke_device(uuid) to authenticated;

notify pgrst, 'reload schema';
commit;
