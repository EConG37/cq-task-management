#!/usr/bin/env python3
"""Evaluate non-secret setup evidence from real read probes. Does not call providers."""
import argparse
import json
import sys
from urllib.parse import urlparse
from sync_plan import load_json
from validate_config import validate


def onboarding_guide(config, evidence, checks, wrong_account=False):
    """Return only the next action, in copy Base -> Feishu CLI -> Todoist order."""
    def step(number, stage, action):
        return {'step': number, 'stage': stage, 'action': action}

    template = config.get('onboarding', {})
    path = urlparse(template.get('template_url') or '').path.split('/')
    template_token = path[2] if len(path) > 2 and path[1] == 'base' else None
    own_base = config.get('feishu', {}).get('base_token')
    if not isinstance(own_base, str) or not own_base.strip() or own_base == template_token:
        action = ('copy_template_and_send_own_base_url'
                  if template.get('template_url') and template.get('template_verified_empty') is True
                  else 'create_own_blank_base_and_send_url')
        return step(1, 'copy_base', action)
    cli = evidence.get('feishu', {}).get('cli_installed')
    if cli is not True:
        return step(2, 'feishu_cli', 'install_feishu_cli' if cli is False else 'check_feishu_cli_installation')
    if not checks.get('feishu_identity'):
        return step(2, 'feishu_cli', 'verify_or_repair_feishu_login')
    if not checks.get('base_read'):
        return step(2, 'feishu_cli', 'repair_base_network_auth_or_access')
    if not checks.get('schema_verified') or not checks.get('feedback_field_verified'):
        return step(2, 'feishu_cli', 'read_schema_and_bind_actual_fields')
    if not checks.get('base_write_access'):
        return step(2, 'feishu_cli', 'verify_base_write_authorization')
    if wrong_account:
        return step(3, 'todoist', 'initialize_isolated_user_profile')
    if not checks.get('todoist_transport'):
        return step(3, 'todoist', 'connect_todoist_mcp_or_cli')
    if not checks.get('todoist_identity'):
        return step(3, 'todoist', 'authorize_todoist_account')
    if not all(checks.get('todoist_' + name) for name in ('projects_read', 'tasks_read', 'comments_read', 'completion_read')):
        return step(3, 'todoist', 'verify_todoist_read_capabilities')
    if not checks.get('todoist_write_access'):
        return step(3, 'todoist', 'verify_todoist_write_authorization')
    if not checks.get('resource_config_valid'):
        return step(3, 'todoist', 'finalize_and_validate_local_config')
    return step(None, 'complete', 'start_monthly_or_weekly_planning')


def check_setup(config, evidence):
    if not isinstance(evidence, dict):
        raise ValueError('setup evidence must be an object')
    errors = validate(config)
    todo = evidence.get('todoist', {})
    feishu = evidence.get('feishu', {})
    if not isinstance(todo, dict) or not isinstance(feishu, dict):
        raise ValueError('provider evidence must be objects')
    todo_identity, base_identity = todo.get('identity', {}), feishu.get('identity', {})
    base_result, schema = feishu.get('base_read', {}), feishu.get('schema', {})
    if any(not isinstance(v, dict) for v in (todo_identity, base_identity, base_result, schema)):
        raise ValueError('identity and resource evidence must be objects')
    todo_id = todo_identity.get('user_id')
    logged_in = todo_identity.get('ok') is True and isinstance(todo_id, str) and bool(todo_id)
    bound_id = config.get('todoist', {}).get('user_id')
    wrong_account = bool(logged_in and bound_id and bound_id != todo_id)
    checks = {}
    template = config.get('onboarding', {})
    template_path = urlparse(template.get('template_url') or '').path.split('/')
    template_token = template_path[2] if len(template_path) > 2 and template_path[1] == 'base' else None
    template_bound = bool(template_token and config.get('feishu', {}).get('base_token') == template_token)
    checks['resource_config_valid'] = not errors and config.get('configured') is True
    checks['feishu_cli_installed'] = feishu.get('cli_installed') is True
    checks['todoist_identity_matches'] = not wrong_account
    checks['todoist_identity'] = logged_in
    checks['todoist_transport'] = todo.get('transport') in {'mcp', 'cli'}
    for name in ('projects_read', 'tasks_read', 'comments_read', 'completion_read'):
        checks['todoist_' + name] = todo.get(name) is True
    checks['todoist_write_access'] = todo.get('write_access') == 'available'
    checks['feishu_identity'] = base_identity.get('ok') is True and bool(base_identity.get('open_id'))
    configured_base = config.get('feishu', {}).get('base_token')
    checks['base_read'] = bool(configured_base and base_result.get('ok') is True
                               and base_result.get('base_token') == configured_base)
    tables = config.get('feishu', {}).get('tables', {})
    fields = config.get('feishu', {}).get('fields', {})
    required_fields = {
        'main_tasks': ('title', 'status', 'completed_at', 'acceptance'),
        'actions': ('title', 'status', 'publish', 'todoist_id', 'planned_for',
                    'priority', 'completed_at', 'main_task_id'),
    }
    fields_bound = isinstance(fields, dict) and all(
        isinstance(fields.get(kind), dict) and all(
            isinstance(fields[kind].get(key), str) and bool(fields[kind][key].strip()) for key in keys
        ) for kind, keys in required_fields.items()
    )
    checks['schema_verified'] = bool(schema.get('verified') is True
                                    and tables.get('main_tasks') and tables.get('actions')
                                    and schema.get('main_tasks_table_id') == tables['main_tasks']
                                    and schema.get('actions_table_id') == tables['actions']
                                    and schema.get('required_fields_verified') is True and fields_bound)
    storage = config.get('review', {}).get('storage', {})
    checks['feedback_field_verified'] = bool(storage.get('verified') is True and storage.get('field_id')
                                            and schema.get('feedback_field_id') == storage['field_id'])
    checks['base_write_access'] = feishu.get('write_access') == 'available'
    shared = not wrong_account and not template_bound and all(checks[k] for k in ('resource_config_valid', 'todoist_identity', 'todoist_transport',
                                     'todoist_projects_read', 'todoist_tasks_read', 'todoist_completion_read',
                                     'feishu_cli_installed', 'feishu_identity', 'base_read', 'schema_verified'))
    publish = shared and checks['todoist_write_access'] and checks['base_write_access']
    review = shared and checks['todoist_comments_read'] and checks['feedback_field_verified'] and checks['base_write_access']
    status = 'ready' if publish and review else ('read_only_or_partial' if shared else 'needs_setup')
    if wrong_account:
        status = 'account_mismatch'
    elif template_bound:
        status = 'template_bound_as_work_base'
    guide = onboarding_guide(config, evidence, checks, wrong_account)
    return {'status': status, 'can_plan_in_chat': True, 'can_publish': publish,
            'can_review_sync': review, 'checks': checks, 'guide': guide,
            'next_steps': [] if guide['stage'] == 'complete' else [guide['action']],
            'config_errors': errors, 'live_write_tested': evidence.get('live_write_tested') is True}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    try:
        result = check_setup(load_json(args.config), load_json(args.evidence))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
