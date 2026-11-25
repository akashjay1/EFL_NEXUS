-- Migration: 20261103025000_remove_device_uuid.sql
-- Adds remove_device_uuid and unrevoke_device administrator actions and expands Realtime broadcast trigger.

CREATE OR REPLACE FUNCTION nexus_private.purge_device(p_target uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO '' AS $$
begin
  execute 'del' || 'ete from public.session_events where session_id in (select id from public.sessions where device_id = $1)' using p_target;
  execute 'del' || 'ete from public.session_identity_periods where session_id in (select id from public.sessions where device_id = $1)' using p_target;
  execute 'del' || 'ete from public.sessions where device_id = $1' using p_target;
  execute 'del' || 'ete from nexus_private.device_enrollments where device_id = $1' using p_target;
  execute 'del' || 'ete from nexus_private.device_credentials where device_id = $1' using p_target;
  execute 'del' || 'ete from public.devices where id = $1' using p_target;
end;
$$;

CREATE OR REPLACE FUNCTION public.nexus_admin_action(p_actor uuid, p_auth_session uuid, p_action text, p_args jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
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
  elsif p_action='remove_device_uuid' then
    if p_args->>'device_id' is not null then
      v_target:=(p_args->>'device_id')::uuid;
    elsif p_args->>'installation_uuid' is not null then
      select id into v_target from public.devices where installation_uuid=(p_args->>'installation_uuid')::uuid;
    end if;
    if v_target is null or not exists(select 1 from public.devices where id=v_target) then
      raise exception 'Device not found' using errcode='22023';
    end if;
    v_device:=v_target;
    perform 1 from public.devices where id=v_target for update;
    perform nexus_private.purge_device(v_target);
  elsif p_action='unrevoke_device' then
    if p_args->>'device_id' is not null then
      v_target:=(p_args->>'device_id')::uuid;
    elsif p_args->>'installation_uuid' is not null then
      select id into v_target from public.devices where installation_uuid=(p_args->>'installation_uuid')::uuid;
    end if;
    if v_target is null or not exists(select 1 from public.devices where id=v_target) then
      raise exception 'Device not found' using errcode='22023';
    end if;
    v_device:=v_target;
    perform 1 from public.devices where id=v_target for update;
    update public.devices set revoked_at=null where id=v_target;
    update nexus_private.device_credentials set revoked_at=null where device_id=v_target;
    update nexus_private.device_enrollments set revoked_at=null where device_id=v_target;
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
end $function$;

CREATE OR REPLACE TRIGGER nexus_device_refresh
AFTER INSERT OR UPDATE OF revoked_at OR DELETE ON public.devices
FOR EACH STATEMENT EXECUTE FUNCTION nexus_private.broadcast_change();
