-- Explicitly deny client access even if a table grant is accidentally added later.
do $$ declare t text; begin
  foreach t in array array['device_credentials','device_enrollments','admin_invitations','admin_audit_events'] loop
    execute format('create policy no_client_access on nexus_private.%I for all to anon,authenticated using (false) with check (false)',t);
  end loop;
end $$;

create extension if not exists pg_cron with schema pg_catalog;
select cron.schedule('nexus-monitoring-maintenance','* * * * *','select nexus_private.maintenance()');
