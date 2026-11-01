#!/usr/bin/env python3
"""Install public skill files to the current user's global skills directory."""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
from package_release import PUBLIC_FILES, SKILL_DIRECTORY, validate_example


def install(skills_dir=None, source=ROOT):
    source = Path(source).resolve()
    parent = Path(skills_dir).expanduser() if skills_dir is not None else Path.home() / '.agents' / 'skills'
    parent = parent.resolve()
    target = parent / SKILL_DIRECTORY
    if os.path.lexists(target):
        raise ValueError('skill already exists; preserve its state and use INSTALL.md for updates')
    payloads = {}
    for name in PUBLIC_FILES:
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source) or not path.is_file():
            raise ValueError('missing or redirected public file: ' + name)
        payloads[name] = path.read_bytes()
    validate_example(json.loads(payloads['assets/config.example.json']))
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.cq-task-install-', dir=parent))
    try:
        for name, content in payloads.items():
            output = staging / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
        # rename refuses an intervening nonempty installation; never merge user state.
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {'ok': True, 'skill_dir': str(target), 'files': len(payloads),
            'state_initialized': False, 'next': 'read SKILL.md and references/onboarding.md'}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', help='global skills parent directory; default: ~/.agents/skills')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.skills_dir), ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
