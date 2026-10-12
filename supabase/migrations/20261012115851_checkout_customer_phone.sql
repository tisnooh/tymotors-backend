-- Collected by Stripe Checkout. No public tracking response includes this field.
alter table public.orders add column if not exists customer_phone text
  check (customer_phone is null or length(customer_phone) <= 40);
