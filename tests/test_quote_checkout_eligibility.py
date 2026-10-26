"""An eligible quote permits only a sandbox request, not settlement or shipment."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from app.commerce_quote_service import public_quote


@pytest.mark.parametrize('state',['ready','consumed','superseded'])
@pytest.mark.parametrize('expired',[False,True])
@pytest.mark.parametrize('enabled',[False,True,'true',1])
def test_only_explicit_boolean_and_ready_unexpired_quotes_can_request_test_checkout(state,expired,enabled):
    now=datetime.now(timezone.utc)
    row={'id':str(uuid4()),'state':state,'expires_at':(now+timedelta(minutes=-1 if expired else 30)).isoformat(),
         'currency':'EUR','country':'FR','mode':'tracked','subtotal_cents':1000,'shipping_cents':100,'tax_cents':0,'total_cents':1100,
         'payload':{'groups':[{'lines':[]}]}}
    before=deepcopy(row)
    result=public_quote(row,now,sandbox_checkout_available=enabled)
    assert result['checkout_available'] is (enabled is True and state=='ready' and not expired)
    assert result['requires_revalidation'] is True
    assert result['scope']=='persisted_quote_not_payment_or_reservation'
    assert row==before
