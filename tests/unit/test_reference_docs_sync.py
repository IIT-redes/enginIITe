"""The reference pages must describe what the shipped examples use and what a run writes.

The first test needs only the repository. The others read a finished CIGRE run in `examples/cigre/data_out/`, or in
the folder named by the environment variable `ENGINIITE_RESULTS_ROOT`, whose first scenario runs a corrective market, and
are skipped when it is not there.
"""
import csv
import json
import os
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = (ROOT / 'docs' / 'reference' / 'configuration.md').read_text(encoding='utf-8')
OUTPUTS = (ROOT / 'docs' / 'reference' / 'output-files.md').read_text(encoding='utf-8')
RESULTS = Path(os.environ.get('ENGINIITE_RESULTS_ROOT') or ROOT / 'examples' / 'cigre' / 'data_out')
CASE = RESULTS / 'CIGRE_CMVC_SK01_L120' / 'CIGRE_CMVC_PQ_VL01_F01_SK01_L120'


def first_cells(text, marker):
    """The backticked names in the first column of the first table after the line that contains the marker."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if marker in line)
    table = [i for i in range(start, len(lines)) if lines[i].startswith('|')]
    rows = []
    for index in table[2:]:
        if lines[index].startswith('|') and (index == table[2] or lines[index - 1].startswith('|')):
            rows.append(lines[index])
        else:
            break
    names = []
    for row in rows:
        names += re.findall(r'`([^`]+)`', row.strip('|').split('|')[0])
    return names


class ConfigurationReferenceTests(unittest.TestCase):
    def test_every_key_of_the_shipped_configurations_is_documented(self):
        documented = set(re.findall(r'`([A-Za-z_][A-Za-z0-9_.]*)`', CONFIGURATION))
        missing = {}
        for path in sorted((ROOT / 'examples').glob('*/config/*.yaml')):
            config = yaml.safe_load(path.read_text(encoding='utf-8'))
            keys = [k for k in config if k != 'visualization']
            keys += ['network.' + k for k in config.get('network', {})]
            keys += ['network.fsp.' + k for k in (config.get('network', {}).get('fsp') or {})]
            for key in keys:
                plain = key.split('.')[-1]
                if plain not in documented and key not in documented:
                    missing.setdefault(key, path.name)
        self.assertEqual(missing, {}, 'keys of the shipped configurations that docs/reference/configuration.md never mentions')


@unittest.skipUnless(CASE.is_dir(), 'No finished run of the CIGRE example in examples/cigre/data_out or in ENGINIITE_RESULTS_ROOT')
class OutputReferenceTests(unittest.TestCase):
    FILES = ('ACMarketValidation.csv', 'ACMarketValidationBySnapshot.csv', 'ACValidationPolicy.json',
             'FinalNetSettlement.csv', 'FinalNetSettlementChecks.csv', 'SequentialActivationByStage.csv',
             'SequentialActivationChurn.csv', 'ACValidationCumulativeMarket_iteration_00.xlsx',
             'ACValidationCumulativeMarket_iteration_01.xlsx')

    def header(self, name):
        with open(CASE / name, encoding='utf-8', newline='') as handle:
            return next(csv.reader(handle))

    def test_every_documented_file_is_written_and_every_written_file_is_documented(self):
        for name in self.FILES:
            with self.subTest(file=name):
                self.assertTrue((CASE / name).is_file(), 'the reference describes a file that the run does not write')
                stem = re.sub(r'_0\d\.xlsx$', '', name)
                self.assertIn(stem, OUTPUTS, 'the run writes a file that the reference does not mention')

    def test_the_stage_folders_are_written_as_described(self):
        for folder in ('ACCorrectionStages/stage_00_initial', 'ACCorrectionStages/stage_01_corrective', 'main_market_results'):
            with self.subTest(folder=folder):
                self.assertTrue((CASE / folder).is_dir())
                self.assertIn(folder.split('/')[-1].split('_0')[0], OUTPUTS)
        for name in ('ACCorrectionStageManifest.csv', 'PilotBusOrder.csv', 'total_cm_PreMKT.xlsx', 'VM_Problems_Stats_preMKT.xlsx'):
            with self.subTest(stage_file=name):
                self.assertTrue((CASE / 'ACCorrectionStages' / 'stage_00_initial' / name).is_file())
                self.assertIn(name.split('.')[0], OUTPUTS)

    def test_the_columns_of_the_validation_file_are_exactly_the_documented_ones(self):
        documented = first_cells(OUTPUTS, 'The columns of `ACMarketValidation.csv`')
        self.assertEqual(sorted(documented), sorted(self.header('ACMarketValidation.csv')))

    def test_the_columns_of_the_snapshot_file_are_all_named_in_the_reference(self):
        text = OUTPUTS[OUTPUTS.index('The columns of `ACMarketValidationBySnapshot.csv`'):]
        paragraph = text.split('\n\n')[0]
        for column in self.header('ACMarketValidationBySnapshot.csv'):
            with self.subTest(column=column):
                if column.startswith('post_'):
                    continue  # described as "the same post figures"
                self.assertIn(column, paragraph)

    def test_the_documented_settlement_columns_exist(self):
        documented = first_cells(OUTPUTS, 'The main columns of `FinalNetSettlement.csv`')
        header = set(self.header('FinalNetSettlement.csv'))
        self.assertGreaterEqual(len(documented), 15)
        self.assertEqual(sorted(set(documented) - header), [])

    def test_the_policy_keys_are_all_named_in_the_reference(self):
        policy = json.loads((CASE / 'ACValidationPolicy.json').read_text(encoding='utf-8'))
        for key in policy:
            with self.subTest(key=key):
                self.assertIn('`%s`' % key, OUTPUTS)


if __name__ == '__main__':
    unittest.main()
