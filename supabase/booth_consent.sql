-- Booth visits, consent on the phone (run once, after booth_visits.sql).
--
-- The Pi's dashboard shows each visitor's own QR code (?v=<code>) the whole
-- time. Scanning it asks on the phone first; "yes" adds the code here. The
-- Pi checks has_consent(code) and only then sends the drive and photos with
-- put_visit, and keeps them up to date while the visitor drives. Nothing is
-- stored without the yes. Everything stops and is deleted after 24 Nov 2026.

create table if not exists public.visit_consents (
  code text primary key check (code ~ '^[a-z0-9]{10}$'),
  created_at timestamptz not null default now()
);
alter table public.visit_consents enable row level security;
drop policy if exists "a phone can say yes" on public.visit_consents;
create policy "a phone can say yes" on public.visit_consents
  for insert to anon with check (now() < timestamptz '2026-11-25 00:00:00+09');
revoke all on public.visit_consents from anon, authenticated;
grant insert on public.visit_consents to anon;

create or replace function public.has_consent(c text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.visit_consents where code = c)
$$;
revoke all on function public.has_consent(text) from public;
grant execute on function public.has_consent(text) to anon;

-- The Pi sends (and updates) a visit only for a code a phone said yes to,
-- within 3 hours of that yes.
create or replace function public.put_visit(c text, p jsonb) returns boolean
language plpgsql security definer set search_path = public as $$
begin
  if now() >= timestamptz '2026-11-25 00:00:00+09' or pg_column_size(p) >= 400000 then
    return false;
  end if;
  if not exists (select 1 from public.visit_consents
                 where code = c and created_at > now() - interval '3 hours') then
    return false;
  end if;
  insert into public.visits (code, payload) values (c, p)
    on conflict (code) do update set payload = excluded.payload;
  return true;
end
$$;
revoke all on function public.put_visit(text, jsonb) from public;
grant execute on function public.put_visit(text, jsonb) to anon;

select cron.unschedule(jobid) from cron.job where jobname = 'bamnun-consents-expire';
select cron.schedule('bamnun-consents-expire', '0 * * * *',
  $$delete from public.visit_consents where now() >= timestamptz '2026-11-25 00:00:00+09'$$);
