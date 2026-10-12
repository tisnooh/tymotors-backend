import pytest
from app.config import get_settings
from tests.test_email_system import settings

def read_settings(monkeypatch, **values):
    for key in ('EMAIL_FROM', 'EMAIL_FROM_ADDRESS', 'EMAIL_REPLY_TO'):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items(): monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try: return get_settings()
    finally: get_settings.cache_clear()

def test_no_sender_is_invented(monkeypatch):
    config = read_settings(monkeypatch)
    assert config.email_from_address == '' and config.email_reply_to == ''

def test_canonical_sender_and_default_reply(monkeypatch):
    config = read_settings(monkeypatch, EMAIL_FROM='sender@example.com', EMAIL_FROM_ADDRESS='legacy@example.com')
    assert config.email_from_address == 'sender@example.com' and config.email_reply_to == 'sender@example.com'

def test_legacy_render_configuration_is_compatible(monkeypatch):
    assert read_settings(monkeypatch, EMAIL_FROM_ADDRESS='legacy@example.com').email_from_address == 'legacy@example.com'

@pytest.mark.parametrize('values', [{'email_from_address':'not-an-email'}, {'email_reply_to':'bad\r\n@example.com'}, {'email_from_name':'TY\nInjected'}])
def test_sender_headers_are_validated(values):
    with pytest.raises(RuntimeError, match='email headers'): settings(**values).validate()
