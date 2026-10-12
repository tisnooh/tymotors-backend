-- Service-only revocation check after Auth has verified the incoming access JWT.
create or replace function public.is_auth_session_active(p_session_id uuid, p_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists(select 1 from auth.sessions s where s.id = p_session_id
    and s.user_id = p_user_id and (s.not_after is null or s.not_after > now()));
$$;
revoke all on function public.is_auth_session_active(uuid, uuid) from public, anon, authenticated;
grant execute on function public.is_auth_session_active(uuid, uuid) to service_role;
