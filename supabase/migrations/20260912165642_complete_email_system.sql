-- TYMotors email system. Apply to staging first; never place SMTP credentials in SQL.

do $$
begin
  if to_regclass('public.newsletter_subscriptions') is not null
     and to_regclass('public.newsletter_subscribers') is null then
    alter table public.newsletter_subscriptions rename to newsletter_subscribers;
  end if;
end $$;

alter table public.newsletter_subscribers
  add column if not exists status text not null default 'pending',
  add column if not exists consent_source text not null default 'footer',
  add column if not exists confirmed_at timestamptz,
  add column if not exists confirmation_token_hash text,
  add column if not exists confirmation_expires_at timestamptz,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

-- Preserve one consent record per normalized address before enforcing uniqueness.
delete from public.newsletter_subscribers duplicate
using public.newsletter_subscribers keeper
where lower(trim(duplicate.email)) = lower(trim(keeper.email))
  and duplicate.id::text > keeper.id::text;

update public.newsletter_subscribers
set email = lower(trim(email)),
    status = case when unsubscribed_at is not null then 'unsubscribed' when confirmed_at is not null then 'subscribed' else 'pending' end,
    created_at = coalesce(created_at, consent_at),
    updated_at = now();

alter table public.newsletter_subscribers
  drop constraint if exists newsletter_subscribers_status_check,
  drop constraint if exists newsletter_subscribers_consent_source_check;
alter table public.newsletter_subscribers
  add constraint newsletter_subscribers_status_check check (status in ('pending','subscribed','unsubscribed')),
  add constraint newsletter_subscribers_consent_source_check check (consent_source in ('footer','account','checkout','admin'));

create unique index if not exists newsletter_subscribers_email_normalized_idx
  on public.newsletter_subscribers (lower(email));
create unique index if not exists newsletter_subscribers_confirmation_token_idx
  on public.newsletter_subscribers (confirmation_token_hash)
  where confirmation_token_hash is not null;
create index if not exists newsletter_subscribers_status_idx
  on public.newsletter_subscribers (status, created_at desc);

drop trigger if exists set_newsletter_subscriptions_updated_at on public.newsletter_subscribers;
drop trigger if exists set_newsletter_subscribers_updated_at on public.newsletter_subscribers;
create trigger set_newsletter_subscribers_updated_at before update on public.newsletter_subscribers
for each row execute function public.set_updated_at();

create table if not exists public.email_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete set null,
  order_id uuid references public.orders(id) on delete set null,
  recipient text not null,
  email_type text not null check (email_type in (
    'account_confirmation','welcome','password_reset','email_change',
    'newsletter_confirmation','order_confirmation','payment_confirmed',
    'order_processing','order_shipped','order_delivered','order_cancelled','refund_confirmed'
  )),
  provider_message_id text,
  status text not null default 'queued' check (status in ('queued','sent','failed')),
  error_message text,
  idempotency_key text not null unique,
  metadata jsonb not null default '{}'::jsonb,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists email_logs_created_idx on public.email_logs (created_at desc);
create index if not exists email_logs_order_idx on public.email_logs (order_id, created_at desc);
create index if not exists email_logs_status_idx on public.email_logs (status, created_at desc);
drop trigger if exists set_email_logs_updated_at on public.email_logs;
create trigger set_email_logs_updated_at before update on public.email_logs
for each row execute function public.set_updated_at();

create table if not exists public.newsletter_campaigns (
  id uuid primary key default gen_random_uuid(),
  subject text not null,
  preview_text text,
  content text not null,
  status text not null default 'draft' check (status in ('draft','scheduled','sending','sent')),
  scheduled_at timestamptz,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
drop trigger if exists set_newsletter_campaigns_updated_at on public.newsletter_campaigns;
create trigger set_newsletter_campaigns_updated_at before update on public.newsletter_campaigns
for each row execute function public.set_updated_at();

alter table public.orders
  add column if not exists carrier text,
  add column if not exists tracking_url text;

alter table public.newsletter_subscribers enable row level security;
alter table public.email_logs enable row level security;
alter table public.newsletter_campaigns enable row level security;

drop policy if exists admin_read_newsletter on public.newsletter_subscribers;
create policy admin_read_newsletter on public.newsletter_subscribers for select to authenticated
using ((select private.is_admin()));
create policy admin_manage_newsletter on public.newsletter_subscribers for update to authenticated
using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_read_email_logs on public.email_logs for select to authenticated
using ((select private.is_admin()));
create policy admin_manage_campaigns on public.newsletter_campaigns for all to authenticated
using ((select private.is_admin())) with check ((select private.is_admin()));

revoke all on public.newsletter_subscribers, public.email_logs, public.newsletter_campaigns from anon;
grant select, update on public.newsletter_subscribers to authenticated;
grant select on public.email_logs to authenticated;
grant select, insert, update, delete on public.newsletter_campaigns to authenticated;
grant all on public.newsletter_subscribers, public.email_logs, public.newsletter_campaigns to service_role;
