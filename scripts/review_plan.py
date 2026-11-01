#!/usr/bin/env python3
"""Plan authorized feedback writes from normalized Todoist comments; no network calls."""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from sync_plan import day, fingerprint, indexed, load_json, operation, validate_bindings


def comment_fingerprint(scope, comment):
    return fingerprint([scope, comment['task_id'], comment['id'], comment['author_id'],
                        comment['posted_at'], comment['text']])


def comment_key(comment):
    return comment['task_id'] + ':' + comment['id']


def posted(value):
    if not isinstance(value, str):
        raise ValueError('comment posted_at must be an ISO timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('comment timestamp requires timezone')
    return result


def plan_reviews(snapshot):
    scope, owner = snapshot.get('scope'), snapshot.get('todoist_user_id')
    if not isinstance(scope, str) or not scope or not isinstance(owner, str) or not owner:
        raise ValueError('scope and todoist_user_id are required')
    if any(snapshot.get('coverage', {}).get(k) is not True for k in ('base', 'todoist', 'comments')):
        raise ValueError('feedback planning requires complete Base, task and comment coverage')
    if snapshot.get('facts_synced') is not True:
        raise ValueError('read back execution facts before planning feedback writes')
    actions = indexed(snapshot.get('base_actions'), True)
    tasks = indexed(snapshot.get('todoist_tasks'), False)
    mappings = snapshot.get('action_mappings', {})
    validate_bindings(snapshot.get('main_task_bindings', {}), mappings)
    consumed = snapshot.get('processed_comments', {})
    interpretations = snapshot.get('interpretations', {})
    comments = snapshot.get('comments', [])
    authorized = snapshot.get('authorized_action_ids', [])
    if (not isinstance(consumed, dict) or not isinstance(interpretations, dict)
            or not isinstance(comments, list) or not isinstance(authorized, list)
            or any(not isinstance(a, str) or not a for a in authorized)):
        raise ValueError('invalid feedback snapshot collections')
    if any(not isinstance(v, dict) for v in consumed.values()):
        raise ValueError('processed comment entries must be objects')
    groups, notices, seen = defaultdict(list), [], set()
    for comment in comments:
        if not isinstance(comment, dict):
            raise ValueError('comments must be objects')
        for key in ('id', 'task_id', 'posted_at', 'text'):
            if not isinstance(comment.get(key), str) or not comment[key].strip():
                raise ValueError('comment ' + key + ' must be a nonempty string')
        posted(comment['posted_at'])
        key = comment_key(comment)
        if key in seen:
            raise ValueError('duplicate comment in snapshot: ' + key)
        seen.add(key)
        if comment.get('author_id') != owner:
            notices.append({'comment_key': key, 'reason': 'author_not_verified_as_owner'})
            continue
        groups[comment['task_id']].append(comment)

    operations, conflicts, updates, adjustments = [], [], {}, []
    reverse = defaultdict(list)
    for action in actions.values():
        stored = mappings.get(action['id'])
        base_id = action.get('todoist_id')
        if stored and base_id and stored != base_id:
            conflicts.append({'action_id': action['id'], 'reason': 'mapping_disagrees_with_base'})
            continue
        if stored or base_id:
            reverse[stored or base_id].append(action['id'])

    for task_id, entries in sorted(groups.items()):
        owners = reverse.get(task_id, [])
        if len(owners) != 1:
            conflicts.append({'task_id': task_id, 'reason': 'feedback_task_binding_ambiguous'})
            continue
        action_id = owners[0]
        if action_id not in authorized:
            continue
        action, task = actions[action_id], tasks.get(task_id)
        if (task is None or task['status'] == 'deleted' or task['recurring']
                or action['status'] == 'cancelled'):
            conflicts.append({'action_id': action_id, 'reason': 'feedback_task_not_safely_open_or_done'})
            continue
        if (action['status'] == 'done') != (task['status'] == 'done'):
            conflicts.append({'action_id': action_id, 'reason': 'pull_completion_facts_first'})
            continue
        entries.sort(key=lambda c: (posted(c['posted_at']), c['id']))
        fresh = [c for c in entries if consumed.get(comment_key(c), {}).get('fingerprint')
                 != comment_fingerprint(scope, c)]
        if not fresh:
            continue
        if snapshot.get('feedback_field_verified') is not True or not isinstance(action.get('details'), str):
            conflicts.append({'action_id': action_id, 'reason': 'verified_text_field_and_original_details_required'})
            continue
        details = action['details']
        fields, pending = {}, {}
        for comment in fresh:
            key = comment_key(comment)
            digest = comment_fingerprint(scope, comment)
            meaning = interpretations.get(key, {})
            if not isinstance(meaning, dict):
                raise ValueError('comment interpretation must be an object')
            status = meaning.get('status', 'unknown')
            if status not in {'pending', 'active', 'blocked', 'done', 'cancelled', 'unknown'}:
                raise ValueError('unsupported comment status interpretation')
            if not isinstance(meaning.get('next_action', ''), str):
                raise ValueError('next_action must be text')
            marker = '[personal-task-flow-review:' + fingerprint([scope, task_id, comment['id']])[:32] + ']'
            revision = marker + ' revision=' + digest
            if revision not in details.splitlines():
                block = ('\n\n' + revision + '\n评论ID：' + comment['id'] + '\n作者：'
                         + comment['author_id'] + '\n时间：' + comment['posted_at']
                         + '\n原文：\n' + comment['text'] + '\n状态解释：' + status
                         + '\n下一步：' + meaning.get('next_action', ''))
                details += block
            pending[key] = {'fingerprint': digest, 'action_id': action_id, 'task_id': task_id,
                            'comment_id': comment['id'], 'posted_at': comment['posted_at']}
        latest = entries[-1]
        latest_key = comment_key(latest)
        # An old comment edit must not override a newer already-consumed comment.
        if latest in fresh:
            meaning = interpretations.get(latest_key, {})
            status = meaning.get('status', 'unknown')
            if task['status'] == 'open' and status in {'pending', 'active', 'blocked'}:
                if action['status'] != status:
                    fields['status'] = status
            elif status in {'done', 'cancelled'}:
                notices.append({'action_id': action_id, 'comment_key': latest_key,
                                'reason': 'reported_completion_or_cancellation_requires_fact_or_authorization'})
            elif task['status'] == 'done' and status in {'pending', 'active', 'blocked'}:
                notices.append({'action_id': action_id, 'comment_key': latest_key,
                                'reason': 'comment_disagrees_with_completion'})
            suggested_date = meaning.get('proposed_date')
            if suggested_date is not None:
                day(suggested_date)
                adjustments.append({'action_id': action_id, 'planned_for': suggested_date,
                                    'source_comment_key': latest_key, 'requires_authorization': True})
        if details != action['details']:
            fields['details'] = details
        if fields:
            write = operation('base.update', action, fields, action_id, action)
            write['precondition']['todoist_hash'] = fingerprint(task)
            operations.append(write)
            for entry in pending.values():
                entry['op_id'] = write['op_id']
        else:
            # Recover a Base write whose local commit failed; post-readback still required.
            for entry in pending.values():
                entry['op_id'] = None
                entry['expected_details_hash'] = fingerprint(details)
        updates.update(pending)
    return {'schema_version': '2.0', 'scope': scope, 'direction': 'review',
            'operations': operations, 'conflicts': conflicts, 'notices': notices,
            'proposed_adjustments': adjustments, 'review_updates': updates,
            'state_hashes': snapshot.get('state_hashes', {})}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        result = plan_reviews(load_json(args.input))
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            from pathlib import Path
            Path(args.output).write_text(rendered + '\n', encoding='utf-8')
        else:
            print(rendered)
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
