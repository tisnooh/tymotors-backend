"""Full local paid pipeline then signed failure receipts against disposable SQL.

Stripe transport, goods and shipment remain explicitly synthetic. No provider,
SMTP, hosted database, production configuration or existing payment is touched.
"""
from copy import deepcopy
import json
from urllib.error import HTTPError
from uuid import uuid4
from tests import commerce_pipeline_http_probe as pipeline
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import sql, eq
from tests.test_commerce_failure_receipts import KINDS, failure


def protected():
    result={}
    for table in ('orders','commerce_checkout_attempts','commerce_variant_reservations',
                  'commerce_test_tasks','commerce_hypersku_preparations','email_logs'):
        try:
            rows=sql('select row_to_json(t) as snapshot from public.'+table+' t')
        except HTTPError as error:
            raise RuntimeError('Synthetic snapshot failed for '+table+': '+error.read().decode()) from None
        result[table]=sorted(rows,key=lambda row:json.dumps(row,sort_keys=True))
    return result


def main():
    pipeline.main()
    before=protected()
    start=probe.checks
    for kind in KINDS:
        event=failure(kind)
        event['id']='evt_'+uuid4().hex
        first=pipeline.webhook(event)
        eq(first['event_recorded'],True)
        eq(first['requires_reconciliation'],True)
        eq(first['duplicate'],False)
        row=sql('select * from stripe_events where event_id=$1',[event['id']])[0]
        eq(row['status'],'completed')
        eq(row['payload'],{'scope':'test_failure_receipt_only',
                           'object_id':event['data']['object']['id'],'requires_reconciliation':True})
        eq('PRIVATE' in str(row),False)
        eq(pipeline.webhook(event)['duplicate'],True)
        eq(sql('select count(*) n from stripe_events where event_id=$1',[event['id']])[0]['n'],1)
        changed=deepcopy(event)
        changed['data']['object']['id'] += '_different'
        pipeline.webhook(changed,expected=500)
        eq(sql('select * from stripe_events where event_id=$1',[event['id']])[0],row)
        eq(protected(),before)
    invalid=failure()
    invalid['id']='evt_'+uuid4().hex
    pipeline.webhook(invalid,valid=False,expected=400)
    eq(sql('select count(*) n from stripe_events where event_id=$1',[invalid['id']])[0]['n'],0)
    eq(protected(),before)
    print('Failure receipt HTTP/SQL checks:',probe.checks-start,
          '; no financial, reservation, shipment or email side effect; synthetic transport only.')


if __name__=='__main__': main()
