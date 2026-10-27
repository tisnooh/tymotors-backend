"""Opt-in real sandbox refund of ONE already-paid archived QA Checkout.

Never creates a payment/session/customer/order with Stripe, or touches hosted
storage. Archive restoration is setup, NOT reauthentication of its old event.
The current provider identity is independently read before the one refund call.
"""
import argparse
import asyncio
import hmac
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

from app.commerce_payment_service import TestStripeGateway
from app.commerce_checkout_events import validate_checkout_session
from tests.commerce_http_probe import sql
from tests.run_stripe_sandbox import load_profile


PRIVATE_ROOT=Path.home()/'.codex'/'stripe-phoenix-private'


def private_run_paths(paid_run,directory):
    """Resolved paths stay strictly within the existing dedicated private root."""
    root=PRIVATE_ROOT.resolve()
    paid_run=Path(paid_run).resolve();directory=Path(directory).resolve()
    if (root not in paid_run.parents or root not in directory.parents
            or directory==paid_run or paid_run in directory.parents or directory in paid_run.parents):
        raise ValueError('separate_private_report_directory_required')
    return paid_run,directory


def ready_banner_matches(line,expected_secret):
    """Only a single actual listener secret, compared in memory, can arm writes."""
    if not isinstance(line,str) or 'Ready!' not in line or not isinstance(expected_secret,str):
        return False
    observed=re.findall(r'whsec_[A-Za-z0-9_]+',line)
    return len(observed)==1 and hmac.compare_digest(observed[0],expected_secret)


class ListenerIdentity:
    """Any additional ready banner invalidates the original binding permanently."""
    def __init__(self,secret):
        self._secret=secret;self._lock=threading.Lock();self._banners=0;self._matched=False
        self.ready=threading.Event()

    def observe(self,line):
        if 'Ready!' not in line: return
        with self._lock:
            self._banners+=1
            self._matched=self._banners==1 and ready_banner_matches(line,self._secret)
            self.ready.set()

    def require_verified(self):
        with self._lock:
            if self._banners!=1 or self._matched is not True:
                raise RuntimeError('sandbox_listener_signing_identity_mismatch')


def resource(value):
    return value.to_dict() if hasattr(value,'to_dict') else value


async def verify_provider(gateway, receipt, archive):
    """Current read-only identity/money corroboration. No refund or payment call."""
    if not isinstance(gateway,TestStripeGateway):
        raise ValueError('explicit_test_gateway_required')
    order=archive['order']
    attempt={**archive['attempt'],'session_id':archive['session']['session_id'],
        'payment_intent_id':order['stripe_payment_intent_id']}
    session=resource(await gateway.retrieve(receipt['session_id']))
    verified=validate_checkout_session(session,attempt,order,require_paid=True)
    if (session.get('id')!=receipt['session_id'] or session.get('amount_total')!=3500
            or session.get('payment_status')!='paid' or not verified['financial_valid']
            or not verified['destination_matches']):
        raise ValueError('current_test_checkout_mismatch')
    intent=resource(await gateway.client.v1.payment_intents.retrieve_async(order['stripe_payment_intent_id']))
    if (intent.get('object')!='payment_intent' or intent.get('id')!=order['stripe_payment_intent_id']
            or intent.get('livemode') is not False or intent.get('status')!='succeeded'
            or intent.get('currency')!='eur' or intent.get('amount')!=3500 or intent.get('amount_received')!=3500):
        raise ValueError('current_test_intent_mismatch')
    page=await gateway.client.v1.refunds.list_async({'payment_intent':intent['id'],'limit':100})
    if page.data or page.has_more:
        raise ValueError('existing_refund_requires_manual_inspection')
    return {'provider_payment_verified':True,'is_test':True,'amount_cents':3500,'currency':'EUR'}


def ensure_free_ports():
    for port in (8765,8766):
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1',port))==0:
                raise RuntimeError('refusing_unknown_fixture_process')


def safe_child_environment():
    return {**os.environ,'PYTHON_DOTENV_DISABLED':'1','ENVIRONMENT':'test','STRIPE_MODE':'test',
        'STRIPE_API_KEY':'','STRIPE_SECRET_KEY':'','STRIPE_WEBHOOK_SECRET':'',
        'SUPABASE_URL':'https://sandbox-fixture.invalid.supabase.co',
        'SUPABASE_SECRET_KEY':'synthetic-service','SUPABASE_SERVICE_ROLE_KEY':'synthetic-service',
        'SUPABASE_PUBLISHABLE_KEY':'synthetic-publishable','EMAIL_ENABLED':'false',
        'BREVO_API_KEY':'','SMTP_USERNAME':'','SMTP_PASSWORD':'','CLOUDINARY_URL':'',
        'CLOUDINARY_API_KEY':'','CLOUDINARY_API_SECRET':'',
        'FRONTEND_URL':'http://127.0.0.1:8765','SITE_URL':'http://127.0.0.1:8765',
        'CORS_ORIGINS':'http://127.0.0.1:8765'}


def wait_ready(predicate, processes, *, seconds=90, stop_file=None):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if stop_file is not None and stop_file.exists():
            raise RuntimeError('emergency_stop')
        if any(process.poll() is not None for process in processes):
            raise RuntimeError('owned_fixture_exited')
        try:
            if predicate(): return
        except (OSError,TimeoutError):
            pass
        time.sleep(.25)
    raise RuntimeError('owned_fixture_readiness_timeout')


def untouched_state():
    return sql("""select
        (select count(*) from public.orders) orders,
        (select count(*) from public.commerce_checkout_attempts) attempts,
        (select count(*) from public.commerce_test_sessions) sessions,
        (select count(*) from public.commerce_test_payment_events) payments,
        (select count(*) from public.commerce_variant_reservations) reservations,
        (select count(*) from public.supplier_orders) supplier_orders,
        (select count(*) from public.email_logs) emails,
        (select jsonb_agg(to_jsonb(p) order by p.id) from public.products p) products,
        (select jsonb_agg(to_jsonb(v) order by v.id) from public.product_variants v) variants""")[0]


def save_snapshot(directory, order_id):
    snapshot={}
    for table in ('orders','commerce_test_refund_events'):
        if table=='orders': snapshot[table]=sql('select * from public.orders where id=$1',[order_id])
        else: snapshot[table]=sql('select * from public.commerce_test_refund_events order by received_at,event_id')
    path=directory/'refund-disposable-state.json'
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot,indent=2),encoding='utf-8'); temporary.replace(path)


async def run(args):
    from tests.stripe_refund_archive import validate_paid_archive,restore_financial_archive
    if (getattr(args,'accept_sandbox_test_only',False) is not True
            or getattr(args,'execute_test_refund',False) is not True):
        raise ValueError('explicit_test_refund_opt_in_required')
    repository=Path(__file__).resolve().parents[1]
    paid_run,directory=private_run_paths(args.paid_run_directory,args.report_directory)
    receipt=json.loads((paid_run/'stripe-sandbox-result.json').read_text(encoding='utf-8'))
    original=json.loads((paid_run/'disposable-state.json').read_text(encoding='utf-8'))
    archive=validate_paid_archive(receipt,original)
    if receipt['account_id']!=args.account:
        raise ValueError('explicit_test_account_mismatch')
    gateway=TestStripeGateway(load_profile(args.config,args.profile,args.account))
    ensure_free_ports()
    directory.mkdir(parents=True,exist_ok=False)
    report_path=directory/'stripe-refund-result.json';stop_file=directory/'STOP'
    result={'status':'starting','is_test':True,'real_money_refund':False,'new_payment_created':False,
        'supplier_orders_created':0,'hosted_database_access':False,'provider_payment_verified':False,
        'actual_stripe_test_refund_created':False,'signed_refund_webhook_verified':False,
        'initial_payment_event_reauthenticated':False,'active_fulfillment_task_tested':False}
    processes=[];reader=None;stage='provider_read_only_verification';restored=False
    def save():
        temporary=report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({**result,'stage':stage},indent=2),encoding='utf-8')
        temporary.replace(report_path)
    save()
    try:
        result.update(await verify_provider(gateway,receipt,archive));save()
        cli=[args.stripe_cli,'--config',str(Path(args.config).resolve()),'--project-name',args.profile]
        environment=safe_child_environment()
        stage='listener_secret'
        secret_call=subprocess.run(cli+['listen','--print-secret','--skip-update'],env=environment,
            capture_output=True,text=True,timeout=60)
        secrets=re.findall(r'whsec_[A-Za-z0-9_]+',secret_call.stdout)
        if secret_call.returncode or len(secrets)!=1:
            raise RuntimeError('sandbox_listener_secret_unavailable')
        stage='owned_disposable_database'
        processes.append(subprocess.Popen([args.node,'tests/admin_database.mjs','--serve','--refund-archive'],cwd=repository,
            env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        wait_ready(lambda:bool(sql('select 1')),processes,stop_file=stop_file)
        stage='historical_financial_archive_restore'
        restore_financial_archive(sql,archive)
        restored=True
        result['restored_financial_rows']=6;save_snapshot(directory,archive['order']['id']);save()
        stage='signed_receipt_server'
        server_environment={**environment,'STRIPE_WEBHOOK_SECRET':secrets[0],
            'PHOENIX_STRIPE_REFUND_FIXTURE':'explicit-test-only','PHOENIX_REFUND_ORDER_ID':archive['order']['id'],
            'PHOENIX_REFUND_PAYMENT_INTENT':archive['order']['stripe_payment_intent_id']}
        processes.append(subprocess.Popen([sys.executable,'-m','tests.serve_stripe_refund_fixture'],cwd=repository,
            env=server_environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        def server_ready():
            with urlopen('http://127.0.0.1:8765/qa-stripe-refund-status',timeout=2) as response:
                identity=json.load(response)
            return (identity.get('fixture')=='real_stripe_refund_existing_test_payment_disposable_db'
                and identity.get('new_payment_allowed') is False)
        wait_ready(server_ready,processes,stop_file=stop_file)
        stage='real_test_event_listener'
        listener_identity=ListenerIdentity(secrets[0])
        listener=subprocess.Popen(cli+['listen','--skip-update','--events',
            'refund.created,refund.updated,refund.failed,charge.refunded',
            '--forward-to','http://127.0.0.1:8765/api/stripe/webhook'],cwd=repository,env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        processes.append(listener)
        def discard_listener_output():
            # CLI prints its signing secret in the ready banner: inspect only a
            # ready bit, discard every line, NEVER persist/print raw CLI logs.
            for line in listener.stdout:
                listener_identity.observe(line)
        reader=threading.Thread(target=discard_listener_output,daemon=True);reader.start()
        wait_ready(listener_identity.ready.is_set,processes,stop_file=stop_file)
        # Readiness alone is insufficient: CLI profile/listener identity could
        # otherwise differ from the receipt server's ephemeral signing secret.
        listener_identity.require_verified()
        before=untouched_state()
        if stop_file.exists(): raise RuntimeError('emergency_stop')
        # Recheck current funds just before the sole write. Never refund another
        # charge, infer write permissions, retry an unknown response or create a PI.
        await verify_provider(gateway,receipt,archive)
        if stop_file.exists(): raise RuntimeError('emergency_stop')
        if any(p.poll() is not None for p in processes): raise RuntimeError('owned_fixture_exited')
        listener_identity.require_verified()
        stage='test_refund_request_claimed_outcome_unknown'
        result.update(status='provider_outcome_unknown',actual_stripe_test_refund_created=None);save()
        print(json.dumps({'stage':stage,'is_test':True,'real_money_refund':False}),flush=True)
        refund=resource(await gateway.client.v1.refunds.create_async({
            'payment_intent':archive['order']['stripe_payment_intent_id'],'amount':3500,
            'metadata':{'purpose':'phoenix_existing_sandbox_refund_receipt','is_test':'true'}},
            options={'idempotency_key':'phoenix-refund-sandbox-v1:'+archive['order']['id'],
                     'max_network_retries':0}))
        if (not re.fullmatch(r're_[A-Za-z0-9_]{1,240}',refund.get('id',''))
                or refund.get('payment_intent')!=archive['order']['stripe_payment_intent_id']
                or refund.get('amount')!=3500 or refund.get('currency')!='eur'):
            raise RuntimeError('test_refund_response_requires_inspection')
        result.update(actual_stripe_test_refund_created=True,refund_id=refund['id'],
            provider_refund_status=refund.get('status'),status='awaiting_real_signed_refund_webhook')
        stage='signed_webhook_and_financial_projection';save()
        deadline=time.monotonic()+args.wait_seconds
        while time.monotonic()<deadline:
            if stop_file.exists(): raise RuntimeError('emergency_stop')
            if any(p.poll() is not None for p in processes): raise RuntimeError('owned_fixture_exited')
            row=sql('select payment_status,refunded_amount_cents,financial_review_required from public.orders where id=$1',
                [archive['order']['id']])[0]
            events=sql("select event_id from public.commerce_test_refund_events where refund_id=$1 and refund_status='succeeded'",[refund['id']])
            if (row['payment_status']=='refunded' and row['refunded_amount_cents']==3500
                    and row['financial_review_required'] is True and events):
                if untouched_state()!=before:
                    raise RuntimeError('unrelated_disposable_state_changed')
                hold=sql('select private.commerce_test_refund_hold($1) held',[archive['order']['id']])[0]['held']
                if hold is not True: raise RuntimeError('financial_hold_not_preserved')
                result.update(status='real_sandbox_signed_refund_receipt_passed',
                    signed_refund_webhook_verified=True,refunded_amount_cents=3500,financial_review_required=True,
                    financial_event_count=len(events),unrelated_state_unchanged=True)
                break
            await asyncio.sleep(.5)
        else:
            raise RuntimeError('real_signed_refund_receipt_not_verified_before_deadline')
        save_snapshot(directory,archive['order']['id']);save()
        print(json.dumps({k:result[k] for k in ('status','is_test','actual_stripe_test_refund_created',
            'signed_refund_webhook_verified','refunded_amount_cents','new_payment_created','real_money_refund')}),flush=True)
        return result
    except Exception as error:
        if result['status']=='starting': result['status']='blocked_before_refund_write'
        result['error_type']=type(error).__name__;save()
        print(json.dumps({'status':result['status'],'stage':stage,'error_type':type(error).__name__,
            'is_test':True,'raw_logs_withheld':True}),flush=True)
        raise RuntimeError('isolated_refund_run_requires_inspection_no_automatic_retry') from None
    finally:
        if restored:
            try: save_snapshot(directory,archive['order']['id'])
            except Exception: pass
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
        if reader is not None: reader.join(timeout=2)


def main():
    parser=argparse.ArgumentParser()
    for name in ('node','stripe-cli','config','profile','account','paid-run-directory','report-directory'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--accept-sandbox-test-only',action='store_true',required=True)
    parser.add_argument('--execute-test-refund',action='store_true',required=True)
    parser.add_argument('--wait-seconds',type=int,default=90)
    args=parser.parse_args()
    if not 10<=args.wait_seconds<=180: parser.error('Bounded 10..180 seconds required')
    for name in ('stripe','stripe._http_client','httpx','httpcore'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    asyncio.run(run(args))


if __name__=='__main__': main()
