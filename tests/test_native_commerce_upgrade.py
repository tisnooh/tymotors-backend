"""Independent lifecycle failures only: no PostgreSQL process or network starts."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests import run_native_commerce_upgrade as runner


def wire(monkeypatch, tmp_path, *, failure=None):
    binary = tmp_path / 'vendor-bin'
    binary.mkdir()
    for name in ('initdb', 'pg_ctl', 'psql', 'pg_dump', 'pg_restore', 'createdb'):
        (binary / (name + '.exe')).touch()
    private = tmp_path / 'private'
    monkeypatch.setattr('sys.argv', ['native-upgrade', '--pg-bin', str(binary),
        '--private-root', str(private), '--port', '18877'])
    check = MagicMock()
    check.__enter__.return_value.connect_ex.return_value = 0 if failure == 'occupied' else 1
    monkeypatch.setattr(runner.socket, 'socket', lambda: check)
    observed = {'commands': [], 'snapshots': [], 'password': None}

    def invoke(command, **options):
        tool = Path(command[0]).stem
        observed['commands'].append((tool, command[1:]))
        observed['password'] = options['env']['PGPASSWORD']
        assert options['env']['PGHOST'] == '127.0.0.1'
        assert options['env']['PGPORT'] == '18877'
        if tool == 'initdb':
            cluster = Path(command[command.index('-D') + 1])
            cluster.mkdir()
            (cluster / 'PG_VERSION').write_text('17')
            if failure == 'initdb':
                return SimpleNamespace(returncode=1, stdout='', stderr='synthetic init failure')
        if tool == 'pg_ctl':
            cluster = Path(command[command.index('-D') + 1])
            pid = cluster / 'postmaster.pid'
            if command[-1] == 'start':
                assert '-h 127.0.0.1 -p 18877' in command
                pid.write_text('synthetic owned pid')
                if failure == 'start_timeout':
                    raise subprocess.TimeoutExpired(command, 1)
            elif command[-1] == 'stop':
                if failure == 'stop':
                    return SimpleNamespace(returncode=1, stdout='', stderr='synthetic stop failure')
                pid.unlink(missing_ok=True)
            elif command[-1] == 'status':
                return SimpleNamespace(returncode=0 if pid.exists() else 3, stdout='', stderr='')
        if tool == 'pg_dump' and '--file' in command:
            Path(command[command.index('--file') + 1]).write_bytes(b'synthetic archive')
        if tool == 'psql':
            if '--version' in command:
                return SimpleNamespace(returncode=0, stdout='psql (PostgreSQL) 17.11', stderr='')
            sql = options.get('input_text', options.get('input', '')) or ''
            if 'jsonb_agg' in sql:
                observed['snapshots'].append(sql)
                return SimpleNamespace(returncode=0,
                    stdout=json.dumps([{'id': 'synthetic-history', 'value': 'unchanged'}]), stderr='')
            if 'commerce_live_enabled' in sql:
                return SimpleNamespace(returncode=0, stdout='f\n', stderr='')
            if failure == 'migration' and any('20261023132803_commerce_foundation.sql' in str(x) for x in command):
                return SimpleNamespace(returncode=1, stdout='', stderr='synthetic migration failure')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def run(command, **options):
        completed = invoke(command, **options)
        # The native runner uses temporary files instead of inherited pipes.
        for field in ('stdout', 'stderr'):
            handle = options.get(field)
            if hasattr(handle, 'write'):
                handle.write(getattr(completed, field).encode('utf-8'))
                handle.flush()
        return completed

    monkeypatch.setattr(runner.subprocess, 'run', run)
    return private, observed


def result_file(private):
    files = list(private.glob('native-upgrade-*/result.json'))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding='utf-8'))


@pytest.mark.parametrize('failure', ['start_timeout', 'migration'])
def test_failure_after_start_attempt_always_stops_owned_cluster(monkeypatch, tmp_path, failure):
    private, observed = wire(monkeypatch, tmp_path, failure=failure)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        runner.main()
    _, result = result_file(private)
    assert any(tool == 'pg_ctl' and args[-1] == 'stop' for tool, args in observed['commands'])
    assert result['cluster_stopped'] is True
    assert result['status'] != 'PASS'
    assert not list(private.glob('native-upgrade-*/password.txt'))
    assert observed['password'] not in json.dumps(result)


def test_stop_failure_never_leaves_pass_result(monkeypatch, tmp_path):
    private, observed = wire(monkeypatch, tmp_path, failure='stop')
    with pytest.raises(RuntimeError):
        runner.main()
    _, result = result_file(private)
    assert result['status'] != 'PASS'
    assert result.get('cluster_stopped') is not True
    assert not list(private.glob('native-upgrade-*/password.txt'))
    assert observed['password'] not in json.dumps(result)


def test_occupied_port_refuses_before_process_or_password_creation(monkeypatch, tmp_path):
    private, observed = wire(monkeypatch, tmp_path, failure='occupied')
    with pytest.raises(RuntimeError, match='Port occupied'):
        runner.main()
    assert observed['commands'] == []
    assert not private.exists()


def test_snapshot_order_is_keyed_and_success_is_stopped(monkeypatch, tmp_path):
    private, observed = wire(monkeypatch, tmp_path)
    runner.main()
    _, result = result_file(private)
    assert result['status'] == 'PASS'
    assert result['cluster_stopped'] is True
    assert len(observed['snapshots']) == 15
    assert all('order by 1)' not in sql.lower() for sql in observed['snapshots'])
    assert all('order by' in sql.lower() for sql in observed['snapshots'])
    assert not list(private.glob('native-upgrade-*/password.txt'))
    assert observed['password'] not in json.dumps(result)
