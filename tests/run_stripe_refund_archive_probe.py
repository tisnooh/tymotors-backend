"""Opt-in local HTTP/SQL receipt probe; ZERO Stripe calls or real signatures.

Original identifiers are restored only inside an owned disposable PGlite. The
old paid event is archival setup, not authenticated again. All subsequent refund
events and their HMACs are deliberately synthetic. Never use this as network
Stripe, active fulfillment, hosted concurrency or commercial approval evidence.
"""
from copy import deepcopy
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time

from tests.commerce_http_probe import sql
from tests.run_stripe_refund_sandbox import ensure_free_ports,safe_child_environment,untouched_state,wait_ready
from tests.stripe_refund_archive import ArchiveRestoreError,restore_financial_archive,validate_paid_archive,_guards


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--node',required=True)
    parser.add_argument('--paid-run-directory',required=True)
    parser.add_argument('--accept-local-restore-only',action='store_true',required=True)
    args=parser.parse_args()
    source=Path(args.paid_run_directory)
    archive=validate_paid_archive(
        json.loads((source/'stripe-sandbox-result.json').read_text(encoding='utf-8')),
        json.loads((source/'disposable-state.json').read_text(encoding='utf-8')))
    ensure_free_ports()
    environment=safe_child_environment()
    os.environ.update(environment)  # Only this opt-in subprocess; no hosted keys.
    process=subprocess.Popen([args.node,'tests/admin_database.mjs','--serve','--refund-archive'],
        cwd=Path(__file__).resolve().parents[1],env=environment,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    checks=0
    def eq(actual,expected):
        nonlocal checks
        if actual!=expected: raise AssertionError('local_refund_archive_probe_mismatch')
        checks+=1
    def counts():
        return sql('select '+','.join('(select count(*) from public.'+t+') '+t for t in
            ('carts','orders','commerce_quotes','commerce_checkout_attempts','commerce_test_sessions',
             'commerce_test_payment_events','commerce_test_refund_events')))[0]
    last={}
    def restore_sql(statement,params=None):
        if statement!='ROLLBACK':
            last['statement']=statement
            last['scalar_result']=None
        rows=sql(statement,params)
        if len(rows)==1 and set(rows[0]) in ({'n'},{'exact'}):
            last['scalar_result']=rows[0]
        return rows
    try:
        wait_ready(lambda:bool(sql('select 1')),[process])
        before=counts();guards=_guards(sql);unchanged=untouched_state()
        corrupt=deepcopy(archive);corrupt['attempt']['params_hash']='0'*64
        try: restore_financial_archive(sql,corrupt)
        except ArchiveRestoreError: checks+=1
        else: raise AssertionError('corrupt_hash_import_accepted')
        eq(counts(),before);eq(_guards(sql),guards);eq(untouched_state(),unchanged)
        try: result=restore_financial_archive(restore_sql,archive)
        except ArchiveRestoreError:
            # Static SQL/booleans only; bound archival values are never logged.
            print(json.dumps({'status':'restore_failed','last_static_check':last}),flush=True)
            raise
        eq(result['restored_rows'],6);eq(result['triggers_enabled'],True);eq(_guards(sql),guards)
        imported=counts()
        for table in ('carts','orders','commerce_quotes','commerce_checkout_attempts','commerce_test_sessions','commerce_test_payment_events'):
            eq(imported[table],before[table]+1)
        eq(imported['commerce_test_refund_events'],0)
        try: restore_financial_archive(sql,archive)
        except ArchiveRestoreError: checks+=1
        else: raise AssertionError('duplicate_import_accepted')
        eq(counts(),imported);eq(_guards(sql),guards)
        before_receipt=untouched_state()
        from fastapi.testclient import TestClient
        from tests.serve_stripe_refund_fixture import create_app
        from tests.commerce_refund_http_probe import refund
        secret='whsec_synthetic_local_archive_probe_only'
        oid=archive['order']['id'];pi=archive['order']['stripe_payment_intent_id']
        app=create_app(signing_secret=secret,order_id=oid,payment_intent_id=pi)
        def signed(client,event,valid=True):
            body=json.dumps(event,separators=(',',':')).encode();timestamp=int(time.time())
            signature=hmac.new(secret.encode(),str(timestamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
            return client.post('/api/stripe/webhook',content=body,
                headers={'Stripe-Signature':f't={timestamp},v1={signature if valid else "invalid"}'})
        with TestClient(app,client=('127.0.0.1',50000)) as client:
            eq(client.get('/qa-stripe-refund-status').status_code,200)
            eq(client.post('/api/create-checkout-session').status_code,403)
            event=refund(pi,3500,refund_id='re_synthetic_archive_probe')
            eq(signed(client,event,False).status_code,400)
            foreign=deepcopy(event);foreign['data']['object']['payment_intent']='pi_foreign_fixture'
            eq(signed(client,foreign).status_code,400)
            live=deepcopy(event);live['livemode']=True
            eq(signed(client,live).status_code,400)
            eq(counts(),imported)
            eq(signed(client,event).status_code,200)
            eq(signed(client,event).json().get('duplicate'),True)
            late=refund(pi,3500,'pending',refund_id='re_synthetic_archive_probe')
            eq(signed(client,late).status_code,200)
        row=sql('select payment_status,refunded_amount_cents,financial_review_required from public.orders where id=$1',[oid])[0]
        eq(row,{'payment_status':'refunded','refunded_amount_cents':3500,'financial_review_required':True})
        eq(sql('select private.commerce_test_refund_hold($1) held',[oid])[0]['held'],True)
        eq(counts()['commerce_test_refund_events'],2)
        eq(untouched_state(),before_receipt);eq(_guards(sql),guards)
        print(json.dumps({'status':'local_archive_synthetic_receipt_passed','checks':checks,
            'restored_rows':6,'real_stripe_calls':0,'real_refund_created':False,
            'original_payment_reauthenticated':False,'active_fulfillment_task_tested':False,
            'rollback_and_guards_verified':True,'hosted_database_access':False}))
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)


if __name__=='__main__': main()
