import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from package_release import PUBLIC_FILES

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('skill_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_default_is_current_users_global_agents_directory(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Path, 'home', return_value=Path(temp)):
            result = installer.install()
            target = Path(temp) / '.agents/skills/cq-task-management'
            self.assertEqual(Path(result['skill_dir']), target)
            self.assertEqual({str(p.relative_to(target)).replace('\\', '/') for p in target.rglob('*') if p.is_file()}, set(PUBLIC_FILES))
            self.assertFalse((target / 'state').exists())
            config = json.loads((target / 'assets/config.example.json').read_text(encoding='utf-8'))
            self.assertFalse(config['configured'])
            self.assertIsNone(config['onboarding']['template_url'])

    def test_existing_state_is_preserved_when_install_is_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(installer.install(temp)['skill_dir'])
            (target / 'state').mkdir()
            private = target / 'state/config.json'
            private.write_bytes(b'private-user-state')
            with self.assertRaises(ValueError):
                installer.install(temp)
            self.assertEqual(private.read_bytes(), b'private-user-state')


if __name__ == '__main__':
    unittest.main()
