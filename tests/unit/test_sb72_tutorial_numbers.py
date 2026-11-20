"""The tables of the SB72 tutorial must show the values of the example.

The cost table is compared with the reference file of the example, which is versioned. The other tables are
compared with a finished run, when its results are in `examples/sb72/data_out/` or in the folder named by the
environment variable `ENGINIITE_RESULTS_ROOT`, and their tests are skipped otherwise.
"""
import glob
import json
import os
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = ROOT / 'docs' / 'tutorial' / 'sb72-snapshots.md'
EXAMPLE = ROOT / 'examples' / 'sb72'
TAGS = ('T1', 'BAS')
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


def number(text):
    return float(text.replace(',', ''))


def run_folder():
    for tag in TAGS:
        root = os.environ.get('ENGINIITE_RESULTS_ROOT') or str(EXAMPLE / 'data_out')
        for folder in glob.glob(os.path.join(root, '*_SK01_' + tag)):
            if glob.glob(os.path.join(folder, 'KPI_results_*', '*.xlsx')):
                return folder
    return None


class CostTableTests(unittest.TestCase):
    def test_the_cost_table_matches_the_reference_file(self):
        rows = table('| Scenario | Objective (EUR)')
        self.assertEqual(len(rows), 3)
        expected = json.loads((EXAMPLE / 'expected' / 'sb72.json').read_text(encoding='utf-8'))
        for row in rows:
            values = expected['PQ_VL01_' + row[0]]
            settlement = values['active_power_cost_eur'] + values['reactive_power_cost_eur']
            with self.subTest(scenario=row[0]):
                self.assertAlmostEqual(number(row[1]), values['objective_eur'], delta=0.011)
                self.assertAlmostEqual(number(row[2]), settlement, delta=0.011)
                self.assertAlmostEqual(number(row[3]), values['objective_eur'] - settlement, delta=0.02)

    def test_the_images_of_the_page_exist(self):
        import re
        text = TUTORIAL.read_text(encoding='utf-8')
        images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text)
        self.assertEqual(len(images), 3)
        for image in images:
            with self.subTest(image=image):
                self.assertTrue((TUTORIAL.parent / image).is_file())


class ResultsTablesTests(unittest.TestCase):
    """Tables that need a finished run."""

    def results(self):
        folder = run_folder()
        if folder is None:
            self.skipTest('No finished run of the SB72 example in examples/sb72/data_out or in ENGINIITE_RESULTS_ROOT')
        return folder

    def workbook(self, folder):
        path = [f for f in glob.glob(os.path.join(folder, 'KPI_results_*', '*.xlsx')) if 'VolFlex' not in f][0]
        return pd.ExcelFile(path)

    def test_the_security_table_and_the_grid_match_the_validation_files(self):
        folder = self.results()
        security = {r[0]: r for r in table('| Scenario | Secure after the main market')}
        grid = {r[0]: r for r in table('| Scenario | S1 |')}
        book = self.workbook(folder)
        volt = book.parse('AvoidVoltageViol_Results', index_col=0)
        cong = book.parse('AvoidCongestions_Results', index_col=0)
        for step in STEPS:
            path = glob.glob(os.path.join(folder, '*_PQ_VL01_%s_*' % step, 'ACMarketValidationBySnapshot.csv'))[0]
            data = pd.read_csv(path)
            marks = []
            for snapshot in range(12):
                rows = data[data.snapshot == snapshot].sort_values('iteration')
                first, last = bool(rows.iloc[0].secure), bool(rows.iloc[-1].secure)
                marks.append('S' if first else ('C' if last else '-'))
            with self.subTest(scenario=step):
                self.assertEqual(grid[step][1:], marks)
                row = security[step]
                self.assertEqual(row[1], '%d of 12' % marks.count('S'))
                self.assertEqual(row[2], '%d of 12' % (marks.count('S') + marks.count('C')))
                scenario = [s for s in volt.index if '_%s_' % step in s][0]
                self.assertEqual(int(row[3]), int(volt.loc[scenario, 'n_post_B [u]']))
                self.assertEqual(int(row[4]), int(cong.loc[scenario, 'n_post_Total [u]']))

    def test_the_activation_and_hosting_capacity_tables_match_the_workbook(self):
        folder = self.results()
        activation = {r[0]: r for r in table('| Scenario | Active power A / B / C (MW)')}
        hosting = table('| F01 (MVA) | F02 (MVA) | F03 (MVA) |')[0]
        book = self.workbook(folder)
        flex = book.parse('FlexALL', index_col=0)
        ihc = book.parse('IHC_Results', index_col=0)
        for step in STEPS:
            column = [c for c in flex.columns if '_%s_' % step in c][0]
            active = ['%.2f' % (flex.loc['DW_%s_U_total' % t, column] + flex.loc['DW_%s_D_total' % t, column]) for t in 'ABC']
            reactive = ['%.2f' % (flex.loc['DR_%s_U_total' % t, column] + flex.loc['DR_%s_D_total' % t, column]) for t in 'ABC']
            with self.subTest(scenario=step):
                row = activation[step]
                self.assertEqual(row[1], ' / '.join(active))
                self.assertEqual(row[2], ' / '.join(reactive))
                value = float(ihc.loc[[s for s in ihc.index if '_%s_' % step in s][0]].iloc[0])
                self.assertEqual(hosting[STEPS.index(step)], '%.3f' % value)


if __name__ == '__main__':
    unittest.main()
