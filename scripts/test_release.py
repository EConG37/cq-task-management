import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from zipfile import ZipFile
from package_release import PUBLIC_FILES, SKILL_DIRECTORY, build_release

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.task-release-test-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.source.mkdir()
        for name in PUBLIC_FILES:
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        private = self.source / 'state'
        (private / 'outbox').mkdir(parents=True)
        unique = uuid.uuid4().hex
        self.account_id = 'private-account-' + unique
        self.email = unique + '@example.invalid'
        self.base_token = 'private-base-' + unique
        self.history = 'private-history-' + unique
        (private / 'config.json').write_text(json.dumps({'user_id': self.account_id,
                                                        'email': self.email,
                                                        'base_token': self.base_token}))
        (private / 'outbox/history.json').write_text(json.dumps({'old_task': self.history}))
        (self.source / 'profiles').mkdir()
        (self.source / 'profiles/private.json').write_text(json.dumps({'scope': str(uuid.uuid4())}))
        (self.source / 'secret-notes.md').write_text('private notes')
        self.output = Path(self.temp.name) / 'public.zip'

    def test_release_contains_only_public_files_and_no_history(self):
        result = build_release(self.source, self.output)
        self.assertFalse(result['user_state_included'])
        with ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {SKILL_DIRECTORY + '/' + name for name in PUBLIC_FILES})
            text = ''.join(archive.read(name).decode('utf-8') for name in archive.namelist())
            self.assertFalse(self.account_id in text, 'Private account marker leaked')
            self.assertFalse(self.history in text, 'Private history marker leaked')
        self.assertTrue((self.source / 'state/config.json').exists())

    def test_accidental_personal_id_in_reference_blocks_packaging(self):
        path = self.source / 'references/structure.md'
        path.write_text(path.read_text(encoding='utf-8') + '\n' + self.account_id + '\n', encoding='utf-8')
        with self.assertRaises(ValueError): build_release(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_personalized_example_is_rejected(self):
        path = self.source / 'assets/config.example.json'
        config = json.loads(path.read_text(encoding='utf-8'))
        config['configured'] = True
        path.write_text(json.dumps(config))
        with self.assertRaises(ValueError): build_release(self.source, self.output)

    def test_validation_failure_does_not_replace_previous_clean_archive(self):
        build_release(self.source, self.output)
        previous = self.output.read_bytes()
        (self.source / 'SKILL.md').write_text(self.base_token)
        with self.assertRaises(ValueError): build_release(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_missing_allowlisted_file_is_not_silently_omitted(self):
        (self.source / 'references/onboarding.md').unlink()
        with self.assertRaises(ValueError): build_release(self.source, self.output)


if __name__ == '__main__':
    unittest.main()
