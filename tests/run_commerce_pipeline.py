"""Own-process isolated HTTP/SQL regression runner; no hosted credentials.

Requires an explicit Node executable, existing pinned PGlite and Python deps.
Refuses occupied fixture ports instead of using an unknown database/server.
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--node',required=True)
    parser.add_argument('--wait-for-browser',action='store_true',
                        help='Keep owned loopback fixtures until Enter after a successful probe')
    parser.add_argument('--probe-module',default='tests.commerce_pipeline_http_probe',
                        choices=['tests.commerce_pipeline_http_probe','tests.commerce_multigroup_http_probe',
                                 'tests.commerce_customer_http_probe','tests.order_dispatch_http_probe',
                                 'tests.commerce_refund_http_probe'])
    args=parser.parse_args()
    for port in (8765,8766):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port))==0:
                raise RuntimeError(f'Port {port} occupied; refusing unknown fixture')
    cwd=Path(__file__).resolve().parents[1]
    env={**os.environ,'PYTHON_DOTENV_DISABLED':'1','ENVIRONMENT':'test','SUPABASE_URL':'https://example.supabase.co',
         'SUPABASE_PUBLISHABLE_KEY':'synthetic-publishable','SUPABASE_SECRET_KEY':'synthetic-service',
         'SUPABASE_SERVICE_ROLE_KEY':'synthetic-service',
         'FRONTEND_URL':'http://127.0.0.1:8765','CORS_ORIGINS':'http://127.0.0.1:8765',
         'STRIPE_MODE':'test','STRIPE_SECRET_KEY':'','EMAIL_ENABLED':'false',
         'BREVO_API_KEY':'','SMTP_PASSWORD':'','CLOUDINARY_URL':'','CLOUDINARY_API_KEY':'','CLOUDINARY_API_SECRET':''}
    processes=[]
    with tempfile.TemporaryFile(mode='w+b') as log:
        try:
            for command in ([args.node,'tests/admin_database.mjs','--serve'],
                            [sys.executable,'-m','tests.serve_admin_fixture']):
                processes.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=log))
            ready=False
            for _ in range(120):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('A disposable fixture exited before readiness')
                try:
                    req=Request('http://127.0.0.1:8766/query',method='POST',
                                data=b'{"sql":"select 1","params":[]}',headers={'Content-Type':'application/json'})
                    with urlopen(req,timeout=1): pass
                    with urlopen('http://127.0.0.1:8765/api/health',timeout=1): pass
                    ready=True;break
                except (OSError,TimeoutError): time.sleep(.25)
            if not ready: raise RuntimeError('Disposable fixture readiness timed out')
            subprocess.run([sys.executable,'-m',args.probe_module],cwd=cwd,env=env,
                           check=True,timeout=600)
            if args.wait_for_browser:
                if args.probe_module != 'tests.commerce_customer_http_probe':
                    raise RuntimeError('Browser cart preparation requires the customer probe')
                from tests.commerce_http_probe import request, sql
                line=sql("""select ci.product_id,ci.variant_id,ci.selected_vehicle from cart_items ci
                    join product_variants v on v.id=ci.variant_id
                    where v.sku like 'CUSTOMER-HTTP-SYNTHETIC-%' limit 1""")[0]
                request('/cart','POST',{**line,'quantity':1},
                        {'X-Session-Id':'delivery_browser_synthetic_guest'})
                print('Open http://127.0.0.1:8765/qa-delivery to load a synthetic guest cart (no real personal data).')
                input('Disposable FAKE fixtures ready on loopback. Press Enter to close owned processes.\n')
        except Exception:
            log.seek(0)
            print(log.read().decode(errors='replace')[-6000:],file=sys.stderr)
            raise
        finally:
            for p in reversed(processes):
                if p.poll() is None:
                    p.terminate()
                    try: p.wait(timeout=10)
                    except subprocess.TimeoutExpired: p.kill();p.wait(timeout=5)


if __name__=='__main__': main()
