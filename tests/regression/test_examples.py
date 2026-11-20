"""Regression tests of the shipped examples against compact reference values.

Run from the repository root:

    python -m unittest discover -s tests/regression

By default a test compares the reference in `examples/<example>/expected/` with a finished run
found in `examples/<example>/data_out/` and is skipped when no such run exists. Set `ENGINIITE_RUN_REGRESSION=1` to run the missing examples
first (needs a Gurobi licence; from about 4 minutes for CIGRE to about 20 minutes for
the SB72 example). Set `ENGINIITE_RESULTS_ROOT` to read the runs from another folder.

The runs may use any simulation tag among the ones listed per case. Keep the tag short,
because Windows limits a full path to 260 characters.
"""
import glob
import json
import os
import re
import subprocess
import sys
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

from make_reference import read_overall_results  # noqa: E402

EXAMPLES = os.path.join(ROOT, 'examples')
RESULTS_ROOT = os.environ.get('ENGINIITE_RESULTS_ROOT')
RUN_MISSING = os.environ.get('ENGINIITE_RUN_REGRESSION') == '1'
# (example folder, reference name, config file, simulation tags that identify a finished run; the first one is used to run it)
CASES = (
    ('cigre', 'cigre', 'config_CIGRE.yaml', ('L120',)),
    ('sb72', 'sb72', 'config_SB72.yaml', ('T1', 'BAS')),
)
RTOL = 2e-3
ATOL = 0.05


def load_reference(example, name):
    with open(os.path.join(EXAMPLES, example, 'expected', name + '.json'), encoding='utf-8') as handle:
        return json.load(handle)


def find_run(example, tags):
    """Return the results folder of a finished run that used one of the tags, or None."""
    root = RESULTS_ROOT or os.path.join(EXAMPLES, example, 'data_out')
    for tag in tags:
        for folder in glob.glob(os.path.join(root, '*_SK01_' + tag)):
            if glob.glob(os.path.join(folder, 'KPI_results_*', '*.xlsx')):
                return folder
    return None


def run_example(example, config_file, tag):
    """Run `enginiite run` on a copy of the config that only changes the simulation tag."""
    workspace = os.path.join(EXAMPLES, example)
    with open(os.path.join(workspace, 'config', config_file), encoding='utf-8') as handle:
        text = handle.read()
    text, count = re.subn(r"(?m)^(simulation_tag:\s*)(['\"]).*?\2", lambda m: m.group(1) + "'" + tag + "'", text)
    if count != 1:
        raise RuntimeError(f'Could not set simulation_tag in {config_file}')
    temp_name = '_regression_' + config_file
    temp_path = os.path.join(workspace, 'config', temp_name)
    with open(temp_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    try:
        subprocess.run([sys.executable, '-m', 'enginiite', 'run', temp_name, '--workspace', workspace], check=True)
    finally:
        os.remove(temp_path)


class ReferenceFilesTests(unittest.TestCase):
    def test_every_reference_covers_three_scenarios_with_all_values(self):
        for example, name, _, _ in CASES:
            with self.subTest(case=name):
                reference = load_reference(example, name)
                self.assertEqual(sorted(reference), ['PQ_VL01_F01', 'PQ_VL01_F02', 'PQ_VL01_F03'])
                for values in reference.values():
                    self.assertEqual(len(values), 6)

    def test_every_config_exists_and_sets_a_simulation_tag(self):
        for example, name, config_file, _ in CASES:
            with self.subTest(case=name):
                with open(os.path.join(EXAMPLES, example, 'config', config_file), encoding='utf-8') as handle:
                    self.assertIn('simulation_tag', yaml.safe_load(handle))


class ExampleRegressionTests(unittest.TestCase):
    def check_case(self, example, name, config_file, tags):
        folder = find_run(example, tags)
        if folder is None and RUN_MISSING:
            run_example(example, config_file, tags[0])
            folder = find_run(example, tags)
        if folder is None:
            self.skipTest(f'No finished run of {name} (tags {tags}); set ENGINIITE_RUN_REGRESSION=1 to run it')
        reference = load_reference(example, name)
        obtained = read_overall_results(folder)
        self.assertEqual(sorted(obtained), sorted(reference))
        for scenario, expected in reference.items():
            for value_name, expected_value in expected.items():
                with self.subTest(case=name, scenario=scenario, value=value_name):
                    self.assertAlmostEqual(
                        obtained[scenario][value_name], expected_value,
                        delta=ATOL + RTOL * abs(expected_value))

    def test_cigre(self):
        self.check_case(*CASES[0])

    def test_sb72(self):
        self.check_case(*CASES[1])


if __name__ == '__main__':
    unittest.main()
