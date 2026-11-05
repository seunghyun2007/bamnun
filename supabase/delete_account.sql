-- Adds Settings -> Delete account to a database made before it existed.
-- (It's also at the end of schema.sql.) Paste into SQL Editor and Run.

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
