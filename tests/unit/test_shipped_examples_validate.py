"""The configurations shipped with the examples must pass the input validator without errors.

The validator reads the real networks, profiles and provider tables of every example, so this test also catches a
validator that rejects inputs the platform accepts. It takes a few seconds per configuration.
"""
import contextlib
import importlib.util
import io
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'validate_inputs.py'
_spec = importlib.util.spec_from_file_location('validate_inputs', SCRIPT)
vi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vi)


def shipped_configurations():
    for config in sorted((ROOT / 'examples').glob('*/config/*.yaml')):
        if not config.name.startswith('_'):
            yield config.parent.parent, config


class ShippedExamplesValidateTests(unittest.TestCase):
    def test_there_are_configurations_to_check(self):
        self.assertEqual(len(list(shipped_configurations())), 2)

    def test_every_shipped_configuration_has_no_errors(self):
        for workspace, config in shipped_configurations():
            with self.subTest(configuration=config.name):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = vi.main([str(config), '--root', str(workspace)])
                errors = [line for line in output.getvalue().splitlines() if line.startswith('[ERROR')]
                self.assertEqual(errors, [])
                self.assertEqual(exit_code, 0)


if __name__ == '__main__':
    unittest.main()
