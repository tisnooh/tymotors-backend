"""Disposable-only restoration of a previously recorded sandbox payment archive.

NOT a new authenticated payment event, checkout journey, refund request, or
permission to access hosted storage. No file, credential, configuration, SDK or
network access exists here. The caller owns the disposable process and supplies
its fixed-loopback SQL bridge; a Python callable cannot prove its destination.
Only six historical financial rows are imported. Catalogue/fulfillment/stock,
permissions, RLS, FKs and all other triggers remain untouched.
"""
from copy import deepcopy
from datetime import datetime
import json
import re
from uuid import UUID


class ArchiveValidationError(ValueError):
    def __init__(self):
        super().__init__('invalid_paid_sandbox_archive')


class ArchiveRestoreError(RuntimeError):
    pass


_TABLES = {
    'cart': ('carts', 'id'), 'quote': ('commerce_quotes', 'id'),
    'order': ('orders', 'id'), 'attempt': ('commerce_checkout_attempts', 'id'),
    'session': ('commerce_test_sessions', 'attempt_id'),
    'payment_event': ('commerce_test_payment_events', 'event_id'),
}
_FIELDS = {
    'carts': set('id user_id guest_session_id currency created_at updated_at'.split()),
    'commerce_quotes': set('id cart_id owner_user_id owner_guest_session country mode destination source_context payload currency subtotal_cents shipping_cents tax_cents total_cents expires_at request_key state created_at'.split()),
    'orders': set('id order_number user_id cart_id guest_session_id stripe_session_id stripe_payment_intent_id status payment_status fulfillment_status customer_email customer_name customer_phone shipping_address billing_address subtotal_cents shipping_amount_cents tax_amount_cents total_cents currency requires_compatibility_review tracking_number created_at updated_at paid_at shipped_at stock_applied_at refunded_amount_cents discount_amount_cents sales_channel delivered_at promotion_id carrier tracking_url commerce_quote_id is_test financial_review_required'.split()),
    'commerce_checkout_attempts': set('id order_id commerce_quote_id is_test currency total_cents expires_at quote_expires_at frontend_origin integration_identifier idempotency_key state params params_hash first_requested_at session_id session_url created_at updated_at'.split()),
    'commerce_test_sessions': set('attempt_id session_id created_at'.split()),
    'commerce_test_payment_events': set('event_id attempt_id event_type session_id payment_intent_id amount_cents destination_matches created_at'.split()),
}
_EMPTY_TABLES = ('commerce_quotes', 'commerce_checkout_attempts', 'commerce_test_sessions',
                 'commerce_test_payment_events', 'commerce_test_refund_events')
_TARGET_TRIGGERS = {('commerce_quotes', 'commerce_quotes_history'),
                    ('commerce_checkout_attempts', 'commerce_attempt_history')}
_REGCLASSES = ','.join("'public." + name + "'::regclass" for name, _ in _TABLES.values())


def _fail():
    raise ArchiveValidationError() from None


def _uuid(value):
    if not isinstance(value, str):
        _fail()
    try:
        parsed = UUID(value)
    except ValueError:
        _fail()
    if not parsed.int or str(parsed) != value:
        _fail()
    return value


def _identity(value, prefix):
    if not isinstance(value, str) or re.fullmatch(prefix + r'_[A-Za-z0-9_]{1,240}', value) is None:
        _fail()
    return value


def _time(value):
    if not isinstance(value, str):
        _fail()
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _fail()
    if result.tzinfo is None:
        _fail()
    return result


def _integer(value, low=0, high=3500):
    if type(value) is not int or not low <= value <= high:
        _fail()
    return value


def _one(rows, field, identity):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000 or any(not isinstance(r, dict) for r in rows):
        _fail()
    selected = [row for row in rows if row.get(field) == identity]
    if len(selected) != 1:
        _fail()
    return selected[0]


def _no_live_flags(value):
    if isinstance(value, dict):
        if 'livemode' in value and value['livemode'] is not False:
            _fail()
        for nested in value.values():
            _no_live_flags(nested)
    elif isinstance(value, list):
        for nested in value:
            _no_live_flags(nested)


def _json_safe(value):
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        _fail()


def _rows_valid(archive):
    _json_safe(archive)
    if not isinstance(archive, dict) or set(archive) != set(_TABLES):
        _fail()
    for key, (table, _) in _TABLES.items():
        row = archive[key]
        if not isinstance(row, dict) or not row or not set(row) <= _FIELDS[table]:
            _fail()
        _no_live_flags(row)
    c, q, o, a, s, p = (archive[key] for key in _TABLES)
    for row in (c, q, o, a):
        _uuid(row.get('id'))
        if row.get('currency') != 'EUR':
            _fail()
    _uuid(q.get('request_key'))
    if (c.get('user_id') is not None or o.get('user_id') is not None or q.get('owner_user_id') is not None
            or not isinstance(c.get('guest_session_id'), str) or not 16 <= len(c['guest_session_id']) <= 128
            or q.get('owner_guest_session') != c['guest_session_id']
            or o.get('guest_session_id') != c['guest_session_id']
            or q.get('cart_id') != c['id'] or o.get('cart_id') != c['id']
            or o.get('commerce_quote_id') != q['id'] or a.get('commerce_quote_id') != q['id']
            or a.get('order_id') != o['id'] or s.get('attempt_id') != a['id'] or p.get('attempt_id') != a['id']):
        _fail()
    if (o.get('is_test') is not True or a.get('is_test') is not True
            or o.get('status') != 'paid' or o.get('payment_status') != 'paid' or q.get('state') != 'consumed'
            or a.get('state') not in ('creating', 'unknown')
            or o.get('financial_review_required', False) is not False
            or _integer(o.get('refunded_amount_cents')) != 0 or o.get('promotion_id') is not None
            or _integer(o.get('discount_amount_cents')) != 0):
        _fail()
    for row in (o, q, a):
        if _integer(row.get('total_cents')) != 3500:
            _fail()
    subtotal = _integer(o.get('subtotal_cents'), 1)
    shipping = _integer(o.get('shipping_amount_cents'))
    tax = _integer(o.get('tax_amount_cents'))
    if subtotal + shipping != 3500 or (q.get('subtotal_cents'), q.get('shipping_cents'), q.get('tax_cents')) != (subtotal, shipping, tax):
        _fail()
    # Bool equality must not be accepted for any quote amount.
    for field in ('subtotal_cents', 'shipping_cents', 'tax_cents'):
        _integer(q.get(field))
    session_id = _identity(o.get('stripe_session_id'), 'cs_test')
    intent_id = _identity(o.get('stripe_payment_intent_id'), 'pi')
    _identity(p.get('event_id'), 'evt')
    if (s.get('session_id') != session_id or p.get('session_id') != session_id
            or p.get('payment_intent_id') != intent_id or a.get('session_id') is not None
            or a.get('session_url') is not None or _integer(p.get('amount_cents')) != 3500
            or p.get('destination_matches') is not True
            or p.get('event_type') not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded')):
        _fail()
    for row, fields in ((o, ('paid_at',)), (q, ('created_at', 'expires_at')),
                        (a, ('first_requested_at', 'quote_expires_at')), (s, ('created_at',)), (p, ('created_at',))):
        for field in fields:
            _time(row.get(field))
    if (_time(a['quote_expires_at']) != _time(q['expires_at']) or _time(q['expires_at']) <= _time(q['created_at'])
            or (_time(q['expires_at']) - _time(q['created_at'])).total_seconds() > 2700
            or type(a.get('expires_at')) is not int or a['expires_at'] <= 0
            or a['expires_at'] > int(_time(q['expires_at']).timestamp())):
        _fail()
    params = a.get('params')
    if (not isinstance(params, dict) or not isinstance(a.get('params_hash'), str)
            or re.fullmatch('[a-f0-9]{64}', a['params_hash']) is None
            or not isinstance(a.get('idempotency_key'), str) or not 16 <= len(a['idempotency_key']) <= 200
            or not isinstance(a.get('integration_identifier'), str) or not a['integration_identifier']
            or params.get('metadata') != {'order_id': o['id'], 'quote_id': q['id'], 'attempt_id': a['id']}
            or params.get('client_reference_id') != o['id'] or params.get('mode') != 'payment'
            or params.get('expires_at') != a['expires_at']):
        _fail()
    source = q.get('source_context')
    payload = q.get('payload')
    if (not isinstance(source, dict) or source.get('cart') != c or not isinstance(payload, dict)
            or payload.get('currency') != 'EUR' or not isinstance(payload.get('groups'), list)
            or len(payload['groups']) != 1):
        _fail()
    group = payload['groups'][0]
    if not isinstance(group, dict) or not isinstance(group.get('lines'), list) or not 1 <= len(group['lines']) <= 100:
        _fail()
    for line in group['lines']:
        if not isinstance(line, dict) or not isinstance(line.get('sku'), str) or not re.fullmatch(r'SANDBOX-SYNTHETIC-[A-Za-z0-9_-]{1,80}', line['sku']):
            _fail()


def validate_paid_archive(report, snapshot):
    """Select/deep-copy six exact rows. Old receipt flags are not new signature proof."""
    if not isinstance(report, dict) or not isinstance(snapshot, dict):
        _fail()
    _json_safe(report)
    _json_safe(snapshot)
    if 'commerce_test_refund_events' in snapshot and snapshot['commerce_test_refund_events'] != []:
        _fail()
    _no_live_flags(report)
    if (any(report.get(field) is not True for field in
            ('is_test', 'actual_stripe_test_payment', 'payment_completed', 'signed_webhook_verified'))
            or report.get('real_money_payment') is not False
            or any(type(report.get(field)) is not int or report[field] != 0 for field in
                   ('real_supplier_orders', 'commercial_products_validated'))
            or report.get('status') != 'sandbox_signed_payment_and_internal_preparation_passed'
            or report.get('currency') != 'EUR' or _integer(report.get('expected_total_cents')) != 3500):
        _fail()
    for field in ('order_id', 'quote_id', 'attempt_id', 'cart_id'):
        _uuid(report.get(field))
    _identity(report.get('session_id'), 'cs_test')
    _identity(report.get('account_id'), 'acct')
    sku = report.get('sku')
    if not isinstance(sku, str) or re.fullmatch(r'SANDBOX-SYNTHETIC-[A-Za-z0-9_-]{1,80}', sku) is None:
        _fail()
    q = _one(snapshot.get('commerce_quotes'), 'id', report['quote_id'])
    if not isinstance(q.get('source_context'), dict):
        _fail()
    archive = {
        'cart': q['source_context'].get('cart'), 'quote': q,
        'order': _one(snapshot.get('orders'), 'id', report['order_id']),
        'attempt': _one(snapshot.get('commerce_checkout_attempts'), 'id', report['attempt_id']),
        'session': _one(snapshot.get('commerce_test_sessions'), 'attempt_id', report['attempt_id']),
        'payment_event': _one(snapshot.get('commerce_test_payment_events'), 'attempt_id', report['attempt_id']),
    }
    _rows_valid(archive)
    if archive['cart']['id'] != report['cart_id'] or archive['session']['session_id'] != report['session_id']:
        _fail()
    lines = snapshot.get('commerce_order_lines')
    if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
        _fail()
    selected = [line for line in lines if line.get('order_id') == report['order_id']]
    if not 1 <= len(selected) <= 100:
        _fail()
    for line in selected:
        _uuid(line.get('id'))
        _uuid(line.get('order_item_id'))
        detail = line.get('line_snapshot')
        if (line.get('quote_id') != report['quote_id'] or not isinstance(detail, dict)
                or detail.get('sku') != sku or line.get('order_id') != archive['order']['id']):
            _fail()
    if len({line['id'] for line in selected}) != len(selected):
        _fail()
    if len(selected) != len(q['payload']['groups'][0]['lines']) or any(line['sku'] != sku for line in q['payload']['groups'][0]['lines']):
        _fail()
    return deepcopy(archive)


def _query(sql, statement, params=None):
    rows = sql(statement, params or [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ArchiveRestoreError('archive_restore_invalid_bridge_result')
    return rows


def _scalar(sql, statement, params=None, *, field='n', expected=0):
    rows = _query(sql, statement, params)
    if len(rows) != 1 or type(rows[0].get(field)) is not type(expected) or rows[0][field] != expected:
        raise ArchiveRestoreError('archive_restore_precondition_failed')


def _guards(sql):
    triggers = _query(sql, 'select c.relname as table_name,t.tgname as trigger_name,t.tgenabled as enabled,'
                      't.tgisinternal as internal from pg_catalog.pg_trigger t '
                      'join pg_catalog.pg_class c on c.oid=t.tgrelid '
                      'where c.oid in (' + _REGCLASSES + ') order by c.relname,t.tgname')
    targets = {(r.get('table_name'), r.get('trigger_name')) for r in triggers
               if r.get('enabled') == 'O' and r.get('internal') is False}
    if not _TARGET_TRIGGERS <= targets:
        raise ArchiveRestoreError('archive_restore_history_guard_missing')
    rls = _query(sql, 'select relname as table_name,relrowsecurity as rls,relforcerowsecurity as force_rls '
                 'from pg_catalog.pg_class where oid in (' + _REGCLASSES + ') order by relname')
    if len(rls) != 6 or {r.get('table_name') for r in rls} != {name for name, _ in _TABLES.values()} or any(r.get('rls') is not True for r in rls):
        raise ArchiveRestoreError('archive_restore_rls_required')
    return triggers, rls


def restore_financial_archive(sql, archive):
    """Restore exact historical rows on the caller-owned fixed-loopback bridge.

    No business RPC or new financial event is generated. The caller MUST reserve
    this single disposable connection for the whole transaction; no concurrent
    query or webhook listener may run until return. Failure rolls back imports
    and transactional ALTERs; lost COMMIT acknowledgement remains uncertain.
    """
    _rows_valid(archive)
    archive = deepcopy(archive)
    if not callable(sql):
        raise ArchiveRestoreError('archive_restore_bridge_required')
    commit_attempted = False
    try:
        _query(sql, 'BEGIN')
        _query(sql, "SET LOCAL statement_timeout='10s'")
        tables = ['products', *[name for name, _ in _TABLES.values()], 'commerce_test_refund_events']
        _query(sql, 'LOCK TABLE ' + ','.join('public.' + name for name in tables) + ' IN EXCLUSIVE MODE NOWAIT')
        _scalar(sql, "select count(*)::integer n from public.products where sku='TEST-001' and status='active'", expected=1)
        for table in _EMPTY_TABLES:
            _scalar(sql, 'select count(*)::integer n from public.' + table)
        c, o = archive['cart'], archive['order']
        _scalar(sql, 'select count(*)::integer n from public.carts where id=$1 or guest_session_id=$2',
                [c['id'], c['guest_session_id']])
        _scalar(sql, 'select count(*)::integer n from public.orders where id=$1 or commerce_quote_id=$2 '
                'or stripe_session_id=$3 or stripe_payment_intent_id=$4 or order_number=$5',
                [o['id'], o['commerce_quote_id'], o['stripe_session_id'], o['stripe_payment_intent_id'], o.get('order_number')])
        columns = _query(sql, 'select c.relname as table_name,a.attname as column_name from pg_catalog.pg_attribute a '
                         'join pg_catalog.pg_class c on c.oid=a.attrelid where c.oid in (' + _REGCLASSES + ') '
                         "and a.attnum>0 and not a.attisdropped and a.attgenerated='' order by c.relname,a.attnum")
        for key, (table, _) in _TABLES.items():
            existing = {r.get('column_name') for r in columns if r.get('table_name') == table}
            if not set(archive[key]) <= existing:
                raise ArchiveRestoreError('archive_restore_schema_mismatch')
        before = _guards(sql)
        _query(sql, 'ALTER TABLE public.commerce_quotes DISABLE TRIGGER commerce_quotes_history')
        _query(sql, 'ALTER TABLE public.commerce_checkout_attempts DISABLE TRIGGER commerce_attempt_history')
        for key, (table, _) in _TABLES.items():
            fields = sorted(archive[key])  # Already in static allowlist AND actual pg_attribute.
            names = ','.join('"' + name + '"' for name in fields)
            values = ','.join('r."' + name + '"' for name in fields)
            _query(sql, 'INSERT INTO public.' + table + '(' + names + ') SELECT ' + values +
                   ' FROM jsonb_populate_record(NULL::public.' + table + ',$1::jsonb) AS r',
                   [json.dumps(archive[key], allow_nan=False)])
        _query(sql, 'ALTER TABLE public.commerce_quotes ENABLE TRIGGER commerce_quotes_history')
        _query(sql, 'ALTER TABLE public.commerce_checkout_attempts ENABLE TRIGGER commerce_attempt_history')
        if _guards(sql) != before:
            raise ArchiveRestoreError('archive_restore_guards_changed')
        for key, (table, identity) in _TABLES.items():
            _scalar(sql, 'select (t IS NOT DISTINCT FROM jsonb_populate_record(t,$2::jsonb)) as exact '
                    'from public.' + table + ' t where "' + identity + '"=$1',
                    [archive[key][identity], json.dumps(archive[key], allow_nan=False)], field='exact', expected=True)
        _scalar(sql, "select count(*)::integer n from public.carts c join public.commerce_quotes q on q.cart_id=c.id "
                'join public.orders o on o.commerce_quote_id=q.id and o.cart_id=c.id '
                'join public.commerce_checkout_attempts a on a.order_id=o.id and a.commerce_quote_id=q.id '
                'join public.commerce_test_sessions s on s.attempt_id=a.id and s.session_id=o.stripe_session_id '
                'join public.commerce_test_payment_events p on p.attempt_id=a.id and p.session_id=s.session_id '
                'and p.payment_intent_id=o.stripe_payment_intent_id '
                "where o.id=$1 and o.is_test and a.is_test and o.currency='EUR' and q.currency='EUR' and a.currency='EUR' "
                "and o.payment_status='paid' and o.status='paid' and not o.financial_review_required and o.refunded_amount_cents=0 "
                'and o.total_cents=3500 and q.total_cents=3500 and a.total_cents=3500 and p.amount_cents=3500 '
                "and a.params_hash=encode(sha256(convert_to(a.params::text,'UTF8')),'hex')",
                [o['id']], expected=1)
        commit_attempted = True
        _query(sql, 'COMMIT')
    except Exception:
        try:
            _query(sql, 'ROLLBACK')
        except Exception:
            raise ArchiveRestoreError('archive_restore_rollback_failed') from None
        raise ArchiveRestoreError('archive_restore_commit_uncertain' if commit_attempted else 'archive_restore_failed') from None
    return {'restored_rows': 6, 'is_test': True, 'triggers_enabled': True,
            'scope': 'historical_archive_not_new_authenticated_payment'}
