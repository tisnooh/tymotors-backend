"""Read-only launch diagnostics. No payment authority or provider authentication.

Profiles below are EXPECTATIONS from server configuration. Matching an account
identifier or a service-written approval never authenticates a Stripe account.
No route uses this as permission to bypass the existing closed live workflow.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re

from app.site_config import LEGAL_FIELDS, legal_ready


@dataclass(frozen=True, slots=True)
class ExpectedLaunchProfile:
    account_id: str
    webhook_profile_id: str
    policy_revision: str
    mode: str = 'production'


def legal_fingerprint(legal):
    if not isinstance(legal, dict) or any(not isinstance(legal.get(k, ''), str) for k in LEGAL_FIELDS):
        raise ValueError('Invalid legal configuration')
    canonical = {k: legal.get(k, '').strip() for k in LEGAL_FIELDS}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def evaluate_launch(legal, profile, approval, *, now):
    """Return safe codes only; never inputs, addresses, secrets or fake readiness."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware server clock required')
    blocked = []
    fingerprint = legal_fingerprint(legal)
    if not legal_ready({k: legal.get(k, '').strip() for k in LEGAL_FIELDS}):
        blocked.append('legal_identity_incomplete')
    valid_profile = (type(profile) is ExpectedLaunchProfile and profile.mode == 'production'
        and isinstance(profile.account_id, str) and re.fullmatch(r'acct_[A-Za-z0-9]{1,240}', profile.account_id)
        and all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', v)
                for v in (profile.webhook_profile_id, profile.policy_revision)))
    if not valid_profile: blocked.append('server_profile_missing_or_invalid')
    if not isinstance(approval, dict): approval = {}
    if approval.get('enabled') is not True: blocked.append('launch_disabled')
    if approval.get('registration_approved') is not True: blocked.append('registration_not_approved')
    if approval.get('legal_fingerprint') != fingerprint: blocked.append('legal_identity_changed_or_unapproved')
    try:
        verified_at = datetime.fromisoformat(approval['approved_at'].replace('Z', '+00:00'))
        expires_at = datetime.fromisoformat(approval['expires_at'].replace('Z', '+00:00'))
        if not (verified_at <= now < expires_at): raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError):
        blocked.append('approval_missing_or_expired')
    if valid_profile:
        if approval.get('account_id') != profile.account_id: blocked.append('account_context_mismatch')
        if approval.get('webhook_profile_id') != profile.webhook_profile_id: blocked.append('webhook_context_mismatch')
        if approval.get('policy_revision') != profile.policy_revision: blocked.append('policy_revision_mismatch')
    # A durable declaration is insufficient evidence of these external states.
    blocked.extend(('provider_authentication_not_integrated', 'commercial_offers_not_approved',
                    'production_workflow_not_implemented'))
    return {'ready_for_live': False, 'blockers': blocked}
