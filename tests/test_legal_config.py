from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.site_config import LEGAL_FIELDS, legal_configuration, legal_ready
import server

def test_no_fake_company_values(monkeypatch):
    for field in LEGAL_FIELDS: monkeypatch.delenv('LEGAL_'+field.upper(), raising=False)
    assert all(value == '' for value in legal_configuration().values())
    assert legal_ready() is False
    data = TestClient(server.app).get('/api/site-config').json()
    assert data['legal_ready'] is False
    assert 'stripe_secret_key' not in data and 'email_token_secret' not in data

def test_legal_values_are_configurable(monkeypatch):
    monkeypatch.setenv('LEGAL_COMPANY_NAME','Fixture legal entity')
    assert legal_configuration()['company_name'] == 'Fixture legal entity'

def test_withdrawal_requires_explicit_confirmation():
    result = TestClient(server.app).post('/api/withdrawals', json={'name':'Fixture', 'email':'qa@example.com','order_number':'TY-2026-12345','confirmed':False})
    assert result.status_code == 422

def test_withdrawal_is_saved_without_automatic_refund(monkeypatch):
    server.contact_attempts.clear()
    monkeypatch.setattr(server.db,'select',AsyncMock(return_value=[{'id':'fixture','order_number':'TY-2026-12345'}]))
    insert = AsyncMock(return_value=[{'id':'receipt-fixture'}]); monkeypatch.setattr(server.db,'insert',insert)
    monkeypatch.setattr(server.email_service,'send',AsyncMock(return_value={'sent':False}))
    result = TestClient(server.app).post('/api/withdrawals',json={'name':'Fixture','email':'qa@example.com','order_number':'TY-2026-12345','confirmed':True})
    assert result.status_code == 201 and result.json()['email_sent'] is False
    assert 'Commande' in result.json()['receipt_text']
    assert insert.call_args.args[0] == 'contact_messages'
