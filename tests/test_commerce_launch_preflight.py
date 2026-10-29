from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest
from app.commerce_launch_preflight import ExpectedLaunchProfile, evaluate_launch, legal_fingerprint
from app.site_config import LEGAL_FIELDS

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
PROFILE = ExpectedLaunchProfile('acct_SyntheticOnly', 'synthetic_hook', 'synthetic_revision')


def inputs():
    legal = {k: 'SYNTHETIC ONLY '+k for k in LEGAL_FIELDS}
    approval = {'enabled': True, 'registration_approved': True, 'legal_fingerprint': legal_fingerprint(legal),
        'account_id': PROFILE.account_id, 'webhook_profile_id': PROFILE.webhook_profile_id,
        'policy_revision': PROFILE.policy_revision, 'approved_at': '2026-10-28T00:00:00Z',
        'expires_at': '2026-10-30T00:00:00Z'}
    return legal, approval


def test_all_declared_proofs_still_never_authorize_real_checkout():
    legal, approval = inputs()
    before = deepcopy((legal, approval))
    result = evaluate_launch(legal, PROFILE, approval, now=NOW)
    assert result['ready_for_live'] is False
    assert 'production_workflow_not_implemented' in result['blockers']
    assert 'provider_authentication_not_integrated' in result['blockers']
    assert (legal, approval) == before
    assert 'SYNTHETIC' not in str(result) and 'acct_' not in str(result)


@pytest.mark.parametrize('field,value,code', [
    ('enabled', 'true', 'launch_disabled'), ('enabled', False, 'launch_disabled'),
    ('registration_approved', 1, 'registration_not_approved'),
    ('legal_fingerprint', 'other', 'legal_identity_changed_or_unapproved'),
    ('account_id', 'acct_Other', 'account_context_mismatch'),
    ('webhook_profile_id', 'other', 'webhook_context_mismatch'),
    ('policy_revision', 'other', 'policy_revision_mismatch'),
    ('expires_at', '2026-10-29T00:00:00Z', 'approval_missing_or_expired'),
    ('approved_at', '2026-10-30T00:00:00Z', 'approval_missing_or_expired'),
    ('approved_at', '2026-10-28', 'approval_missing_or_expired')])
def test_mismatches_are_reported_without_approval(field, value, code):
    legal, approval = inputs(); approval[field] = value
    assert code in evaluate_launch(legal, PROFILE, approval, now=NOW)['blockers']


def test_missing_company_and_profile_and_revocation():
    result = evaluate_launch({}, {}, None, now=NOW)
    assert {'legal_identity_incomplete', 'launch_disabled', 'registration_not_approved',
            'server_profile_missing_or_invalid'}.issubset(result['blockers'])


def test_whitespace_identity_is_incomplete_even_with_matching_hash():
    legal, approval = inputs(); legal['siret'] = '   '
    approval['legal_fingerprint'] = legal_fingerprint(legal)
    assert 'legal_identity_incomplete' in evaluate_launch(legal, PROFILE, approval, now=NOW)['blockers']


def test_profile_is_immutable_and_client_dict_is_not_server_profile():
    with pytest.raises(FrozenInstanceError): PROFILE.account_id = 'acct_Other'
    legal, approval = inputs()
    assert 'server_profile_missing_or_invalid' in evaluate_launch(legal, PROFILE.__dict__ if hasattr(PROFILE, '__dict__') else {}, approval, now=NOW)['blockers']


def test_fingerprint_is_stable_but_changes_for_legal_updates():
    legal, _ = inputs()
    assert legal_fingerprint(legal) == legal_fingerprint(dict(reversed(list(legal.items()))))
    legal['address'] += ' changed'
    assert legal_fingerprint(legal) != legal_fingerprint(inputs()[0])


def test_clock_and_malformed_legal_configuration_are_refused():
    with pytest.raises(ValueError): evaluate_launch({}, None, None, now=datetime(2026, 10, 29))
    with pytest.raises(ValueError): legal_fingerprint({'address': None})
