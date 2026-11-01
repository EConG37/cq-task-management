import copy
import json
import tempfile
import unittest
from pathlib import Path
from init_state import initialize
from setup_check import check_setup
from validate_config import validate

ROOT = Path(__file__).resolve().parents[1]


def configured():
    config = json.loads((ROOT / 'assets/config.example.json').read_text(encoding='utf-8'))
    config.update(configured=True, scope='test-scope')
    config['feishu']['base_token'] = 'test-work-base'
    config['feishu']['tables'] = {'main_tasks': 'test-main-table', 'actions': 'test-actions-table'}
    config['feishu']['fields'] = {kind: {key: kind + '-' + key for key in fields}
                                 for kind, fields in config['feishu']['fields'].items()}
    config['todoist'].update(user_id='test-owner', transport='mcp')
    for key in ('base_read', 'base_write', 'todoist_read', 'todoist_write'):
        config['capabilities'][key] = True
    config['review']['storage'].update(verified=True, field_id='feedback-field')
    return config


def evidence(config, transport='mcp'):
    return {'todoist': {'transport': transport, 'identity': {'ok': True, 'user_id': config['todoist']['user_id']},
                       'projects_read': True, 'tasks_read': True, 'comments_read': True,
                       'completion_read': True, 'write_access': 'available'},
            'feishu': {'cli_installed': True, 'identity': {'ok': True, 'open_id': 'current-user'},
                       'base_read': {'ok': True, 'base_token': config['feishu']['base_token']},
                       'schema': {'verified': True, 'main_tasks_table_id': config['feishu']['tables']['main_tasks'],
                                  'actions_table_id': config['feishu']['tables']['actions'],
                                  'required_fields_verified': True, 'feedback_field_id': 'feedback-field'},
                       'write_access': 'available'}}


class OnboardingTests(unittest.TestCase):
    def test_fresh_install_only_prompts_for_template_copy(self):
        config = json.loads((ROOT / 'assets/config.example.json').read_text(encoding='utf-8'))
        result = check_setup(config, {})
        self.assertEqual(result['guide']['step'], 1)
        self.assertEqual(result['next_steps'], ['copy_template_and_send_own_base_url'])

    def test_user_supplied_verified_template_can_be_copied(self):
        config = json.loads((ROOT / 'assets/config.example.json').read_text(encoding='utf-8'))
        config['onboarding'].update(template_url='https://example.feishu.cn/base/test-public-template',
                                    template_verified_empty=True)
        self.assertEqual(check_setup(config, {})['next_steps'], ['copy_template_and_send_own_base_url'])

    def test_copied_base_advances_to_cli_check_before_todoist(self):
        result = check_setup(configured(), {})
        self.assertEqual(result['guide']['step'], 2)
        self.assertEqual(result['next_steps'], ['check_feishu_cli_installation'])

    def test_missing_cli_stays_in_step_two_even_if_todoist_ready(self):
        config = configured(); probe = evidence(config)
        probe['feishu']['cli_installed'] = False
        result = check_setup(config, probe)
        self.assertEqual(result['next_steps'], ['install_feishu_cli'])
        self.assertFalse(result['can_publish'])

    def test_feishu_login_schema_and_write_failures_stay_in_step_two(self):
        config = configured()
        for field, value, action in (
            ('identity', {}, 'verify_or_repair_feishu_login'),
            ('base_read', {}, 'repair_base_network_auth_or_access'),
            ('schema', {}, 'read_schema_and_bind_actual_fields'),
            ('write_access', 'unknown', 'verify_base_write_authorization'),
        ):
            with self.subTest(field=field):
                probe = evidence(config); probe['feishu'][field] = value
                result = check_setup(config, probe)
                self.assertEqual(result['guide']['step'], 2)
                self.assertEqual(result['next_steps'], [action])

    def test_verified_feishu_advances_to_todoist_connection(self):
        config = configured(); probe = evidence(config)
        probe['todoist'] = {}
        result = check_setup(config, probe)
        self.assertEqual(result['guide']['step'], 3)
        self.assertEqual(result['next_steps'], ['connect_todoist_mcp_or_cli'])

    def test_schema_probe_cannot_skip_missing_local_field_bindings(self):
        config = configured(); probe = evidence(config)
        config['feishu']['fields']['actions']['title'] = None
        result = check_setup(config, probe)
        self.assertEqual(result['guide']['step'], 2)
        self.assertEqual(result['next_steps'], ['read_schema_and_bind_actual_fields'])

    def test_todoist_connection_requires_login_and_read_checks_in_order(self):
        config = configured(); probe = evidence(config)
        probe['todoist']['identity'] = {}
        self.assertEqual(check_setup(config, probe)['next_steps'], ['authorize_todoist_account'])
        probe = evidence(config); probe['todoist']['comments_read'] = False
        self.assertEqual(check_setup(config, probe)['next_steps'], ['verify_todoist_read_capabilities'])

    def test_completed_probes_require_final_local_config_then_finish(self):
        config = configured(); probe = evidence(config)
        config['configured'] = False
        self.assertEqual(check_setup(config, probe)['next_steps'], ['finalize_and_validate_local_config'])
        config['configured'] = True
        result = check_setup(config, probe)
        self.assertEqual(result['guide']['stage'], 'complete')
        self.assertEqual(result['next_steps'], [])

    def test_configured_flag_alone_does_not_prove_ready(self):
        result = check_setup(configured(), {})
        self.assertFalse(result['can_publish'])
        self.assertFalse(result['can_review_sync'])

    def test_both_mcp_and_cli_can_support_same_workflow(self):
        config = configured()
        for mode in ('mcp', 'cli'):
            result = check_setup(config, evidence(config, mode))
            self.assertEqual(result['status'], 'ready')
            self.assertFalse(result['live_write_tested'])

    def test_read_only_todoist_can_review_but_not_publish(self):
        config = configured(); probe = evidence(config)
        probe['todoist']['write_access'] = 'read_only'
        result = check_setup(config, probe)
        self.assertFalse(result['can_publish'])
        self.assertTrue(result['can_review_sync'])
        self.assertEqual(result['status'], 'read_only_or_partial')

    def test_unknown_write_scope_is_not_treated_as_permission(self):
        config = configured(); probe = evidence(config)
        probe['feishu']['write_access'] = 'unknown'
        result = check_setup(config, probe)
        self.assertFalse(result['can_publish'])
        self.assertFalse(result['can_review_sync'])

    def test_account_mismatch_preserves_author_data(self):
        config = configured(); original = copy.deepcopy(config)
        probe = evidence(config); probe['todoist']['identity']['user_id'] = 'new-user'
        result = check_setup(config, probe)
        self.assertEqual(result['status'], 'account_mismatch')
        self.assertEqual(config, original)
        self.assertFalse(result['can_publish'])

    def test_comments_capability_missing_does_not_claim_evening_review_ready(self):
        config = configured(); probe = evidence(config)
        probe['todoist']['comments_read'] = False
        result = check_setup(config, probe)
        self.assertTrue(result['can_publish'])
        self.assertFalse(result['can_review_sync'])

    def test_wrong_base_or_schema_is_not_accepted(self):
        config = configured()
        for location, key in (('base_read', 'base_token'), ('schema', 'actions_table_id')):
            probe = evidence(config); probe['feishu'][location][key] = 'different-resource'
            self.assertFalse(check_setup(config, probe)['can_publish'])

    def test_template_is_copy_entry_not_configured_work_base(self):
        config = json.loads((ROOT / 'assets/config.example.json').read_text(encoding='utf-8'))
        self.assertIsNone(config['feishu']['base_token'])
        result = check_setup(config, {})
        self.assertIn('copy_template_and_send_own_base_url', result['next_steps'])
        self.assertFalse(result['can_publish'])

    def test_new_state_is_clean_and_has_fresh_scope(self):
        with tempfile.TemporaryDirectory(prefix='.task-setup-test-', dir=Path.cwd()) as temp:
            one = initialize(Path(temp) / 'one', 'Asia/Singapore')
            two = initialize(Path(temp) / 'two', 'Asia/Singapore')
            self.assertNotEqual(one['scope'], two['scope'])
            config = json.loads((Path(temp) / 'one/config.json').read_text(encoding='utf-8'))
            self.assertEqual(validate(config), [])
            self.assertFalse(config['configured'])
            self.assertIsNone(config['todoist']['user_id'])
            self.assertNotIn('legacy', config)
            bindings = json.loads((Path(temp) / 'one/mappings.json').read_text(encoding='utf-8'))
            self.assertEqual(bindings['scopes'][one['scope']], {'main_tasks': {}, 'actions': {}})
            prefs = json.loads((Path(temp) / 'one/preferences.json').read_text(encoding='utf-8'))
            self.assertNotIn('daily_template', prefs)

    def test_shared_template_cannot_be_used_as_users_work_base(self):
        config = configured()
        from urllib.parse import urlparse
        config['feishu']['base_token'] = urlparse(config['onboarding']['template_url']).path.split('/')[2]
        result = check_setup(config, evidence(config))
        self.assertEqual(result['status'], 'template_bound_as_work_base')
        self.assertFalse(result['can_publish'])

    def test_unverified_template_is_not_presented_as_ready(self):
        config = json.loads((ROOT / 'assets/config.example.json').read_text(encoding='utf-8'))
        config['onboarding']['template_verified_empty'] = False
        result = check_setup(config, {})
        self.assertIn('create_own_blank_base_and_send_url', result['next_steps'])

    def test_existing_state_cannot_be_overwritten_by_initialization(self):
        with tempfile.TemporaryDirectory(prefix='.task-setup-test-', dir=Path.cwd()) as temp:
            path = Path(temp) / 'state'; initialize(path, 'Asia/Singapore')
            before = (path / 'config.json').read_bytes()
            with self.assertRaises(ValueError): initialize(path, 'Asia/Singapore')
            self.assertEqual((path / 'config.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
