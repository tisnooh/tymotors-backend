-- Receipt only. No automatic refund or change to order state.
alter table public.email_logs drop constraint if exists email_logs_email_type_check;
alter table public.email_logs add constraint email_logs_email_type_check check (email_type in (
 'account_confirmation','welcome','password_reset','email_change','newsletter_confirmation',
 'order_confirmation','payment_confirmed','order_processing','order_shipped','order_delivered',
 'order_cancelled','refund_confirmed','withdrawal_received'
));
