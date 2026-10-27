"""No network/process/provider writes: refusal and uncertainty orchestration."""
import asyncio
from copy import deepcopy
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.commerce_payment_service import TestStripeGateway as Gateway
from tests import run_stripe_refund_sandbox as runner
from tests.test_stripe_refund_archive import case


@pytest.fixture
def provider():
    oid,qid,aid=(str(uuid4()) for _ in range(3))
    address={'line1':'1 Synthetic Street','city':'Paris','postal_code':'75001','country':'FR'}
    order={'id':oid,'commerce_quote_id':qid,'is_test':True,'currency':'EUR',
        'subtotal_cents':3000,'shipping_amount_cents':500,'tax_amount_cents':0,'total_cents':3500,
        'shipping_address':address,'stripe_payment_intent_id':'pi_synthetic_refund_runner'}
    attempt={'id':aid,'order_id':oid,'commerce_quote_id':qid,'is_test':True,'currency':'EUR',
        'total_cents':3500,'expires_at':1793014800}
    sid='cs_test_synthetic_refund_runner'
    session={'object':'checkout.session','id':sid,'mode':'payment','livemode':False,'currency':'eur',
        'client_reference_id':oid,'expires_at':attempt['expires_at'],
        'metadata':{'order_id':oid,'quote_id':qid,'attempt_id':aid},'amount_subtotal':3000,'amount_total':3500,
        'total_details':{'amount_discount':0,'amount_shipping':500,'amount_tax':0},
        'automatic_tax':{'enabled':False},'status':'complete','payment_status':'paid',
        'payment_intent':order['stripe_payment_intent_id'],'shipping_details':{'address':deepcopy(address)}}
    intent={'object':'payment_intent','id':order['stripe_payment_intent_id'],'livemode':False,
        'status':'succeeded','currency':'eur','amount':3500,'amount_received':3500}
    refunds=SimpleNamespace(list_async=AsyncMock(return_value=SimpleNamespace(data=[],has_more=False)),create_async=AsyncMock())
    gateway=Gateway('sk_test_synthetic_refund_runner')
    gateway.retrieve=AsyncMock(return_value=session)
    gateway.client=SimpleNamespace(v1=SimpleNamespace(payment_intents=SimpleNamespace(retrieve_async=AsyncMock(return_value=intent)),refunds=refunds))
    return gateway,{'session_id':sid},{'order':order,'attempt':attempt,'session':{'session_id':sid}},session,intent


def test_provider_preflight_reads_exact_funds_without_any_write(provider):
    gateway,receipt,archive,_,_=provider
    assert asyncio.run(runner.verify_provider(gateway,receipt,archive))['provider_payment_verified'] is True
    gateway.client.v1.refunds.create_async.assert_not_awaited()


@pytest.mark.parametrize('change',['live-session','destination','foreign-metadata','wrong-total','different-intent',
    'live-intent','unpaid-intent','wrong-received','existing-refund','more-refunds'])
def test_provider_mismatch_never_reaches_refund_write(provider,change):
    gateway,receipt,archive,session,intent=provider
    if change=='live-session': session['livemode']=True
    elif change=='destination': session['shipping_details']['address']['postal_code']='69001'
    elif change=='foreign-metadata': session['metadata']['order_id']=str(uuid4())
    elif change=='wrong-total': session['amount_total']=3501
    elif change=='different-intent': session['payment_intent']='pi_foreign'
    elif change=='live-intent': intent['livemode']=True
    elif change=='unpaid-intent': intent['status']='requires_payment_method'
    elif change=='wrong-received': intent['amount_received']=3499
    elif change=='existing-refund': gateway.client.v1.refunds.list_async.return_value.data=[{'id':'re_existing'}]
    elif change=='more-refunds': gateway.client.v1.refunds.list_async.return_value.has_more=True
    with pytest.raises(ValueError): asyncio.run(runner.verify_provider(gateway,receipt,archive))
    gateway.client.v1.refunds.create_async.assert_not_awaited()


@pytest.fixture
def execution(case,tmp_path,monkeypatch):
    receipt,snapshot=case
    root=tmp_path/'private';root.mkdir()
    monkeypatch.setattr(runner,'PRIVATE_ROOT',root)
    paid=root/'paid';paid.mkdir()
    (paid/'stripe-sandbox-result.json').write_text(json.dumps(receipt),encoding='utf-8')
    (paid/'disposable-state.json').write_text(json.dumps(snapshot),encoding='utf-8')
    args=SimpleNamespace(paid_run_directory=str(paid),report_directory=str(root/'refund'),
        config='not-read',profile='synthetic',account=receipt['account_id'],node='not-launched',
        stripe_cli='not-launched',wait_seconds=10,accept_sandbox_test_only=True,execute_test_refund=True)
    create=AsyncMock(return_value={'id':'re_synthetic_runner','payment_intent':snapshot['orders'][0]['stripe_payment_intent_id'],
        'amount':3500,'currency':'eur','status':'succeeded'})
    gateway=SimpleNamespace(client=SimpleNamespace(v1=SimpleNamespace(refunds=SimpleNamespace(create_async=create))))
    monkeypatch.setattr(runner,'load_profile',lambda *a:'sk_test_synthetic_runner')
    monkeypatch.setattr(runner,'TestStripeGateway',lambda key:gateway)
    identity_class=runner.ListenerIdentity
    def identity(secret):
        args.listener_identity=identity_class(secret)
        return args.listener_identity
    monkeypatch.setattr(runner,'ListenerIdentity',identity)
    monkeypatch.setattr(runner,'ensure_free_ports',lambda:None)
    monkeypatch.setattr(runner,'verify_provider',AsyncMock(return_value={'provider_payment_verified':True}))
    def fake_wait(predicate,*a,**k):
        # Do not race the real short-lived banner reader. Other predicates would
        # perform HTTP/SQL and are deliberately not invoked by these mock tests.
        event=getattr(predicate,'__self__',None)
        if isinstance(event,threading.Event):
            assert event.wait(timeout=2)
    monkeypatch.setattr(runner,'wait_ready',fake_wait)
    monkeypatch.setattr(runner,'save_snapshot',lambda *a:None)
    monkeypatch.setattr(runner,'untouched_state',lambda:{'stable':True})
    monkeypatch.setattr('tests.stripe_refund_archive.restore_financial_archive',lambda *a:{'restored_rows':6})
    def sql(statement,params=None):
        if 'payment_status' in statement: return [{'payment_status':'refunded','refunded_amount_cents':3500,'financial_review_required':True}]
        if 'refund_events' in statement: return [{'event_id':'evt_synthetic_runner'}]
        if 'refund_hold' in statement: return [{'held':True}]
        raise AssertionError('unexpected_SQL')
    monkeypatch.setattr(runner,'sql',sql)
    monkeypatch.setattr(runner.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='whsec_synthetic_runner_not_real'))
    processes=[]
    class Process:
        def __init__(self,*a,**k):
            self.stopped=False
            self.stdout=iter([getattr(args,'listener_banner','Ready! Your webhook signing secret is whsec_synthetic_runner_not_real\n')])
            processes.append(self)
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped=True
        def kill(self): self.stopped=True
        def wait(self,timeout=None): self.stopped=True;return 0
    monkeypatch.setattr(runner.subprocess,'Popen',Process)
    return args,create,processes,receipt,root


def test_simulated_runner_one_idempotent_refund_and_owned_cleanup(execution):
    args,create,processes,receipt,_=execution
    result=asyncio.run(runner.run(args))
    assert result['status']=='real_sandbox_signed_refund_receipt_passed'  # Entire transport mocked here.
    assert result['initial_payment_event_reauthenticated'] is False
    assert result['active_fulfillment_task_tested'] is False
    create.assert_awaited_once()
    assert create.call_args.kwargs['options']=={'idempotency_key':'phoenix-refund-sandbox-v1:'+receipt['order_id'],'max_network_retries':0}
    assert len(processes)==3 and all(p.stopped for p in processes)


def test_lost_provider_response_stays_unknown_and_is_never_retried(execution,capsys):
    args,create,processes,_,root=execution
    create.side_effect=TimeoutError('PRIVATE_PROVIDER_DETAIL')
    with pytest.raises(RuntimeError,match='no_automatic_retry'): asyncio.run(runner.run(args))
    report=json.loads((root/'refund'/'stripe-refund-result.json').read_text())
    assert report['status']=='provider_outcome_unknown'
    assert report['actual_stripe_test_refund_created'] is None
    create.assert_awaited_once()
    assert all(p.stopped for p in processes)
    assert 'PRIVATE_PROVIDER_DETAIL' not in capsys.readouterr().out


def test_stop_during_final_preflight_prevents_write(execution,monkeypatch):
    args,create,processes,_,root=execution
    calls=0
    async def preflight(*a):
        nonlocal calls
        calls+=1
        if calls==2: (root/'refund'/'STOP').write_text('stop')
        return {'provider_payment_verified':True}
    monkeypatch.setattr(runner,'verify_provider',preflight)
    with pytest.raises(RuntimeError): asyncio.run(runner.run(args))
    create.assert_not_awaited()
    report=json.loads((root/'refund'/'stripe-refund-result.json').read_text())
    assert report['status']=='blocked_before_refund_write'
    assert report['actual_stripe_test_refund_created'] is False
    assert all(p.stopped for p in processes)


@pytest.mark.parametrize('field',['accept_sandbox_test_only','execute_test_refund'])
def test_missing_opt_in_refused_before_io(execution,field):
    args,create,processes,_,root=execution
    setattr(args,field,False)
    with pytest.raises(ValueError,match='explicit_test_refund_opt_in'): asyncio.run(runner.run(args))
    create.assert_not_awaited();assert not processes and not (root/'refund').exists()


def test_original_archive_directory_never_overwritten(execution):
    args,create,processes,_,_=execution
    args.report_directory=args.paid_run_directory+'/child'
    with pytest.raises(ValueError,match='separate_private_report_directory'): asyncio.run(runner.run(args))
    create.assert_not_awaited();assert not processes


@pytest.mark.parametrize('target',['public','sibling','ancestor','root'])
def test_output_never_leaves_dedicated_private_root(execution,target):
    args,create,processes,_,root=execution
    paths={'public':root.parent/'frontend'/'public'/'capture','sibling':root.parent/'private-other'/'capture',
        'ancestor':root.parent,'root':root}
    args.report_directory=str(paths[target])
    with pytest.raises(ValueError,match='separate_private_report_directory'): asyncio.run(runner.run(args))
    create.assert_not_awaited();assert not processes and not paths[target].joinpath('stripe-refund-result.json').exists()


def test_archive_itself_must_be_inside_private_root(execution):
    args,create,processes,_,root=execution
    args.paid_run_directory=str(root.parent/'public-archive')
    with pytest.raises(ValueError,match='separate_private_report_directory'): asyncio.run(runner.run(args))
    create.assert_not_awaited();assert not processes


@pytest.mark.parametrize('banner',['Ready! No secret','Ready! whsec_different_synthetic',
    'Ready! whsec_synthetic_runner_not_real whsec_extra'])
def test_unverified_listener_secret_never_arms_write(execution,banner):
    args,create,processes,_,root=execution
    args.listener_banner=banner
    with pytest.raises(RuntimeError): asyncio.run(runner.run(args))
    create.assert_not_awaited();assert all(p.stopped for p in processes)
    report=json.loads((root/'refund'/'stripe-refund-result.json').read_text())
    assert report['status']=='blocked_before_refund_write'
    assert report['stage']=='real_test_event_listener'


@pytest.mark.parametrize('line,accepted',[
    ('Ready! whsec_synthetic_not_real',True),('Ready! \x1b[1mwhsec_synthetic_not_real\x1b[0m',True),
    ('Ready! whsec_synthetic_not_real_extra',False),('Ready! No secret',False),
    ('Not ready whsec_synthetic_not_real',False),('Ready! whsec_synthetic_not_real whsec_synthetic_not_real',False)])
def test_ready_banner_requires_exact_single_secret(line,accepted):
    assert runner.ready_banner_matches(line,'whsec_synthetic_not_real') is accepted


@pytest.mark.parametrize('second',['Ready! whsec_other_synthetic','Ready! whsec_synthetic_not_real','Ready! No secret'])
def test_second_ready_line_permanently_invalidates_binding(second):
    identity=runner.ListenerIdentity('whsec_synthetic_not_real')
    identity.observe('Ready! whsec_synthetic_not_real')
    identity.require_verified()
    identity.observe(second)
    with pytest.raises(RuntimeError): identity.require_verified()
    identity.observe('Ready! whsec_synthetic_not_real')
    with pytest.raises(RuntimeError): identity.require_verified()


def test_listener_change_during_final_preflight_prevents_write(execution,monkeypatch):
    args,create,processes,_,root=execution
    calls=0
    async def preflight(*a):
        nonlocal calls
        calls+=1
        if calls==2: args.listener_identity.observe('Ready! whsec_other_synthetic')
        return {'provider_payment_verified':True}
    monkeypatch.setattr(runner,'verify_provider',preflight)
    with pytest.raises(RuntimeError): asyncio.run(runner.run(args))
    create.assert_not_awaited();assert all(p.stopped for p in processes)
    report=json.loads((root/'refund'/'stripe-refund-result.json').read_text())
    assert report['status']=='blocked_before_refund_write'
