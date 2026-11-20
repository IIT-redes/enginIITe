"""Characterisation tests for small helpers of the visualization modules.

The expected titles are what the helpers returned for the names of real figures of the shipped examples. Nothing here
draws a figure, and nothing is read from the results of a run.
"""
import os
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use('Agg')

from enginiite.visualization import market_analytics, technical_accuracy  # noqa: E402

TITLES = {
    'ActivationPersistence_CIGRE_MV_CMVC_PQ_VL01_F01_SK01_L120':
        'ActivationPersistence CIGRE MV CMVC PQ VL01 F01 SK01 L120',
    'AssetSpecificHeatmaps_CM_P_ALL_SB72_CMVC_PQ_VL01_F01_SK01_MOD__corrective_market_01':
        'Monitored-Element-Specific Sensitivity Heatmaps ALL SB72 CMVC PQ VL01 F01 SK01 MOD corrective market 01',
    'BaseTopologyInteractive_CIGRE_MV_CMVC_PQ_VL01_F01_SK01_L120':
        'BaseTopologyInteractive CIGRE MV CMVC PQ VL01 F01 SK01 L120',
    'ClearedFlexibility_CIGRE_MV_CMVC_PQ_VL01_F01_SK01_L120':
        'Cleared Flexibility CIGRE MV CMVC PQ VL01 F01 SK01 L120',
    'CongestionAccuracyScatter_CIGRE_MV_CMVC_PQ_VL01_F01_SK01_L120__final_stage_local':
        'CongestionAccuracyScatter CIGRE MV CMVC PQ VL01 F01 SK01 L120 final stage local',
}


class FigureTitleTests(unittest.TestCase):
    def test_the_titles_of_real_figures_are_unchanged(self):
        for module in (market_analytics,):
            for raw, expected in TITLES.items():
                with self.subTest(module=module.__name__.split('.')[-1], figure=raw):
                    self.assertEqual(module._humanize_figure_title(raw), expected)

    def test_an_empty_title_gets_the_default_header(self):
        for module in (market_analytics,):
            with self.subTest(module=module.__name__.split('.')[-1]):
                self.assertEqual(module._humanize_figure_title(''), 'Network and Market Visualization')

    def test_the_module_has_one_definition_of_the_title_helper(self):
        for module in (market_analytics,):
            source = Path(module.__file__).read_text(encoding='utf-8')
            with self.subTest(module=module.__name__.split('.')[-1]):
                self.assertEqual(source.count('def _humanize_figure_title('), 1)


class SearchPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_the_sensitivity_folder_is_found_from_the_scenario_folder_or_from_any_folder_below_it(self):
        matrices = self.root / 'market_inputs' / 'h24SensitivityMatrixes'
        matrices.mkdir(parents=True)
        deep = self.root / 'data_out' / 'case' / 'scenario'
        deep.mkdir(parents=True)
        for start in (self.root, self.root / 'data_out', deep):
            with self.subTest(start=str(start.relative_to(self.root))):
                found = market_analytics._resolve_sensitivity_root_for_cm(None, str(start))
                self.assertEqual(os.path.normcase(found), os.path.normcase(str(matrices)))

    def test_nothing_is_found_when_the_folder_does_not_exist(self):
        self.assertIsNone(market_analytics._resolve_sensitivity_root_for_cm(None, str(self.root)))

    def test_a_folder_named_after_a_network_is_not_searched_for_a_sensitivity_folder(self):
        (self.root / 'some_network' / 'market_inputs' / 'h24SensitivityMatrixes').mkdir(parents=True)
        self.assertIsNone(market_analytics._resolve_sensitivity_root_for_cm(None, str(self.root)))

    def test_the_given_sensitivity_folder_wins(self):
        given = self.root / 'given'
        given.mkdir()
        self.assertEqual(market_analytics._resolve_sensitivity_root_for_cm(str(given), None), str(given))

    def test_the_network_workbook_for_the_physical_diagnostics_must_be_passed_explicitly(self):
        workbook = self.root / 'network' / 'network.xlsx'
        workbook.parent.mkdir()
        workbook.write_bytes(b'x')
        for finder, first in ((market_analytics._ma_find_network_file_for_asset_loading, 'sens_matrix_root'),
                              (technical_accuracy._sv_find_network_file_for_asset_loading, 'sensitivity_root')):
            with self.subTest(finder=finder.__name__):
                self.assertIsNone(finder(**{first: str(self.root)}, scenario_root=str(self.root)))
                self.assertEqual(finder(network_file=str(workbook)), str(workbook))
                self.assertIsNone(finder(network_file=str(self.root / 'missing.xlsx')))

    def test_scenarios_are_not_guessed_from_a_folder_pattern_of_one_case(self):
        folder = self.root / 'bundle'
        (folder / 'anything_CMVC_PQ_VL01_F01_SK01_T1').mkdir(parents=True)
        self.assertEqual(technical_accuracy._tech_acc_discover_scenario_roots_v11(str(folder), None, None), [])
        explicit = technical_accuracy._tech_acc_discover_scenario_roots_v11(str(folder), None, [str(folder / 'a')])
        self.assertEqual(explicit, [os.path.abspath(str(folder / 'a'))])



if __name__ == '__main__':
    unittest.main()
