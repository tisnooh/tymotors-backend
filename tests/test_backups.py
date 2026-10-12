from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import pytest
from scripts.backup_database import BackupError, output_directory, run_backup, prune_backups, sha256_file


@pytest.fixture
def backup_env(monkeypatch):
    monkeypatch.setattr('scripts.backup_database.shutil.which', lambda _: 'trusted-dump-tool')
    return {'PGHOST': 'fixture.test', 'PGDATABASE': 'fixture', 'PGUSER': 'fixture', 'PGPASSWORD': 'private_fixture'}


def test_atomic_postgres_export_and_manifest(tmp_path, backup_env):
    def runner(args, **kwargs):
        assert 'private_fixture' not in str(args) and kwargs['env']['PGPASSWORD'] == 'private_fixture'
        assert kwargs['env']['PGSSLMODE'] == 'verify-full'
        assert '--schema=public' in args and '--schema=auth' in args
        Path(args[args.index('--file')+1]).write_bytes(b'PGDMP-fixture')
        return SimpleNamespace(returncode=0)
    result = run_backup('postgres', tmp_path, backup_env, runner=runner)
    assert result['bytes'] == 13 and result['pruned'] == 0
    archive = tmp_path / result['file']
    assert result['sha256'] == sha256_file(archive)
    assert json.loads(Path(str(archive)+'.json').read_text())['engine'] == 'postgres'
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('failure', ['error', 'timeout', 'empty'])
def test_failed_export_never_prunes_previous_backup(tmp_path, backup_env, failure):
    old = tmp_path / 'tymotors-postgres-20200101T000000Z-12345678.dump'
    old.write_bytes(b'last-good-backup')
    def runner(args, **_):
        if failure == 'timeout': raise subprocess.TimeoutExpired(args[0], 1)
        return SimpleNamespace(returncode=1 if failure == 'error' else 0)
    with pytest.raises(BackupError): run_backup('postgres', tmp_path, backup_env, prune=True, runner=runner)
    assert old.read_bytes() == b'last-good-backup'


def test_retention_only_exact_tool_files_not_foreign_files_or_directories(tmp_path):
    old = tmp_path / 'tymotors-postgres-20200101T000000Z-12345678.dump'
    old.write_bytes(b'old'); Path(str(old)+'.json').write_text('{}')
    (tmp_path/'important.dump').write_bytes(b'keep')
    (tmp_path/'tymotors-mongodb-20200101T000000Z-12345678.archive.gz').write_bytes(b'other engine')
    (tmp_path/'subdirectory').mkdir()
    assert prune_backups(tmp_path, 'postgres', 14, now=datetime(2026,1,1,tzinfo=timezone.utc)) == 1
    assert (tmp_path/'important.dump').exists() and (tmp_path/'subdirectory').exists()
    assert not old.exists() and not Path(str(old)+'.json').exists()


def test_zero_retention_disables_removal(tmp_path):
    assert prune_backups(tmp_path, 'postgres', 0) == 0


def test_refuses_broad_directory():
    with pytest.raises(BackupError): output_directory(str(Path.home()))


def test_mongodb_credentials_use_protected_temp_config_not_argv(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.backup_database.shutil.which', lambda _: 'trusted-mongodump')
    seen = []
    uri = 'mongodb://fixture:private_fixture@localhost/fixture'
    def runner(args, **kwargs):
        if args[0] == 'icacls': return SimpleNamespace(returncode=0)
        assert uri not in str(args) and 'MONGODB_URI' not in kwargs['env']
        config = Path(args[args.index('--config')+1]); seen.append(config)
        assert uri in config.read_text()
        Path(next(arg.removeprefix('--archive=') for arg in args if arg.startswith('--archive='))).write_bytes(b'fixture-archive')
        return SimpleNamespace(returncode=0)
    result = run_backup('mongodb', tmp_path, {'MONGODB_URI': uri, 'MONGODB_DATABASE': 'fixture'}, runner=runner)
    assert result['engine'] == 'mongodb' and not seen[0].exists()
