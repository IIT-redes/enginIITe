"""Unit tests for the KPI figures: the label of the volume axis and the position of the legends.

The figures are drawn with a non-interactive backend from small tables, and nothing is read from disk.
"""
import unittest

import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from enginiite.kpis import eval_kpis  # noqa: E402

SCENARIOS = ['net_CMVC_PQ_VL01_F01_SK01_T', 'net_CMVC_PQ_VL01_F02_SK01_T', 'net_CMVC_PQ_VL01_F03_SK01_T']


def bid_table():
    return pd.DataFrame({'Cleared': [7.5, 6.4, 2.2], 'Offered': [25.4, 48.0, 69.0]}, index=SCENARIOS)


def avoided_table(prefix):
    data = {}
    for band, units, percents in (('standard', [28, 34, 34], [82.0, 100.0, 100.0]),
                                  ('detection', [28, 34, 34], [82.0, 100.0, 100.0]),
                                  ('optimization', [37, 61, 66], [51.0, 85.0, 92.0])):
        data['%s_%s [u]' % (prefix, band)] = units
        data['%s_%s [%%]' % (prefix, band)] = percents
    return pd.DataFrame(data, index=SCENARIOS)


class KpiPlotTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_the_volume_axis_says_active_power_for_the_active_product(self):
        fig = eval_kpis.bid_quantities_plots(bid_table(), SCENARIOS, 'T', [[], [0, 100]], _product='P')
        self.assertEqual(fig.axes[0].get_ylabel(), 'Volume of Active Power Product [MWh]')

    def test_the_volume_axis_says_reactive_power_for_the_reactive_product(self):
        fig = eval_kpis.bid_quantities_plots(bid_table(), SCENARIOS, 'T', [[], [0, 100]], _product='Q')
        self.assertEqual(fig.axes[0].get_ylabel(), 'Volume of Reactive Power Product [MVArh]')

    def test_the_active_product_is_the_default_so_that_older_callers_keep_working(self):
        fig = eval_kpis.bid_quantities_plots(bid_table(), SCENARIOS, 'T', [[], [0, 100]])
        self.assertIn('Active', fig.axes[0].get_ylabel())

    def test_an_unknown_product_is_refused(self):
        with self.assertRaises(ValueError):
            eval_kpis.bid_quantities_plots(bid_table(), SCENARIOS, 'T', [[], [0, 100]], _product='X')

    def assert_legend_is_clear_of_the_bars(self, fig):
        fig.canvas.draw()
        self.assertTrue(all(ax.get_legend() is None for ax in fig.axes), 'a legend inside an axes can cover the bars')
        self.assertEqual(len(fig.legends), 1)
        legend_box = fig.legends[0].get_window_extent()
        figure_box = fig.bbox
        self.assertFalse(any(legend_box.overlaps(ax.get_window_extent()) for ax in fig.axes),
                         'the legend overlaps the plotting area')
        self.assertFalse(legend_box.overlaps(fig.axes[0].title.get_window_extent()), 'the legend overlaps the subtitle')
        self.assertFalse(legend_box.overlaps(fig._suptitle.get_window_extent()), 'the legend overlaps the title')
        self.assertGreaterEqual(legend_box.x0, figure_box.x0)
        self.assertLessEqual(legend_box.x1, figure_box.x1)
        self.assertLessEqual(legend_box.y1, figure_box.y1)

    def test_the_legend_of_the_avoided_voltage_violations_does_not_cover_the_bars(self):
        fig = eval_kpis.avoided_voltage_viol_plots(avoided_table('AvoidVoltage'), SCENARIOS, 'T', [[], []])
        self.assert_legend_is_clear_of_the_bars(fig)

    def test_the_legend_of_the_avoided_congestions_does_not_cover_the_bars(self):
        fig = eval_kpis.avoided_cong_plots(avoided_table('AvoidCongestion'), SCENARIOS, 'T', [[], []])
        self.assert_legend_is_clear_of_the_bars(fig)

    def test_the_legend_keeps_the_six_entries_of_bars_and_lines(self):
        fig = eval_kpis.avoided_voltage_viol_plots(avoided_table('AvoidVoltage'), SCENARIOS, 'T', [[], []])
        labels = [text.get_text() for text in fig.legends[0].get_texts()]
        self.assertEqual(len(labels), 6)
        self.assertEqual(sorted(set(labels)), ['Detection', 'Optimization', 'Standard'])


if __name__ == '__main__':
    unittest.main()
