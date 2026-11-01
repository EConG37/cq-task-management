#!/usr/bin/env python3
"""Build a clean distributable skill ZIP from an explicit allowlist; exclude all user state."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

SKILL_DIRECTORY = 'cq-task-management'
PUBLIC_FILES = (
    'README.md', 'INSTALL.md', 'LICENSE', 'install.py',
    'SKILL.md', 'agents/openai.yaml', 'assets/config.example.json',
    'references/structure.md', 'references/sync.md', 'references/weekly-loop.md',
    'references/daily-review.md', 'references/onboarding.md',
    'references/todoist-access.md', 'references/script-contract.md',
    'scripts/sync_plan.py', 'scripts/review_plan.py', 'scripts/commit_state.py',
    'scripts/validate_config.py', 'scripts/init_state.py', 'scripts/setup_check.py',
    'scripts/package_release.py', 'scripts/test_task_flow.py',
    'scripts/test_onboarding.py', 'scripts/test_release.py', 'scripts/test_install.py',
)
IDENTIFIER = re.compile(r'\b(?:rec[A-Za-z0-9]{10,}|tbl[A-Za-z0-9]{8,}|fld[A-Za-z0-9]{6,}|ou_[a-z0-9]{20,}|6h[A-Za-z0-9]{12,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b')
EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
PRIVATE_KEYS = {'base_token', 'user_id', 'user_name', 'username', 'email', 'scope',
                'project_id', 'inbox_id', 'calendar_id', 'okr_owner_id', 'okr_cycle_id',
                'access_token', 'refresh_token', 'api_key', 'api_token', 'app_secret'}


def sensitive_terms(source):
    terms = set()
    def visit(value, key=''):
        if isinstance(value, dict):
            for name, child in value.items():
                terms.update(IDENTIFIER.findall(name))
                visit(child, name)
        elif isinstance(value, list):
            for child in value: visit(child, key)
        elif isinstance(value, str):
            if key.lower() in PRIVATE_KEYS and value.strip(): terms.add(value)
            terms.update(IDENTIFIER.findall(value))
            terms.update(EMAIL.findall(value))
    # These directories are inspected for a leak denylist, never bundled.
    for location in ('state', 'profiles'):
        folder = source / location
        if not folder.exists(): continue
        for path in folder.rglob('*.json'):
            if path.is_symlink(): raise ValueError('refuse redirected user state')
            visit(json.loads(path.read_text(encoding='utf-8-sig')))
    return terms


def validate_example(config):
    feishu, todo = config.get('feishu', {}), config.get('todoist', {})
    if config.get('configured') is not False or config.get('scope') is not None:
        raise ValueError('release example must be unconfigured with no user scope')
    if feishu.get('base_token') is not None or any(v is not None for v in feishu.get('tables', {}).values()):
        raise ValueError('release example contains a working Base or table IDs')
    if any(v is not None for fields in feishu.get('fields', {}).values() for v in fields.values()):
        raise ValueError('release example contains user field IDs')
    if todo.get('user_id') is not None or todo.get('inbox_id') is not None:
        raise ValueError('release example contains a Todoist account or project')
    if any(config.get('capabilities', {}).values()):
        raise ValueError('release example cannot claim preauthorized capabilities')
    sync = config.get('sync', {})
    if sync.get('approved') is not False or sync.get('mode') != 'on_demand' or sync.get('automation_ids'):
        raise ValueError('release example cannot carry ongoing sync approval')
    if 'legacy' in config or '_notes' in config:
        raise ValueError('release example must not include personal history')
    storage = config.get('review', {}).get('storage', {})
    if storage.get('field_id') is not None or storage.get('verified') is not False:
        raise ValueError('release example must not inherit a private feedback field')


def build_release(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir() or not (source / 'SKILL.md').is_file():
        raise ValueError('source is not a skill directory')
    if output.suffix.lower() != '.zip': raise ValueError('output must be a ZIP file')
    payloads = {}
    forbidden = sensitive_terms(source)
    for name in PUBLIC_FILES:
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('public file resolves outside skill: ' + name)
        if not path.is_file(): raise ValueError('public release file missing: ' + name)
        raw = path.read_bytes()
        text = raw.decode('utf-8-sig')
        if any(term in text for term in forbidden):
            raise ValueError('personal identifier found in public file: ' + name)
        for address in EMAIL.findall(text):
            if not address.endswith(('@example.com', '@example.invalid')):
                raise ValueError('unapproved email in public file: ' + name)
        payloads[SKILL_DIRECTORY + '/' + name] = raw
    validate_example(json.loads(payloads[SKILL_DIRECTORY + '/assets/config.example.json']))
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + '.tmp-' + str(os.getpid()))
    try:
        with ZipFile(temp, 'x', ZIP_DEFLATED) as archive:
            for name, raw in payloads.items(): archive.writestr(name, raw)
        with ZipFile(temp) as archive:
            if archive.testzip() is not None: raise ValueError('ZIP checksum failed')
            if set(archive.namelist()) != set(payloads): raise ValueError('ZIP file list differs')
            for name, raw in payloads.items():
                if archive.read(name) != raw: raise ValueError('ZIP content mismatch: ' + name)
        os.replace(temp, output)
    finally:
        if temp.exists(): temp.unlink()
    return {'ok': True, 'archive': str(output), 'files': len(payloads),
            'user_state_included': False, 'private_identifier_matches': 0}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build_release(args.source, args.output), ensure_ascii=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
