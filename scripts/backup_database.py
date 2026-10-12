"""Dated, atomic database exports. Credentials stay out of argv and output.

PostgreSQL is TYMotors' actual database; MongoDB is an optional historical mode.
Run from a protected backup operator account, not the web server process.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid


class BackupError(RuntimeError):
    pass


def output_directory(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
        raise BackupError('Backup directory must not be a symlink or junction')
    directory = candidate.resolve()
    broad = {Path(directory.anchor), Path.home().resolve(), Path.cwd().resolve(), Path(__file__).resolve().parents[1]}
    if directory in broad:
        raise BackupError('Choose a dedicated backup subdirectory, not a broad directory')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def prune_backups(directory: Path, engine: str, retention_days: int, *, now=None) -> int:
    """Remove only this tool's old, completed archives; never recurse/follow links."""
    if retention_days <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    pattern = re.compile(rf'^tymotors-{engine}-(\d{{8}}T\d{{6}}Z)-[a-f0-9]{{8}}\.(?:dump|archive\.gz)$')
    removed = 0
    for archive in directory.iterdir():
        match = pattern.fullmatch(archive.name)
        if not match or archive.is_symlink() or not archive.is_file() or archive.resolve().parent != directory:
            continue
        try:
            created = datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (now - created).total_seconds() <= retention_days * 86400:
            continue
        archive.unlink()
        manifest = archive.with_name(archive.name + '.json')
        if manifest.is_file() and not manifest.is_symlink() and manifest.resolve().parent == directory:
            manifest.unlink()
        removed += 1
    return removed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run_backup(engine: str, directory: Path, env: dict, *, prune=False, runner=subprocess.run) -> dict:
    if engine not in {'postgres', 'mongodb'}:
        raise BackupError('Unsupported database engine')
    directory = output_directory(str(directory))
    try:
        retention = int(env.get('BACKUP_RETENTION_DAYS', '14'))
        timeout = int(env.get('BACKUP_TIMEOUT_SECONDS', '1800'))
        if retention < 0 or timeout < 1: raise ValueError()
    except ValueError:
        raise BackupError('Invalid retention or timeout setting') from None
    binary = env.get('PG_DUMP_PATH' if engine == 'postgres' else 'MONGODUMP_PATH',
                     'pg_dump' if engine == 'postgres' else 'mongodump')
    executable = shutil.which(binary)
    if not executable:
        raise BackupError('Database export tool is not installed or not on PATH')
    created = datetime.now(timezone.utc)
    suffix = 'dump' if engine == 'postgres' else 'archive.gz'
    name = f'tymotors-{engine}-{created:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}.{suffix}'
    archive, partial = directory / name, directory / (name + '.partial')
    config_path = None
    child_env = dict(env)
    try:
        if engine == 'postgres':
            if not all(env.get(key) for key in ('PGHOST', 'PGDATABASE', 'PGUSER')):
                raise BackupError('PGHOST, PGDATABASE and PGUSER are required')
            if not env.get('PGPASSFILE') and not env.get('PGPASSWORD'):
                raise BackupError('Use a protected PGPASSFILE or injected PGPASSWORD')
            child_env.setdefault('PGSSLMODE', 'verify-full')
            schemas = env.get('BACKUP_PG_SCHEMAS', 'public,auth').split(',')
            if not schemas or any(not re.fullmatch(r'[a-z_][a-z0-9_]*', schema) for schema in schemas):
                raise BackupError('Invalid backup schema allowlist')
            args = [executable, '--format=custom', '--no-owner', '--no-privileges', '--no-password',
                    '--file', str(partial), *[f'--schema={schema}' for schema in schemas]]
        else:
            uri = env.get('MONGODB_URI', '')
            database = env.get('MONGODB_DATABASE', '')
            if not uri.startswith(('mongodb://', 'mongodb+srv://')) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', database):
                raise BackupError('MONGODB_URI and a valid MONGODB_DATABASE are required')
            # Mongo tools recommend --config instead of a credential in process argv.
            fd, temporary = tempfile.mkstemp(prefix='tymotors-backup-', suffix='.yaml')
            config_path = Path(temporary)
            os.close(fd)
            if os.name == 'nt':
                account = os.environ.get('USERNAME', '')
                domain = os.environ.get('USERDOMAIN', '')
                if domain: account = domain + '\\' + account
                if not account:
                    raise BackupError('Cannot restrict temporary credential file permissions')
                acl = runner(['icacls', str(config_path), '/inheritance:r', '/grant:r', f'{account}:(F)'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
                if acl.returncode:
                    raise BackupError('Cannot restrict temporary credential file permissions')
            else:
                config_path.chmod(0o600)
            config_path.write_text('uri: ' + json.dumps(uri) + '\n', encoding='utf-8')
            child_env.pop('MONGODB_URI', None)
            args = [executable, '--config', str(config_path), '--db', database,
                    f'--archive={partial}', '--gzip', '--quiet']
        try:
            result = runner(args, env=child_env, timeout=timeout, check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError):
            raise BackupError('Database export failed or timed out; no retention applied') from None
        if result.returncode or not partial.is_file() or partial.stat().st_size == 0:
            raise BackupError('Database export failed or empty; no retention applied')
        partial.chmod(0o600)
        partial.replace(archive)
        manifest = {'engine': engine, 'created_at': created.isoformat(), 'file': archive.name,
                    'bytes': archive.stat().st_size, 'sha256': sha256_file(archive), 'retention_days': retention}
        manifest_path = archive.with_name(archive.name + '.json')
        with manifest_path.open('x', encoding='utf-8') as output:
            json.dump(manifest, output, indent=2)
        removed = prune_backups(directory, engine, retention, now=created) if prune else 0
        return {**manifest, 'pruned': removed}
    finally:
        # Only exact files created by this invocation; never recursive deletion.
        if config_path is not None and config_path.exists(): config_path.unlink()
        if partial.exists(): partial.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['postgres', 'mongodb'], default='postgres')
    parser.add_argument('--directory', default=os.getenv('BACKUP_DIRECTORY', str(Path(__file__).resolve().parents[1] / 'backups')))
    parser.add_argument('--prune', action='store_true', help='Remove only expired tool-created archives after success')
    args = parser.parse_args()
    try:
        result = run_backup(args.engine, Path(args.directory), dict(os.environ), prune=args.prune)
    except (BackupError, OSError) as error:
        # Do not print underlying provider exception text or connection strings.
        print(str(error) if isinstance(error, BackupError) else 'Backup filesystem operation failed')
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
