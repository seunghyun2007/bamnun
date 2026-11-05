-- Bamnun cloud database (Supabase Postgres).
--
-- Paste all of this into Supabase -> SQL Editor -> New query, and Run.
-- It is safe to run again: it only creates what is missing.
--
-- Every table has Row Level Security on, and each policy allows a signed-in
-- user to read and write only rows whose user_id is their own. The app only
-- ever uses the public anon/publishable key plus the user's own sign-in token;
-- the service role key (which skips these rules) is never in the app or repo.
--
-- The Pi stays the source of truth while driving. The phone uploads finished
-- trips and their events when it has internet. A trip is identified by
-- (user_id, device_uid, device_trip_id), so uploading it again updates the
-- same row and never makes a duplicate. Video is never stored here.

-- -------------------------------------------------------------------------
-- profile: one row per user
-- -------------------------------------------------------------------------
create table if not exists public.profiles (
  user_id      uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  email        text,
  name         text not null default '' check (char_length(name) <= 20),
  owl_name     text not null default 'Ollie' check (owl_name = 'Ollie'),  -- the owl is always Ollie
  vehicle      text not null default 'long_haul'
               check (vehicle in ('long_haul', 'delivery', 'bus', 'taxi', 'car')),
  work         jsonb not null default '{}'::jsonb,       -- days, start, end, variable
  voice_lang   text check (voice_lang in ('en', 'ko')),
  app_lang     text not null default 'en' check (app_lang in ('en', 'ko')),
  settings     jsonb not null default '{}'::jsonb,       -- ladder, sensitivity, breaks, emergency contact...
  onboarded    boolean not null default false,           -- finished setup at least once
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- -------------------------------------------------------------------------
-- device: which Bamnun device(s) belong to the user
-- -------------------------------------------------------------------------
create table if not exists public.devices (
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  device_uid   text not null,                            -- the Pi's own random ID (/api/health device_id)
  name         text,                                     -- the Pi's hostname
  version      text,
  first_seen   timestamptz not null default now(),
  last_seen    timestamptz not null default now(),
  primary key (user_id, device_uid)
);

-- -------------------------------------------------------------------------
-- trips: one row per finished drive
-- -------------------------------------------------------------------------
create table if not exists public.trips (
  id               bigint generated always as identity primary key,
  user_id          uuid not null default auth.uid() references auth.users (id) on delete cascade,
  device_uid       text not null,
  device_trip_id   integer not null,                     -- the trip's number on that Pi
  started_at       timestamptz not null,
  ended_at         timestamptz,
  tz_min           integer not null default 0,           -- the driver's UTC offset, minutes
  start_place      text,
  end_place        text,
  distance_km      numeric,
  route            jsonb,                                -- route summary from the Route screen
  duration_s       real,
  drive_s          real,
  calm_s           real,
  alert_free       real,                                 -- share of driving with no alert, 0..1
  alerts           integer not null default 0,
  alerts_by_stage  integer[] not null default '{0,0,0,0}', -- light, mist, voice, alarm (highest step reached)
  max_stage        smallint not null default 0,
  microsleeps      integer not null default 0,
  longest_calm_s   real,                                 -- longest alert-free stretch
  breaks           integer not null default 0,
  break_s          real,
  co2_max          real,
  emergencies      integer not null default 0,
  summary          jsonb not null default '{}'::jsonb,   -- the Pi's full summary, for Insights
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (user_id, device_uid, device_trip_id)
);
create index if not exists trips_user_started on public.trips (user_id, started_at desc);

-- -------------------------------------------------------------------------
-- alert events: what happened during a trip
-- -------------------------------------------------------------------------
create table if not exists public.alert_events (
  id               bigint generated always as identity primary key,
  user_id          uuid not null default auth.uid(),
  device_uid       text not null,
  device_trip_id   integer not null,
  at               timestamptz not null,
  kind             text not null,                        -- alert, microsleep, break, emergency
  stage            smallint,                             -- 1 light, 2 mist, 3 voice, 4 alarm
  reason           text,
  lat              double precision,                     -- location, when the phone knew it
  lng              double precision,
  data             jsonb not null default '{}'::jsonb,
  unique (user_id, device_uid, device_trip_id, at, kind),
  foreign key (user_id, device_uid, device_trip_id)
    references public.trips (user_id, device_uid, device_trip_id) on delete cascade
);
create index if not exists alert_events_user_at on public.alert_events (user_id, at desc);

-- -------------------------------------------------------------------------
-- updated_at
-- -------------------------------------------------------------------------
create or replace function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();
drop trigger if exists trips_touch on public.trips;
create trigger trips_touch before update on public.trips
  for each row execute function public.touch_updated_at();

-- -------------------------------------------------------------------------
-- Row Level Security: each user only ever sees and changes their own rows
-- -------------------------------------------------------------------------
alter table public.profiles     enable row level security;
alter table public.devices      enable row level security;
alter table public.trips        enable row level security;
alter table public.alert_events enable row level security;

do $$
declare t text;
begin
  foreach t in array array['profiles', 'devices', 'trips', 'alert_events'] loop
    execute format('drop policy if exists "own rows" on public.%I', t);
    execute format(
      'create policy "own rows" on public.%I for all to authenticated '
      'using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id)', t);
  end loop;
end $$;

-- Signed-out visitors (the anon role) get nothing at all.
revoke all on public.profiles, public.devices, public.trips, public.alert_events from anon;
grant select, insert, update, delete
  on public.profiles, public.devices, public.trips, public.alert_events to authenticated;
grant usage, select on all sequences in schema public to authenticated;

-- -------------------------------------------------------------------------
-- Delete account (Settings -> Delete account)
-- -------------------------------------------------------------------------
-- Runs with the owner's rights so it can remove the sign-in itself, but only
-- ever the caller's own: auth.uid() is the signed-in user, never a parameter.
create or replace function public.delete_my_account() returns void
language plpgsql security definer set search_path = '' as $$
declare me uuid := auth.uid();
begin
  if me is null then
    raise exception 'not signed in';
  end if;
  delete from public.alert_events where user_id = me;
  delete from public.trips        where user_id = me;
  delete from public.devices      where user_id = me;
  delete from public.profiles     where user_id = me;
  delete from auth.users          where id = me;
end $$;
revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;
