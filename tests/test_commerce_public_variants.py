"""Public identities, not proof of availability or customer checkout approval."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
import server

PRODUCT='10000000-0000-4000-8000-000000000099'
VARIANT='10000000-0000-4000-8000-000000000098'
PATH='/api/products/'+PRODUCT+'/variants'


@pytest.fixture
def public_variants(monkeypatch):
    row={'id':VARIANT,'product_id':PRODUCT,'sku':'SYNTHETIC-VARIANT','name':'Fixture',
         'status':'active','is_verified':True,'evidence_ref':'private supplier evidence',
         'attributes':{'finish':'Gloss black'},'currency':'EUR','price_cents':1000,
         'requires_vehicle':True,'supplier_sku':'PRIVATE','unit_cost_cents':13,
         'stock':4,'responsible_agent_id':'PRIVATE','image_url':'PRIVATE'}
    monkeypatch.setattr(server,'settings',replace(server.settings,stripe_mode='test',test_catalog_enabled=True))
    product=AsyncMock(return_value={'id':PRODUCT,'status':'active','is_verified':True})
    page=AsyncMock(return_value={'items':[row],'total':1})
    monkeypatch.setattr(server.catalog,'product_by',product)
    monkeypatch.setattr(server.db,'page',page)
    rpc=AsyncMock();monkeypatch.setattr(server.db,'rpc',rpc)
    return TestClient(server.app),row,product,page,rpc


def test_public_response_is_strict_noncommercial_projection(public_variants):
    client,row,product,page,rpc=public_variants
    before=deepcopy(row)
    response=client.get(PATH)
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    data=response.json()
    assert set(data)=={'product_id','variants','requires_quote','checkout_available','test_mode'}
    assert data['product_id']==PRODUCT and data['requires_quote'] is True
    assert data['checkout_available'] is False and data['test_mode'] is True
    assert set(data['variants'][0])=={'id','product_id','sku','name','attributes','currency',
                                    'price_cents','requires_vehicle','status','is_verified'}
    assert 'PRIVATE' not in response.text and 'private supplier evidence' not in response.text
    assert 'is_test' not in data['variants'][0]
    assert row==before
    product.assert_awaited_once_with('id',PRODUCT,public_only=False)
    assert page.await_args.kwargs['params']['product_id']=='eq.'+PRODUCT
    rpc.assert_not_awaited()


@pytest.mark.parametrize('product', [None,{'status':'archived'}, {'status':'unknown'}])
def test_missing_or_hidden_product_never_exposes_variants(public_variants,product):
    client,_,lookup,page,rpc=public_variants
    lookup.return_value=product
    assert client.get(PATH).status_code==404
    page.assert_not_awaited();rpc.assert_not_awaited()


@pytest.mark.parametrize('product', [
    {'status':'draft','is_verified':True},{'status':'active','is_verified':False},
    {'status':'active','is_verified':'true'},
])
def test_preview_or_unverified_product_is_not_variant_approval(public_variants,product):
    client,_,lookup,page,_=public_variants
    lookup.return_value=product
    response=client.get(PATH)
    assert response.status_code==200 and response.json()['variants']==[]
    page.assert_not_awaited()


def test_draft_not_available_outside_test_catalog(public_variants,monkeypatch):
    client,_,lookup,page,_=public_variants
    lookup.return_value={'status':'draft','is_verified':False}
    monkeypatch.setattr(server,'settings',replace(server.settings,stripe_mode='live'))
    assert client.get(PATH).status_code==404
    page.assert_not_awaited()


@pytest.mark.parametrize('changes', [
    {'status':'draft'},{'is_verified':False},{'is_verified':'true'},
    {'evidence_ref':None},{'evidence_ref':' '},
])
def test_ineligible_variant_not_exposed_as_a_choice(public_variants,changes):
    client,row,_,_,_=public_variants
    row.update(changes)
    assert client.get(PATH).json()['variants']==[]


@pytest.mark.parametrize('changes', [
    {'id':'bad'}, {'id':'00000000-0000-0000-0000-000000000000'},
    {'product_id':VARIANT}, {'currency':'USD'}, {'price_cents':True}, {'price_cents':-1},
    {'price_cents':2_000_000_001}, {'requires_vehicle':'yes'}, {'sku':''}, {'name':'bad\nname'},
    {'attributes':None}, {'attributes':{'x':1}},
])
def test_corrupt_rows_fail_closed_not_partial_selection(public_variants,changes):
    client,row,_,_,rpc=public_variants
    row.update(changes)
    response=client.get(PATH)
    assert response.status_code==409 and 'PRIVATE' not in response.text
    rpc.assert_not_awaited()


@pytest.mark.parametrize('items,total', [([],1),([],101),([],True),([], -1), (None,0)])
def test_truncated_or_excessive_pages_refused(public_variants,items,total):
    client,_,_,page,_=public_variants
    page.return_value={'items':items,'total':total}
    assert client.get(PATH).status_code==409


def test_duplicate_identity_is_not_a_unique_selection(public_variants):
    client,row,_,page,_=public_variants
    page.return_value={'items':[row,deepcopy(row)],'total':2}
    assert client.get(PATH).status_code==409


def test_invalid_uuid_is_refused_before_storage(public_variants):
    client,_,lookup,page,_=public_variants
    assert client.get(PATH.replace(PRODUCT,'bad')).status_code==422
    lookup.assert_not_awaited();page.assert_not_awaited()
