-- Booth visits (2026 exhibition): a visitor who says yes on the Bamnun
-- screen gets their drive and two small photos in the app until the last
-- exhibition day, 24 Nov 2026. Run once in the Supabase SQL editor.
--
-- The Pi inserts with the public anon key (insert only). Nobody can list or
-- read the table; the website fetches one visit by its random code through
-- get_visit(). Everything is gone after 24 Nov (the function stops answering
-- at once, and an hourly job deletes the rows).

create table if not exists public.visits (
  code text primary key check (code ~ '^[a-z0-9]{10}$'),
  created_at timestamptz not null default now(),
  payload jsonb not null check (pg_column_size(payload) < 400000)
);
alter table public.visits enable row level security;

drop policy if exists "booth can add a visit" on public.visits;
create policy "booth can add a visit" on public.visits
  for insert to anon with check (now() < timestamptz '2026-11-25 00:00:00+09');
revoke all on public.visits from anon, authenticated;
grant insert on public.visits to anon;

create or replace function public.get_visit(c text) returns jsonb
language sql stable security definer set search_path = public as $$
  select payload || jsonb_build_object('created_at', created_at)
  from public.visits
  where code = c and now() < timestamptz '2026-11-25 00:00:00+09'
$$;
revoke all on function public.get_visit(text) from public;
grant execute on function public.get_visit(text) to anon, authenticated;

create extension if not exists pg_cron;
select cron.unschedule(jobid) from cron.job where jobname = 'bamnun-visits-expire';
select cron.schedule('bamnun-visits-expire', '0 * * * *',
  $$delete from public.visits where now() >= timestamptz '2026-11-25 00:00:00+09'$$);
