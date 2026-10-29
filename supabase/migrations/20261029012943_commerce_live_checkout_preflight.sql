-- Durable launch declarations only. No live workflow, activation API, provider
-- authentication, historical backfill or alteration of sandbox CHECKs.
begin;
alter table public.shop_settings
  add column commerce_live_enabled boolean not null default false,
  add column commerce_launch_registration_status text not null default 'pending'
    check(commerce_launch_registration_status in ('pending','declared_registered')),
  add column commerce_launch_approval_ref text
    check(commerce_launch_approval_ref is null or length(btrim(commerce_launch_approval_ref)) between 1 and 200),
  add column commerce_launch_approved_at timestamptz
    check(commerce_launch_approved_at is null or isfinite(commerce_launch_approved_at)),
  add column commerce_launch_approval_expires_at timestamptz
    check(commerce_launch_approval_expires_at is null or isfinite(commerce_launch_approval_expires_at)),
  add column commerce_launch_legal_fingerprint text
    check(commerce_launch_legal_fingerprint is null or commerce_launch_legal_fingerprint ~ '^[a-f0-9]{64}$'),
  add column commerce_launch_stripe_account_id text
    check(commerce_launch_stripe_account_id is null or commerce_launch_stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$'),
  add column commerce_launch_profile_ref text
    check(commerce_launch_profile_ref is null or commerce_launch_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$'),
  add constraint commerce_launch_approval_period check(commerce_launch_approved_at is null
    or commerce_launch_approval_expires_at is null or commerce_launch_approval_expires_at>commerce_launch_approved_at);

comment on column public.shop_settings.commerce_live_enabled is
  'False by default. A future separately approved activation cannot bypass missing legal/provider/operational proof or the unimplemented live checkout.';
comment on column public.shop_settings.commerce_launch_stripe_account_id is
  'Service-declared expected account only: not evidence of provider authentication or ownership.';
comment on column public.shop_settings.commerce_launch_registration_status is
  'Service declaration only; pending by default. Does not verify any official company register.';

create function public.commerce_live_checkout_preflight(p_legal_fingerprint text,p_stripe_account_id text,p_profile_ref text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare s public.shop_settings; checked_at timestamptz:=clock_timestamp(); blockers jsonb:='[]'::jsonb;
  legal_context_valid boolean; account_context_valid boolean; profile_context_valid boolean;
begin
  -- Read-only diagnosis, not a claim or an authorization. A future mutation must
  -- recheck its own policy atomically; this result must never authorize a write.
  begin
    select * into s from public.shop_settings where id;
  exception when insufficient_privilege then s:=null;
  end;
  legal_context_valid:=p_legal_fingerprint is not null and p_legal_fingerprint ~ '^[a-f0-9]{64}$';
  account_context_valid:=p_stripe_account_id is not null and p_stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$';
  profile_context_valid:=p_profile_ref is not null and p_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$';
  if s.commerce_live_enabled is distinct from true then blockers:=blockers||'"commerce_live_disabled"'::jsonb; end if;
  if s.commerce_launch_registration_status is distinct from 'declared_registered' then
    blockers:=blockers||'"legal_registration_pending"'::jsonb; end if;
  if s.commerce_launch_approval_ref is null or s.commerce_launch_approved_at is null
    or s.commerce_launch_approval_expires_at is null then blockers:=blockers||'"launch_approval_missing"'::jsonb; end if;
  if s.commerce_launch_approved_at>checked_at then blockers:=blockers||'"launch_approval_not_yet_valid"'::jsonb; end if;
  if s.commerce_launch_approval_expires_at<=checked_at then blockers:=blockers||'"launch_approval_expired"'::jsonb; end if;
  if s.commerce_launch_legal_fingerprint is null then blockers:=blockers||'"legal_fingerprint_unconfirmed"'::jsonb; end if;
  if not legal_context_valid then blockers:=blockers||'"legal_fingerprint_missing_or_invalid"'::jsonb;
  elsif s.commerce_launch_legal_fingerprint is not null and s.commerce_launch_legal_fingerprint<>p_legal_fingerprint then
    blockers:=blockers||'"legal_fingerprint_mismatch"'::jsonb; end if;
  if s.commerce_launch_stripe_account_id is null then blockers:=blockers||'"stripe_account_unconfirmed"'::jsonb; end if;
  if not account_context_valid then blockers:=blockers||'"stripe_account_missing_or_invalid"'::jsonb;
  elsif s.commerce_launch_stripe_account_id is not null and s.commerce_launch_stripe_account_id<>p_stripe_account_id then
    blockers:=blockers||'"stripe_account_mismatch"'::jsonb; end if;
  if s.commerce_launch_profile_ref is null then blockers:=blockers||'"execution_profile_unconfirmed"'::jsonb; end if;
  if not profile_context_valid then blockers:=blockers||'"execution_profile_missing_or_invalid"'::jsonb;
  elsif s.commerce_launch_profile_ref is not null and s.commerce_launch_profile_ref<>p_profile_ref then
    blockers:=blockers||'"execution_profile_mismatch"'::jsonb; end if;
  -- Deliberately unconditional. Matching declarations never mean a real
  -- gateway, session binding, financial ledger or fulfillment was implemented.
  blockers:=blockers||'"live_checkout_not_implemented"'::jsonb;
  return jsonb_build_object('allowed',false,'live_checkout_implemented',false,
    'configured',s.id is not null,'enabled',coalesce(s.commerce_live_enabled,false),'blockers',blockers);
end $$;

revoke all on function public.commerce_live_checkout_preflight(text,text,text) from public,anon,authenticated;
grant execute on function public.commerce_live_checkout_preflight(text,text,text) to service_role;
commit;
