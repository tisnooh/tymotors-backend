"""Opt-in owned native PostgreSQL backup/restore/upgrade; no remote credentials.

Requires verified vendor binaries. Everything runs on loopback in a new private
directory. This reconstructs migrations, not the current hosted production DB.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pg-bin', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--port', type=int, default=18877)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    binaries = Path(args.pg_bin).resolve()
    private = Path(args.private_root).resolve()
    if private == repo or repo in private.parents or not 1024 <= args.port <= 65535:
        raise ValueError('Private external directory and unprivileged port required')
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1', args.port)) == 0:
            raise RuntimeError('Port occupied; refusing unknown database')
    for tool in ('initdb', 'pg_ctl', 'psql', 'pg_dump', 'pg_restore', 'createdb'):
        if not (binaries / (tool + '.exe')).is_file():
            raise RuntimeError('Required native tool missing: ' + tool)
    private.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='native-upgrade-', dir=private))
    password = secrets.token_urlsafe(40)
    pwfile = run / 'password.txt'
    pwfile.write_text(password, encoding='ascii')
    environment = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    environment.update(PGPASSWORD=password, PGHOST='127.0.0.1', PGPORT=str(args.port),
                       PGUSER='postgres', PGDATABASE='postgres', PGCONNECT_TIMEOUT='5')
    cluster = run / 'cluster'
    start_attempted = False
    result = {'status': 'starting', 'production_writes': 0, 'actual_payments': 0,
              'source': 'reconstructed_migrations_with_synthetic_data', 'production_clone': False}

    def call(tool, *arguments, input_text=None, timeout=90):
        # Native server children can inherit pipes on Windows. Files avoid
        # communicate() waiting on a pipe kept open by the long-lived server.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            completed = subprocess.run([str(binaries / (tool + '.exe')), *map(str, arguments)],
                input=input_text, stdout=out, stderr=err,
                **({'stdin': subprocess.DEVNULL} if input_text is None else {}),
                text=True, encoding='utf-8', errors='replace', env=environment, timeout=timeout)
            out.seek(0); err.seek(0)
            output = out.read().decode('utf-8', errors='replace')
            error_output = err.read().decode('utf-8', errors='replace')
        if completed.returncode:
            # Owned fixture errors only; never print environment or password.
            message = error_output.replace(password, '[redacted]')[-2500:]
            raise RuntimeError(tool + ' failed: ' + message)
        return output

    def execute(sql, database='postgres'):
        return call('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-A', '-t', '-d', database,
                    input_text=sql)

    def snapshot(database):
        tables = ('products', 'product_images', 'orders', 'order_items', 'stripe_events')
        return {table: json.loads(execute(
            f"select coalesce(jsonb_agg(to_jsonb(t) order by t.{'event_id' if table == 'stripe_events' else 'id'}),'[]') from {table} t;", database))
            for table in tables}

    try:
        result['version'] = call('psql', '--version').strip()
        call('initdb', '-D', cluster, '-U', 'postgres', '--pwfile', pwfile,
             '--auth', 'scram-sha-256', '--encoding', 'UTF8', '--locale', 'C')
        # pg_ctl starts only this owned cluster; no Windows service or firewall change.
        start_attempted = True
        call('pg_ctl', '-D', cluster, '-l', run / 'postgres.log', '-w', '-t', '30',
             '-o', f'-h 127.0.0.1 -p {args.port}', 'start')
        execute("""create role anon; create role authenticated; create role service_role bypassrls;
          create schema auth;
          create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
          create table auth.sessions(id uuid primary key,user_id uuid,not_after timestamptz);
          create function auth.uid() returns uuid language sql stable as $$
            select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
          grant usage on schema auth to anon,authenticated,service_role;
          grant execute on function auth.uid() to anon,authenticated,service_role;""")
        migrations = sorted((repo / 'supabase/migrations').glob('*.sql'))
        boundary = '20261013063630_sandbox_catalog_orders.sql'
        old = [p for p in migrations if p.name <= boundary]
        new = [p for p in migrations if p.name > boundary]
        if not old or old[-1].name != boundary or not new:
            raise RuntimeError('Historical migration boundary missing')
        for path in old:
            call('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-f', path)
        # Use the same reviewed synthetic history as the PGlite conservation probe.
        source = (repo / 'tests/commerce_upgrade_preservation.mjs').read_text(encoding='utf-8')
        seed = re.search(r'await db\.exec\(`(insert into categories[\s\S]*?)`\);', source)
        if not seed:
            raise RuntimeError('Synthetic fixture seed missing')
        execute(seed[1])
        before = snapshot('postgres')
        archive = run / 'historical.dump'
        call('pg_dump', '--format=custom', '--file', archive)
        call('createdb', 'restored_fixture')
        call('pg_restore', '--exit-on-error', '--dbname', 'restored_fixture', archive)
        assert snapshot('restored_fixture') == before, 'Restoration changed history'
        result['backup_restore_verified'] = True
        for path in new:
            call('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-d', 'restored_fixture', '-f', path)
        after = snapshot('restored_fixture')
        fields = 0
        for table, rows in before.items():
            assert len(after[table]) == len(rows), 'History row count changed: ' + table
            keyed = {r.get('id', r.get('event_id')): r for r in after[table]}
            for row in rows:
                restored = keyed[row.get('id', row.get('event_id'))]
                for key, value in row.items():
                    assert restored[key] == value, f'History changed: {table}.{key}'
                    fields += 1
        assert execute('select commerce_live_enabled from shop_settings;', 'restored_fixture').strip() == 'f'
        result.update(status='PASS', historical_migrations=len(old), pending_migrations=len(new),
                      preserved_fields=fields, live_enabled=False)
    except BaseException as error:
        result.update(status='FAILED', error_type=type(error).__name__)
        raise
    finally:
        try:
            if start_attempted:
                status = subprocess.run([str(binaries / 'pg_ctl.exe'), '-D', str(cluster), 'status'],
                    capture_output=True, env=environment, timeout=10)
                if status.returncode == 0:
                    call('pg_ctl', '-D', cluster, '-m', 'fast', '-w', '-t', '30', 'stop')
                elif status.returncode != 3:
                    raise RuntimeError('Owned cluster status requires inspection')
                result['cluster_stopped'] = True
        except BaseException as cleanup_error:
            result.update(status='FAILED', cleanup_failed=True,
                          cleanup_error_type=type(cleanup_error).__name__)
            raise
        finally:
            pwfile.unlink(missing_ok=True)
            (run / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
