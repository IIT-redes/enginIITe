"""The tables of the CIGRE tutorial must show the values of the example.

The cost table is compared with the reference file of the example, which is versioned. The other tables are compared
with a finished run, found in `examples/cigre/data_out/` or in the folder named by the environment variable
`ENGINIITE_RESULTS_ROOT`, and their tests are skipped when there is none. If the values change, a test fails until the
page is updated.
"""
import glob
import json
import os
import re
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = ROOT / 'docs' / 'tutorial' / 'first-run.md'
EXPECTED = ROOT / 'examples' / 'cigre' / 'expected' / 'cigre.json'
RESULTS = Path(os.environ.get('ENGINIITE_RESULTS_ROOT') or ROOT / 'examples' / 'cigre' / 'data_out')
RUN = RESULTS / 'CIGRE_CMVC_SK01_L120'
STEPS = ('F01', 'F02', 'F03')


def table(header_start):
    """Rows of the first table whose header starts with the given text, as lists of cells."""
    lines = TUTORIAL.read_text(encoding='utf-8').splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header_start))
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith('|'):
            break
        rows.append([cell.strip() for cell in line.strip('|').split('|')])
    return rows


def cost_table_rows():
    """Rows of the table that starts with the header 'Scenario | Objective (EUR)'."""
    lines = TUTORIAL.read_text(encoding='utf-8').splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('| Scenario | Objective (EUR)'))
    rows = {}
    for line in lines[start + 2:]:
        if not line.startswith('|'):
            break
        cells = [c.strip() for c in line.strip('|').split('|')]
        rows[cells[0]] = cells[1:]
    return rows


def number(text):
    return float(text.replace(',', ''))


class CigreTutorialNumbersTests(unittest.TestCase):
    def setUp(self):
        self.expected = json.loads(EXPECTED.read_text(encoding='utf-8'))
        self.rows = cost_table_rows()

    def test_the_table_has_one_row_per_scenario_of_the_reference(self):
        self.assertEqual(sorted(self.rows), ['F01', 'F02', 'F03'])
        self.assertEqual(sorted(self.expected), ['PQ_VL01_F01', 'PQ_VL01_F02', 'PQ_VL01_F03'])

    def test_the_objective_and_the_costs_match_the_reference(self):
        for step, row in self.rows.items():
            reference = self.expected['PQ_VL01_' + step]
            with self.subTest(scenario=step):
                self.assertAlmostEqual(number(row[0]), reference['objective_eur'], delta=0.01)
                self.assertAlmostEqual(number(row[2]), reference['active_power_cost_eur'], delta=0.01)
                self.assertAlmostEqual(number(row[3]), reference['reactive_power_cost_eur'], delta=0.01)

    def test_the_cleared_volumes_match_the_reference(self):
        for step, row in self.rows.items():
            reference = self.expected['PQ_VL01_' + step]
            with self.subTest(scenario=step):
                self.assertAlmostEqual(number(row[4]), reference['active_power_mw'], delta=0.001)
                self.assertAlmostEqual(number(row[5]), reference['reactive_power_mvar'], delta=0.001)

    def test_the_objective_is_the_sum_of_its_parts(self):
        for step, row in self.rows.items():
            with self.subTest(scenario=step):
                parts = number(row[1]) + number(row[2]) + number(row[3])
                self.assertAlmostEqual(parts, number(row[0]), delta=0.02)

    def test_every_image_of_the_page_exists(self):
        text = TUTORIAL.read_text(encoding='utf-8')
        images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text)
        self.assertGreaterEqual(len(images), 7)
        for image in images:
            with self.subTest(image=image):
                self.assertTrue((TUTORIAL.parent / image).is_file())


@unittest.skipUnless(RUN.is_dir(), 'No finished run of the CIGRE example in examples/cigre/data_out or in ENGINIITE_RESULTS_ROOT')
class CigreResultsTablesTests(unittest.TestCase):
    """Tables that need a finished run."""

    @classmethod
    def setUpClass(cls):
        path = [f for f in glob.glob(str(RUN / 'KPI_results_*' / '*.xlsx')) if 'VolFlex' not in f][0]
        cls.book = pd.ExcelFile(path)

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def scenario(self, step):
        return 'CIGRE_CMVC_PQ_VL01_%s_SK01_L120' % step

    def test_the_verification_table_matches_the_validation_files(self):
        rows = {r[0]: r for r in table('| Scenario | Corrective markets that ran')}
        for step in STEPS:
            data = pd.read_csv(RUN / self.scenario(step) / 'ACMarketValidation.csv').sort_values('iteration')
            last = data.iloc[-1]
            row = rows[step]
            with self.subTest(scenario=step):
                self.assertEqual(int(row[1]), int(data['iteration'].max()))
                self.assertEqual(row[2], '%.4f' % last['post_min_voltage_pu'])
                self.assertEqual(row[3], '%.2f' % last['post_max_loading_percent'])
                self.assertEqual(int(row[4]), int(last['post_voltage_violation_cell_count']))

    def test_the_avoided_violations_table_matches_the_workbook(self):
        rows = {r[0]: r for r in table('| Scenario | Avoided in the standard band')}
        volt = self.book.parse('AvoidVoltageViol_Results', index_col=0)
        for step in STEPS:
            column = self.scenario(step)
            standard, total = volt.loc[column, 'AvoidVoltage_standard [u]'], volt.loc[column, 'n_pre_B [u]']
            optimization = volt.loc[column, 'AvoidVoltage_optimization [u]']
            with self.subTest(scenario=step):
                self.assertEqual(rows[step][1], '%d of %d (%.0f %%)' % (standard, total, 100.0 * standard / total))
                self.assertEqual(rows[step][2].split(' ')[0], '%d' % optimization)
                self.assertEqual(rows[step][2].split('(')[1], '%.0f %%)' % volt.loc[column, 'AvoidVoltage_optimization [%]'])

    def test_the_activation_by_type_matches_the_workbook(self):
        rows = {r[0].split(',')[0]: r for r in table('| Type | Active power F01')}
        flex = self.book.parse('FlexALL', index_col=0)
        for fsp_type in 'ABC':
            for index, kind in ((1, 'DW'), (2, 'DR')):
                values = []
                for step in STEPS:
                    column = self.scenario(step)
                    values.append('%.3f' % (flex.loc['%s_%s_U_total' % (kind, fsp_type), column]
                                            + flex.loc['%s_%s_D_total' % (kind, fsp_type), column]))
                with self.subTest(type=fsp_type, kind=kind):
                    self.assertEqual(rows[fsp_type][index], ' / '.join(values))

    def test_the_hosting_capacity_table_matches_the_workbook(self):
        rows = {r[0]: r for r in table('| Scenario | Before (MVA)')}
        pre = self.book.parse('HC_Results_pre', index_col=0)
        post = self.book.parse('HC_Results_post', index_col=0)
        increase = self.book.parse('IHC_Results', index_col=0)
        for step in STEPS:
            column = self.scenario(step)
            with self.subTest(scenario=step):
                self.assertEqual(rows[step][1], '%.3f' % pre.loc['Hosting Capacity [MVA]', column])
                self.assertEqual(rows[step][2], '%.3f' % post.loc['Hosting Capacity [MVA]', column])
                self.assertEqual(rows[step][3], '%.3f' % increase.loc[column].iloc[0])


if __name__ == '__main__':
    unittest.main()
