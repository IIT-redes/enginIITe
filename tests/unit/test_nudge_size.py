"""Unit tests for the size of the power step used by the sensitivity calculation
(enginiite.auxiliary._def_dp). The network is replaced by small tables; nothing is read from disk.

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from enginiite import auxiliary as aux


def _table(p=(), q=None):
    """P and Q may have different lengths, so the shorter column is padded with NaN, which the code ignores."""
    columns = {'p_mw': pd.Series(list(p), dtype=float)}
    if q is not None:
        columns['q_mvar'] = pd.Series(list(q), dtype=float)
    return pd.DataFrame(columns)


def network(load_p=(), load_q=(), gen_p=(), sgen_p=(), sgen_q=(), storage_p=(), storage_q=()):
    return SimpleNamespace(
        load=_table(load_p, load_q),
        gen=_table(gen_p),
        sgen=_table(sgen_p, sgen_q),
        storage=_table(storage_p, storage_q),
    )


def nudge(net):
    with mock.patch.object(aux.io_file, 'import_network', return_value=net):
        return aux._def_dp({'network': {}})


class NudgeSizeTests(unittest.TestCase):
    def test_the_step_is_one_decade_below_the_smallest_positive_power(self):
        dp, dq = nudge(network(load_p=[0.0123, 3.0], load_q=[0.5, 1.0]))
        self.assertAlmostEqual(dp, 0.001)   # 0.0123 MW -> exponent -2 -> 10^-3
        self.assertAlmostEqual(dq, 0.01)    # 0.5 MVAr  -> exponent -1 -> 10^-2

    def test_zero_and_negative_values_are_ignored(self):
        dp, dq = nudge(network(load_p=[0.0, -2.0, 0.5], load_q=[0.0, 0.5]))
        self.assertAlmostEqual(dp, 0.01)
        self.assertAlmostEqual(dq, 0.01)

    def test_the_smallest_value_is_searched_across_resources(self):
        dp, _ = nudge(network(load_p=[5.0], sgen_p=[0.04], storage_p=[0.9], gen_p=[7.0], load_q=[0.5]))
        self.assertAlmostEqual(dp, 0.001)   # the sgen (0.04) decides

    def test_exact_powers_of_ten(self):
        self.assertAlmostEqual(nudge(network(load_p=[0.1], load_q=[0.1]))[0], 0.01)
        self.assertAlmostEqual(nudge(network(load_p=[0.01], load_q=[0.1]))[0], 0.001)

    def test_when_every_value_is_one_or_larger_the_default_is_used(self):
        self.assertEqual(nudge(network(load_p=[1.5, 3.0], load_q=[2.0])), (0.1, 0.1))

    def test_an_empty_network_uses_the_default(self):
        self.assertEqual(nudge(network()), (0.1, 0.1))

    def test_one_failing_side_resets_both_steps_to_the_default(self):
        """Known quirk. P is small enough for a finer step, but because Q has no value below 1
        both fall back to 0.1 together."""
        self.assertEqual(nudge(network(load_p=[0.0123], load_q=[2.0])), (0.1, 0.1))


if __name__ == '__main__':
    unittest.main()
