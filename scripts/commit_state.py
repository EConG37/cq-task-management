#!/usr/bin/env python3
"""Commit verified dual readbacks to local state with a recoverable journal. No API writes."""
import argparse
import json
import os
import sys
from pathlib import Path
from sync_plan import execution_matches, fingerprint, indexed, load_json, validate_bindings, verify_receipts
from review_plan import comment_fingerprint, comment_key

STATE_FILES = ('mappings.json', 'baselines.json', 'reviews.json')


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def commit(plan, receipts, snapshot, state_dir):
    result = verify_receipts(plan, receipts)
    if not result['ok']:
        raise ValueError('unverified operation receipts: ' + json.dumps(result['failures']))
    scope = plan.get('scope')
    if not scope or snapshot.get('scope') != scope:
        raise ValueError('post-readback scope mismatch')
    if any(snapshot.get('coverage', {}).get(k) is not True for k in ('base', 'todoist')):
        raise ValueError('both providers must be read back before state commit')
    root = Path(state_dir).resolve()
    if not root.is_dir():
        raise ValueError('state directory must already exist')
    lock = root / '.commit.lock'
    # Do not steal locks. A stale lock needs its owner/run checked before removal.
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError('another state commit owns the lock') from exc
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(str(os.getpid()))
        transaction_id = fingerprint([plan, receipts, snapshot])[:32]
        outbox = root / 'outbox'
        outbox.mkdir(exist_ok=True)
        journal_path = outbox / ('state-commit-' + transaction_id + '.json')
        if journal_path.exists():
            journal = load_json(journal_path)
            if journal.get('transaction_id') != transaction_id:
                raise ValueError('state transaction identity mismatch')
        else:
            values = {name: load_json(root / name) for name in STATE_FILES}
            hashes = plan.get('state_hashes', {})
            for name, value in values.items():
                if value.get('schema_version') != '2.0':
                    raise ValueError('state schema must be 2.0')
                if hashes.get(name) != fingerprint(value):
                    raise ValueError('state changed or initial hash missing: ' + name)
            binding = values['mappings.json']['scopes'].get(scope)
            if not isinstance(binding, dict):
                raise ValueError('scope not configured in mappings')
            mappings = binding['actions']
            for action_id, task_id in {**plan.get('recovered_mappings', {}), **result['mapping_updates']}.items():
                if action_id in mappings and mappings[action_id] != task_id:
                    raise ValueError('cannot overwrite a changed binding')
                mappings[action_id] = task_id
            validate_bindings(binding['main_tasks'], mappings)
            actions = indexed(snapshot.get('base_actions'), True)
            tasks = indexed(snapshot.get('todoist_tasks'), False)
            for op in plan.get('operations', []):
                target_id = op['target_id']
                if op['kind'] == 'todoist.create':
                    target_id = result['mapping_updates'].get(op['action_id'])
                observed = (actions if op['kind'] == 'base.update' else tasks).get(target_id)
                if observed is None or any(observed.get(k) != v for k, v in op['fields'].items()):
                    raise ValueError('final readback changed after receipt: ' + op['op_id'])
            touched = set(plan.get('action_ids', []))
            touched.update(op['action_id'] for op in plan.get('operations', []))
            touched.update(plan.get('recovered_mappings', {}))
            touched.update(item['action_id'] for item in plan.get('review_updates', {}).values())
            baselines = values['baselines.json']['scopes'].setdefault(scope, {})
            for action_id in touched:
                action = actions.get(action_id)
                if action is None:
                    raise ValueError('post-readback missing action: ' + action_id)
                task_id = mappings.get(action_id) or action.get('todoist_id')
                task = tasks.get(task_id)
                route = binding['main_tasks'].get(action.get('main_task_id'))
                if (task is None or task['status'] == 'deleted' or task['recurring'] or route is None
                        or not action['publish'] or action.get('todoist_id') != task_id
                        or action['title'] != task['title'] or not execution_matches(action, task)
                        or task.get('project_id') != route['project_id'] or task.get('parent_id') != route['todoist_id']):
                    raise ValueError('final dual snapshot is not consistent: ' + action_id)
                mappings[action_id] = task_id
                baselines[action_id] = {'base': action, 'todoist': task}
            validate_bindings(binding['main_tasks'], mappings)
            processed = values['reviews.json']['scopes'].setdefault(scope, {})
            review_updates = plan.get('review_updates', {})
            comments = {comment_key(c): c for c in snapshot.get('comments', [])}
            if review_updates and snapshot.get('coverage', {}).get('comments') is not True:
                raise ValueError('feedback commit requires source comment readback')
            for key, entry in review_updates.items():
                if key not in comments or comment_fingerprint(scope, comments[key]) != entry['fingerprint']:
                    raise ValueError('source comment changed before commit: ' + key)
                if entry['op_id'] is not None and entry['op_id'] not in result['verified']:
                    raise ValueError('comment write was not verified')
                if entry['op_id'] is None and fingerprint(actions[entry['action_id']].get('details')) != entry['expected_details_hash']:
                    raise ValueError('recovered feedback details do not match')
                processed[key] = {k: v for k, v in entry.items() if k not in ('op_id', 'expected_details_hash')}
            journal = {'transaction_id': transaction_id, 'before_hashes': hashes, 'after': values}
            atomic_json(journal_path, journal)
        # A crash between files can resume this exact transaction. Any unrelated
        # intervening state change stops the replay rather than being overwritten.
        for name in STATE_FILES:
            current = fingerprint(load_json(root / name))
            wanted = journal['after'][name]
            if current == fingerprint(wanted):
                continue
            if current != journal['before_hashes'][name]:
                raise ValueError('state changed during commit/recovery: ' + name)
            atomic_json(root / name, wanted)
        return {'ok': True, 'transaction_id': transaction_id, 'verified': result['verified']}
    finally:
        lock.unlink()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--receipts', required=True)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(commit(load_json(args.plan), load_json(args.receipts), load_json(args.snapshot), args.state_dir)))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
