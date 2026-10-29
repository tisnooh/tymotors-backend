"""Read-only launch diagnosis in a disposable SQL fixture. No provider traffic.

Approval-like values below are synthetic service declarations, never verified
company registration, Stripe ownership or permission to activate payments.
"""
import json
from urllib.error import HTTPError

from tests import commerce_pipeline_http_probe as pipeline
from tests import commerce_financial_outbox_http_probe as financial
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import eq, sql


RPC = 'select public.commerce_live_checkout_preflight($1,$2,$3) value'
CONTEXT = ['a' * 64, 'acct_SyntheticLaunchPolicy', 'synthetic-profile-v1']
one = financial.one


def protected():
    return {'data': financial.protected(), 'settings': sql('select row_to_json(s) snapshot from shop_settings s')}


def read(context=None):
    before = protected()
    result = one(RPC, CONTEXT if context is None else context)['value']
    eq(result['allowed'], False)
    eq(result['live_checkout_implemented'], False)
    eq('live_checkout_not_implemented' in result['blockers'], True)
    eq(len(result['blockers']), len(set(result['blockers'])))
    eq(set(result), {'allowed', 'live_checkout_implemented', 'configured', 'enabled', 'blockers'})
    eq(protected(), before)
    # No original identifiers, approval references or legal fingerprints leak.
    serialized = json.dumps(result)
    for private_value in (*CONTEXT, 'synthetic-approval-does-not-authorize'):
        eq(private_value in serialized, False)
    return result


def valid_declarations():
    sql("""update shop_settings set commerce_live_enabled=true,
      commerce_launch_registration_status='declared_registered',
      commerce_launch_approval_ref='synthetic-approval-does-not-authorize',
      commerce_launch_approved_at=clock_timestamp()-interval '1 hour',
      commerce_launch_approval_expires_at=clock_timestamp()+interval '1 hour',
      commerce_launch_legal_fingerprint=$1,commerce_launch_stripe_account_id=$2,
      commerce_launch_profile_ref=$3 where id""", CONTEXT)


def main():
    pipeline.main()
    start = probe.checks
    initial = read()
    eq(initial['enabled'], False)
    eq(initial['configured'], True)
    for code in ('commerce_live_disabled', 'legal_registration_pending', 'launch_approval_missing',
                 'legal_fingerprint_unconfirmed', 'stripe_account_unconfirmed', 'execution_profile_unconfirmed'):
        eq(code in initial['blockers'], True)
    missing = read([None, None, None])
    for code in ('legal_fingerprint_missing_or_invalid', 'stripe_account_missing_or_invalid',
                 'execution_profile_missing_or_invalid'):
        eq(code in missing['blockers'], True)
    eq(read(['not-a-hash', 'not-an-account', 'https://invalid.example'])['blockers'], missing['blockers'])

    for role in ('anon', 'authenticated', 'service_role'):
        eq(one("select has_function_privilege($1,'public.commerce_live_checkout_preflight(text,text,text)','EXECUTE') allowed",
               [role])['allowed'], role == 'service_role')
    eq(one("select prosecdef value from pg_proc where oid='public.commerce_live_checkout_preflight(text,text,text)'::regprocedure")['value'], False)
    before = protected()
    sql('begin read only')
    try:
        eq(one(RPC, CONTEXT)['value'], initial)
    finally:
        sql('rollback')
    eq(protected(), before)

    sql('begin')
    try:
        sql('delete from shop_settings where id')
        absent = read()
        eq(absent['configured'], False)
        eq(absent['enabled'], False)
        eq(absent['blockers'], initial['blockers'])
    finally:
        sql('rollback')
    eq(protected(), before)
    sql('begin')
    try:
        sql('revoke select on shop_settings from service_role')
        sql('set local role service_role')
        unreadable = one(RPC, CONTEXT)['value']
        eq(unreadable, absent)
    finally:
        sql('rollback')
    eq(protected(), before)

    # This flag is enabled only inside a rollback-only disposable fixture.
    sql('begin')
    try:
        valid_declarations()
        declared = read()
        eq(declared['blockers'], ['live_checkout_not_implemented'])
        eq(declared['enabled'], True)
        for mutation, expected in (
            ('commerce_live_enabled=false', 'commerce_live_disabled'),
            ("commerce_launch_registration_status='pending'", 'legal_registration_pending'),
            ('commerce_launch_approval_ref=null', 'launch_approval_missing'),
            ("commerce_launch_approved_at=clock_timestamp()+interval '10 minutes'", 'launch_approval_not_yet_valid'),
            ("commerce_launch_approved_at=clock_timestamp()-interval '2 hours',commerce_launch_approval_expires_at=clock_timestamp()-interval '1 hour'", 'launch_approval_expired'),
            ('commerce_launch_legal_fingerprint=null', 'legal_fingerprint_unconfirmed'),
            ('commerce_launch_stripe_account_id=null', 'stripe_account_unconfirmed'),
            ('commerce_launch_profile_ref=null', 'execution_profile_unconfirmed'),
        ):
            valid_declarations()
            sql('update shop_settings set ' + mutation + ' where id')
            eq(read()['blockers'], [expected, 'live_checkout_not_implemented'])
        valid_declarations()
        for index, changed, expected in (
            (0, 'b' * 64, 'legal_fingerprint_mismatch'),
            (1, 'acct_SyntheticDifferent', 'stripe_account_mismatch'),
            (2, 'synthetic-other-profile', 'execution_profile_mismatch'),
        ):
            context = list(CONTEXT)
            context[index] = changed
            eq(read(context)['blockers'], [expected, 'live_checkout_not_implemented'])
        # Simultaneous mismatches remain distinct instead of hiding each other.
        eq(read(['b' * 64, 'acct_SyntheticDifferent', 'synthetic-other-profile'])['blockers'],
           ['legal_fingerprint_mismatch', 'stripe_account_mismatch', 'execution_profile_mismatch',
            'live_checkout_not_implemented'])
    finally:
        sql('rollback')
    eq(protected(), before)

    for mutation in ("commerce_launch_registration_status='approved'", "commerce_launch_approval_ref='   '",
                     "commerce_launch_legal_fingerprint='invalid'", "commerce_launch_stripe_account_id='invalid'",
                     "commerce_launch_profile_ref='https://example.test'",
                     "commerce_launch_approved_at=now(),commerce_launch_approval_expires_at=now()-interval '1 hour'",
                     "commerce_launch_approved_at='infinity'::timestamptz",
                     "commerce_launch_approved_at='-infinity'::timestamptz",
                     "commerce_launch_approval_expires_at='infinity'::timestamptz",
                     "commerce_launch_approval_expires_at='-infinity'::timestamptz"):
        failed = False
        sql('begin')
        try:
            try:
                sql('update shop_settings set ' + mutation + ' where id')
            except HTTPError as error:
                eq(error.code, 400)
                eq('check constraint' in error.read().decode().lower(), True)
                failed = True
        finally:
            sql('rollback')
        eq(failed, True)
        eq(protected(), before)
    print(json.dumps({'launch_policy_checks': probe.checks-start, 'live_checkout_allowed': False,
                      'provider_calls': 0, 'payment_calls': 0, 'production_access': False,
                      'company_registration_verified': False, 'stripe_account_authenticated': False}))


if __name__ == '__main__':
    main()
