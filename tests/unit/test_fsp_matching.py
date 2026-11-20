"""Unit tests for the matching of flexibility service providers (FSP) with network elements
(enginiite.market.models.fsp_utils).

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import unittest

import pandas as pd

from enginiite.market.models import fsp_utils


def fsp_table(names, buses=None):
    return pd.DataFrame({'name': names, 'bus': buses if buses is not None else range(len(names))})


class FspLabelsTests(unittest.TestCase):
    def test_unique_names_become_the_index(self):
        labels = fsp_utils.fsp_labels(fsp_table(['a', 'b', 'c']), 'A')
        self.assertEqual(list(labels), ['a', 'b', 'c'])
        self.assertEqual(labels.name, 'fsp_name')

    def test_names_are_converted_to_text(self):
        self.assertEqual(list(fsp_utils.fsp_labels(fsp_table([1, 2]), 'A')), ['1', '2'])

    def test_a_table_without_names_is_rejected(self):
        with self.assertRaises(ValueError):
            fsp_utils.fsp_labels(pd.DataFrame({'bus': [1, 2]}), 'A')

    def test_empty_or_missing_names_are_rejected(self):
        for names in (['a', ''], ['a', '   '], ['a', None]):
            with self.subTest(names=names):
                with self.assertRaises(ValueError):
                    fsp_utils.fsp_labels(fsp_table(names), 'A')

    def test_duplicated_names_are_rejected_even_at_different_buses(self):
        with self.assertRaises(ValueError):
            fsp_utils.fsp_labels(fsp_table(['a', 'a'], buses=[1, 2]), 'A')

    def test_the_bus_series_keeps_identity_in_the_index(self):
        table = fsp_table(['a', 'b'], buses=[5, 7])
        series = fsp_utils.fsp_bus_series(table, fsp_utils.fsp_labels(table, 'A'))
        self.assertEqual(series.to_dict(), {'a': 5, 'b': 7})


class MatchElementTests(unittest.TestCase):
    def setUp(self):
        # a non-default index on purpose, because the match must return the table label and not the position
        self.table = pd.DataFrame({'name': ['x', 'y', 'x'], 'bus': [1, 2, 3]}, index=[10, 20, 30])

    def row(self, name, bus):
        return pd.Series({'name': name, 'bus': bus})

    def test_the_table_index_label_is_returned(self):
        self.assertEqual(fsp_utils.match_pp_element(self.table, self.row('y', 2), 'load'), 20)

    def test_the_bus_disambiguates_equal_names(self):
        self.assertEqual(fsp_utils.match_pp_element(self.table, self.row('x', 3), 'load'), 30)
        self.assertEqual(fsp_utils.match_pp_element(self.table, self.row('x', 1), 'load'), 10)

    def test_an_unknown_name_is_rejected(self):
        with self.assertRaises(ValueError):
            fsp_utils.match_pp_element(self.table, self.row('nope', 1), 'load')

    def test_a_known_name_at_the_wrong_bus_is_rejected(self):
        with self.assertRaises(ValueError):
            fsp_utils.match_pp_element(self.table, self.row('y', 99), 'load')

    def test_two_matches_are_rejected(self):
        table = pd.DataFrame({'name': ['x', 'x'], 'bus': [1, 1]}, index=[1, 2])
        with self.assertRaises(ValueError):
            fsp_utils.match_pp_element(table, self.row('x', 1), 'sgen')

    def test_the_error_names_the_element_and_the_fsp(self):
        with self.assertRaises(ValueError) as ctx:
            fsp_utils.match_pp_element(self.table, self.row('nope', 1), 'storage')
        self.assertIn('storage', str(ctx.exception))
        self.assertIn('nope', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
