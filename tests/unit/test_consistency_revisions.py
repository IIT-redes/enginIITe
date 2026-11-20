import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

from enginiite import tolerance_policy
from enginiite.kpis import eval_kpis
from enginiite.market import run_flex_market
from enginiite.market.models import load_model
from enginiite.network import flex_eval
from enginiite.network import sensitivity_factors
from enginiite.visualization import accuracy_core
from enginiite.visualization import technical_accuracy
from enginiite.visualization import figure_helpers
from enginiite.visualization import consistency_check


# Regression coverage that keeps the tolerance policy, the P-linked Q sensitivity and the accuracy definitions
# synchronized.
class ConsistencyRevisionTests(unittest.TestCase):
    def test_tolerance_policy_uses_inward_percent_margins(self):
        v = tolerance_policy.voltage_limits("VL01", tol_v=3, tol_v_opt=1.03)
        i = tolerance_policy.current_limits(tol_i=3, tol_i_opt=2)
        self.assertAlmostEqual(v["detection_min_pu"], 0.95 * 1.03)
        self.assertAlmostEqual(v["detection_max_pu"], 1.05 * 0.97)
        self.assertAlmostEqual(v["optimization_min_pu"], 0.95 * 1.0403)
        self.assertAlmostEqual(v["optimization_max_pu"], 1.05 * 0.9597)
        self.assertEqual(v["optimization_tolerance_percent"], 4.03)
        self.assertEqual(i["standard_percent"], 100.0)
        self.assertEqual(i["detection_limit_percent"], 97.0)
        self.assertEqual(i["optimization_target_percent"], 95.0)

        vmin_opt, vmax_opt = run_flex_market._resolve_voltage_optimization_limits(
            v["detection_min_pu"],
            v["detection_max_pu"],
            0.0103,
            v["optimization_min_pu"],
            v["optimization_max_pu"],
        )
        self.assertAlmostEqual(vmin_opt, 0.95 * 1.0403)
        self.assertAlmostEqual(vmax_opt, 1.05 * 0.9597)

        with self.assertRaisesRegex(ValueError, "Explicit _vmin_opt"):
            run_flex_market._resolve_voltage_optimization_limits(
                v["detection_min_pu"], v["detection_max_pu"], 0.0103
            )

    def test_voltage_policy_warns_on_collapse_and_rejects_inversion(self):
        with self.assertWarnsRegex(RuntimeWarning, "extremely narrow"):
            collapsed = tolerance_policy.voltage_limits("VL01", tol_v=3, tol_v_opt=2)
        self.assertAlmostEqual(collapsed["optimization_min_pu"], 0.9975)
        self.assertAlmostEqual(collapsed["optimization_max_pu"], 0.9975)
        with self.assertRaisesRegex(ValueError, "minimum .* exceeds maximum"):
            tolerance_policy.voltage_limits("VL01", tol_v=4, tol_v_opt=2)

    def test_full_network_selects_all_without_fake_minus_one_threshold(self):
        net = SimpleNamespace(
            line=pd.DataFrame(
                {"name": ["L0", "L1"], "max_i_ka": [0.21, 0.21], "from_bus": [0, 0]},
                index=[0, 1],
            ),
            bus=pd.DataFrame({"vn_kv": [15.0]}, index=[0]),
        )
        loading = pd.DataFrame({0: [40.0, 50.0], 1: [101.0, 80.0]}, index=[0, 1])
        _, _, target_margin, _, needs, assets = flex_eval.flex_needs_lines(
            net, loading, _tol_opt=2.0, _overload_limit=98.0, _include_all=True
        )
        self.assertEqual(list(assets), [0, 1])
        self.assertEqual(needs.loc[0, "L0"], 0.0)
        self.assertGreater(needs.loc[0, "L1"], 0.0)
        self.assertAlmostEqual(target_margin.loc[0, "L0"], np.sqrt(3) * 0.21 * 15.0 * 0.04)
        self.assertAlmostEqual(target_margin.loc[0, "L1"], np.sqrt(3) * 0.21 * 15.0 * 0.04)
        self.assertAlmostEqual(target_margin.loc[1, "L1"], np.sqrt(3) * 0.21 * 15.0 * 0.04)

        _, _, selected_margin, _, _, selected_assets = flex_eval.flex_needs_lines(
            net, loading, _tol_opt=2.0, _overload_limit=98.0, _include_all=False
        )
        self.assertEqual(list(selected_assets), [1])
        self.assertGreater(selected_margin.loc[0, "L1"], 0.0)
        self.assertGreater(selected_margin.loc[1, "L1"], 0.0)

    def test_exact_threshold_equality_is_compliant(self):
        ts_results = {"bus_vm_pu": pd.DataFrame({0: [0.95, 1.05]})}
        with mock.patch.object(flex_eval.io_file, "save_excel"), mock.patch.object(
            flex_eval.io_file, "save_cvs"
        ):
            outbounds, _, _, hours = flex_eval.flex_needs_buses(
                ts_results, 1.05, 0.95, ["/unused", "/unused"], ["v", "h"]
            )
        self.assertTrue(outbounds.empty)
        self.assertEqual(len(hours), 0)

        status = eval_kpis._congestion_transition_counts(
            pd.DataFrame([[100.0]]), pd.DataFrame([[100.0]]), 100.0
        )
        self.assertEqual(status["pre"], 0)
        self.assertEqual(status["post"], 0)

    def test_p_only_loads_reactive_sensitivity(self):
        matrix = pd.DataFrame([[2.0]], index=["fsp"], columns=["L1"])
        with mock.patch.object(run_flex_market.io_file, "import_data", return_value=matrix):
            cm, _ = run_flex_market._load_sens_matrix(
                {"A": {"contrib": 1}}, [0], 1, 0, "/unused", "CM", "P", "case", -1
            )
        self.assertAlmostEqual(cm["A"][0]["R"].iloc[0, 0], -2.0)

    def test_fixed_power_factor_uses_signed_q_over_p_without_mutation(self):
        self.assertAlmostEqual(load_model._safe_q_over_p(4.0, 2.0), 0.5)
        self.assertEqual(load_model._safe_q_over_p(0.0, 2.0), 0.0)
        self.assertEqual(
            load_model._fixed_power_factor_q_bounds(3.0, 5.0, 4.0, 2.0),
            (1.5, 2.5),
        )

    def test_sensitivity_cache_requires_every_pair_member_and_voltage_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            p_path = Path(tmp, "P.csv")
            q_path = Path(tmp, "Q.csv")
            p_path.write_text("x", encoding="utf-8")
            self.assertTrue(
                sensitivity_factors._should_recalculate_cache(False, str(p_path), str(q_path))
            )
            q_path.write_text("x", encoding="utf-8")
            self.assertFalse(
                sensitivity_factors._should_recalculate_cache(False, str(p_path), str(q_path))
            )
            self.assertTrue(
                sensitivity_factors._should_recalculate_cache(True, str(p_path), str(q_path))
            )
        self.assertAlmostEqual(
            sensitivity_factors._signed_voltage_sensitivity(1.01, 1.00, 0.01), -1.0
        )

    def test_main_uses_current_fsp_diagnostic_flag_and_same_post_scope(self):
        source = Path("src/enginiite/workflow.py").read_text(encoding="utf-8")
        self.assertIn("import enginiite.market.run_flex_market as flx_mrk", source)
        self.assertNotIn("runf_flex_market_old", source)
        self.assertNotIn("run_market_old", source)
        self.assertNotIn("flex_eval_old", source)
        self.assertIn("params_dict['save_invJ'].get(fsp, False)", source)
        post_call = source[source.index("# Evaluate Congestion Flexibility Needs after"):]
        self.assertIn("_full_net=params_dict['full_net']", post_call)

    def test_voltage_accuracy_is_ac_minus_va_minus_alpha(self):
        market = {
            "VA": pd.DataFrame([[1.02]], index=[0], columns=[0]),
            "alpha_DVpu": pd.DataFrame([[0.01]], index=[0], columns=[0]),
        }
        linear = accuracy_core._linear_voltage_matrix("/missing", market)
        self.assertAlmostEqual(linear.iloc[0, 0], 1.01)

    def test_avoided_kpis_report_three_named_thresholds(self):
        scenario = "net_CMVC_P_VL01_F01_SK01_T1"
        table_pre = {scenario: pd.DataFrame([[101.0]])}
        table_post = {scenario: pd.DataFrame([[97.0]])}
        data = {
            "lines_ldg_perc_pre": table_pre,
            "trafos_ldg_perc_pre": {},
            "trafos3w_ldg_perc_pre": {},
            "lines_ldg_perc_post": table_post,
            "trafos_ldg_perc_post": {},
            "trafos3w_ldg_perc_post": {},
            "i_max_perc_pre": 100.0,
            "i_max_perc_post": 100.0,
            "current_thresholds": tolerance_policy.current_limits(2, 2),
        }
        result = eval_kpis.avoided_cong(data, [scenario])
        self.assertIn("AvoidCongestion_standard [%]", result.columns)
        self.assertIn("AvoidCongestion_detection [%]", result.columns)
        self.assertIn("AvoidCongestion_optimization [%]", result.columns)
        self.assertIn("ResolvedCongestion_standard [u]", result.columns)
        self.assertIn("PersistentCongestion_standard [u]", result.columns)
        self.assertIn("NewCongestion_standard [u]", result.columns)
        self.assertNotIn("AvoidCongestions [%]", result.columns)

        voltage_data = {
            "vl_lims": ["VL01"],
            "scenarios_selected": [scenario],
            "bus_vmpu_pre": {scenario: pd.DataFrame([[0.94, 1.06]])},
            "bus_vmpu_post": {scenario: pd.DataFrame([[0.96, 1.04]])},
            "voltage_thresholds": {"VL01": tolerance_policy.voltage_limits("VL01", 0.5, 0.5)},
        }
        voltage_result = eval_kpis.avoided_voltage_violations(voltage_data)
        self.assertIn("AvoidVoltage_standard [%]", voltage_result.columns)
        self.assertIn("AvoidVoltage_detection [%]", voltage_result.columns)
        self.assertIn("AvoidVoltage_optimization [%]", voltage_result.columns)
        self.assertNotIn("AvoidVoltageViolations [%]", voltage_result.columns)
        self.assertNotIn("AvoidVoltageViolations [u]", voltage_result.columns)

    def test_avoided_plots_use_threshold_columns_without_legacy_names(self):
        scenario = "net_CMVC_P_VL01_F01_SK01_T1"
        congestion = pd.DataFrame({
            "AvoidCongestion_standard [u]": [3.0],
            "AvoidCongestion_detection [u]": [2.0],
            "AvoidCongestion_optimization [u]": [1.0],
            "AvoidCongestion_standard [%]": [75.0],
            "AvoidCongestion_detection [%]": [50.0],
            "AvoidCongestion_optimization [%]": [-25.0],
        }, index=[scenario])
        voltage = pd.DataFrame({
            "AvoidVoltage_standard [u]": [6.0],
            "AvoidVoltage_detection [u]": [5.0],
            "AvoidVoltage_optimization [u]": [4.0],
            "AvoidVoltage_standard [%]": [60.0],
            "AvoidVoltage_detection [%]": [50.0],
            "AvoidVoltage_optimization [%]": [40.0],
        }, index=[scenario])

        # Regression coverage that prevents the removed legacy KPI headings from breaking the plotting at the end
        # of a simulation.
        with mock.patch.object(eval_kpis.plt_kpi, "bar_avoid_violations", return_value="figure") as plot:
            result = eval_kpis.avoided_cong_plots(
                congestion, [scenario], "case", [[], []]
            )
            self.assertEqual(result, "figure")
            count_table, percentage_table = plot.call_args.args[:2]
            self.assertEqual(
                list(count_table.columns),
                ["Standard", "Detection", "Optimization"],
            )
            self.assertEqual(
                list(percentage_table.columns),
                ["Standard", "Detection", "Optimization"],
            )

            result = eval_kpis.avoided_voltage_viol_plots(
                voltage, [scenario], "case", [[], []]
            )
            self.assertEqual(result, "figure")
            count_table, percentage_table = plot.call_args.args[:2]
            self.assertEqual(
                list(count_table.columns),
                ["Standard", "Detection", "Optimization"],
            )
            self.assertEqual(
                list(percentage_table.columns),
                ["Standard", "Detection", "Optimization"],
            )

    def test_avoided_plot_helper_remains_legacy_compatible(self):
        legacy = pd.DataFrame({
            "AvoidCong_L[u]": [2.0],
            "AvoidCong_T[u]": [1.0],
            "AvoidCong_T3w[u]": [0.0],
            "AvoidCongestions [%]": [50.0],
        })
        count_table, percentage_table = eval_kpis._avoidance_plot_tables(
            legacy,
            ["AvoidCongestion_standard [u]"],
            ["AvoidCongestion_standard [%]"],
            ["AvoidCong_L[u]", "AvoidCong_T[u]", "AvoidCong_T3w[u]"],
            "AvoidCongestions [%]",
        )
        self.assertEqual(list(count_table.columns), ["Lines", "Trafo_2windings", "Trafo_3windings"])
        self.assertEqual(list(percentage_table.columns), ["Overall"])

    def test_accuracy_color_scales_use_full_finite_ranges(self):
        self.assertEqual(technical_accuracy._finite_abs_max([[-2.0, np.nan], [1.0, np.inf]]), 2.0)
        self.assertEqual(technical_accuracy._finite_abs_max([[0.0]]), 1.0)

    def test_shared_visualization_polish_wraps_subplot_titles(self):
        figure = technical_accuracy.make_subplots(
            rows=1,
            cols=2,
            subplot_titles=(
                "A very long congestion subplot title that must remain inside the first panel",
                "A very long voltage subplot title that must remain inside the second panel",
            ),
        )
        figure_helpers._polish_axis_units_and_overlap(figure)
        self.assertTrue(all("<br>" in str(annotation.text) for annotation in figure.layout.annotations))
        self.assertGreaterEqual(figure.layout.margin.t, 145)
        self.assertTrue(all(annotation.font.size <= 13 for annotation in figure.layout.annotations))

    def test_themed_visualization_places_definitions_below_figure(self):
        figure = technical_accuracy.make_subplots(rows=1, cols=1)
        figure.add_scatter(x=[1, 2], y=[3, 4])
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp, "figure.html")
            figure_helpers._write_themed_plotly_html(
                figure,
                str(html_path),
                "Test figure",
                figure_note="Std = physical standard; REVIEW = diagnostic warning.",
            )
            rendered = html_path.read_text(encoding="utf-8")
        self.assertIn('class="figure-note"', rendered)
        self.assertIn("Std = physical standard", rendered)
        self.assertIn("white-space: pre-line", rendered)
        self.assertLess(rendered.index("plotly-graph-div"), rendered.index('class="figure-note"'))

    def test_consistency_heatmap_hides_redundant_scale_and_explains_rules(self):
        scenario = "net_CMVC_P_VL01_F01_SK01_T1"
        data = pd.DataFrame([{
            "product": "P", "flex_number": 1, "short_label": "P-F01", "voltage_level": "VL01",
            "objective_eur": 1000.0, "cost_alpha_eur": 20.0, "cost_beta_eur": 30.0,
            "active_cost_eur": 40.0, "reactive_cost_eur": 50.0,
            "data_complete": True, "threshold_order_ok": True,
            "congestion_count_monotonic": True, "congestion_cost_resolution_match": False,
            "voltage_cost_resolution_match": True, "deterioration_detected": False,
        }], index=[scenario])
        data.attrs["resolution_tolerance"] = 1e-9
        data.attrs["cost_tolerance"] = 1e-6
        with tempfile.TemporaryDirectory() as tmp:
            cost_path = consistency_check._cost_heatmap_figure(data, Path(tmp))
            status_path = consistency_check._status_matrix_figure(data, Path(tmp))
            cost_html = Path(cost_path).read_text(encoding="utf-8")
            status_html = Path(status_path).read_text(encoding="utf-8")
        self.assertNotIn('"showscale":true', cost_html)
        self.assertNotIn("Relative magnitude", cost_html)
        for rule_text in (
            "1. Data complete", "2. Threshold order", "3. Counts monotonic",
            "4. Beta vs Opt", "5. Alpha vs Opt", "6. No deterioration", "Overall result",
        ):
            self.assertIn(rule_text, status_html)

    def test_colorbar_geometry_and_numeric_direction_are_preserved(self):
        figure = technical_accuracy.go.Figure(technical_accuracy.go.Heatmap(
            z=[[1.0, 2.0]], zmin=5.0, zmax=-2.0,
            colorbar=dict(len=0.31, y=0.78),
        ))
        figure.update_yaxes(range=[8.0, -1.0])
        figure_helpers._update_colorbar_ieee(figure.data[0].colorbar)
        figure_helpers._enforce_ascending_numeric_ranges(figure)
        self.assertAlmostEqual(figure.data[0].colorbar.len, 0.31)
        self.assertAlmostEqual(figure.data[0].colorbar.y, 0.78)
        self.assertEqual(tuple(figure.layout.yaxis.range), (-1.0, 8.0))
        self.assertAlmostEqual(figure.data[0].zmin, -2.0)
        self.assertAlmostEqual(figure.data[0].zmax, 5.0)

    def test_security_trend_uses_two_explicit_ascending_axes(self):
        rows = []
        for product in ("P", "Q", "PQ"):
            for flex_number in (1, 2):
                rows.append({
                    "scenario": f"net_CMVC_{product}_VL01_F0{flex_number}_SK01_T1",
                    "product": product,
                    "flex_case": f"F0{flex_number}",
                    "flex_level": flex_number,
                    "security_score": 40.0 + 10.0 * flex_number,
                    "residual_hours": 12.0 - flex_number,
                    "cm_relief_pct": 50.0,
                    "voltage_relief_pct": 60.0,
                    "short_label": f"{product}-F0{flex_number}",
                })
        with mock.patch.object(
            technical_accuracy,
            "_save_comparison_fig",
            side_effect=lambda figure, *_args, **_kwargs: figure,
        ):
            figure = technical_accuracy.plot_technical_security_trend_by_flex(
                pd.DataFrame(rows), "/unused", "net_CMVC_SK01_T1"
            )
        self.assertEqual(tuple(figure.layout.yaxis.range), (0.0, 100.0))
        self.assertLess(figure.layout.yaxis2.range[0], figure.layout.yaxis2.range[1])
        self.assertTrue(figure.layout.xaxis.showticklabels)
        self.assertTrue(figure.layout.xaxis2.showticklabels)

    def test_congestion_transitions_separate_resolved_persistent_and_new(self):
        pre = pd.DataFrame([[101.0, 99.0], [102.0, 97.0]])
        post = pd.DataFrame([[99.0, 101.0], [103.0, 97.0]])
        status = eval_kpis._congestion_transition_counts(pre, post, 100.0)
        self.assertEqual(status['resolved'], 1)
        self.assertEqual(status['persistent'], 1)
        self.assertEqual(status['new'], 1)
        self.assertEqual(status['pre'], status['resolved'] + status['persistent'])
        self.assertEqual(status['post'], status['persistent'] + status['new'])
        self.assertEqual(status['net_resolved'], status['resolved'] - status['new'])

        partial_post = post.drop(columns=[0])
        partial_status = eval_kpis._congestion_transition_counts(pre, partial_post, 100.0)
        self.assertEqual(partial_status['persistent'], 2)
        self.assertEqual(partial_status['resolved'], 0)

    def test_consistency_check_separates_structural_failure_from_review(self):
        row = {
            "data_complete": True,
            "cost_alpha_eur": 0.0,
            "cost_beta_eur": 25.0,
            "active_cost_eur": 10.0,
            "reactive_cost_eur": 5.0,
            "reported_total_cost_eur": np.nan,
            "voltage_min_standard_pu": 0.95,
            "voltage_min_detection_pu": 0.96,
            "voltage_min_optimization_pu": 0.97,
            "voltage_max_standard_pu": 1.05,
            "voltage_max_detection_pu": 1.04,
            "voltage_max_optimization_pu": 1.03,
            "current_limit_standard_pct": 100.0,
            "current_limit_detection_pct": 98.0,
            "current_limit_optimization_pct": 95.0,
            "avoid_voltage_standard_pct": 100.0,
            "avoid_voltage_detection_pct": 100.0,
            "avoid_voltage_optimization_pct": 100.0,
            "avoid_congestion_standard_pct": 100.0,
            "avoid_congestion_detection_pct": 100.0,
            "avoid_congestion_optimization_pct": 100.0,
        }
        for threshold, resolved, persistent, new in (
            ("standard", 2.0, 0.0, 0.0),
            ("detection", 3.0, 0.0, 0.0),
            ("optimization", 4.0, 0.0, 0.0),
        ):
            row[f"resolved_congestion_{threshold}"] = resolved
            row[f"persistent_congestion_{threshold}"] = persistent
            row[f"new_congestion_{threshold}"] = new

        result = consistency_check._evaluate_consistency(
            pd.DataFrame([row], index=["net_CMVC_P_VL01_F01_SK01_T1"]),
            resolution_tolerance=1e-9,
            cost_tolerance=1e-6,
        ).iloc[0]
        self.assertTrue(result["threshold_order_ok"])
        self.assertTrue(result["congestion_count_monotonic"])
        self.assertFalse(result["congestion_cost_resolution_match"])
        self.assertEqual(result["overall_status"], "REVIEW")
        self.assertAlmostEqual(result["analysis_total_cost_eur"], 40.0)


if __name__ == "__main__":
    unittest.main()
