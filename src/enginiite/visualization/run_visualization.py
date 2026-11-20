"""Every figure of a platform run, in one module called by main.py.

The visualization blocks of main.py were moved here
without changing what they draw, the order in which they draw it, or the folders they write to.  main.py calls:

    import enginiite.visualization.run_visualization as viz

    viz.set_window_mode(params_dict)        # once, after the parameters are read
    viz.case_figures(...)                   # after each case (product, voltage level, bid depth)
    viz.bundle_figures(...)                 # after all cases, before the KPI workbook
    viz.after_kpis(...)                     # after the KPI workbook
    viz.report_stage_times()                # at the very end

Which figure families are drawn is decided by plan(cfg_file), from the visualization section of the YAML file.
"""
import os
import time
from contextlib import contextmanager

import enginiite.visualization.plot_network as plot_net
import enginiite.visualization.market_analytics as mkt_viz
import enginiite.visualization.network_consistency_audit as consistency_viz
import enginiite.visualization.consistency_check as kpi_consistency_viz
from enginiite.visualization import technical_accuracy as tech_viz
from enginiite.visualization import window_mode
from enginiite.visualization.showcase import generate_showcase


# ------------------------------------------------------------------------------------------------ plan
# The visualization YAML is organised in two levels, and this is the ONE place that reads it.
#   1. Always produced, no setting at all:
#        network_topology/              base, pre-market and post-market pages
#        network_technical_analytics/   voltage/congestion heat maps, cleared flexibility, storage,
#                                       not served flexibility
#        showcase/                      storage state of charge, congestion by asset, voltage by bus
#        comparison/technical comparison/   the scenarios of the study side by side
#   2. Every other family is asked for by its CATEGORY (absent means False):
#        consistency_checks     network consistency audit + KPI consistency check
#        kpi_plots              KPI figures of the bundle
# An older configuration that uses the previous per-family keys still works: when a category key is absent,
# its legacy keys (and the legacy master switch 'enabled' / 'run_analytics') are read instead.
VIZ_CATEGORIES = {
    'consistency_checks': ('run_network_consistency_audit', 'run_kpi_consistency_check'),
    'kpi_plots': ('run_kpi_plots',),
}


def plan(cfg_file):
    """Return which figure families this run draws, as a dict of booleans."""
    viz_cfg = cfg_file.get('visualization', {}) or {}
    legacy_master = bool(viz_cfg.get('enabled', viz_cfg.get('run_analytics', True)))   # older configurations only
    result = {'topology': True, 'technical_analytics': True}
    for category, legacy_keys in VIZ_CATEGORIES.items():
        if category in viz_cfg:
            result[category] = bool(viz_cfg[category])
        else:
            result[category] = legacy_master and any(bool(viz_cfg.get(key, False)) for key in legacy_keys)
    return result


# ------------------------------------------------------------------------------------------------ stage timer
# A run ends with several hundred figures; the timer records how long each figure stage takes and prints a
# ranked summary at the end, so that tuning targets the stage that is really slow.
class StageTimer:
    def __init__(self):
        self.marks = []
        self.t0 = time.time()

    @contextmanager
    def stage(self, name):
        start = time.time()
        try:
            yield
        finally:
            self.marks.append((name, time.time() - start))

    def report(self):
        if not self.marks:
            return
        total = time.time() - self.t0
        width = max(len(n) for n, _ in self.marks)
        print()
        print("=" * (width + 26))
        print("STAGE TIMING (slowest first)".center(width + 26))
        print("=" * (width + 26))
        for name, seconds in sorted(self.marks, key=lambda x: -x[1]):
            share = 100.0 * seconds / total if total > 0 else 0.0
            print("  {name:<{w}s} {sec:8.1f} s  {share:5.1f}%".format(name=name, w=width, sec=seconds, share=share))
        print("  {name:<{w}s} {sec:8.1f} s".format(name="TOTAL RUN".ljust(width), w=width, sec=total))
        print("=" * (width + 26))


STAGE_TIMER = StageTimer()


def report_stage_times():
    STAGE_TIMER.report()


# ------------------------------------------------------------------------------------------------ window mode
def set_window_mode(params_dict):
    """Declare once whether the simulation windows are consecutive time steps or independent scenarios.

    Every figure reads this to decide whether a market index may pool the windows or must stay inside one.
    """
    window_mode.set_window_mode(params_dict['window_as_timesteps'])
    print('Simulation windows are interpreted as: {mode}'.format(
        mode='consecutive time steps of one scenario'
        if params_dict['window_as_timesteps'] else 'independent scenarios'))


# ------------------------------------------------------------------------------------------------ one case
def case_figures(cfg_file, file_cfg_name, path_dict, params_dict, net, ts_results, fsp_dict, prod,
                 output_root, output_ts_root, market_file, market_tag, v_min, v_max):
    """Draw the figures of one case into <case>/visualization/.

    net, ts_results: the network and its pre-market time series; output_root, output_ts_root: the case folder and
    its post-market time series; market_file: the market result file (ModelOut[0]); market_tag: the full tag of
    the case, e.g. SB72_CMVC_PQ_VL01_F01_SK01_BIG.
    """
    print("DEBUG full_market_tag for visualization:", market_tag)
    viz_cfg = cfg_file.get('visualization', {}) or {}
    viz_plan = plan(cfg_file)
    visual_root = os.path.join(output_root, 'visualization')      # every family writes its own subfolder here
    os.makedirs(visual_root, exist_ok=True)
    pre_ts_root = path_dict['ts_out_root']
    market_result_file = market_file if os.path.isabs(market_file) else os.path.join(output_root, market_file)

    # 1. Topology: base, pre-market and post-market pages and the comparison dashboard (always produced).
    if viz_plan['topology']:
        prod_for_topology = 'PQ' if 'PQ' in fsp_dict else prod   # PQ holds the complete FSP set
        plot_net.plot_base_pre_post_topology_bundle_html(
            net=net,
            ts_res=ts_results,
            post_market_folder=output_ts_root,
            hour=int(viz_cfg.get('interactive_pf_hour', 0)),
            output_folder=visual_root,
            market_tag=market_tag,
            fsp_data=fsp_dict[prod_for_topology] if viz_cfg.get('plot_fsp_resources', True) else None,
            file_cfg_name=file_cfg_name.replace('.yaml', ''),
            create_base_static_topology=True,
            create_base_topology_html=True,
            create_pre_market_html=True,
            create_post_market_html=True,
            create_comparison_dashboard=True,
            label_mode=viz_cfg.get('topology_label_mode', 'compact'),
            show_bus_labels=viz_cfg.get('show_bus_labels', True),
            show_resource_table=viz_cfg.get('show_resource_table', False),
            save_png=viz_cfg.get('save_png', True),
            save_pdf=viz_cfg.get('save_pdf', True),
            save_svg=viz_cfg.get('save_svg', False),
            dpi=300,
        )

    # 2. Technical analytics: security envelope, voltage/congestion heat maps, activation, storage (always).
    if viz_plan['technical_analytics']:
        with STAGE_TIMER.stage('market analytics (phase 1)'):
            mkt_viz.run_market_analytics_phase1(
                pre_ts_root=pre_ts_root,
                post_ts_root=output_ts_root,
                market_result_file=market_result_file,
                output_folder=visual_root,
                market_tag=market_tag,
                common_output_folder=None,
                vmin=v_min,
                vmax=v_max,
                loading_limit=100.0,
                physical_loading_limit=None,
                cm_detection_limit=params_dict['current_detection_limit'],
                opt_loading_target=params_dict['current_optimization_target'])

    # 3. Technical comparison: the scenarios of the study side by side. Every case redraws it with the sibling
    #    scenarios that have finished, so the last case leaves the whole comparison.
    with STAGE_TIMER.stage('technical comparison figures'):
        tech_viz.technical_comparison(
            pre_ts_root=pre_ts_root,
            post_ts_root=output_ts_root,
            market_result_file=market_result_file,
            output_folder=visual_root,
            market_tag=market_tag,
            vmin=v_min,
            vmax=v_max,
        )

    # 4. Showcase: storage state of charge, congestion by asset and voltage by bus.
    try:
        with STAGE_TIMER.stage('showcase figures'):
            generate_showcase(
                pre_ts_root=pre_ts_root,
                post_ts_root=output_ts_root,
                market_result_file=market_result_file,
                output_folder=visual_root,
                market_tag=market_tag,
                vmin=v_min,
                vmax=v_max,
                loading_limit=100.0,
            )
    except Exception as exc:
        print(f"[Showcase] Visualization skipped: {exc}")


# ------------------------------------------------------------------------------------------------ all cases
def bundle_figures(cfg_file, file_cfg_name, path_dict):
    """Figures of the whole run (all cases), drawn before the KPI workbook: the consistency audit."""
    viz_plan = plan(cfg_file)
    print('Visualization plan: always topology, technical analytics, technical comparison and showcase; optional: '
          + (', '.join(k for k in VIZ_CATEGORIES if viz_plan[k]) or 'none'))
    config_path = os.path.join('config', file_cfg_name)
    if viz_plan['consistency_checks']:
        try:
            consistency_viz.run_network_consistency_audit(scenario_roots=path_dict['net_out_root'],
                                                          config_path=config_path)
        except Exception as exc:
            print(f"[Network Consistency Audit] Visualization skipped: {exc}")


def after_kpis(cfg_file, path_dict):
    """Steps that need the KPI workbook: the KPI consistency check."""
    if plan(cfg_file)['consistency_checks']:
        try:
            outputs = kpi_consistency_viz.run_consistency_check(bundle_root=path_dict['net_out_root'])
            print(f"[KPI Consistency Check] Results saved in: {outputs['output_dir']}")
        except Exception as exc:
            print(f"[KPI Consistency Check] Analysis skipped: {exc}")
