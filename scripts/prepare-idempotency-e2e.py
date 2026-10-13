"""Compose audited PR #5 harness with this fix, without changing its tests."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys

HARNESS = '21fca42cf7dfa123020f9f5c6a794a3297c6e5d5'
ROOT = Path(__file__).resolve().parents[1]


def prepare(target):
    target = Path(target).resolve()
    if target == ROOT or target.is_relative_to(ROOT / 'apps'):
        raise ValueError('Use a separate harness checkout')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=target, text=True).strip()
    if head != HARNESS:
        raise ValueError('Audited harness commit required')
    originals = {}
    for rel in ('apps/web/e2e/workspace.spec.ts', 'apps/web/e2e/mobile.spec.ts'):
        expected = subprocess.check_output(['git', 'show', HARNESS + ':' + rel], cwd=target).replace(b'\r\n', b'\n')
        actual = (target / rel).read_bytes().replace(b'\r\n', b'\n')
        if actual != expected:
            raise ValueError('Original acceptance tests were changed')
        originals[rel] = hashlib.sha256(actual).digest()
    paths = set()
    for args in (['git','ls-files','-z'], ['git','ls-files','--others','--exclude-standard','-z']):
        paths.update(subprocess.check_output(args,cwd=ROOT).decode().split('\0'))
    for rel in paths:
        if not rel.startswith(('apps/api/', 'apps/web/src/', 'apps/shared/', 'apps/web/e2e/')):
            continue
        source, destination = (ROOT / rel).resolve(), (target / rel).resolve()
        if not source.is_relative_to(ROOT) or not destination.is_relative_to(target) or source.name.startswith('.env'):
            continue
        if rel in originals:
            raise ValueError('Fix must not contain original acceptance tests')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    probe = target / 'apps/web/e2e/probe.py'
    body = probe.read_text(encoding='utf-8')
    body = body.replace("'0002_fact_version'", "'0003_idempotency'")
    if "DELETE FROM idempotency_operations" not in body:
        if body.count("db.execute(text('DELETE FROM experience_sessions'))") != 1:
            raise ValueError('Unexpected harness reset implementation')
        body = body.replace("db.execute(text('DELETE FROM experience_sessions'))", "db.execute(text('DELETE FROM idempotency_operations'))\n            db.execute(text('DELETE FROM experience_sessions'))")
    probe.write_text(body, encoding='utf-8')
    for rel, digest in originals.items():
        if hashlib.sha256((target / rel).read_bytes().replace(b'\r\n', b'\n')).digest() != digest:
            raise ValueError('Acceptance assertions were altered')
    print('Combined isolated harness ready; original 11 acceptance tests unchanged')


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except Exception:
        raise SystemExit('Harness preparation refused/failed; no development fallback')
