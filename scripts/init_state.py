#!/usr/bin/env python3
"""Initialize empty user state from the example config; never overwrite existing state."""
import argparse
import copy
import json
import sys
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo


def initialize(state_dir, timezone, example=None):
    ZoneInfo(timezone)
    target = Path(state_dir).resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError('state directory is not empty; use a new user profile instead')
    example = example or Path(__file__).resolve().parents[1] / 'assets' / 'config.example.json'
    config = copy.deepcopy(json.loads(Path(example).read_text(encoding='utf-8-sig')))
    config.update(scope=str(uuid.uuid4()), timezone=timezone, configured=False)
    scope = config['scope']
    values = {'config.json': config,
              'mappings.json': {'schema_version': '2.0', 'scopes': {scope: {'main_tasks': {}, 'actions': {}}}},
              'baselines.json': {'schema_version': '2.0', 'scopes': {scope: {}}},
              'reviews.json': {'schema_version': '2.0', 'scopes': {scope: {}}},
              'preferences.json': {'architecture': {'rule': 'Agent + 飞书多维表 + Todoist'},
                                   'source': '新用户初始化；计划节奏待用户描述，不继承作者偏好'}}
    target.mkdir(parents=True, exist_ok=True)
    for name, value in values.items():
        # Exclusive creation also stops an intervening setup from being overwritten.
        with (target / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return {'ok': True, 'scope': scope, 'state_dir': str(target), 'configured': False}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--timezone', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(initialize(args.state_dir, args.timezone)))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
