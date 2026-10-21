-- TYMotors staging: supplier communications MVP.
-- Keep every record inaccessible to browser clients; only authenticated backend
-- admin endpoints with server-side role verification may use the service key.
create table if not exists public.supplier_contacts (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 2 and 160),
  whatsapp_phone text not null unique check (whatsapp_phone ~ '^[1-9][0-9]{7,14}$'),
  alibaba_url text,
  whatsapp_opt_in boolean not null default false,
  notes text not null default '',
  last_inbound_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.supplier_messages (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.supplier_contacts(id) on delete cascade,
  channel text not null check (channel in ('whatsapp', 'alibaba')),
  direction text not null check (direction in ('inbound', 'outbound')),
  status text not null check (status in ('draft', 'received', 'sending', 'sent', 'failed')),
  body text not null check (char_length(body) between 1 and 4000),
  external_message_id text unique,
  error_code text,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  check (not (channel = 'whatsapp' and direction = 'inbound' and status <> 'received'))
);

create index if not exists supplier_messages_supplier_date_idx
  on public.supplier_messages (supplier_id, created_at desc);

alter table public.supplier_contacts enable row level security;
alter table public.supplier_messages enable row level security;
revoke all on public.supplier_contacts from anon, authenticated;
revoke all on public.supplier_messages from anon, authenticated;
-- No RLS policies: service key on the backend only.
