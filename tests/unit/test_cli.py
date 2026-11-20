"""Unit tests for the command line: how `enginiite run` finds the workspace and the configuration.

A workspace is a folder with `config/`, `data_in/<network>/` and, after a run, `data_out/`.
Nothing here starts a simulation.
"""
import os
import tempfile
import unittest
from pathlib import Path

from enginiite import cli


class ResolveRunTargetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.workspace = self.root / 'case'
        (self.workspace / 'config').mkdir(parents=True)
        (self.workspace / 'config' / 'config_A.yaml').write_text('a: 1\n', encoding='utf-8')
        (self.workspace / 'config' / 'config_B.yml').write_text('b: 1\n', encoding='utf-8')
        self.elsewhere = self.root / 'elsewhere'
        self.elsewhere.mkdir()

    def resolve(self, config, workspace=None, cwd=None):
        return cli.resolve_run_target(config, workspace=workspace, cwd=cwd or self.workspace)

    def test_a_bare_name_uses_the_working_folder_as_workspace(self):
        self.assertEqual(self.resolve('config_A.yaml'), (self.workspace, 'config_A.yaml'))

    def test_the_yml_extension_is_accepted(self):
        self.assertEqual(self.resolve('config_B.yml'), (self.workspace, 'config_B.yml'))

    def test_a_bare_name_with_an_explicit_workspace(self):
        self.assertEqual(self.resolve('config_A.yaml', workspace=self.workspace, cwd=self.elsewhere),
                         (self.workspace, 'config_A.yaml'))

    def test_a_path_inside_a_config_folder_gives_the_workspace(self):
        path = self.workspace / 'config' / 'config_A.yaml'
        self.assertEqual(self.resolve(str(path), cwd=self.elsewhere), (self.workspace, 'config_A.yaml'))

    def test_a_relative_path_is_read_from_the_working_folder(self):
        self.assertEqual(self.resolve(os.path.join('case', 'config', 'config_A.yaml'), cwd=self.root),
                         (self.workspace, 'config_A.yaml'))

    def test_a_path_that_agrees_with_the_explicit_workspace_is_accepted(self):
        path = self.workspace / 'config' / 'config_A.yaml'
        self.assertEqual(self.resolve(str(path), workspace=self.workspace, cwd=self.elsewhere),
                         (self.workspace, 'config_A.yaml'))

    def test_a_path_outside_a_config_folder_is_refused_with_an_explanation(self):
        stray = self.elsewhere / 'config_A.yaml'
        stray.write_text('a: 1\n', encoding='utf-8')
        with self.assertRaises(ValueError) as caught:
            self.resolve(str(stray))
        self.assertIn('config', str(caught.exception))

    def test_a_path_that_disagrees_with_the_explicit_workspace_is_refused(self):
        other = self.root / 'other'
        (other / 'config').mkdir(parents=True)
        (other / 'config' / 'config_A.yaml').write_text('a: 1\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.resolve(str(other / 'config' / 'config_A.yaml'), workspace=self.workspace)

    def test_an_extension_other_than_yaml_is_refused(self):
        (self.workspace / 'config' / 'notes.txt').write_text('x', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.resolve('notes.txt')

    def test_a_missing_configuration_names_the_place_where_it_was_looked_for(self):
        with self.assertRaises(FileNotFoundError) as caught:
            self.resolve('config_missing.yaml')
        self.assertIn(str(self.workspace / 'config'), str(caught.exception))

    def test_a_missing_workspace_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            self.resolve('config_A.yaml', workspace=self.root / 'nowhere')


class ResolveOutputTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cwd = Path(self._tmp.name).resolve()

    def test_no_output_keeps_the_default_inside_the_workspace(self):
        self.assertIsNone(cli.resolve_output(None, cwd=self.cwd))

    def test_a_relative_output_is_read_from_the_working_folder(self):
        self.assertEqual(cli.resolve_output('short', cwd=self.cwd), self.cwd / 'short')

    def test_an_absolute_output_is_kept(self):
        target = self.cwd / 'elsewhere' / 'results'
        self.assertEqual(cli.resolve_output(str(target), cwd=self.cwd), target)

    def test_the_output_folder_does_not_need_to_exist(self):
        self.assertFalse((self.cwd / 'new').exists())
        cli.resolve_output('new', cwd=self.cwd)
        self.assertFalse((self.cwd / 'new').exists())

    def test_an_output_that_is_a_file_is_refused(self):
        (self.cwd / 'file.txt').write_text('x', encoding='utf-8')
        with self.assertRaises(ValueError):
            cli.resolve_output('file.txt', cwd=self.cwd)


class ParserTests(unittest.TestCase):
    def test_output_is_optional_and_taken_as_given(self):
        parser = cli.build_parser()
        self.assertIsNone(parser.parse_args(['run', 'c.yaml']).output)
        self.assertEqual(parser.parse_args(['run', 'c.yaml', '--output', 'R']).output, 'R')

    def test_run_takes_a_configuration_and_an_optional_workspace(self):
        args = cli.build_parser().parse_args(['run', 'config_A.yaml', '--workspace', 'somewhere'])
        self.assertEqual((args.command, args.config, args.workspace), ('run', 'config_A.yaml', 'somewhere'))

    def test_the_workspace_is_optional(self):
        self.assertIsNone(cli.build_parser().parse_args(['run', 'config_A.yaml']).workspace)

    def test_a_command_is_required(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])


if __name__ == '__main__':
    unittest.main()
