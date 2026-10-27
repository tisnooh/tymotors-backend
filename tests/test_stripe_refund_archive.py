"""No private files, servers, SDK or network: pure archive and mock SQL tests.

The SQL mock checks orchestration/parameters, not PostgreSQL execution. Root's
owned disposable integration remains necessary to prove real restoration.
"""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from tests.stripe_refund_archive import (
    ArchiveRestoreError, ArchiveValidationError, _FIELDS, _TABLES,
    restore_financial_archive, validate_paid_archive,
)


@pytest.fixture
def case():
    cid, qid, oid, aid, lid, iid = (str(uuid4()) for _ in range(6))
    now, end = '2026-10-26T11:00:00+00:00', '2026-10-26T11:40:00+00:00'
    guest, sku = 'sandbox_private_guest_fixture', 'SANDBOX-SYNTHETIC-unit-fixture'
    cart = dict(id=cid, user_id=None, guest_session_id=guest, currency='EUR', created_at=now, updated_at=now)
    meta = dict(order_id=oid, quote_id=qid, attempt_id=aid)
    quote = dict(id=qid, cart_id=cid, owner_user_id=None, owner_guest_session=guest,
        country='FR', mode='tracked', destination={'country': 'FR', 'postal_code': '75001'},
        source_context={'cart': deepcopy(cart)}, payload={'currency': 'EUR', 'groups': [{'lines': [{'sku': sku}]}]},
        currency='EUR', subtotal_cents=3000, shipping_cents=500, tax_cents=0, total_cents=3500,
        expires_at=end, request_key=str(uuid4()), state='consumed', created_at=now)
    order = dict(id=oid, order_number='ARCHIVE-UNIT-TEST', user_id=None, cart_id=cid,
        guest_session_id=guest, stripe_session_id='cs_test_archived_fixture',
        stripe_payment_intent_id='pi_archived_fixture', status='paid', payment_status='paid',
        fulfillment_status='requires_review', customer_email='PRIVATE-DO-NOT-OUTPUT@example.test',
        shipping_address={'country': 'FR'}, billing_address={}, subtotal_cents=3000,
        shipping_amount_cents=500, tax_amount_cents=0, total_cents=3500, currency='EUR',
        is_test=True, commerce_quote_id=qid, paid_at=now, refunded_amount_cents=0,
        discount_amount_cents=0, promotion_id=None)
    attempt = dict(id=aid, order_id=oid, commerce_quote_id=qid, is_test=True,
        currency='EUR', total_cents=3500, expires_at=1793014800, quote_expires_at=end,
        frontend_origin='http://127.0.0.1:8765', integration_identifier='unit_fixture_abcdefgh',
        idempotency_key='PRIVATE-ARCHIVED-IDEMPOTENCY', state='creating',
        params={'metadata': meta, 'mode': 'payment', 'client_reference_id': oid, 'expires_at': 1793014800},
        params_hash='a'*64, first_requested_at=now, session_id=None, session_url=None)
    session = dict(attempt_id=aid, session_id=order['stripe_session_id'], created_at=now)
    payment = dict(event_id='evt_archived_fixture', attempt_id=aid,
        event_type='checkout.session.completed', session_id=order['stripe_session_id'],
        payment_intent_id=order['stripe_payment_intent_id'], amount_cents=3500,
        destination_matches=True, created_at=now)
    line = dict(id=lid, order_id=oid, quote_id=qid, order_item_id=iid, line_snapshot={'sku': sku})
    report = dict(account_id='acct_archived_fixture', is_test=True, real_money_payment=False,
        actual_stripe_test_payment=True, real_supplier_orders=0, commercial_products_validated=0,
        status='sandbox_signed_payment_and_internal_preparation_passed', signed_webhook_verified=True,
        payment_completed=True, cart_id=cid, order_id=oid, quote_id=qid, attempt_id=aid,
        session_id=session['session_id'], sku=sku, expected_total_cents=3500, currency='EUR')
    snapshot = {'orders': [order], 'commerce_quotes': [quote], 'commerce_checkout_attempts': [attempt],
        'commerce_test_sessions': [session], 'commerce_test_payment_events': [payment], 'commerce_order_lines': [line]}
    return report, snapshot


def valid(case):
    return validate_paid_archive(*case)


def refused(case):
    before = deepcopy(case)
    with pytest.raises(ArchiveValidationError, match='^invalid_paid_sandbox_archive$'):
        valid(case)
    assert case == before


def test_exact_six_rows_deep_copied_with_no_generated_identity(case):
    before = deepcopy(case)
    archive = valid(case)
    assert set(archive) == set(_TABLES)
    assert archive['cart'] == case[1]['commerce_quotes'][0]['source_context']['cart']
    for key, table in [('quote','commerce_quotes'),('order','orders'),('attempt','commerce_checkout_attempts'),
                       ('session','commerce_test_sessions'),('payment_event','commerce_test_payment_events')]:
        assert archive[key] == case[1][table][0]
    archive['quote']['source_context']['cart']['currency'] = 'CHANGED'
    archive['attempt']['params']['metadata']['order_id'] = 'CHANGED'
    assert case == before


@pytest.mark.parametrize('field,value', [
    ('is_test', False), ('is_test', 1), ('actual_stripe_test_payment', False),
    ('payment_completed', 1), ('signed_webhook_verified', None), ('real_money_payment', 0),
    ('real_money_payment', True), ('real_supplier_orders', True), ('real_supplier_orders', 1),
    ('commercial_products_validated', False), ('commercial_products_validated', 1),
    ('status','passed'), ('currency','eur'), ('expected_total_cents',True), ('expected_total_cents',3500.0),
    ('expected_total_cents',3501), ('sku','REAL-CATALOGUE-SKU'), ('account_id','acct_'),
    ('session_id','cs_live_forbidden'), ('order_id','00000000-0000-0000-0000-000000000000'),
    ('quote_id',None), ('attempt_id',123), ('cart_id','not-uuid'), ('livemode',True),
])
def test_receipt_proof_contract_refused(case, field, value):
    case[0][field] = value
    refused(case)


@pytest.mark.parametrize('field', ['is_test','actual_stripe_test_payment','payment_completed','signed_webhook_verified',
    'real_money_payment','real_supplier_orders','commercial_products_validated','status','currency',
    'expected_total_cents','sku','account_id','session_id','order_id','quote_id','attempt_id','cart_id'])
def test_missing_receipt_fields_refused(case, field):
    del case[0][field]
    refused(case)


@pytest.mark.parametrize('table', ['orders','commerce_quotes','commerce_checkout_attempts','commerce_test_sessions',
                                  'commerce_test_payment_events','commerce_order_lines'])
@pytest.mark.parametrize('mode', ['missing','wrong_type','duplicate','foreign'])
def test_snapshot_missing_ambiguous_or_foreign_selection(case, table, mode):
    rows = case[1][table]
    if mode == 'missing': case[1].pop(table)
    elif mode == 'wrong_type': case[1][table] = {}
    elif mode == 'duplicate': rows.append(deepcopy(rows[0]))
    else:
        rows[0]['attempt_id' if table in ('commerce_test_sessions','commerce_test_payment_events') else 'order_id' if table=='commerce_order_lines' else 'id'] = str(uuid4())
    refused(case)


@pytest.mark.parametrize('table,field,value', [
    ('orders','is_test',False), ('orders','is_test',1), ('orders','currency','USD'),
    ('orders','payment_status','unpaid'), ('orders','status','refunded'), ('orders','refunded_amount_cents',1),
    ('orders','refunded_amount_cents',False), ('orders','financial_review_required',True),
    ('orders','user_id',str(uuid4())), ('orders','commerce_quote_id',str(uuid4())),
    ('orders','cart_id',str(uuid4())), ('orders','guest_session_id','other'),
    ('orders','total_cents',True), ('orders','total_cents',3501), ('orders','shipping_amount_cents',501),
    ('orders','stripe_payment_intent_id','pi_'), ('orders','stripe_session_id','cs_live_forbidden'),
    ('orders','promotion_id',str(uuid4())), ('orders','paid_at',None),
    ('commerce_quotes','state','ready'), ('commerce_quotes','tax_cents',False),
    ('commerce_quotes','owner_user_id',str(uuid4())), ('commerce_quotes','owner_guest_session','other'),
    ('commerce_quotes','total_cents',3501), ('commerce_quotes','expires_at','2026-10-26T14:00:00+00:00'),
    ('commerce_checkout_attempts','is_test',False), ('commerce_checkout_attempts','state','ready'),
    ('commerce_checkout_attempts','order_id',str(uuid4())), ('commerce_checkout_attempts','total_cents',3501),
    ('commerce_checkout_attempts','params',None), ('commerce_checkout_attempts','params_hash','bad'),
    ('commerce_checkout_attempts','first_requested_at',None), ('commerce_checkout_attempts','session_id','cs_test_other'),
    ('commerce_checkout_attempts','expires_at',True), ('commerce_test_sessions','session_id','cs_test_other'),
    ('commerce_test_payment_events','event_id','evt_bad\n'), ('commerce_test_payment_events','amount_cents',3501),
    ('commerce_test_payment_events','destination_matches',1), ('commerce_test_payment_events','payment_intent_id','pi_other'),
    ('commerce_test_payment_events','event_type','refund.updated'),
])
def test_rows_refuse_changed_financial_identity_or_state(case, table, field, value):
    case[1][table][0][field] = value
    refused(case)


@pytest.mark.parametrize('mode', ['production_sku','wrong_quote','wrong_sku','malformed_id','payload_sku','payload_live','unknown_column'])
def test_source_proof_and_column_safety(case, mode):
    line = case[1]['commerce_order_lines'][0]
    quote = case[1]['commerce_quotes'][0]
    if mode == 'production_sku': line['line_snapshot']['sku'] = 'PRODUCTION'
    elif mode == 'wrong_quote': line['quote_id'] = str(uuid4())
    elif mode == 'wrong_sku': line['line_snapshot']['sku'] = 'SANDBOX-SYNTHETIC-other'
    elif mode == 'malformed_id': line['id'] = []
    elif mode == 'payload_sku': quote['payload']['groups'][0]['lines'][0]['sku'] = 'PRODUCTION'
    elif mode == 'payload_live': quote['source_context']['livemode'] = True
    else: case[1]['orders'][0]['id); DROP TABLE orders;--'] = 'PRIVATE'
    refused(case)


@pytest.mark.parametrize('value', [None, [], 1, 'PRIVATE'])
def test_non_mapping_inputs_fixed_error(case, value):
    with pytest.raises(ArchiveValidationError): validate_paid_archive(value,case[1])
    with pytest.raises(ArchiveValidationError): validate_paid_archive(case[0],value)


def test_cycle_and_non_json_values_refused(case):
    case[1]['orders'][0]['billing_address'] = object()
    with pytest.raises(ArchiveValidationError): valid(case)
    case[1]['orders'][0]['billing_address'] = case[1]
    with pytest.raises(ArchiveValidationError): valid(case)


@pytest.mark.parametrize('refunds', [[{'event_id':'evt_previous'}], None, {}, True])
def test_archive_already_containing_refund_receipts_is_refused(case, refunds):
    case[1]['commerce_test_refund_events']=refunds
    refused(case)


def test_empty_refund_journal_accepted_and_not_imported(case):
    case[1]['commerce_test_refund_events']=[]
    assert set(valid(case))==set(_TABLES)


class SQLMock:
    """Models only response protocol and transactional rollback of ALTERs/inserts."""
    def __init__(self):
        self.calls=[]; self.inserted=[]; self.disabled=set(); self.committed=False
        self.fail_at=None; self.override=None; self.guard_changed=False

    def __call__(self, statement, params=None):
        params=params or []
        self.calls.append((statement,deepcopy(params)))
        if self.fail_at and self.fail_at in statement:
            raise RuntimeError('PRIVATE PROVIDER ERROR')
        if self.override:
            result=self.override(statement,params)
            if result is not None: return result
        if statement=='ROLLBACK':
            self.inserted.clear();self.disabled.clear();return []
        if statement=='COMMIT': self.committed=True;return []
        if 'pg_catalog.pg_attribute' in statement:
            return [{'table_name':table,'column_name':field} for table,fields in _FIELDS.items() for field in fields]
        if 'pg_catalog.pg_trigger' in statement:
            return [{'table_name':'commerce_quotes','trigger_name':'commerce_quotes_history','enabled':'O','internal':False},
                    {'table_name':'commerce_checkout_attempts','trigger_name':'commerce_attempt_history','enabled':'O','internal':False},
                    {'table_name':'orders','trigger_name':'FK-test','enabled':'D' if self.guard_changed and self.inserted else 'O','internal':True}]
        if 'relrowsecurity' in statement:
            return [{'table_name':table,'rls':True,'force_rls':False} for table,_ in _TABLES.values()]
        if 'DISABLE TRIGGER' in statement:
            self.disabled.add(statement.split()[-1]);return []
        if 'ENABLE TRIGGER' in statement:
            self.disabled.remove(statement.split()[-1]);return []
        if statement.startswith('INSERT INTO'):
            assert self.disabled == {'commerce_quotes_history','commerce_attempt_history'}
            self.inserted.append((statement,params));return []
        if ' IS NOT DISTINCT FROM jsonb_populate_record' in statement: return [{'exact':True}]
        if 'join public.commerce_quotes q' in statement: return [{'n':1}]
        if "sku='TEST-001'" in statement: return [{'n':1}]
        if 'count(*)' in statement: return [{'n':0}]
        return []


def test_restore_only_exact_six_rows_preserving_defaults_and_guards(case):
    archive=valid(case);before=deepcopy(archive);sql=SQLMock()
    result=restore_financial_archive(sql,archive)
    assert result == {'restored_rows':6,'is_test':True,'triggers_enabled':True,
                      'scope':'historical_archive_not_new_authenticated_payment'}
    assert sql.committed and not sql.disabled and archive==before
    assert len(sql.inserted)==6
    for (statement,params),(key,(table,_)) in zip(sql.inserted,_TABLES.items()):
        assert statement.startswith('INSERT INTO public.'+table+'(')
        assert json.loads(params[0])==archive[key]
        assert 'SELECT *' not in statement
    order_sql=next(text for text,_ in sql.inserted if text.startswith('INSERT INTO public.orders('))
    assert 'financial_review_required' not in order_sql
    statements=[text for text,_ in sql.calls]
    assert [s for s in statements if 'DISABLE TRIGGER' in s] == [
        'ALTER TABLE public.commerce_quotes DISABLE TRIGGER commerce_quotes_history',
        'ALTER TABLE public.commerce_checkout_attempts DISABLE TRIGGER commerce_attempt_history']
    assert statements.index('ALTER TABLE public.commerce_checkout_attempts ENABLE TRIGGER commerce_attempt_history') < statements.index('COMMIT')
    for forbidden in ('session_replication_role','DROP TRIGGER','DISABLE ROW','DISABLE TRIGGER ALL','create_checkout','commerce_settle','record_order_refund'):
        assert forbidden.lower() not in '\n'.join(statements).lower()
    assert all('PRIVATE' not in text for text in statements)


@pytest.mark.parametrize('needle', ['BEGIN','LOCK TABLE','pg_catalog.pg_attribute',
    'ALTER TABLE public.commerce_quotes DISABLE','ALTER TABLE public.commerce_checkout_attempts DISABLE',
    'INSERT INTO public.carts','INSERT INTO public.commerce_quotes','INSERT INTO public.orders',
    'INSERT INTO public.commerce_checkout_attempts','INSERT INTO public.commerce_test_sessions',
    'INSERT INTO public.commerce_test_payment_events','ALTER TABLE public.commerce_quotes ENABLE',
    'ALTER TABLE public.commerce_checkout_attempts ENABLE','IS NOT DISTINCT FROM jsonb_populate_record'])
def test_every_import_failure_rolls_back_and_never_commits(case, needle):
    sql=SQLMock();sql.fail_at=needle
    with pytest.raises(ArchiveRestoreError,match='^archive_restore_failed$'):
        restore_financial_archive(sql,valid(case))
    assert not sql.committed and not sql.disabled and not sql.inserted
    assert sql.calls[-1][0]=='ROLLBACK'


@pytest.mark.parametrize('table', ['commerce_quotes','commerce_checkout_attempts','commerce_test_sessions',
                                  'commerce_test_payment_events','commerce_test_refund_events','carts','orders','products'])
def test_non_fixture_or_occupied_targets_refused_before_disabling(case,table):
    sql=SQLMock()
    def override(statement,params):
        if 'count(*)' in statement and ('from public.'+table+' ' in statement or statement.endswith('from public.'+table)):
            return [{'n':0 if table=='products' else 1}]
    sql.override=override
    with pytest.raises(ArchiveRestoreError): restore_financial_archive(sql,valid(case))
    assert not sql.inserted and not any('DISABLE TRIGGER' in s for s,_ in sql.calls)


@pytest.mark.parametrize('mode',['missing_column','missing_trigger','disabled_trigger','rls_off','bad_response','post_guard_change','post_link_failure','exact_failure'])
def test_schema_guard_and_postconditions_fail_closed(case, mode):
    sql=SQLMock()
    def override(statement,params):
        if mode=='missing_column' and 'pg_catalog.pg_attribute' in statement: return []
        if mode=='missing_trigger' and 'pg_catalog.pg_trigger' in statement: return []
        if mode=='disabled_trigger' and 'pg_catalog.pg_trigger' in statement:
            return [{'table_name':'commerce_quotes','trigger_name':'commerce_quotes_history','enabled':'D','internal':False}]
        if mode=='rls_off' and 'relrowsecurity' in statement: return []
        if mode=='bad_response' and 'count(*)' in statement: return {'n':0}
        if mode=='post_link_failure' and 'join public.commerce_quotes q' in statement: return [{'n':0}]
        if mode=='exact_failure' and 'IS NOT DISTINCT FROM jsonb_populate_record' in statement: return [{'exact':False}]
    sql.guard_changed=mode=='post_guard_change';sql.override=override
    with pytest.raises(ArchiveRestoreError): restore_financial_archive(sql,valid(case))
    assert not sql.committed and not sql.disabled and not sql.inserted


def test_commit_ack_failure_is_explicit_uncertainty_not_claimed_rollback_proof(case):
    sql=SQLMock();sql.fail_at='COMMIT'
    with pytest.raises(ArchiveRestoreError,match='^archive_restore_commit_uncertain$'):
        restore_financial_archive(sql,valid(case))
    assert sql.calls[-1][0]=='ROLLBACK'


def test_rollback_failure_is_explicit_uncertainty_without_private_error(case):
    sql=SQLMock()
    def override(statement,params):
        if statement.startswith('INSERT INTO') or statement=='ROLLBACK': raise RuntimeError('PRIVATE')
    sql.override=override
    with pytest.raises(ArchiveRestoreError,match='^archive_restore_rollback_failed$'):
        restore_financial_archive(sql,valid(case))
    assert not sql.committed


def test_invalid_archive_rejected_before_sql_and_no_callable_destination_options(case):
    archive=valid(case);archive['order']['currency']='USD';sql=SQLMock()
    with pytest.raises(ArchiveValidationError): restore_financial_archive(sql,archive)
    assert sql.calls==[]
    with pytest.raises(ArchiveRestoreError,match='^archive_restore_bridge_required$'):
        restore_financial_archive(None,valid(case))


def test_unknown_columns_rejected_even_if_mock_database_would_accept(case):
    archive=valid(case);archive['order']['dangerous_column']='PRIVATE';sql=SQLMock()
    with pytest.raises(ArchiveValidationError): restore_financial_archive(sql,archive)
    assert sql.calls==[]
