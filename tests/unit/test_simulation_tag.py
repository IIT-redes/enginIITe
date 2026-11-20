"""Unit tests for the simulation tag of a run.

When a configuration file leaves `simulation_tag` empty or absent, the run derives one from the file name. Every later
step must see that same tag: the KPI step reads it from the configuration and looks for files named with it.
"""
import unittest

from enginiite import workflow


class ResolveSimulationTagTests(unittest.TestCase):
    def test_a_tag_in_the_configuration_is_kept(self):
        cfg = {'simulation_tag': 'L120'}
        self.assertEqual(workflow.resolve_simulation_tag(cfg, 'config_CIGRE_MV.yaml'), 'L120')
        self.assertEqual(cfg['simulation_tag'], 'L120')

    def test_an_empty_tag_is_derived_from_the_file_name(self):
        cfg = {'simulation_tag': ''}
        self.assertEqual(workflow.resolve_simulation_tag(cfg, 'config_CIGRE_MV.yaml'), 'CIGRE_MV')

    def test_an_absent_tag_is_derived_from_the_file_name(self):
        cfg = {}
        self.assertEqual(workflow.resolve_simulation_tag(cfg, 'config_CIGRE_MV.yaml'), 'CIGRE_MV')

    def test_a_tag_of_spaces_is_treated_as_empty(self):
        cfg = {'simulation_tag': '   '}
        self.assertEqual(workflow.resolve_simulation_tag(cfg, 'config_A.yaml'), 'A')

    def test_the_derived_tag_is_written_back_so_that_every_step_sees_it(self):
        for cfg in ({'simulation_tag': ''}, {'simulation_tag': None}, {}):
            with self.subTest(cfg=cfg):
                tag = workflow.resolve_simulation_tag(cfg, 'config_CIGRE_MV.yaml')
                self.assertEqual(cfg['simulation_tag'], tag)

    def test_a_path_to_the_file_uses_only_its_name(self):
        self.assertEqual(workflow.resolve_simulation_tag({}, 'some/folder/config_CASE.yml'), 'CASE')

    def test_a_file_name_without_the_prefix_is_used_as_it_is(self):
        self.assertEqual(workflow.resolve_simulation_tag({}, 'my_case.yaml'), 'my_case')

    def test_a_file_that_is_only_the_prefix_gets_a_fixed_tag(self):
        self.assertEqual(workflow.resolve_simulation_tag({}, 'config_.yaml'), 'NoTag')


if __name__ == '__main__':
    unittest.main()
