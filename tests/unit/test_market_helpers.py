"""Unit tests for small helpers of the market step (enginiite.market.run_flex_market).

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import unittest

from enginiite.market import run_flex_market as market


class ParseMarketTagTests(unittest.TestCase):
    def test_model_and_product_are_found_in_a_plain_tag(self):
        self.assertEqual(market._parse_market_tag('NetA_CMVC_P_VL01_F01'), ('CMVC', 'P'))

    def test_network_names_with_underscores_do_not_confuse_the_parser(self):
        self.assertEqual(market._parse_market_tag('my_big_net_CM_PQ_VL02'), ('CM', 'PQ'))

    def test_a_long_tag_with_trailing_scenario_tags(self):
        self.assertEqual(market._parse_market_tag('Example_MV_VC_Q_VL05_F02_SK01_T1'), ('VC', 'Q'))

    def test_every_valid_model_is_accepted(self):
        for model in ('CM', 'VC', 'CMVC', 'VCCM'):
            with self.subTest(model=model):
                self.assertEqual(market._parse_market_tag('Net_%s_PQ' % model), (model, 'PQ'))

    def test_a_tag_without_model_is_rejected(self):
        with self.assertRaises(ValueError):
            market._parse_market_tag('Net_P_VL01')

    def test_a_model_without_product_is_rejected(self):
        with self.assertRaises(ValueError):
            market._parse_market_tag('Net_CM')

    def test_an_unknown_product_is_rejected(self):
        with self.assertRaises(ValueError):
            market._parse_market_tag('Net_CM_Z_VL01')

    def test_an_empty_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            market._parse_market_tag('')


class DivideChunksTests(unittest.TestCase):
    def chunks(self, hours, n):
        return [list(c) for c in market._divide_chunks(hours, n)]

    def test_the_last_chunk_keeps_the_remainder(self):
        self.assertEqual(self.chunks(list(range(10)), 4), [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]])

    def test_a_chunk_larger_than_the_list_gives_a_single_block(self):
        self.assertEqual(self.chunks([3, 4, 5], 24), [[3, 4, 5]])

    def test_no_hours_give_no_blocks(self):
        self.assertEqual(self.chunks([], 24), [])

    def test_chunks_are_cut_by_position_not_by_clock_time(self):
        """Separated hours are grouped as if they were consecutive, and nothing links the blocks."""
        self.assertEqual(self.chunks([2, 5, 9, 20, 23], 2), [[2, 5], [9, 20], [23]])


class VoltageOptimisationLimitsTests(unittest.TestCase):
    def test_the_explicit_limits_are_returned_as_floats(self):
        self.assertEqual(market._resolve_voltage_optimization_limits(0.95, 1.05, 0.0, '0.96', 1.04), (0.96, 1.04))

    def test_the_legacy_tolerance_argument_is_ignored(self):
        a = market._resolve_voltage_optimization_limits(0.95, 1.05, 0.0, 0.96, 1.04)
        b = market._resolve_voltage_optimization_limits(0.90, 1.10, 5.0, 0.96, 1.04)
        self.assertEqual(a, b)

    def test_missing_explicit_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            market._resolve_voltage_optimization_limits(0.95, 1.05, 0.0, None, 1.04)
        with self.assertRaises(ValueError):
            market._resolve_voltage_optimization_limits(0.95, 1.05, 0.0, 0.96, None)

    def test_an_inverted_band_is_rejected(self):
        with self.assertRaises(ValueError):
            market._resolve_voltage_optimization_limits(0.95, 1.05, 0.0, 1.04, 0.96)

    def test_a_zero_width_band_is_accepted(self):
        self.assertEqual(market._resolve_voltage_optimization_limits(0.95, 1.05, 0.0, 1.0, 1.0), (1.0, 1.0))


if __name__ == '__main__':
    unittest.main()
