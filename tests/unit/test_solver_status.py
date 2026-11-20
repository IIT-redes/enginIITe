"""Unit tests for the names of the solver statuses.

Gurobi 12 removed `gp.StatusConstClass`, which the market step used to turn a status code into its name. These tests
keep the code working with the version 11 and 12 of `gurobipy` by building the names without that class.
"""
import re
import unittest
from pathlib import Path

import gurobipy as gp
from gurobipy import GRB

from enginiite.market import run_flex_market, solver_status

SRC = Path(__file__).resolve().parents[2] / 'src' / 'enginiite'


def tiny_model(feasible=True):
    model = gp.Model()
    model.Params.OutputFlag = 0
    x = model.addVar(lb=0, ub=10, name='x')
    model.addConstr(x >= 2, name='lower')
    model.addConstr(x <= (5 if feasible else 1), name='upper')
    model.setObjective(x, GRB.MINIMIZE)
    return model


class StatusNamesTests(unittest.TestCase):
    def test_the_common_codes_have_their_gurobi_names(self):
        names = solver_status.status_names()
        for name in ('OPTIMAL', 'INFEASIBLE', 'INF_OR_UNBD', 'UNBOUNDED', 'NUMERIC', 'TIME_LIMIT'):
            with self.subTest(name=name):
                self.assertEqual(names[getattr(GRB, name)], name)

    def test_names_are_never_confused_with_other_constants(self):
        # GRB.MINIMIZE is 1, the same number as the status LOADED: only statuses may be in the table
        self.assertEqual(solver_status.status_names()[1], 'LOADED')
        self.assertNotIn('MINIMIZE', solver_status.status_names().values())

    def test_an_unknown_code_gets_a_readable_name(self):
        self.assertEqual(solver_status.status_name(9999), 'status 9999')

    def test_a_solved_model_reports_optimal(self):
        model = tiny_model()
        model.optimize()
        self.assertEqual(solver_status.status_name(model.status), 'OPTIMAL')


class DiagnosticTests(unittest.TestCase):
    def test_an_optimal_model_passes_the_diagnostic(self):
        model = tiny_model()
        model.optimize()
        self.assertTrue(run_flex_market._diagnostic(model))

    def test_an_infeasible_model_is_reported_by_name_and_stops_the_run(self):
        model = tiny_model(feasible=False)
        model.optimize()
        with self.assertRaises(Warning) as caught:
            run_flex_market._diagnostic(model)
        self.assertIn('infeasible', str(caught.exception))


class NoRemovedApiTests(unittest.TestCase):
    def test_the_code_does_not_use_the_class_removed_in_gurobi_12(self):
        offenders = [str(f.relative_to(SRC)) for f in SRC.rglob('*.py')
                     if re.search(r'StatusConstClass', f.read_text(encoding='utf-8', errors='replace'))]
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
