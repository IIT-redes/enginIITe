"""Unit tests for the selection of the hours to study (enginiite.network.flex_eval.get_sim_hours).

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import contextlib
import glob
import io
import os
import tempfile
import unittest

import pandas as pd

from enginiite.network import flex_eval


def problem_table(hours_with_problem, n_rows=3, hours=range(24), value=0.93):
    """Rows x hours table that is non-zero only where there is a problem (the shape used by the needs detection)."""
    table = pd.DataFrame(0.0, index=range(n_rows), columns=list(hours))
    for hour in hours_with_problem:
        table.loc[0, hour] = value
    return table


class GetSimHoursTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = self._tmp.name

    def hours(self, model, voltage_hours, congestion_hours, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            result = flex_eval.get_sim_hours(
                model, [0, 24], problem_table(voltage_hours), problem_table(congestion_hours, value=1.2),
                self.out_dir, **kwargs)
        return [int(h) for h in result]

    # ---- which hours are selected for each market model
    def test_voltage_control_uses_only_voltage_hours(self):
        self.assertEqual(self.hours('VC', [8, 9], [18]), [8, 9])

    def test_cv_is_an_alias_of_voltage_control(self):
        self.assertEqual(self.hours('CV', [8, 9], [18]), [8, 9])

    def test_congestion_management_uses_only_congestion_hours(self):
        self.assertEqual(self.hours('CM', [8, 9], [18]), [18])

    def test_any_other_tag_is_treated_as_congestion_management(self):
        self.assertEqual(self.hours('SOMETHING_ELSE', [8, 9], [18]), [18])

    def test_combined_model_returns_the_sorted_union_without_duplicates(self):
        self.assertEqual(self.hours('CMVC', [9, 8], [18, 8]), [8, 9, 18])

    # ---- intertemporal constraints
    def test_intertemporal_constraints_use_the_whole_window(self):
        self.assertEqual(self.hours('CM', [], [], _intertemp_cons=True), list(range(0, 24)))

    # ---- nothing to do
    def test_no_problems_stops_the_whole_run(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                flex_eval.get_sim_hours('CMVC', [0, 24], problem_table([]), problem_table([]), self.out_dir)

    # ---- side effect
    def test_the_selected_hours_are_saved(self):
        self.hours('VC', [8, 9], [])
        saved = glob.glob(os.path.join(self.out_dir, 'HoursToStudy*'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(pd.read_csv(saved[0], index_col=0).iloc[:, 0].tolist(), [8, 9])

    # ---- known issue, the "worst hour" branch is unreachable because its condition is contradictory
    def test_only_worst_hour_flag_currently_has_no_effect(self):
        """Documents today's behaviour. The flag is ignored and every hour with a problem is returned."""
        self.assertEqual(self.hours('VC', [8, 9, 10], [], _only_worst_hour=True), [8, 9, 10])

    def test_worst_hour_and_intertemporal_together_currently_return_the_problem_hours(self):
        self.assertEqual(self.hours('VC', [8, 9, 10], [], _only_worst_hour=True, _intertemp_cons=True), [8, 9, 10])

    @unittest.expectedFailure
    def test_only_worst_hour_should_select_a_single_hour(self):
        """What the docstring promises. It fails today. If it starts passing the issue was fixed, so remove
        the 'currently' tests above and the expectedFailure marker."""
        self.assertEqual(len(self.hours('VC', [8, 9, 10], [], _only_worst_hour=True)), 1)


if __name__ == '__main__':
    unittest.main()
