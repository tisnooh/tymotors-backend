"""Opt-in REAL Stripe sandbox + disposable SQL. Never a live-mode runner.

No secret appears in arguments/output/reports. CLI credentials remain in its
private profile; the test key and webhook secret reach only child memory/env.
An owned bounded execution waits for hosted Checkout (test card only), records
signed settlement and internal HyperSKU preparation. No supplier call exists.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from urllib.request import Request, urlopen


def load_profile(config, name, expected_account):
    profile = tomllib.loads(Path(config).read_text(encoding='utf-8'))[name]
    key = profile.get('test_mode_api_key', '')
    if (not re.fullmatch(r'(sk|rk|rkcs)_test_[A-Za-z0-9_]+', key)
            or profile.get('live_mode_api_key') or profile.get('account_id') != expected_account):
        raise ValueError('Explicit isolated test-only CLI profile/account required')
    return key


def main():
    # Support both `python -m tests.run_stripe_sandbox` and direct script entry.
    # Resolve local helpers BEFORE any remote operation, not after creation.
    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path: sys.path.insert(0, str(repository))
    from tests.commerce_http_probe import request, sql, HEADERS
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', required=True)
    parser.add_argument('--stripe-cli', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--report-directory', required=True)
    parser.add_argument('--accept-sandbox-test-only', action='store_true', required=True)
    parser.add_argument('--wait-seconds', type=int, default=1200)
    args = parser.parse_args()
    if not 60 <= args.wait_seconds <= 1800:
        raise ValueError('Bounded 60..1800 second execution required')
    cwd = Path(__file__).resolve().parents[1]
    private = Path(args.report_directory).resolve()
    if private == cwd or cwd in private.parents:
        raise ValueError('Reports must be outside the implementation repository')
    key = load_profile(args.config, args.profile, args.account)
    for port in (8765, 8766):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Fixture port occupied; refusing unknown process')
    private.mkdir(parents=True, exist_ok=True)
    report = private / 'stripe-sandbox-result.json'
    if report.exists():
        raise RuntimeError('Existing run report preserved; use a new run directory')
    stop_file = private / 'STOP'
    if stop_file.exists():
        raise RuntimeError('Emergency STOP file present')
    result = {'account_id': args.account, 'is_test': True, 'real_money_payment': False,
              'actual_stripe_test_payment': False,
              'real_supplier_orders': 0, 'commercial_products_validated': 0,
              'status': 'starting', 'signed_webhook_verified': False}

    def save():
        temporary = report.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
        temporary.replace(report)

    def save_disposable_snapshot():
        # Only this owned, freshly seeded disposable SQL instance; no hosted DB.
        # Retain immutable attempt/params/session evidence before cleanup so an
        # ambiguous provider creation is inspectable after process interruption.
        tables = ('orders','order_items','commerce_quotes','commerce_order_lines',
                  'commerce_checkout_attempts','commerce_test_sessions','commerce_test_payment_events',
                  'commerce_test_tasks','commerce_test_task_events','commerce_hypersku_mappings',
                  'commerce_hypersku_preparations')
        statement = 'select jsonb_build_object(' + ','.join(
            "'" + table + "',coalesce((select jsonb_agg(to_jsonb(t)) from public." + table + " t),'[]'::jsonb)"
            for table in tables) + ') snapshot'
        req = Request('http://127.0.0.1:8766/query', method='POST',
            data=json.dumps({'sql': statement, 'params': []}).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=15) as response:
            snapshot = json.load(response)['rows'][0]['snapshot']
        target = private / 'disposable-state.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
        temporary.replace(target)

    cli = [args.stripe_cli, '--config', str(Path(args.config).resolve()), '--project-name', args.profile]
    env = {**os.environ, 'STRIPE_API_KEY': '', 'STRIPE_SECRET_KEY': '', 'STRIPE_WEBHOOK_SECRET': '',
           'ENVIRONMENT': 'test', 'STRIPE_MODE': 'test', 'EMAIL_ENABLED': 'false',
           'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_SECRET_KEY': '',
           'SUPABASE_PUBLISHABLE_KEY': 'synthetic-publishable',
           'SUPABASE_SERVICE_ROLE_KEY': 'synthetic-service',
           'FRONTEND_URL': 'http://127.0.0.1:8765', 'SITE_URL': 'http://127.0.0.1:8765',
           'CORS_ORIGINS': 'http://127.0.0.1:8765', 'PHOENIX_STRIPE_SANDBOX_FIXTURE': 'explicit-test-only'}
    processes = []
    stage = 'webhook_secret'
    save()
    with tempfile.TemporaryFile(mode='w+b') as log:
        try:
            secret_call = subprocess.run(cli + ['listen', '--print-secret', '--skip-update'],
                env=env, capture_output=True, text=True, timeout=90)
            secrets = re.findall(r'whsec_[A-Za-z0-9_]+', secret_call.stdout)
            if secret_call.returncode or len(secrets) != 1:
                raise RuntimeError('Official sandbox webhook secret unavailable; raw output withheld')
            server_env = {**env, 'STRIPE_WEBHOOK_SECRET': secrets[0], 'STRIPE_SECRET_KEY': key}
            stage = 'fixture_startup'
            commands = [
                [args.node, 'tests/admin_database.mjs', '--serve'],
                [sys.executable, '-m', 'tests.serve_stripe_sandbox_fixture'],
                cli + ['listen', '--skip-update', '--events',
                       'checkout.session.completed,checkout.session.async_payment_succeeded',
                       '--forward-to', 'http://127.0.0.1:8765/api/stripe/webhook'],
            ]
            for index, command in enumerate(commands):
                processes.append(subprocess.Popen(command, cwd=cwd, env=server_env if index == 1 else env, stdout=log, stderr=log))
                if index == 0:
                    for _ in range(120):
                        if processes[0].poll() is not None:
                            raise RuntimeError('Owned database exited before readiness')
                        try:
                            req = Request('http://127.0.0.1:8766/query', method='POST',
                                data=b'{"sql":"select 1","params":[]}', headers={'Content-Type': 'application/json'})
                            with urlopen(req, timeout=1): pass
                            break
                        except (OSError, TimeoutError): time.sleep(.5)
                    else: raise RuntimeError('Owned disposable database readiness timed out')
            for _ in range(180):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('Owned fixture/listener exited before readiness')
                try:
                    with urlopen('http://127.0.0.1:8765/qa-stripe-sandbox-status', timeout=1) as response:
                        status = json.load(response)
                    if (status.get('fixture') != 'real_stripe_sandbox_disposable_database'
                            or status.get('is_test') is not True or status.get('provider_transport') != 'real_stripe_sdk'):
                        raise RuntimeError('Unexpected sandbox fixture identity')
                    req = Request('http://127.0.0.1:8766/query', method='POST',
                        data=b'{"sql":"select 1","params":[]}', headers={'Content-Type': 'application/json'})
                    with urlopen(req, timeout=1): pass
                    break
                except (OSError, TimeoutError):
                    time.sleep(.5)
            else:
                raise RuntimeError('Owned isolated fixture readiness timed out')
            stage = 'real_session_creation'
            if stop_file.exists():
                raise RuntimeError('Emergency STOP before remote session creation')
            preparation = subprocess.run([sys.executable, '-m', 'tests.prepare_stripe_sandbox_case'],
                cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
            if preparation.returncode:
                # Child diagnostics may include provider details: no raw dump.
                try:
                    child = json.loads(preparation.stdout)
                    result['preparation_diagnostic'] = {k: child[k] for k in
                        ('error_type', 'http_status', 'path', 'provider_diagnostic') if k in child}
                except (ValueError, TypeError): pass
                raise RuntimeError('Sandbox case preparation failed; inspect redacted fixture diagnostics')
            case = json.loads(preparation.stdout)
            result.update(case, status='awaiting_test_checkout')
            save_disposable_snapshot()
            save()
            print(json.dumps(result), flush=True)
            stage = 'signed_payment_and_internal_preparation'
            deadline = time.monotonic() + args.wait_seconds
            while time.monotonic() < deadline:
                if stop_file.exists():
                    result['status'] = 'stopped_by_emergency_file'
                    break
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('Owned fixture/listener exited during checkout')
                rows = sql('select payment_status from orders where id=$1', [case['order_id']])
                if rows[0]['payment_status'] == 'paid':
                    tasks = sql('select * from commerce_test_tasks where order_id=$1', [case['order_id']])
                    counts = sql('select count(*)::int n from orders where commerce_quote_id=$1', [case['quote_id']])
                    events = sql('select count(*)::int n from commerce_test_payment_events where attempt_id=$1', [case['attempt_id']])
                    if counts[0]['n'] != 1 or events[0]['n'] < 1:
                        raise RuntimeError('Sandbox signed payment journal or unique order missing')
                    result.update(signed_webhook_verified=True, actual_stripe_test_payment=True,
                        payment_completed=True, paid_order_count=counts[0]['n'], task_count=len(tasks))
                    if len(tasks) != 1 or tasks[0]['agent_id'] != case['agent_id']:
                        raise RuntimeError('Paid sandbox task association mismatch')
                    internal = request('/admin/commerce/hypersku/tasks/' + tasks[0]['id'] + '/prepare',
                        'POST', {'mapping_id': case['hypersku_mapping_id']}, HEADERS)
                    if internal['external_send_allowed'] or internal['expenses_authorized']:
                        raise RuntimeError('Unexpected external authorization')
                    result.update(status='sandbox_signed_payment_and_internal_preparation_passed',
                        internal_preparation_id=internal['id'], hypersku_connected=False)
                    break
                time.sleep(2)
            else:
                result['status'] = 'test_checkout_not_completed_before_deadline'
            save()
            print(json.dumps(result), flush=True)
            if result['status'] != 'sandbox_signed_payment_and_internal_preparation_passed':
                raise RuntimeError('Sandbox checkout not completed; not a passing test')
        except KeyboardInterrupt:
            result.update(status='interrupted', blocked_stage=stage)
            save()
            raise
        except Exception as error:
            if result['status'] in ('starting','awaiting_test_checkout'):
                result['status'] = 'blocked'
            result.update(blocked_stage=stage, error_type=type(error).__name__)
            save()
            # No exception/provider content or raw logs, including secret values.
            print(json.dumps(result), flush=True)
            raise RuntimeError('Isolated sandbox run failed; secrets/raw logs withheld') from None
        finally:
            try: save_disposable_snapshot()
            except Exception: pass  # Preserve the last successfully saved state.
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    main()
