-- Device-reported portal snapshots; assignments come from User KPI, not the
-- reporting device's current operator. Browser access remains admin/AAL2 only.
create table public.reconciliation_jobs (
  device_id uuid not null references public.devices(id) on delete cascade,
  job_id text not null,
  warehouse text not null default '',
  client text not null default '',
  status text not null check (status in ('Pending','In Progress','Completed','Unknown')),
  assigned_user text not null default '',
  observed_at timestamptz not null,
  received_at timestamptz not null default now(),
  primary key (device_id,job_id,warehouse)
);
create index reconciliation_jobs_observed_idx on public.reconciliation_jobs(observed_at desc);
alter table public.reconciliation_jobs enable row level security;
revoke all on public.reconciliation_jobs from public,anon,authenticated;
grant select on public.reconciliation_jobs to authenticated;
grant all on public.reconciliation_jobs to service_role;
create policy admin_read on public.reconciliation_jobs for select to authenticated
  using ((select public.nexus_is_admin()));

create function public.nexus_ingest_jobs(p_credential_id uuid,p_secret text,p_jobs jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare c nexus_private.device_credentials%rowtype; d public.devices%rowtype;
  j jsonb; stamp timestamptz; accepted integer:=0;
begin
  if p_secret is null or p_secret !~ '^[0-9a-f]{64}$' then
    raise exception 'Device credential rejected' using errcode='42501'; end if;
  select * into c from nexus_private.device_credentials where id=p_credential_id;
  select * into d from public.devices where id=c.device_id for update;
  select * into c from nexus_private.device_credentials where id=p_credential_id for update;
  if c.id is null or d.id is null or c.revoked_at is not null or d.revoked_at is not null
    or c.credential_hash<>sha256(convert_to(p_secret,'UTF8')) then
    raise exception 'Device credential rejected' using errcode='42501'; end if;
  if jsonb_typeof(p_jobs) is distinct from 'array' or jsonb_array_length(p_jobs)>50 then
    raise exception 'Invalid job batch' using errcode='22023'; end if;
  if c.request_window<now()-interval '1 minute' then c.request_window:=now(); c.request_count:=0; end if;
  if c.request_count>=60 then raise exception 'Device request limit reached' using errcode='P0429'; end if;
  update nexus_private.device_credentials set request_window=c.request_window,request_count=c.request_count+1 where id=c.id;
  for j in select value from jsonb_array_elements(p_jobs) loop
    if jsonb_typeof(j) is distinct from 'object'
      or (j - array['job_id','warehouse','client','status','assigned_user','observed_at'])<>'{}'::jsonb
      or not (j ?& array['job_id','warehouse','client','status','assigned_user','observed_at'])
      or exists (select 1 from jsonb_each(j) e where jsonb_typeof(e.value)<>'string')
      or j->>'status' not in ('Pending','In Progress','Completed','Unknown') then
      raise exception 'Invalid job record' using errcode='22023'; end if;
    perform nexus_private.checked_text(j->>'job_id',160);
    if length(j->>'warehouse')>0 then perform nexus_private.checked_text(j->>'warehouse',80); end if;
    if length(j->>'client')>0 then perform nexus_private.checked_text(j->>'client',160); end if;
    if length(j->>'assigned_user')>0 then perform nexus_private.checked_text(j->>'assigned_user',500); end if;
    stamp:=(j->>'observed_at')::timestamptz;
    if stamp is null or not isfinite(stamp) or stamp>now()+interval '5 minutes' or stamp<now()-interval '7 days' then
      raise exception 'Invalid observation time' using errcode='22023'; end if;
    insert into public.reconciliation_jobs as stored(device_id,job_id,warehouse,client,status,assigned_user,observed_at)
      values(d.id,upper(btrim(j->>'job_id')),upper(btrim(j->>'warehouse')),j->>'client',j->>'status',j->>'assigned_user',stamp)
    on conflict (device_id,job_id,warehouse) do update set client=excluded.client,status=excluded.status,
      assigned_user=excluded.assigned_user,observed_at=excluded.observed_at,received_at=now()
      where excluded.observed_at>=stored.observed_at;
    accepted:=accepted+1;
  end loop;
  return jsonb_build_object('accepted',accepted);
end $$;
revoke all on function public.nexus_ingest_jobs(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.nexus_ingest_jobs(uuid,text,jsonb) to service_role;

create function public.nexus_reconciliation_jobs() returns jsonb
language plpgsql stable security invoker set search_path='' as $$
begin
  if not public.nexus_is_admin() then raise exception 'Administrator access required' using errcode='42501'; end if;
  return (select coalesce(jsonb_agg(to_jsonb(latest) order by latest.observed_at desc,latest.job_id),'[]'::jsonb) from (
    select distinct on (j.job_id,j.warehouse)
      j.job_id,j.warehouse,j.client,j.status,j.assigned_user,j.observed_at,j.received_at,d.device_name
    from public.reconciliation_jobs j join public.devices d on d.id=j.device_id
    where d.revoked_at is null and j.observed_at>=now()-interval '7 days'
    order by j.job_id,j.warehouse,j.observed_at desc,j.received_at desc,j.device_id
  ) latest);
end $$;
revoke all on function public.nexus_reconciliation_jobs() from public,anon;
grant execute on function public.nexus_reconciliation_jobs() to authenticated;
