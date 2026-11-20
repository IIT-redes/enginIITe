"""Characterisation tests for the KPI formulas (enginiite.kpis.eval_kpis).

They use small hand-made tables, so no simulation and no solver are needed. Most tests state what the code is meant
to do. Tests whose name contains "currently" pin behaviour that looks wrong, so that the day it is fixed the test
fails and says so. For those cases a second test, marked as an expected failure, states the behaviour a fix should
give. When a fix lands, delete the "currently" test and the expectedFailure marker together.

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import contextlib
import io
import math
import os
import unittest

os.environ.setdefault('MPLBACKEND', 'Agg')

import numpy as np
import pandas as pd
import pandapower as pp

from enginiite.kpis import eval_kpis as kpi


def frame(rows, index=None, columns=None):
    return pd.DataFrame(rows, index=index, columns=columns)


class HelperTests(unittest.TestCase):
    def test_check_consistency_keeps_only_the_simulated_values(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(kpi._check_consis(['P', 'X'], ['P', 'Q']), ['P'])

    def test_check_consistency_falls_back_to_everything_simulated(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(kpi._check_consis(['X'], ['P', 'Q']), ['P', 'Q'])
        self.assertIn('will consider', out.getvalue())

    def test_scenario_names_follow_product_band_coefficient_order(self):
        names = kpi._get_scenario_names('grid', 'CMVC', ['P', 'Q'], ['VL01'], ['F01', 'F02'], 'SK01', 'T1')
        self.assertEqual(names, ['grid_CMVC_P_VL01_F01_SK01_T1', 'grid_CMVC_P_VL01_F02_SK01_T1',
                                 'grid_CMVC_Q_VL01_F01_SK01_T1', 'grid_CMVC_Q_VL01_F02_SK01_T1'])

    def test_scenario_names_drop_empty_parts(self):
        names = kpi._get_scenario_names('grid', 'CM', ['P'], ['VL01'], ['F01'], '', '')
        self.assertEqual(names, ['grid_CM_P_VL01_F01'])

    def test_max_of_a_table_gives_value_row_and_column(self):
        table = frame([[1.0, 5.0], [7.0, 2.0]], index=[10, 11], columns=[0, 1])
        self.assertEqual(kpi.max_mat_df(table), (7.0, 11, 0))

    def test_max_of_a_table_ignores_missing_values_and_takes_the_first_tie(self):
        table = frame([[np.nan, 4.0], [4.0, 1.0]], index=[3, 4], columns=[0, 1])
        self.assertEqual(kpi.max_mat_df(table), (4.0, 3, 1))

    def test_max_of_an_empty_table_currently_raises(self):
        with self.assertRaises(ValueError):
            kpi.max_mat_df(pd.DataFrame())

    def test_numeric_looking_labels_become_integers(self):
        table = frame([[1, 2], [3, 4]], index=['0', '1'], columns=['5', '6'])
        out = kpi._coerce_numeric_axis_labels(table)
        self.assertEqual(list(out.index), [0, 1])
        self.assertEqual(list(out.columns), [5, 6])
        self.assertEqual(list(table.index), ['0', '1'])

    def test_text_labels_are_left_alone(self):
        table = frame([[1, 2]], index=['bus_a'], columns=['h0', 'h1'])
        out = kpi._coerce_numeric_axis_labels(table)
        self.assertEqual(list(out.index), ['bus_a'])
        self.assertEqual(list(out.columns), ['h0', 'h1'])

    def test_mixed_labels_are_left_alone(self):
        table = frame([[1], [2]], index=['0', 'x'], columns=['0'])
        self.assertEqual(list(kpi._coerce_numeric_axis_labels(table).index), ['0', 'x'])

    def test_safe_lookup_finds_a_value_with_text_labels_in_the_table(self):
        table = frame([[1.5, 2.5]], index=['2'], columns=['0', '1'])
        self.assertEqual(kpi._safe_table_value(table, 2, 1), 2.5)

    def test_safe_lookup_explains_a_missing_row(self):
        table = frame([[1.5]], index=[0], columns=[0])
        with self.assertRaises(KeyError) as ctx:
            kpi._safe_table_value(table, 9, 0, table_name='vpu_table')
        self.assertIn('vpu_table', str(ctx.exception))

    def test_safe_lookup_explains_a_missing_column(self):
        table = frame([[1.5]], index=[0], columns=[0])
        with self.assertRaises(KeyError):
            kpi._safe_table_value(table, 0, 7)


class CongestionTests(unittest.TestCase):
    def test_transitions_split_into_resolved_persistent_and_new(self):
        pre = frame([[101, 101, 50, 50]])
        post = frame([[99, 101, 101, 50]])
        counts = kpi._congestion_transition_counts(pre, post, 100)
        self.assertEqual((counts['resolved'], counts['persistent'], counts['new']), (1, 1, 1))
        self.assertEqual((counts['pre'], counts['post'], counts['net_resolved']), (2, 2, 0))

    def test_a_loading_equal_to_the_threshold_is_not_congested(self):
        counts = kpi._congestion_transition_counts(frame([[100.0]]), frame([[100.0]]), 100)
        self.assertEqual(counts['pre'], 0)

    def test_hours_missing_after_the_market_keep_their_pre_market_state(self):
        pre = frame([[101, 101, 101]], columns=[0, 1, 2])
        post = frame([[99]], columns=[0])
        counts = kpi._congestion_transition_counts(pre, post, 100)
        self.assertEqual(counts['resolved'], 1)
        self.assertEqual(counts['persistent'], 2)

    def test_empty_tables_count_nothing(self):
        counts = kpi._congestion_transition_counts({}, {}, 100)
        self.assertEqual((counts['pre'], counts['post']), (0, 0))

    def test_avoided_congestion_is_a_percentage_of_the_pre_market_count(self):
        data_pre = {'Ipline_table': frame([[101, 101, 50]]), 'Iptrafo_table': {}, 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        data_post = {'Ipline_table': frame([[99, 101, 50]]), 'Iptrafo_table': {}, 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        out = kpi.eval_avoided_congestion(data_pre, data_post)
        self.assertEqual(out['AvoidCongestions [%]'], 50.0)
        self.assertEqual((out['n_pre_L [u]'], out['n_post_L [u]'], out['AvoidCong_L[u]']), (2, 1, 1))

    def test_with_nothing_congested_before_the_market_the_percentage_is_zero(self):
        data = {'Ipline_table': frame([[10, 20]]), 'Iptrafo_table': {}, 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        self.assertEqual(kpi.eval_avoided_congestion(data, data)['AvoidCongestions [%]'], 0)

    def test_a_new_congestion_cancels_a_resolved_one_in_the_percentage(self):
        data_pre = {'Ipline_table': frame([[101, 50]]), 'Iptrafo_table': {}, 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        data_post = {'Ipline_table': frame([[50, 101]]), 'Iptrafo_table': {}, 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        out = kpi.eval_avoided_congestion(data_pre, data_post)
        self.assertEqual(out['AvoidCongestions [%]'], 0.0)
        self.assertEqual((out['_ResolvedCong_Total [u]'], out['_NewCong_Total [u]']), (1, 1))

    def test_lines_and_transformers_are_added_up(self):
        data_pre = {'Ipline_table': frame([[101]]), 'Iptrafo_table': frame([[120]]), 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        data_post = {'Ipline_table': frame([[90]]), 'Iptrafo_table': frame([[120]]), 'Iptrafo3w_table': {}, 'i_max_perc': 100}
        out = kpi.eval_avoided_congestion(data_pre, data_post)
        self.assertEqual((out['n_pre_Total [u]'], out['n_post_Total [u]']), (2, 1))
        self.assertEqual(out['AvoidCongestions [%]'], 50.0)

    def test_scenario_table_reports_three_thresholds_side_by_side(self):
        name = 'grid_CMVC_P_VL01_F01_SK01_T1'
        in_dict = {
            'lines_ldg_perc_pre': {name: frame([[101, 96, 50, 92]])},
            'lines_ldg_perc_post': {name: frame([[99, 96, 50, 85]])},
            'trafos_ldg_perc_pre': {}, 'trafos_ldg_perc_post': {},
            'trafos3w_ldg_perc_pre': {}, 'trafos3w_ldg_perc_post': {},
            'i_max_perc_pre': 95, 'i_max_perc_post': 90,
            'current_thresholds': {'standard_percent': 100.0, 'detection_limit_percent': 95.0,
                                   'optimization_target_percent': 90.0},
        }
        row = kpi.avoided_cong(in_dict, [name]).loc[name]
        self.assertEqual(row['AvoidCongestion_standard [%]'], 100.0)
        self.assertEqual(row['ResolvedCongestion_standard [u]'], 1)
        self.assertEqual(row['AvoidCongestion_detection [%]'], 0.0)
        self.assertEqual(row['PersistentCongestion_detection [u]'], 2)
        self.assertAlmostEqual(row['AvoidCongestion_optimization [%]'], 33.333, places=3)
        self.assertEqual(row['Threshold_optimization [%]'], 90.0)
        self.assertEqual(row['AvoidCong_L[u]'], 1)


class VoltageViolationTests(unittest.TestCase):
    BAND = {'vbus_max': 1.05, 'vbus_min': 0.95}

    def evaluate(self, pre, post):
        return kpi.eval_avoided_voltage_violation(dict(self.BAND, vpu_table=pre), dict(self.BAND, vpu_table=post))

    def test_under_and_over_voltages_are_counted_before_and_after(self):
        pre = frame([[0.94, 1.0, 1.06], [1.0, 0.96, 1.0]])
        post = frame([[0.96, 1.0, 1.04], [1.0, 0.96, 0.94]])
        out = self.evaluate(pre, post)
        self.assertEqual((out['n_pre_B_Under [u]'], out['n_pre_B_Over [u]']), (1, 1))
        self.assertEqual((out['n_post_B_Under [u]'], out['n_post_B_Over [u]']), (1, 0))
        self.assertEqual(out['AvoidVoltageViolations [%]'], 50.0)
        self.assertEqual(out['AvoidVoltageViolations [u]'], 1)

    def test_values_on_the_limits_are_not_violations(self):
        out = self.evaluate(frame([[0.95, 1.05]]), frame([[0.95, 1.05]]))
        self.assertEqual(out['n_pre_B [u]'], 0)

    def test_zero_voltage_is_treated_as_a_disconnected_bus_and_not_counted_as_under_voltage(self):
        out = self.evaluate(frame([[0.0, 1.0]]), frame([[0.0, 1.0]]))
        self.assertEqual(out['n_pre_B_Under [u]'], 0)

    def test_with_no_violation_before_the_market_the_percentage_is_zero(self):
        out = self.evaluate(frame([[1.0]]), frame([[1.0]]))
        self.assertEqual(out['AvoidVoltageViolations [%]'], 0)

    def test_hours_missing_after_the_market_currently_count_as_avoided(self):
        pre = frame([[1.0, 1.0, 0.94]], columns=[0, 1, 2])
        post = frame([[1.0, 1.0]], columns=[0, 1])
        out = self.evaluate(pre, post)
        self.assertEqual(out['AvoidVoltageViolations [%]'], 100.0)

    @unittest.expectedFailure
    def test_hours_missing_after_the_market_should_not_count_as_avoided(self):
        pre = frame([[1.0, 1.0, 0.94]], columns=[0, 1, 2])
        post = frame([[1.0, 1.0]], columns=[0, 1])
        out = self.evaluate(pre, post)
        self.assertNotEqual(out['AvoidVoltageViolations [%]'], 100.0)


class HostingCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        net = pp.create_empty_network()
        b0 = pp.create_bus(net, vn_kv=20.0)
        b1 = pp.create_bus(net, vn_kv=20.0)
        b2 = pp.create_bus(net, vn_kv=0.4)
        pp.create_ext_grid(net, b0)
        pp.create_line(net, b0, b1, 1.0, 'NA2XS2Y 1x95 RM/25 12/20 kV')
        pp.create_transformer(net, b0, b2, '0.4 MVA 20/0.4 kV')
        cls.net = net
        cls.line_ka = float(net.line.at[0, 'max_i_ka'])
        cls.trafo_mva = float(net.trafo.at[0, 'sn_mva'])

    def data(self, line=None, trafo=None, hc_info=None, vmax=1.05):
        return {
            'vpu_table': frame([[1.0, 1.0]] * 3, index=[0, 1, 2], columns=[0, 1]),
            'Ipline_table': frame([line], index=[0]) if line is not None else {},
            'Iptrafo_table': frame([trafo], index=[0]) if trafo is not None else {},
            'Iptrafo3w_table': {},
            'HC_info': hc_info if hc_info is not None else [],
            'vbus_max_V': vmax, 'i_max_perc': 100,
        }

    def line_headroom(self, loading):
        return math.sqrt(3) * ((100 - loading) / 100) * self.line_ka * 20.0

    def test_line_headroom_follows_the_loading_and_the_rating(self):
        out = kpi.eval_hosting_capacity(self.net, self.data(line=[50.0, 30.0]))
        self.assertAlmostEqual(out['Hosting Capacity [MVA]'], self.line_headroom(50.0), places=3)
        self.assertEqual(out['Type component'], 'Line')
        self.assertEqual(out['CM line_hour'], 0)

    def test_the_most_loaded_hour_decides(self):
        out = kpi.eval_hosting_capacity(self.net, self.data(line=[10.0, 80.0]))
        self.assertAlmostEqual(out['CM perc_Load_L [%]'], 80.0)
        self.assertEqual(out['CM line_hour'], 1)

    def test_the_tightest_component_gives_the_hosting_capacity(self):
        out = kpi.eval_hosting_capacity(self.net, self.data(line=[50.0, 30.0], trafo=[90.0, 10.0]))
        self.assertEqual(out['Type component'], 'Trafo')
        self.assertAlmostEqual(out['Hosting Capacity [MVA]'], 0.1 * self.trafo_mva, places=3)

    def test_voltage_headroom_is_used_when_the_voltage_information_is_given(self):
        info = frame({'HV_m': [0.001], 'maxV_val': [1.04], 'maxV_hour': [3]}, index=[1])
        out = kpi.eval_hosting_capacity(self.net, self.data(line=[50.0, 30.0], hc_info=info))
        self.assertAlmostEqual(out['VC HC [MVA]'], 200.0, places=3)
        self.assertEqual(out['VC hour'], 3)
        self.assertEqual(out['Type component'], 'Line')

    def test_without_voltage_information_the_voltage_part_is_infinite(self):
        out = kpi.eval_hosting_capacity(self.net, self.data(line=[50.0, 30.0]))
        self.assertNotIn('VC HC [MVA]', out)

    def test_with_no_tables_at_all_the_result_is_infinite_and_names_a_node(self):
        out = kpi.eval_hosting_capacity(self.net, self.data())
        self.assertTrue(math.isinf(out['Hosting Capacity [MVA]']))
        self.assertEqual(out['Type component'], 'Node')

    def test_the_increase_is_the_post_market_capacity_minus_the_pre_market_one(self):
        name = 'grid_CMVC_P_VL01_F01_SK01_T1'
        vpu = frame([[1.0, 1.0]] * 3, index=[0, 1, 2], columns=[0, 1])
        in_dict = {
            'network': self.net, 'vl_lims': ['VL01'], 'scenarios_selected': [name],
            'lines_ldg_perc_pre': {name: frame([[80.0, 70.0]], index=[0])},
            'lines_ldg_perc_post': {name: frame([[60.0, 50.0]], index=[0])},
            'trafos_ldg_perc_pre': {}, 'trafos_ldg_perc_post': {},
            'trafos3w_ldg_perc_pre': {}, 'trafos3w_ldg_perc_post': {},
            'bus_vmpu_pre': {name: vpu}, 'bus_vmpu_post': {name: vpu},
            'hc_pre': [], 'hc_post': [],
            'vbus_max_pre': [1.05], 'vbus_max_post': [1.05],
            'i_max_perc_pre': 100, 'i_max_perc_post': 100,
        }
        pre, post, ihc, pihc = kpi.increase_hc(in_dict)
        gain = self.line_headroom(60.0) - self.line_headroom(80.0)
        self.assertAlmostEqual(float(ihc.loc[name, 'Increase Hosting Capacity [MVA]']), gain, places=2)
        self.assertAlmostEqual(float(pihc.loc[name, 'Percentage of IHC [%]']), 100.0, places=1)
        self.assertNotIn('VC HC [MVA]', pre.index)


class FlexibilityCostTests(unittest.TestCase):
    FSP = ['f1', 'f2']
    HOURS = [0, 1]

    def table(self, rows):
        return frame(rows, index=self.FSP, columns=self.HOURS)

    def load_case(self, dr_up=None):
        dict_res = {'A': {
            'DW_A_U': self.table([[1, 2], [0, 1]]),
            'DW_A_D': self.table([[0, 1], [2, 0]]),
            'DR_A_U': self.table(dr_up if dr_up is not None else [[0.5, 0], [0, 0.5]]),
            'DR_A_D': self.table([[0, 0], [0, 0.25]]),
        }}
        dict_costs = {'A': {
            'W_U_Cost_A': self.table([[10, 10], [20, 20]]),
            'W_D_Cost_A': self.table([[5, 5], [8, 8]]),
            'R_U_Cost_A': self.table([[1, 1], [1, 1]]),
            'R_D_Cost_A': self.table([[2, 2], [2, 2]]),
        }}
        return dict_res, dict_costs

    def others(self, objective):
        return {'ABS_alpha_primo': self.table([[0.1, 0.2], [0, 0]]), 'ABS_beta': frame([[0.05]]),
                'ObjValue': frame({'ObjValue': [objective]})}

    def run_costs(self, dict_res, dict_costs, objective=107.5, types=('A',), flat=None):
        in_dict = {'fsp_file': {t: 'x' for t in types}, 'cost_alpha': 100.0, 'cost_beta': 100.0}
        for t in types:
            in_dict['flat_' + t] = True if flat is None else flat[t]
        return kpi.eval_flexibility_costs(in_dict, dict_res, self.others(objective), dict_costs)

    def test_each_activation_is_settled_at_its_own_bid_price(self):
        out = self.run_costs(*self.load_case())
        self.assertEqual(out['DW_A_U_Cost'], 1 * 10 + 2 * 10 + 0 * 20 + 1 * 20)
        self.assertEqual(out['DW_A_D_Cost'], 0 * 5 + 1 * 5 + 2 * 8 + 0 * 8)
        self.assertEqual(out['C_FM_A_W_Total'], 71)
        self.assertEqual(out['C_FM_A_R_Total'], 1.5)

    def test_activated_power_adds_the_upward_and_downward_magnitudes(self):
        out = self.run_costs(*self.load_case())
        self.assertEqual((out['DW_A_U_total'], out['DW_A_D_total']), (4, 3))
        self.assertEqual(out['W_A'], 7)
        self.assertEqual(out['R_A'], 1.25)
        self.assertEqual(out['ActivePower_Total [MW]'], 7)

    def test_the_average_cost_is_the_total_cost_over_the_activated_power(self):
        out = self.run_costs(*self.load_case())
        self.assertAlmostEqual(out['DW_A_Net_Cost_Avg'], 71 / 7)
        self.assertAlmostEqual(out['C_FM_ActivePower_Avg [Eur/MW]'], round(71 / 7, 3))
        self.assertAlmostEqual(out['DW_A_U_Cost_Avg'], 12.5)

    def test_slack_penalties_use_the_absolute_slacks_and_their_prices(self):
        out = self.run_costs(*self.load_case())
        self.assertAlmostEqual(out['Alpha [MW]'], 0.3)
        self.assertAlmostEqual(out['Cost_Alpha_Total'], 30.0)
        self.assertAlmostEqual(out['Beta [MVA]'], 0.05)
        self.assertAlmostEqual(out['Cost_Beta_Total'], 5.0)

    def test_without_slack_the_average_penalty_is_zero(self):
        dict_res, dict_costs = self.load_case()
        in_dict = {'fsp_file': {'A': 'x'}, 'flat_A': True, 'cost_alpha': 100.0, 'cost_beta': 100.0}
        zero = {'ABS_alpha_primo': self.table([[0, 0], [0, 0]]), 'ABS_beta': frame([[0.0]]),
                'ObjValue': frame({'ObjValue': [1.0]})}
        out = kpi.eval_flexibility_costs(in_dict, dict_res, zero, dict_costs)
        self.assertEqual((out['Cost_Alpha_Avg'], out['Cost_Beta_Avg']), (0, 0))

    def test_total_cost_equals_the_objective_value_when_the_pieces_add_up(self):
        out = self.run_costs(*self.load_case())
        table = kpi.build_final_table({'s1': out})
        self.assertAlmostEqual(table.loc['s1', 'TotalCost [Eur]'], 107.5)
        self.assertAlmostEqual(table.loc['s1', 'TotalCost [Eur]'], table.loc['s1', 'ObjValue [Eur]'])

    def test_the_final_table_has_one_row_per_scenario(self):
        out1 = self.run_costs(*self.load_case())
        out2 = self.run_costs(*self.load_case())
        table = kpi.build_final_table({'s1': out1, 's2': out2})
        self.assertEqual(list(table.index), ['s1', 's2'])
        self.assertIn('ActivePowerCost [Eur]', table.columns)

    def battery_costs(self):
        t = lambda rows: frame(rows, index=['b1'], columns=self.HOURS)
        dict_res = {'C': {
            'DW_C_U_inj': t([[1, 0]]), 'DW_C_U_ads': t([[0, 2]]),
            'DW_C_D_inj': t([[0.5, 0]]), 'DW_C_D_ads': t([[0, 0.5]]),
            'DR_C_U': t([[0, 0]]), 'DR_C_D': t([[0, 0]]),
        }}
        dict_costs = {'C': {
            'W_U_inj_Cost_C': t([[10, 10]]), 'W_U_ads_Cost_C': t([[4, 4]]),
            'W_D_inj_Cost_C': t([[6, 6]]), 'W_D_ads_Cost_C': t([[2, 2]]),
            'R_U_Cost_C': t([[1, 1]]), 'R_D_Cost_C': t([[1, 1]]),
        }}
        return self.run_costs(dict_res, dict_costs, types=('C',))

    def test_a_battery_adds_its_injection_and_adsorption_parts(self):
        out = self.battery_costs()
        self.assertEqual(out['DW_C_U_total'], 3)
        self.assertEqual(out['DW_C_U_Cost'], 1 * 10 + 2 * 4)
        self.assertEqual(out['DW_C_D_Cost'], 0.5 * 6 + 0.5 * 2)
        self.assertEqual(out['C_FM_C_W_Total'], 22)

    def test_a_type_that_is_not_present_contributes_zero(self):
        dict_res, dict_costs = self.load_case()
        out = self.run_costs(dict_res, dict_costs, types=('A', 'B'), flat={'A': True, 'B': False})
        self.assertEqual(out['W_B'], 0)
        self.assertEqual(out['C_FM_B_W_Total'], 0)
        self.assertEqual(out['C_FM_ActivePower [Eur]'], 71)

    # ---- known issue, the average cost per direction is guarded by the REACTIVE total instead of the active one
    def test_the_upward_average_active_cost_currently_depends_on_the_reactive_total(self):
        dict_res, dict_costs = self.load_case(dr_up=[[0, 0], [0, 0]])
        out = self.run_costs(dict_res, dict_costs)
        self.assertEqual(out['DW_A_U_total'], 4)
        self.assertEqual(out['DW_A_U_Cost_Avg'], 0)

    @unittest.expectedFailure
    def test_the_upward_average_active_cost_should_not_depend_on_the_reactive_total(self):
        dict_res, dict_costs = self.load_case(dr_up=[[0, 0], [0, 0]])
        out = self.run_costs(dict_res, dict_costs)
        self.assertAlmostEqual(out['DW_A_U_Cost_Avg'], 12.5)

    def test_a_battery_without_reactive_activation_currently_reports_a_zero_average_active_cost(self):
        out = self.battery_costs()
        self.assertEqual(out['DW_C_U_total'], 3)
        self.assertEqual(out['DW_C_U_Cost_Avg'], 0)

    def test_the_average_with_reactive_but_no_active_activation_currently_is_not_a_number(self):
        dict_res, dict_costs = self.load_case()
        dict_res['A']['DW_A_U'] = self.table([[0, 0], [0, 0]])
        out = self.run_costs(dict_res, dict_costs)
        self.assertTrue(np.isnan(out['DW_A_U_Cost_Avg']))


class VolumeStatisticsTests(unittest.TestCase):
    FSP = ['f1', 'f2']
    HOURS = [0, 1]

    def table(self, rows):
        return frame(rows, index=self.FSP, columns=self.HOURS)

    def case(self):
        in_dict = {'fsp_file': {'A': 'x'}, 'flat_A': True}
        dict_costs = {'A': {
            'Winit_A': self.table([[4.0, 4.0], [2.0, 2.0]]),
            'Rinit_A': self.table([[1.0, 1.0], [0.5, 0.5]]),
            'WLB_ULim_A': self.table([[3.0, 3.0], [1.5, 1.5]]),
            'WUB_DLim_A': self.table([[5.0, 5.0], [2.5, 2.5]]),
            'RUB_ULim_A': self.table([[0.5, 0.5], [0.25, 0.25]]),
            'RUB_DLim_A': self.table([[1.5, 1.5], [0.75, 0.75]]),
        }}
        dict_res = {'A': {
            'DW_A_U': self.table([[1.0, 0.5], [0.0, 0.0]]),
            'DW_A_D': self.table([[0.0, 0.0], [0.4, 0.2]]),
            'DR_A_U': self.table([[0.2, 0.1], [0.0, 0.0]]),
            'DR_A_D': self.table([[0.0, 0.0], [0.3, 0.3]]),
        }}
        return in_dict, dict_res, dict_costs

    def run_stats(self):
        in_dict, dict_res, dict_costs = self.case()
        return kpi.eval_statistics_volume_flex(in_dict, dict_res, dict_costs, 'scenario')

    def test_the_offered_volume_of_a_load_is_the_distance_to_its_limits(self):
        out = self.run_stats()
        self.assertEqual(out['ST_WOffered_A_U'].loc['f1', 'mean'], 1.0)
        self.assertEqual(out['ST_WOffered_A_U'].loc['f2', 'sum'], 1.0)
        self.assertEqual(out['ST_WOffered_A_D'].loc['f1', 'max'], 1.0)
        self.assertEqual(out['ST_ROffered_A_U'].loc['f1', 'mean'], 0.5)

    def test_the_cleared_volume_has_the_statistics_of_each_provider(self):
        out = self.run_stats()
        cleared = out['ST_WCleared_A_U'].loc['f1']
        self.assertEqual((cleared['mean'], cleared['max'], cleared['min'], cleared['sum']), (0.75, 1.0, 0.5, 1.5))
        self.assertAlmostEqual(out['ST_WCleared_A_D'].loc['f2', 'sum'], 0.6)

    def test_the_baseline_statistics_are_reported(self):
        out = self.run_stats()
        self.assertEqual(out['ST_Winit_A'].loc['f1', 'sum'], 8.0)
        self.assertEqual(out['ST_Rinit_A'].loc['f2', 'mean'], 0.5)

    def test_types_that_are_not_present_are_left_out(self):
        in_dict, dict_res, dict_costs = self.case()
        in_dict['flat_A'] = False
        self.assertEqual(kpi.eval_statistics_volume_flex(in_dict, dict_res, dict_costs, 's'), {})

    # ---- known issue, the downward reactive volume reads the upward sheet
    def test_the_downward_reactive_volume_currently_repeats_the_upward_one(self):
        out = self.run_stats()
        pd.testing.assert_frame_equal(out['ST_RCleared_A_D'], out['ST_RCleared_A_U'])
        self.assertAlmostEqual(out['ST_RCleared_A_D'].loc['f1', 'sum'], 0.3)

    @unittest.expectedFailure
    def test_the_downward_reactive_volume_should_come_from_the_downward_sheet(self):
        out = self.run_stats()
        self.assertAlmostEqual(out['ST_RCleared_A_D'].loc['f2', 'sum'], 0.6)


if __name__ == '__main__':
    unittest.main()
