import os
import time
import json
import copy as cp
import shutil  # Consolidated case folder

import pandas as pd
import enginiite.auxiliary as aux
import enginiite.pathcheck as pathcheck
import enginiite.file_io as io_file
import enginiite.kpis.eval_kpis as kpi_fcn
import enginiite.network.flex_eval as feval
import enginiite.network.ac_market_validation as ac_validation
import enginiite.network.run_network as rnet
import enginiite.market.run_flex_market as flx_mrk
import enginiite.network.sensitivity_factors as calc_sens
# every figure of a run is drawn by one module
import enginiite.visualization.run_visualization as viz


# A run can take hours. On a Windows laptop, Modern Standby can pause Python and Gurobi
# whenever the screen times out, until someone wakes the machine. While a run is active
# it asks Windows to keep the system and the display on (the request ends with the
# process). Closing the lid can still put a laptop to sleep, depending on its power
# settings. Set keep_awake: False in the YAML to turn this off.
def _keep_system_awake(_enabled=True):
    if not _enabled or os.name != 'nt':
        return False
    try:
        import ctypes
        es_continuous, es_system_required, es_display_required = 0x80000000, 0x00000001, 0x00000002
        ok = ctypes.windll.kernel32.SetThreadExecutionState(
            es_continuous | es_system_required | es_display_required)
        if ok:
            print('Keep-awake: Windows will not sleep or turn the screen off while this run is active.')
        return bool(ok)
    except Exception as exc:
        print(f'Keep-awake request failed ({exc}); keep the laptop awake manually.')
        return False


def resolve_simulation_tag(cfg_file, file_cfg_name):
    """Return the simulation tag of a run and make sure the configuration carries it.

    Older or regenerated scenario files may leave ``simulation_tag`` empty or absent. A short, unique tag is then
    derived from the configuration file name instead of aborting the complete batch. The derived tag is written back
    to ``cfg_file``, because later steps (the KPIs) read the tag from the configuration and look for files named
    with it.
    """
    simulation_tag = cfg_file.get('simulation_tag')
    if simulation_tag is None or str(simulation_tag).strip() == "":
        config_stem = os.path.splitext(os.path.basename(str(file_cfg_name)))[0]
        simulation_tag = config_stem.removeprefix('config_') or "NoTag"
        print(
            "  Warning: simulation_tag is absent; using "
            f"'{simulation_tag}' derived from the configuration filename."
        )
        cfg_file['simulation_tag'] = simulation_tag
    return simulation_tag


def run(file_cfg_name, output=None):
    """Run every scenario of one configuration file.

    The file is read from the ``config`` folder of the working folder, and the inputs and the results are
    read and written under the same working folder (``data_in`` and ``data_out``). ``output`` sends the
    results to another folder. Use ``enginiite run`` to start a run from anywhere.
    """
    start_time = time.time() # Start timer

    if not file_cfg_name.lower().endswith(('.yaml', '.yml')):
        raise ValueError(
            'The configuration filename must include .yaml or .yml.'
        )
    print(f'Selected configuration: {file_cfg_name}')
    
    # Import Yaml Config File
    cfg_file = io_file.import_yaml(_yaml_filename=file_cfg_name, _folder='config')
    # No standby while the run is active.
    _keep_system_awake(bool(cfg_file.get('keep_awake', True)))
    simulation_tag = resolve_simulation_tag(cfg_file, file_cfg_name)
    # Define General Directories
    path_dict = aux.set_paths(_main_root=os.getcwd(), _name_network=cfg_file['network']['net_folder'],
                              _model_tag=cfg_file['ModelTAG'], _product_tags=cfg_file['ProductTAG'],
                              _vl_tags=cfg_file['VLTAG'], _fsp_tags=cfg_file['FspTAG'], _ess_tag=cfg_file['StorageTag'],
                              _sim_tag=simulation_tag, _in_root='data_in',
                              _out_root='data_out' if output is None else str(output))
    # Windows refuses long paths unless they are enabled; say so now instead of failing minutes into the run
    path_warning = pathcheck.check_output_paths(path_dict)
    if path_warning:
        print(f'  {path_warning}')

    # Define General Parameters
    params_dict = aux.set_params(_cfg_file=cfg_file, _path_dict=path_dict, _vl_tags=cfg_file['VLTAG'],
                                 _fsp_tags=cfg_file['FspTAG'], _ess_tag=cfg_file['StorageTag'])

    # Declare once whether the entries of simulation_window are
    # consecutive time steps of one scenario or independent scenarios (read by every figure).
    viz.set_window_mode(params_dict)

    # Load Pandapower Network
    net = io_file.import_network(cfg_file['network'])
    net_post_pre = cp.deepcopy(net)

    # Import Network Profiles
    dict_profiles_s01 = io_file.import_profiles_s01(_cfg_file=cfg_file, _pp_net=net, _timestep=params_dict['timestep'])
    # Optional supply voltage of the external grid per
    # time step (network.ext_grid_profile); it joins the pre-market and every post-market time series.
    ext_grid_profile = io_file.import_ext_grid_profile(_cfg_file=cfg_file, _pp_net=net,
                                                       _timestep=params_dict['timestep'])
    if ext_grid_profile is not None:
        dict_profiles_s01['ext_grid_vm'] = ext_grid_profile

    # Load FSP Dictionary Data
    fsp_dict, _ = io_file.import_fsp_data(cfg_file['network'])

    # Run Timeseries Power Flow
    force_ts = params_dict['force_ts']
    ts_results = rnet.run_pf_timeseries(_pp_net=net, _dict_profiles=dict_profiles_s01, _time_steps=params_dict['timestep'],
                                        _out_root=path_dict['ts_out_root'], _out_filetype=params_dict['ts_output_file_type'],
                                        _all_steps=True, _force_ts=force_ts, res_bus=['vm_pu'], res_line=['loading_percent'],
                                        res_load=['p_mw', 'q_mvar'], res_sgen=['p_mw', 'q_mvar'], res_storage=['p_mw', 'q_mvar'],
                                        res_trafo=['loading_percent'], res_trafo3w=['loading_percent'])

    for prod in cfg_file['ProductTAG']:
        for vl in cfg_file['VLTAG']:
            v_max = params_dict['vbus_max'][vl]
            v_min = params_dict['vbus_min'][vl]
            # Detection uses the tol_v
            # limits above; optimization uses tol_v + tol_v_opt explicitly.
            v_max_opt = params_dict['vbus_max_opt'][vl]
            v_min_opt = params_dict['vbus_min_opt'][vl]
            for fsp in cfg_file['FspTAG']:
                net_post = cp.deepcopy(net_post_pre)
                print('\n----- Simulating Scenario: {a} {b} {c} {d} {e} -----'
                      .format(a=cfg_file['ModelTAG'], b=prod, c=vl, d=fsp, e=cfg_file['StorageTag']))
                # Define Simulation Parameters
                output_root = path_dict['mrk_outputs']['res_market'][prod][vl][fsp]
                output_ts_root = path_dict['mrk_outputs']['ts_postmrk_out_root'][prod][vl][fsp]
                input_root = path_dict['mrk_inputs'][prod][vl][fsp]
                market_tag = path_dict['simulation_tag'][prod][vl][fsp]
                # Build the full scenario tag (Network_Model_Product_Voltage_Flex_Storage_Simulation) before the
                # corrective-market loop, because the activation churn CSVs of the loop use it.
                network_tag = cfg_file['network']['net_folder']
                model_tag = cfg_file['ModelTAG']
                storage_tag = cfg_file['StorageTag']
                full_market_tag = (
                    f"{network_tag}_"
                    f"{model_tag}_"
                    f"{prod}_"
                    f"{vl}_"
                    f"{fsp}_"
                    f"{storage_tag}_"
                    f"{simulation_tag}"
                )

                # Evaluate Voltage Flexibility Needs
                vbus_outbounds, _, _, VCHoursToStudy = feval.flex_needs_buses(_ts_res=ts_results, _v_max=v_max, _v_min=v_min,
                                                                              _folders=[output_root, input_root],
                                                                              _filenames=['VM_Problems_Stats_preMKT', 'VCHoursToStudy'])

                # Evaluate Congestion Flexibility Needs
                smax_mva, sinit_mva, deltas_max_df, pilot_asset, \
                idx_clines, idx_ctrafo2w, idx_ctrafo3w,\
                CMHoursToStudy, cong_needs_df,\
                cong_assets = feval.congestion_needs(_net=net, _ts_res=ts_results, _llimit=params_dict['line_overload_limit'],
                                                     _tlimit=params_dict['trafo_overload_limit'], _di_tol_opt=params_dict['di_tol_opt'],
                                                     _full_net=params_dict['full_net'], _folders=[output_root, input_root],
                                                     _filenames=['total_cm_PreMKT', 'CMHoursToStudy'])

                # Define hours to study
                HoursToStudy = feval.get_sim_hours(_model=cfg_file['ModelTAG'], _timesteps=params_dict['timestep'],
                                                   _v_out=vbus_outbounds, _br_cong=cong_needs_df.T, _input_root=input_root,
                                                   _v_min=v_min, _v_max=v_max, _only_worst_hour=params_dict['only_worst_hour'],
                                                   _intertemp_cons=params_dict['intertemp_cons'])
                s_mva_init = sinit_mva.T.loc[:, HoursToStudy]
                ds_mva = deltas_max_df.T.loc[:, HoursToStudy]
                cong_needs = cong_needs_df.T.loc[:, HoursToStudy]

                # Define FSP Parameters File
                fsp_file, fsp_bus = aux.fsp_converter(_net=net, _ts_res=ts_results, _fsp_data=fsp_dict[prod],
                                                      _out_root=input_root, _hours=HoursToStudy, _params_dict=params_dict,
                                                      _cfg_file=cfg_file, _fsp_tag=fsp, _sim_tag=market_tag, _k_opt=1)

                # Define the Pilot Buses for Voltage Control
                pilot_bus, pilot_bus_hts, out_bus = rnet.select_pilot_bus(_net=net, _bus_voltages=ts_results['bus_vm_pu'],
                                                                          _fsp_data=fsp_dict[prod], _vbus_outbounds=vbus_outbounds,
                                                                          _hours=HoursToStudy, _vn_kv_mv=cfg_file['vn_kv_mv'],
                                                                          _out_root=input_root,
                                                                          _flag_vpilot=cfg_file['debug_save_VPilotBus_FULLH'],
                                                                          _flag_only_mv=cfg_file['only_pilot_busMV'],
                                                                          _flag_all_net=params_dict['full_net'])

                # independent-scenario mode.
                # With simulation_window_as_timesteps False every window is an independent scenario: it monitors only
                # the branches and buses outside the operational limits (tol_i, tol_v included) in ITS OWN operating
                # point, its post-clearing AC power-flow validation is judged on its own, and only the scenarios
                # still insecure are re-cleared by a corrective iteration.  With True (one scenario over consecutive
                # time steps) the represented set stays shared by every hour and the corrective loop case-wide.
                # With full_network every scenario monitors everything anyway, so only the corrective decision
                # becomes per scenario.
                independent_snapshots = ac_validation.independent_snapshot_mode(
                    params_dict['window_as_timesteps'], params_dict['consec_hours'], params_dict['intertemp_cons'])
                study_hours = [h for h in HoursToStudy]
                snapshot_assets = snapshot_buses = None
                if independent_snapshots and not params_dict['full_net']:
                    snapshot_assets = ac_validation.snapshot_asset_sets(cong_needs, study_hours)
                    snapshot_buses = ac_validation.snapshot_bus_sets(
                        pilot_bus, ts_results['bus_vm_pu'], v_min, v_max, fsp_dict[prod].bus, study_hours)
                print('Scenario mode: {m} ({n} windows).'.format(
                    m='independent scenarios (per-scenario sets and corrective iterations)' if independent_snapshots
                    else 'one scenario over consecutive time steps (shared sets, case-wide corrective loop)',
                    n=len(study_hours)))

                # Evaluate Voltage Control Sensitivity Factors Calculation
                calc_sens.calc_sens_factors_vc(_net=net_post_pre, _fsp_file=fsp_file, _fsp_bus=fsp_bus, _ts_res=ts_results,
                                               _pilot_bus=pilot_bus, _hours=HoursToStudy, _sens_type='PQ',
                                               _dp=params_dict['vc_deltaP_coeff'], _dq=params_dict['vc_deltaQ_coeff'],
                                               _path_matrix=path_dict['sens_matrix_root'], _sim_tag=simulation_tag,
                                               # Pass the current
                                               # FSP's diagnostic flag, not the complete dictionary.
                                               _force_hvm=params_dict['force_HVM'],
                                               _save_inv_js=params_dict['save_invJ'].get(fsp, False))

                # Evaluate Congestion Management Sensitivity Factors Calculation
                calc_sens.calc_sens_factors_cm(_net=net_post_pre, _fsp_file=fsp_file, _fsp_bus=fsp_bus, _ts_res=ts_results,
                                               _cm_branch=idx_clines, _cm_trafo=idx_ctrafo2w, _cm_trafo3w=idx_ctrafo3w,
                                               _hours=HoursToStudy, _dp=params_dict['cm_deltaP_coeff'],
                                               _dq=params_dict['cm_deltaQ_coeff'], _path_matrix=path_dict['sens_matrix_root'],
                                               _sens_type='PQ', _sim_tag=simulation_tag, _sens_mode='VSGEN', _only_ds=True,
                                               _force_hcm=params_dict['force_HCM'],
                                               # HCM basis (cm_sensitivity_basis).
                                               _sens_basis=params_dict['cm_sensitivity_basis'])

                # Keep the canonical
                # tol_v/tol_i AC acceptance limits fixed. If the linear market
                # and nonlinear AC result disagree, recompute HVM/HCM at the
                # latest AC operating point in an iteration-specific folder and
                # clear an incremental sequential-linear market step.
                ac_validation_enabled = params_dict['ac_validate_post_market']
                max_ac_corrections = (
                    params_dict['max_corrective_market_running']
                    if ac_validation_enabled else 0
                )
                market_ds_tol = ds_mva.copy(deep=True)
                market_vmin_opt = v_min_opt
                market_vmax_opt = v_max_opt
                market_s_init = s_mva_init
                market_cong_needs = cong_needs
                market_hours_cm = CMHoursToStudy
                market_v_before = pilot_bus_hts.T
                market_matrix_root = path_dict['sens_matrix_root']
                market_fsp_file = fsp_file
                cumulative_market_archive = None
                # Keep every cumulative
                # archive of this case so the sequence can be decomposed after the
                # loop into what was finally committed, what was activated on the
                # way there, and what one iteration procured and a later iteration undid.
                cumulative_market_archives = []
                ac_validation_rows = []
                ac_stage_roots = []
                # the scenarios the next market clears (every
                # scenario in the main market; with independent scenarios, only those still insecure afterwards),
                # and one row per scenario and iteration for ACMarketValidationBySnapshot.csv.
                active_hours = list(study_hours)
                snapshot_rows = []
                for ac_iteration in range(max_ac_corrections + 1):
                    # A fresh network is required because pandapower attaches
                    # time-series controllers during every AC validation run.
                    net_post = cp.deepcopy(net_post_pre)

                    # consecutive time steps always clear every hour.
                    round_hours = list(active_hours) if independent_snapshots else list(study_hours)
                    partial_round = len(round_hours) < len(study_hours)
                    ModelOut = flx_mrk.flex_market(_fsp_file=market_fsp_file, _hours=round_hours, _pilot_asset=pilot_asset,
                                                   _pilot_bus=pilot_bus, _in_root=input_root, _out_root=output_root,
                                                   _matrix_root=market_matrix_root, _v_before=market_v_before,
                                                   _vmin=v_min, _vmax=v_max, _dv_tol_opt=params_dict['dv_tol_opt'],
                                                   _vmin_opt=market_vmin_opt, _vmax_opt=market_vmax_opt,
                                                   _outbounds_bus=out_bus, _smax=smax_mva, _sinit=market_s_init,
                                                   _ds_tol=market_ds_tol, _cong_needs=market_cong_needs,
                                                   _cong_assets=cong_assets, _alpha_cost=params_dict['alpha_cost'],
                                                   _beta_cost=params_dict['beta_cost'], _mrk_tag=market_tag,
                                                   _sim_tag=simulation_tag, _consec_h=params_dict['consec_hours'],
                                                   _hours_vc=VCHoursToStudy, _hours_cm=market_hours_cm,
                                                   _net_mrk=params_dict['net_in_market'],
                                                   _cap_cstr=params_dict['cap_curve_cons'], _dt=params_dict['dt'],
                                                   _int_soc=params_dict['intertemp_cons'],
                                                   _cm_factor=params_dict['cm_factor'],
                                                   _mip_focus=params_dict['mip_focus'], _mip_gap=params_dict['mip_gap'],
                                                   # Optional solve limits.
                                                   _time_limit=params_dict['time_limit'], _threads=params_dict['threads'],
                                                   _log_console=params_dict['solver_log_to_console'],
                                                   _nnvonvex=params_dict['nnvonvex'], _method=params_dict['method'],
                                                   _flag_lp=params_dict['flag_lp'], _flag_mps=params_dict['flag_mps'],
                                                   # what each
                                                   # scenario monitors (None for consecutive time steps) and where the
                                                   # cleared scenarios sit in the FSP workbooks (every studied hour).
                                                   _assets_by_hour=snapshot_assets, _buses_by_hour=snapshot_buses,
                                                   _hour_positions=[study_hours.index(h) for h in round_hours])
                    # A corrective iteration is priced incrementally (only its own correction of the residual, at
                    # the FSPs' offers); the sequence is settled as one market on the final net position
                    # (merge_sequential_market_results).
                    if partial_round:
                        # the scenarios this iteration did not
                        # re-clear keep their last clearing (zero increment), so every later step reads all of them.
                        ac_validation.complete_round_result(
                            ModelOut[0], cumulative_market_archive, round_hours, study_hours)

                    dict_profiles_postmkt = rnet.change_net_fsp(
                        _net=net_post, _hours2study=HoursToStudy, _fsp_file=market_fsp_file,
                        _timestep=params_dict['timestep'], _ts_res=ts_results,
                        _root_fsp=input_root, _root_results=output_root,
                        _simulation_tag=market_tag)
                    # The post-market AC state keeps the
                    # supply voltage of its time step.
                    if ext_grid_profile is not None:
                        dict_profiles_postmkt['ext_grid_vm'] = ext_grid_profile.loc[HoursToStudy]

                    ts_results_post = rnet.run_pf_timeseries(
                        _pp_net=net_post, _dict_profiles=dict_profiles_postmkt,
                        _time_steps=HoursToStudy, _out_filetype=params_dict['ts_output_file_type'],
                        _out_root=output_ts_root, _all_steps=False, _force_ts=True,
                        res_bus=['vm_pu', 'p_mw'], res_line=['loading_percent'],
                        res_load=['p_mw', 'q_mvar'], res_sgen=['p_mw', 'q_mvar'],
                        res_storage=['p_mw', 'q_mvar'], res_trafo=['loading_percent'],
                        res_trafo3w=['loading_percent'])

                    ac_summary = ac_validation.physical_security_summary(
                        net_post, ts_results_post, v_min, v_max,
                        params_dict['ac_validation_loading_limit'])
                    if ac_iteration == 0:
                        cumulative_market_archive = ac_validation.archive_market_result(
                            ModelOut[0], 'ACValidationCumulativeMarket_iteration_00.xlsx')
                    elif cumulative_market_archive is not None:
                        # After each
                        # corrective pass the main workbook becomes cumulative:
                        # initial + corrective_01 + corrective_02 + ...
                        # W/R remain the final dispatch of the latest pass.
                        ac_validation.merge_sequential_market_results(
                            cumulative_market_archive, ModelOut[0], fsp_file,
                            # The merge
                            # settles the whole sequence as one market.  It needs
                            # the slack prices to charge the remaining residual
                            # once, and the original FSP workbooks to price the
                            # NET committed position of every provider instead of
                            # the gross activation of each round.
                            _alpha_cost=params_dict['alpha_cost'],
                            _beta_cost=params_dict['beta_cost'],
                            # The merge checks the
                            # solver objective against the iteration's own increment (incremental
                            # pricing); the reported cost is the final net settlement.
                            _input_root=input_root,
                            # the solver saw only these scenarios.
                            _round_hours=(round_hours if partial_round else None))
                        cumulative_market_archive = ac_validation.archive_market_result(
                            ModelOut[0],
                            f'ACValidationCumulativeMarket_iteration_{ac_iteration:02d}.xlsx')
                    if cumulative_market_archive is not None:
                        cumulative_market_archives.append(cumulative_market_archive)
                    ac_stage_roots.append(ac_validation.snapshot_market_stage(
                        output_root, output_ts_root, ModelOut[0], ac_iteration,
                        _sensitivity_root=market_matrix_root,
                        # Record the
                        # pilot-bus order this market actually used, so the
                        # linear/AC voltage accuracy pairs each VA row with the
                        # correct bus even after a corrective pass expands the
                        # represented pilot-bus set.
                        _pilot_bus=pilot_bus,
                        # Archive only this run's matrices.
                        _sim_tag=simulation_tag))
                    ac_validation_rows.append(ac_validation.validation_record(
                        ac_iteration, ac_summary, market_vmin_opt,
                        market_vmax_opt, market_ds_tol, smax_mva,
                        _linearization=('initial' if ac_iteration == 0 else 'post_dispatch_ac'),
                        _sensitivity_root=market_matrix_root))
                    physically_secure = (
                        ac_summary['overload_cell_count'] == 0
                        and ac_summary['voltage_violation_cell_count'] == 0
                    )
                    # the security verdict of every scenario.  With
                    # independent scenarios it decides, scenario by scenario, whether that scenario is cleared again;
                    # a secure scenario stops and keeps its clearing, an insecure one goes on while corrective
                    # iterations remain.  For consecutive time steps the case-wide verdict decides, as before.
                    snapshot_security = ac_validation.snapshot_security_table(
                        ac_summary, study_hours, params_dict['ac_validation_loading_limit'], v_min, v_max)
                    rounds_left = ac_iteration < max_ac_corrections
                    if independent_snapshots:
                        next_hours = [h for h in round_hours
                                      if not bool(snapshot_security.loc[h, 'secure'])] if rounds_left else []
                    else:
                        next_hours = list(study_hours) if (rounds_left and not physically_secure) else []
                    for h in study_hours:
                        cleared = h in round_hours
                        secure_h = bool(snapshot_security.loc[h, 'secure'])
                        if not cleared:
                            decision = 'kept_earlier_clearing'
                        elif h in next_hours:
                            decision = 'corrective_iteration_next'
                        elif secure_h:
                            decision = 'stop_secure'
                        elif not rounds_left:
                            decision = 'stop_corrective_limit'
                        else:
                            decision = 'stop_case_secure'
                        snapshot_rows.append({
                            'market_tag': full_market_tag,
                            'snapshot_mode': 'independent' if independent_snapshots else 'joint',
                            'iteration': ac_iteration,
                            'cleared_in_iteration': cleared,
                            **snapshot_security.loc[h].to_dict(),
                            'decision': decision,
                        })
                    if not next_hours:
                        break

                    if params_dict['max_corrective_market_running'] <= 0:
                        print('WARNING: AC residual violations remain, but operating-point relinearization is disabled.')
                        break
                    # the scenarios the corrective iteration re-clears.
                    active_hours = list(next_hours)

                    # Preserve the first
                    # clearing, then rebase Winit/Rinit at its accepted physical
                    # dispatch. The corrective market therefore optimizes only
                    # additional flexibility within the remaining capacity.
                    market_fsp_file = ac_validation.rebase_fsp_files_at_market_result(
                        ModelOut[0], fsp_file, input_root, HoursToStudy,
                        _iteration=ac_iteration + 1,
                        _result_to_input_sign={
                            key: -1.0 if aux.res_fcn.get(key) == 'storage_model'
                            else 1.0
                            for key in fsp_file
                        })
                    # Rebased FSP variables are increments from the new AC point, so H multiplies them directly.
                    market_matrix_root = ac_validation.iteration_sensitivity_root(
                        input_root,
                        params_dict['ac_validation_sensitivity_subfolder'],
                        ac_iteration + 1,
                        _reset=True,
                        # Scope the
                        # corrective cache by simulation tag, so two scenarios
                        # of one study can never delete each other's matrices.
                        _sim_tag=simulation_tag)

                    # Expand the represented set when AC reveals a new branch
                    # or pilot-bus violation after dispatch. Existing represented
                    # elements remain protected in all later iterations.
                    operating_state = ac_validation.expanded_operating_point_market_state(
                        net_post, ac_summary, HoursToStudy, smax_mva.index,
                        _loading_limit=params_dict['ac_validation_loading_limit'],
                        _optimization_target_percent=params_dict['current_optimization_target'])
                    smax_mva = operating_state['smax']
                    market_s_init = operating_state['s_init']
                    market_ds_tol = operating_state['ds_tol']
                    market_cong_needs = operating_state['cong_needs']
                    market_hours_cm = operating_state['congested_hours']
                    cong_assets = operating_state['congested_assets']
                    idx_clines = operating_state['line_indices']
                    idx_ctrafo2w = operating_state['trafo_indices']
                    idx_ctrafo3w = operating_state['trafo3w_indices']
                    pilot_asset = idx_clines + idx_ctrafo2w + idx_ctrafo3w
                    pilot_bus = ac_validation.expanded_pilot_buses(
                        net_post, ac_summary, pilot_bus, v_min, v_max,
                        _only_mv=cfg_file['only_pilot_busMV'],
                        _vn_kv_mv=cfg_file['vn_kv_mv'])
                    market_v_before = ac_summary['voltage'].reindex(
                        index=HoursToStudy, columns=pilot_bus)
                    # with independent scenarios every scenario that
                    # goes on keeps what it monitored and adds what ITS OWN post-clearing AC result newly violates
                    # (outside the operational limits, tol_i and tol_v included); the represented set above already
                    # holds those new branches and pilot buses, with their sensitivities rebuilt below.
                    if independent_snapshots:
                        snapshot_assets, snapshot_buses = ac_validation.expand_snapshot_sets(
                            snapshot_assets, snapshot_buses, ac_summary, active_hours,
                            params_dict['ac_validation_loading_limit'], v_min, v_max, pilot_bus)

                    # Recalculate every
                    # required P/Q pair at the nonlinear AC
                    # post-dispatch point. The reusable initial cache remains in
                    # path_dict['sens_matrix_root'] and is never overwritten.
                    # only for the scenarios the iteration re-clears.
                    calc_sens.calc_sens_factors_vc(
                        _net=net_post, _fsp_file=market_fsp_file, _fsp_bus=fsp_bus,
                        _ts_res=ts_results_post, _pilot_bus=pilot_bus,
                        _hours=active_hours, _sens_type='PQ',
                        _dp=params_dict['vc_deltaP_coeff'],
                        _dq=params_dict['vc_deltaQ_coeff'],
                        _path_matrix=market_matrix_root, _sim_tag=simulation_tag,
                        _force_hvm=True, _save_inv_js=False)
                    calc_sens.calc_sens_factors_cm(
                        _net=net_post, _fsp_file=market_fsp_file, _fsp_bus=fsp_bus,
                        _ts_res=ts_results_post, _cm_branch=idx_clines,
                        _cm_trafo=idx_ctrafo2w, _cm_trafo3w=idx_ctrafo3w,
                        _hours=active_hours, _dp=params_dict['cm_deltaP_coeff'],
                        _dq=params_dict['cm_deltaQ_coeff'],
                        _path_matrix=market_matrix_root, _sens_type='PQ',
                        _sim_tag=simulation_tag, _sens_mode='VSGEN',
                        _only_ds=True, _force_hcm=True,
                        # HCM basis (cm_sensitivity_basis).
                        _sens_basis=params_dict['cm_sensitivity_basis'])

                    print(
                        'Nonlinear AC validation requested operating-point '
                        'relinearization and corrective market '
                        f'iteration {ac_iteration + 1}: '
                        f"overload cells={ac_summary['overload_cell_count']}, "
                        f"voltage cells={ac_summary['voltage_violation_cell_count']}"
                        # which scenarios are re-cleared.
                        + (f"; scenarios re-cleared: {active_hours}." if independent_snapshots else '.')
                    )

                # Decompose the sequence
                # into what was finally committed, what was activated along the
                # way, and what one round bought and a later round undid.
                #
                # The difference is not a bookkeeping curiosity.  Measured on the
                # earlier SB72 runs it was 5.6 % of all activation, reaching 19 % in the
                # case with the widest locational reach, and it is what a market
                # settled round by round would pay for twice.  It is also the
                # quantity that says how much of a corrective market is genuinely
                # new procurement and how much is undoing the previous round.
                #
                # Every provider, hour and
                # P/Q component is settled on its FINAL NET position against the
                # original pre-market point (main + every corrective increment),
                # at the price of its final direction.  FinalNetSettlement.csv is
                # that settlement row by row, beside the main-market cost and the
                # gross corrective transaction cost kept as diagnostics; its
                # checks are in FinalNetSettlementChecks.csv.
                settlement_table = pd.DataFrame()
                if cumulative_market_archives:
                    try:
                        settlement_table, settlement_checks = (
                            ac_validation.final_net_settlement_table(
                                cumulative_market_archives, fsp_file, input_root,
                                _settled_market_file=cumulative_market_archives[-1]))
                        if not settlement_table.empty:
                            settlement_table.insert(0, 'market_tag', full_market_tag)
                            settlement_table.to_csv(
                                os.path.join(output_root, 'FinalNetSettlement.csv'),
                                index=False)
                            pd.DataFrame([{'market_tag': full_market_tag, **settlement_checks}]).to_csv(
                                os.path.join(output_root, 'FinalNetSettlementChecks.csv'),
                                index=False)
                            print(
                                'Settlement: main market {m:.2f} EUR, corrective '
                                'transactions {c:.2f} EUR, final net settlement '
                                '{n:.2f} EUR (reversed activation {r:.2f} EUR).'.format(
                                    m=settlement_checks['main_market_cost_eur'],
                                    c=settlement_checks['corrective_incremental_cost_eur'],
                                    n=settlement_checks['final_net_settlement_cost_eur'],
                                    r=settlement_checks['reversed_activation_cost_eur']))
                            failed = [
                                key for key, value in settlement_checks.items()
                                if (key.endswith('_rows') and key != 'crossing_rows' and value)
                                or (key.endswith(('_error', '_residual'))
                                    and pd.notna(value) and value > 1e-4)
                            ]
                            if failed:
                                print('WARNING: final net settlement checks failed: '
                                      + ', '.join(failed))
                    except Exception as exc:
                        print(f"[Final net settlement] Skipped: {exc}")

                if len(cumulative_market_archives) > 1:
                    try:
                        churn_stages, churn_summary = (
                            ac_validation.sequential_market_activation_summary(
                                cumulative_market_archives))
                        churn_summary = churn_summary.copy()
                        churn_summary['churn_percent_of_gross'] = [
                            100.0 * reversal / gross if gross else 0.0
                            for reversal, gross in zip(
                                churn_summary['reversal_total'],
                                churn_summary['gross_total'])
                        ]
                        # The gross and reversed
                        # movements stay as they were; the three costs are added per
                        # class and quantity, so the churn file shows what the
                        # movements cost and what is finally paid.
                        if not settlement_table.empty:
                            costs = settlement_table.assign(
                                quantity=settlement_table['product'].map({'P': 'DW', 'Q': 'DR'})
                            ).groupby(['quantity', 'fsp_type'], as_index=False)[[
                                'main_market_cost_eur', 'corrective_incremental_cost_eur',
                                'final_net_settlement_cost_eur']].sum()
                            costs['reversed_activation_cost_eur'] = (
                                costs['main_market_cost_eur']
                                + costs['corrective_incremental_cost_eur']
                                - costs['final_net_settlement_cost_eur'])
                            churn_summary = churn_summary.merge(
                                costs, on=['quantity', 'fsp_type'], how='left')
                        churn_summary.insert(0, 'market_tag', full_market_tag)
                        churn_stages.insert(0, 'market_tag', full_market_tag)
                        churn_summary.to_csv(
                            os.path.join(output_root, 'SequentialActivationChurn.csv'),
                            index=False)
                        churn_stages.to_csv(
                            os.path.join(output_root, 'SequentialActivationByStage.csv'),
                            index=False)
                        gross_total = float(churn_summary['gross_total'].sum())
                        reversal_total = float(churn_summary['reversal_total'].sum())
                        print(
                            'Sequential activation: {g:.3f} activated in total, '
                            '{n:.3f} finally committed, {r:.3f} bought and later '
                            'undone ({p:.1f} % churn).'.format(
                                g=gross_total,
                                n=float(churn_summary['final_net_abs_total'].sum()),
                                r=reversal_total,
                                p=100.0 * reversal_total / gross_total
                                if gross_total else 0.0))
                    except Exception as exc:
                        print(f"[Sequential activation churn] Skipped: {exc}")

                if ac_validation_enabled:
                    pd.DataFrame(ac_validation_rows).to_csv(
                        os.path.join(output_root, 'ACMarketValidation.csv'),
                        index=False)
                    # one row per scenario and iteration -- whether
                    # the iteration cleared it, its AC security afterwards and what was decided for it -- so the
                    # corrective iterations and stopping decisions of every scenario are auditable.
                    pd.DataFrame(snapshot_rows).to_csv(
                        os.path.join(output_root, 'ACMarketValidationBySnapshot.csv'),
                        index=False)
                    # The policy of this run (relinearisation at the AC operating point), saved with its results.
                    with open(
                        os.path.join(output_root, 'ACValidationPolicy.json'),
                        'w', encoding='utf-8'
                    ) as policy_file:
                        # The validation
                        # manifest records whether this run was a one-pass AC
                        # audit or an explicit corrective relinearized market.
                        policy_relinearize = bool(
                            params_dict['max_corrective_market_running'] > 0
                        )
                        json.dump({
                            'policy_version': 3,
                            'ac_validate_post_market': True,
                            'run_corrective_market': policy_relinearize,
                            'max_corrective_market_running':
                                params_dict['max_corrective_market_running'],
                            'max_corrective_market_reruns':
                                params_dict['max_corrective_market_running'],
                            'sequential_remaining_capacity':
                                policy_relinearize,
                            'fresh_corrective_sensitivities':
                                policy_relinearize,
                            'ac_validation_sensitivity_subfolder':
                                params_dict['ac_validation_sensitivity_subfolder'],
                            # per-scenario or case-wide loop.
                            'snapshot_mode': 'independent' if independent_snapshots else 'joint',
                        }, policy_file, indent=2)

                # One consolidated folder
                # per case.  The case folder itself holds the FINAL market (the
                # settled result after the last corrective market) and every
                # figure is drawn from it.  The MAIN market is kept only as CSV in
                # <case>/main_market_results/ for comparison after the run, and
                # the pre-market AC power flow is copied in, so the case folder is
                # self-contained.
                final_stage_iteration = len(ac_stage_roots) - 1
                if ac_stage_roots and bool(cfg_file.get('save_main_market_csv', True)):
                    main_csv_root = ac_validation.export_main_market_csv(
                        output_root, ac_stage_roots[0], final_stage_iteration)
                    print(f'Main-market results (CSV, for comparison): {main_csv_root}')
                case_pre_ts_root = os.path.join(output_root, 'res_ts_net')
                if os.path.isdir(path_dict['ts_out_root']):
                    # Overwrite in place; an
                    # rmtree on the previous run's folder fails with WinError 5 when
                    # a sync client holds the folder.
                    ac_validation.sync_tree(path_dict['ts_out_root'], case_pre_ts_root)

                # Evaluate Voltage Flexibility Needs after the Flexibility Market
                _, _, _, VCHoursToStudy_postMKT = feval.flex_needs_buses(_ts_res=ts_results_post, _v_max=v_max, _v_min=v_min,
                                                                         _folders=[output_root, output_root],
                                                                         _filenames=['VM_Problems_Stats_postMKT', 'VCHoursToStudy_post'])

                # Evaluate Congestion Flexibility Needs after the Flexibility Market
                _, _, _, _, _, _, _, CMHoursToStudy_postMKT, \
                _, _ = feval.congestion_needs(_net=net_post, _ts_res=ts_results_post, _llimit=params_dict['line_overload_limit'],
                                              _tlimit=params_dict['trafo_overload_limit'], _di_tol_opt=params_dict['di_tol_opt'],
                                              # post-market AC
                                              # detection uses the same network scope as pre-market.
                                              _full_net=params_dict['full_net'],
                                              _folders=[output_root, output_root], _filenames=['total_cm_postMKT', 'CMHoursToStudy_post'])
                # every figure of this case, in
                # <case>/visualization/ (topology, technical analytics, technical comparison, showcase).
                viz.case_figures(cfg_file=cfg_file, file_cfg_name=file_cfg_name, path_dict=path_dict,
                                 params_dict=params_dict, net=net, ts_results=ts_results, fsp_dict=fsp_dict,
                                 prod=prod, output_root=output_root, output_ts_root=output_ts_root,
                                 market_file=ModelOut[0], market_tag=full_market_tag, v_min=v_min, v_max=v_max)

                # Evaluate Energy Support of FSP Resources
                aux.eval_energy_support_res(_ts_res=ts_results_post, _pilot_bus=pilot_bus, _hours=HoursToStudy,
                                            _in_root=input_root, _out_root=output_root, _fsp_file=fsp_file,
                                            _filename_lfm=ModelOut[0])

    # figures of all cases (consistency audit)
    viz.bundle_figures(cfg_file=cfg_file, file_cfg_name=file_cfg_name, path_dict=path_dict)

    # Evaluate KPIs
    kpi_fcn.evaluate_kpis(_cfg_file=cfg_file, _paths=path_dict, _fsp_file=fsp_file,
                          _prods=cfg_file['ProductTAG'], _vls=cfg_file['VLTAG'], _fsps=cfg_file['FspTAG'],
                          _draw_plots=viz.plan(cfg_file)['kpi_plots'], _draw_net=False)  # Category kpi_plots

    # KPI consistency check and comparison across cases
    viz.after_kpis(cfg_file=cfg_file, path_dict=path_dict)

    # Print final simulation information
    print("Simulation finished.\nSimulated case information:")    
    print(f"  {'Config file'}: {file_cfg_name}")
    print(f"  {'SimulationTAG'}: {simulation_tag}")
    print(f"  {'ModelTAG'}: {cfg_file['ModelTAG']}")
    print(f"  {'ProductTAG'}: {cfg_file['ProductTAG']}")
    print(f"  {'VLTAG'}: {cfg_file['VLTAG']}")
    print(f"  {'FspTAG'}: {cfg_file['FspTAG']}")
    
                
    # Record the end time
    end_time = time.time()
    # Calculate the elapsed time
    elapsed_time_seconds = end_time - start_time
    # Convert seconds to hours, minutes, and seconds
    hours, remainder = divmod(elapsed_time_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    print('Time elapsed: {:0.2f} hours, {:0.2f} minutes, {:0.2f} seconds'.format(hours, minutes, seconds))
    # Show which stage actually spent the
    # wall clock, so tuning targets the slow stage rather than the visible one.
    viz.report_stage_times()
