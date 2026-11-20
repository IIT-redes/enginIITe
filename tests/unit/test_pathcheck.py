"""Unit tests for the early warning about paths that Windows may refuse (the 260 character limit).

The longest files of a run are figures whose names repeat the scenario name. The expected lengths below are the
real longest paths of finished runs, so the estimate is checked against what the platform actually writes.
"""
import os
import tempfile
import unittest
from pathlib import Path

from enginiite import pathcheck

# Longest relative paths written by finished runs of the shipped examples, below the results folder.
SB72_LONGEST = ('SB72_CMVC_SK01_T1\\SB72_CMVC_PQ_VL01_F01_SK01_T1\\visualization\\'
                'network_technical_analytics\\voltage_congestion\\VoltageViolationHeatmap_SB72_CMVC_PQ_VL01_F01_SK01_T1.html')
CIGRE_LONGEST = ('CIGRE_CMVC_SK01_L120\\CIGRE_CMVC_PQ_VL01_F01_SK01_L120\\visualization\\'
                 'network_technical_analytics\\voltage_congestion\\VoltageViolationHeatmap_CIGRE_CMVC_PQ_VL01_F01_SK01_L120.html')


def scenario_dir(output_root, case, scenario):
    return output_root + '\\' + case + '\\' + scenario


def path_dict_for(output_root, case, scenarios):
    """The part of the dictionary of `set_paths` that the check reads."""
    res = {'PQ': {'VL01': {}}}
    for fsp, scenario in scenarios.items():
        res['PQ']['VL01'][fsp] = scenario_dir(output_root, case, scenario)
    return {'mrk_outputs': {'res_market': res}}


class LongestExpectedPathTests(unittest.TestCase):
    def test_it_reproduces_the_longest_path_of_the_sb72_run(self):
        root = 'D:\\runs\\data_out'
        expected = len(root + '\\' + SB72_LONGEST)
        self.assertEqual(pathcheck.longest_expected_path(
            scenario_dir(root, 'SB72_CMVC_SK01_T1', 'SB72_CMVC_PQ_VL01_F01_SK01_T1')), expected)

    def test_it_never_underestimates_the_longest_path_of_the_cigre_run(self):
        root = 'D:\\runs\\data_out'
        actual = len(root + '\\' + CIGRE_LONGEST)
        self.assertGreaterEqual(pathcheck.longest_expected_path(
            scenario_dir(root, 'CIGRE_CMVC_SK01_L120', 'CIGRE_CMVC_PQ_VL01_F01_SK01_L120')), actual)

    def test_a_longer_tag_makes_the_estimate_longer_once_per_place_where_it_appears(self):
        short = pathcheck.longest_expected_path(scenario_dir('C:\\o', 'N_CMVC_SK01_AB', 'N_CMVC_PQ_VL01_F01_SK01_AB'))
        long_ = pathcheck.longest_expected_path(scenario_dir('C:\\o', 'N_CMVC_SK01_ABCDE', 'N_CMVC_PQ_VL01_F01_SK01_ABCDE'))
        self.assertEqual(long_ - short, 3 * 3)  # the tag shows up in the case folder, in the scenario folder and in the file name


class CheckOutputPathsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def accepts(self, base, length):
        self.calls.append(length)
        return self.accepting

    def check(self, path_dict, accepting):
        self.accepting = accepting
        return pathcheck.check_output_paths(path_dict, accepts=self.accepts)

    def test_short_paths_pass_without_probing_the_system(self):
        paths = path_dict_for('C:\\o', 'N_CMVC_SK01_T', {'F01': 'N_CMVC_PQ_VL01_F01_SK01_T'})
        self.assertIsNone(self.check(paths, accepting=False))
        self.assertEqual(self.calls, [])

    def test_long_paths_pass_when_the_system_accepts_them(self):
        root = 'D:\\' + 'long_folder_name\\' * 8 + 'data_out'
        paths = path_dict_for(root, 'SB72_CMVC_SK01_T1', {'F01': 'SB72_CMVC_PQ_VL01_F01_SK01_T1'})
        self.assertIsNone(self.check(paths, accepting=True))
        self.assertEqual(len(self.calls), 1)

    def test_long_paths_are_reported_when_the_system_refuses_them(self):
        root = 'D:\\' + 'long_folder_name\\' * 8 + 'data_out'
        paths = path_dict_for(root, 'SB72_CMVC_SK01_T1', {'F01': 'SB72_CMVC_PQ_VL01_F01_SK01_T1'})
        message = self.check(paths, accepting=False)
        self.assertIsNotNone(message)
        for advice in ('259', 'simulation_tag', '--output'):
            self.assertIn(advice, message)

    def test_the_longest_scenario_decides(self):
        root = 'D:\\' + 'x' * 120
        paths = path_dict_for(root, 'N_CMVC_SK01_T', {'F01': 'N_CMVC_PQ_VL01_F01_SK01_T',
                                                       'F02': 'N_CMVC_PQ_VL01_F02_SK01_T_a_much_longer_name'})
        self.check(paths, accepting=True)
        longest = pathcheck.longest_expected_path(root + '\\N_CMVC_SK01_T\\N_CMVC_PQ_VL01_F02_SK01_T_a_much_longer_name')
        self.assertEqual(self.calls, [longest])


class ProbePathTests(unittest.TestCase):
    def test_the_probe_path_has_exactly_the_requested_length(self):
        probe_dir = 'C:\\some\\folder\\.path_probe'
        for length in range(len(probe_dir) + 2, len(probe_dir) + 900):
            with self.subTest(length=length):
                self.assertEqual(len(pathcheck.probe_path(probe_dir, length)), length)

    def test_no_component_of_the_probe_path_exceeds_the_limit_of_a_name(self):
        probe_dir = 'C:\\some\\folder\\.path_probe'
        for length in (300, 700, 1200):
            parts = pathcheck.probe_path(probe_dir, length)[len(probe_dir) + 1:].split('\\')
            self.assertTrue(all(0 < len(part) <= 255 for part in parts), length)


class SystemProbeTests(unittest.TestCase):
    def test_a_short_length_is_accepted_and_nothing_is_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            self.assertTrue(pathcheck.os_accepts_path_length(str(base), len(str(base)) + 40))
            self.assertEqual(os.listdir(base), [])

    @unittest.skipUnless(os.name == 'nt', 'the limit only exists on Windows')
    def test_an_over_long_path_gives_a_clean_answer_and_nothing_is_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            self.assertIn(pathcheck.os_accepts_path_length(str(base), 400), (True, False))
            self.assertEqual(os.listdir(base), [])

    @unittest.skipIf(os.name == 'nt', 'tested on the other systems only')
    def test_other_systems_always_accept(self):
        self.assertTrue(pathcheck.os_accepts_path_length('/tmp', 1000))


if __name__ == '__main__':
    unittest.main()
