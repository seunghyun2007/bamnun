-- The booth remote (2026 exhibition): a staff phone sends commands to the Pi
-- through this mailbox (stages 1-4 and 0 = all off, next person, calibrate,
-- photos on/off, volume, voice). Every call needs the staff code; the real
-- code replaces __STAFF_CODE__ when this is run (it is not kept in git; the
-- Pi has it in frontend/.env as STAFF_CODE, the staff page takes it from ?k=).

create table if not exists public.booth_commands (
  id bigserial primary key,
  cmd text not null check (cmd ~ '^(stage[0-4]|next|calibrate|photos_off|photos_on|vol_up|vol_down|voice)$'),
  created_at timestamptz not null default now(),
  done_at timestamptz
);
alter table public.booth_commands enable row level security;
revoke all on public.booth_commands from anon, authenticated;

create or replace function public.staff_ok(k text) returns boolean
language sql immutable as $$ select k = '__STAFF_CODE__' $$;
revoke all on function public.staff_ok(text) from public, anon, authenticated;

create or replace function public.send_command(k text, c text) returns bigint
language plpgsql security definer set search_path = public as $$
declare i bigint;
begin
  if not staff_ok(k) then return null; end if;
  insert into public.booth_commands (cmd) values (c) returning id into i;
  return i;
end $$;

-- The Pi takes what's new (anything older than 15 s is dropped: a stale
-- "alarm" shouldn't go off when the Pi comes back online).
create or replace function public.take_commands(k text)
returns table (id bigint, cmd text)
language plpgsql security definer set search_path = public as $$
begin
  if not staff_ok(k) then return; end if;
  return query
    update public.booth_commands b set done_at = now()
    where b.done_at is null and b.created_at > now() - interval '15 seconds'
    returning b.id, b.cmd;
end $$;

create or replace function public.command_done(k text, i bigint) returns boolean
language sql stable security definer set search_path = public as $$
  select staff_ok(k) and exists (select 1 from public.booth_commands where id = i and done_at is not null)
$$;

revoke all on function public.send_command(text, text) from public;
revoke all on function public.take_commands(text) from public;
revoke all on function public.command_done(text, bigint) from public;
grant execute on function public.send_command(text, text) to anon;
grant execute on function public.take_commands(text) to anon;
grant execute on function public.command_done(text, bigint) to anon;

select cron.unschedule(jobid) from cron.job where jobname = 'bamnun-commands-clean';
select cron.schedule('bamnun-commands-clean', '15 * * * *',
  $$delete from public.booth_commands where created_at < now() - interval '1 day'$$);
