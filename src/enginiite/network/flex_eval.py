import sys
import math
import numpy as np
import pandas as pd
import enginiite.file_io as io_file


def flex_needs_buses(_ts_res, _v_max, _v_min, _folders, _filenames):
    """Function that identify under and over bus voltages.
    :param _ts_res: Dictionary with the results of the timeseries simulation.
    :param _v_max: Maximum voltage limitation.
    :param _v_min: Minimum voltage limitation.
    :param _folders: List of folders where to save data.
    :param _filenames: List of file names used to name the data.
    :return vbus_outbounds: Dataframe with the buses that are with over and under voltage problems
    :return vbus_over_flex: Dataframe with the buses that are with over voltage problems
    :return vbus_under_flex: Dataframe with the buses that are with under voltage problems
    :return vc_hours2study: Numpy array with the over and under voltage hours.
    """
    _bus_voltages = _ts_res['bus_vm_pu']

    # Exact equality with a technical
    # threshold is compliant in detection, as it is in the KPI calculations.
    vbus_over = _bus_voltages[_bus_voltages > _v_max]
    vbus_under = _bus_voltages[_bus_voltages < _v_min]

    vbus_over_flex = pd.DataFrame()
    vbus_under_flex = pd.DataFrame()

    # Extract the bus with voltage issues (Over & Under Voltage)
    v_over_bus = vbus_over.columns[vbus_over.notna().any()].tolist()
    v_under_bus = vbus_under.columns[vbus_under.notna().any()].tolist()

    # Get the Dataframe with only bus with voltage issue
    vbus_out = pd.concat([vbus_over.loc[:, v_over_bus].fillna(0).T, vbus_under.loc[:, v_under_bus].fillna(0).T])

    # populate vbus_over_flex dataframe
    vbus_over_flex['Bus'] = vbus_over.stack().index.get_level_values(1).values
    vbus_over_flex['TimeStep'] = vbus_over.stack().index.get_level_values(0).values
    vbus_over_flex['VMpu'] = vbus_over.stack().values

    # populate the dataframe
    vbus_under_flex['Bus'] = vbus_under.stack().index.get_level_values(1).values
    vbus_under_flex['TimeStep'] = vbus_under.stack().index.get_level_values(0).values
    vbus_under_flex['VMpu'] = vbus_under.stack().values

    vbus_outbounds = pd.concat([vbus_over_flex, vbus_under_flex])

    vc_hours2study = vbus_outbounds['TimeStep'].unique()

    vm_stats_premrk = pd.DataFrame({'Total_Bxh': vbus_outbounds.shape[0],
                                    'OverV_Bxh': vbus_over_flex.shape[0],
                                    'UnderV_Bxh': vbus_under_flex.shape[0]}, index=[0])
    io_file.save_excel(vm_stats_premrk, _folders[0], _filenames[0], _sheetname='Stats')
    io_file.save_excel(vbus_over_flex, _folders[0], _filenames[0], _sheetname='Vbus_over', _mode='a')
    io_file.save_excel(vbus_under_flex, _folders[0], _filenames[0], _sheetname='Vbus_under', _mode='a')

    io_file.save_cvs(pd.DataFrame(vc_hours2study), _folders[1], _filenames[1])

    return vbus_out, vbus_over_flex, vbus_under_flex, vc_hours2study


def flex_needs_lines(_net, _line_loading, _tol_opt, _overload_limit, _include_all=False):
    """Evaluate the Apparent Power of Lines."""
    _flex_limit = _overload_limit # _tol_opt is just for optimization not detection stage. we detect with just tol_i and optimize with _tol_i - tol_i_opt

    line_overload = _line_loading.where(_line_loading > _flex_limit)

    # full-network monitoring selects all
    # assets without replacing the real preventive threshold by a fake -1%.
    cong_lines = _line_loading.columns.to_numpy() if _include_all else np.unique(line_overload.stack().index.get_level_values(1).values)
    _lloading = _line_loading.loc[:, cong_lines]
    smax_lines = pd.Series({
        _l: math.sqrt(3) * _net.line.loc[_l, 'max_i_ka'] * _net.bus.loc[_net.line.loc[_l, 'from_bus'], 'vn_kv']
        for _l in cong_lines
    })
    smax_lines_mva = smax_lines.to_list()
    total_margin = max(100.0 - float(_flex_limit), 0.0) + float(_tol_opt)
    delta_smax_lines_mva = [_smax * (total_margin / 100) for _smax in smax_lines_mva]

    s_init_lines_mva = (_lloading / 100).mul(smax_lines, axis=1)
    s_init_lines_mva.columns = _net.line.loc[cong_lines, 'name']

    idx_lines = list(cong_lines)

    flex_lines = ((_line_loading.loc[:, cong_lines] - _flex_limit).clip(lower=0) / 100).mul(smax_lines, axis=1).fillna(0)
    flex_lines.columns = _net.line.loc[cong_lines, 'name'].tolist()

    # Every hour of every selected asset
    # receives the optimization target, not only cells congested at detection.
    delta_smax_lines_t_mva = pd.DataFrame(
        np.tile(delta_smax_lines_mva, (len(_lloading.index), 1)),
        index=_lloading.index,
        columns=flex_lines.columns,
    )
    return smax_lines_mva, s_init_lines_mva, delta_smax_lines_t_mva, idx_lines, flex_lines, cong_lines


def flex_needs_trafos_2w(_net, _trafo_loading, _tol_opt, _overload_limit, _include_all=False):
    """Evaluates the Apparent Power of 2 Winding Transformers."""
    _flex_limit = _overload_limit # _tol_opt is just for optimization not detection stage. we detect with just tol_i and optimize with _tol_i - tol_i_opt
    trafo_overload = _trafo_loading.where(_trafo_loading > _flex_limit)

    # Selection scope and violation
    # threshold are independent for two-winding transformers.
    cong_tr = _trafo_loading.columns.to_numpy() if _include_all else np.unique(trafo_overload.stack().index.get_level_values(1).values)
    _t2wloading = _trafo_loading.loc[:, cong_tr]
    smax_trafo = _net.trafo.loc[cong_tr, 'sn_mva']
    smax_trafo_mva = smax_trafo.to_list()
    total_margin = max(100.0 - float(_flex_limit), 0.0) + float(_tol_opt)
    delta_smax_trafo_mva = [_smax * (total_margin / 100) for _smax in smax_trafo_mva]

    s_init_trafo_mva = (_t2wloading / 100).mul(smax_trafo, axis=1)
    s_init_trafo_mva.columns = _net.trafo.loc[cong_tr, 'name']

    idx_trafo = list(cong_tr)

    flex_trafo = ((_trafo_loading.loc[:, cong_tr] - _flex_limit).clip(lower=0) / 100).mul(smax_trafo, axis=1).fillna(0)
    flex_trafo.columns = _net.trafo.loc[cong_tr, 'name'].tolist()

    # Apply the target to all represented
    # hours of each selected two-winding transformer.
    delta_smax_trafo_t_mva = pd.DataFrame(
        np.tile(delta_smax_trafo_mva, (len(_t2wloading.index), 1)),
        index=_t2wloading.index,
        columns=flex_trafo.columns,
    )
    return smax_trafo_mva, s_init_trafo_mva, delta_smax_trafo_t_mva, idx_trafo, flex_trafo, cong_tr


def flex_needs_trafos_3w(_net, _trafo_loading, _tol_opt, _overload_limit, _include_all=False):
    """Evaluate the Apparent Power of 3 Winding Transformers."""
    _flex_limit = _overload_limit # It is now in percent but has to be in MVA

    trafo_overload = _trafo_loading.where(_trafo_loading > _flex_limit)

    # full-network mode includes every
    # three-winding transformer but keeps the configured detection threshold.
    cong_tr = _trafo_loading.columns.to_numpy() if _include_all else np.unique(trafo_overload.stack().index.get_level_values(1).values)
    _t3wloading = _trafo_loading.loc[:, cong_tr]
    smax_trafo3w = _net.trafo3w.loc[cong_tr, 'sn_hv_mva']
    smax_trafo3w_mva = smax_trafo3w.to_list()
    total_margin = max(100.0 - float(_flex_limit), 0.0) + float(_tol_opt)
    delta_smax_trafo3w_mva = [_smax * (total_margin / 100) for _smax in smax_trafo3w_mva]

    s_init_trafo3w_mva = (_t3wloading / 100).mul(smax_trafo3w, axis=1)
    s_init_trafo3w_mva.columns = _net.trafo3w.loc[cong_tr, 'name']

    idx_trafo3w = list(cong_tr)

    flex_trafo3w = ((_trafo_loading.loc[:, cong_tr] - _flex_limit).clip(lower=0) / 100).mul(smax_trafo3w, axis=1).fillna(0)
    flex_trafo3w.columns = _net.trafo3w.loc[cong_tr, 'name'].tolist() # net.tranfo is for 2_windings trans not 3.

    # Apply the target to all represented
    # hours of each selected three-winding transformer.
    delta_smax_trafo_t_mva = pd.DataFrame(
        np.tile(delta_smax_trafo3w_mva, (len(_t3wloading.index), 1)),
        index=_t3wloading.index,
        columns=flex_trafo3w.columns,
    )
    return smax_trafo3w_mva, s_init_trafo3w_mva, delta_smax_trafo_t_mva, idx_trafo3w, flex_trafo3w, cong_tr


def congestion_needs(_net, _ts_res, _di_tol_opt, _folders, _filenames, _full_net=False, _llimit=100, _tlimit=100):
    """Function to evaluate the congestion needs summary.
    :param _net: Pandapower network.
    :param _ts_res: Dictionary with the results of the timeseries simulation.
    :param _di_tol_opt: Maximum flexibility available to the dso in percentage.
    :param _folders: List of two elements: the folders where to save 'Congestion Needs' and 'Congested Hours' files.
    :param _filenames: List of two elements: the file names of the files 'Congestion Needs' and 'Congested Hours'.
    :param _full_net: Boolean to indicate if the full network representation is considered.
    :param _llimit: Operating Limitation for the current flowing in the line.
    :param _tlimit: Operating Limitation for the current flowing in the trafo.
    :return cong_needs_df: Dataframe with the information about all the congestions.
    :return lines_flex_df: Dataframe with the information about the line congested.
    :return trafos_flex_df: Dataframe with the information about the trafo 2 windings congested.
    :return trafos3w_flex_df: Dataframe with the information about the trafo 3 windings congested.
    :return cong_hours: Numpy array with the congested hours.
    """
    _lloading = _ts_res['line_loading_percent']
    _t2wloading = _ts_res['trafo_loading_percent']
    _t3wloading = _ts_res['trafo3w_loading_percent']

    # Lines
    smax_lines_mva, sinit_lines_mva, ds_lines_mva, idx_clines, lines_flex, cong_lines = flex_needs_lines(_net=_net, _line_loading=_lloading, _tol_opt=_di_tol_opt, _overload_limit=_llimit, _include_all=_full_net)

    # Trafos2W
    smax_trafo_mva, sinit_trafo_mva, ds_trafo_mva, idx_ctrafo, trafos_flex, cong_trafo = flex_needs_trafos_2w(_net=_net, _trafo_loading=_t2wloading, _tol_opt=_di_tol_opt, _overload_limit=_tlimit, _include_all=_full_net)

    # Trafos 3W
    smax_trafo3w_mva, sinit_trafo3w_mva, ds_trafo3w_mva, idx_ctrafo3w, trafos3w_flex, cong_trafo3w = flex_needs_trafos_3w(_net=_net, _trafo_loading=_t3wloading, _tol_opt=_di_tol_opt, _overload_limit=_tlimit, _include_all=_full_net)

    # Concat all congestion needs
    cong_needs_df = pd.concat([lines_flex, trafos_flex, trafos3w_flex], axis=1)

    # Save File
    io_file.save_excel(cong_needs_df, _folders[0], _filenames[0], _sheetname='Congestion needs')

    cong_filtered = cong_needs_df[(cong_needs_df > 0).any(axis=1)]
    cong_hours = cong_filtered.index.values

    cong_elements = cong_needs_df.T[(cong_needs_df > 0).any(axis=0)].index.tolist()

    # Save file
    io_file.save_cvs(pd.DataFrame(cong_hours), _folders[1], _filenames[1])

    # Concat all Dataframe
    sinit_mva = pd.concat([sinit_lines_mva, sinit_trafo_mva, sinit_trafo3w_mva], axis=1)
    smax_mva = pd.concat([pd.DataFrame(smax_lines_mva, index=_net.line.name[cong_lines]),
                          pd.DataFrame(smax_trafo_mva, index=_net.trafo.name[cong_trafo]),
                          pd.DataFrame(smax_trafo3w_mva, index=_net.trafo3w.name[cong_trafo3w])], axis=0)
    deltas_max_df = pd.concat([ds_lines_mva, ds_trafo_mva, ds_trafo3w_mva], axis=1)

    pilot_assets = idx_clines + idx_ctrafo + idx_ctrafo3w
    return smax_mva, sinit_mva, deltas_max_df, pilot_assets, idx_clines, idx_ctrafo, idx_ctrafo3w, cong_hours, cong_needs_df, cong_elements


def eval_mva_assets(_net, _ts_res, _di_tol_opt):
    """Function to evaluate the MVA per each asset (Lines, Trafo 2 Windings and Trafo 3 Windings).
    :param _net: Pandapower network.
    :param _ts_res: Dictionary with the results of the timeseries simulation.
    :param _di_tol_opt: Maximum flexibility available to the dso in percentage.
    """
    _lloading = _ts_res['line_loading_percent']
    _t2wloading = _ts_res['trafo_loading_percent']
    _t3wloading = _ts_res['trafo3w_loading_percent']

    # Lines
    smax_lines_mva = [math.sqrt(3) * _net.line.max_i_ka[_l] * _net.bus.vn_kv[_net.line.from_bus[_l]] for _l in _net.line.index]
    tol_smax_lines_mva = [_smax * ((100 - _di_tol_opt)/100) for _smax in smax_lines_mva]
    s_init_lines_mva = _lloading/100 * smax_lines_mva
    s_init_lines_mva.columns = _net.line.name
    idx_lines = _net.line.index.tolist()

    # Trafos 2W
    smax_trafo_mva = _net.trafo.sn_mva.values.tolist()
    tol_smax_trafo_mva = [_smax * ((100 - _di_tol_opt)/100) for _smax in smax_trafo_mva]
    s_init_trafo_mva = _t2wloading / 100 * smax_trafo_mva
    s_init_trafo_mva.columns = _net.trafo.name
    idx_trafo = _net.trafo.index.tolist()

    # Trafos 3W
    smax_trafo3w_mva = _net.trafo3w.sn_hv_mva.values.tolist()
    tol_smax_trafo3w_mva = [_smax * ((100 - _di_tol_opt)/100) for _smax in smax_trafo3w_mva]
    s_init_trafo3w_mva = _t3wloading / 100 * smax_trafo3w_mva
    s_init_trafo3w_mva.columns = _net.trafo3w.name
    idx_trafo3w = _net.trafo3w.index.tolist()

    # Concat all Dataframe
    s_init_df = pd.concat([s_init_lines_mva, s_init_trafo_mva, s_init_trafo3w_mva], axis=1)
    s_max_df = pd.concat([pd.DataFrame(smax_lines_mva, index=_net.line.name), pd.DataFrame(smax_trafo_mva, index=_net.trafo.name), pd.DataFrame(smax_trafo3w_mva, index=_net.trafo3w.name)], axis=0)
    tol_s_max_df = pd.concat([pd.DataFrame(tol_smax_lines_mva, index=_net.line.name), pd.DataFrame(tol_smax_trafo_mva, index=_net.trafo.name), pd.DataFrame(tol_smax_trafo3w_mva, index=_net.trafo3w.name)], axis=0)

    return s_init_df.T, s_max_df, tol_s_max_df, idx_lines, idx_trafo, idx_trafo3w


def get_sim_hours(_model, _timesteps, _v_out, _br_cong, _input_root, _v_min=0.95, _v_max=1.05, _only_worst_hour=False,
                  _intertemp_cons=False):
    """
    This function determines the optimal simulation interval based on critical congestion and voltage violation events.
    If _only_worst_hour is True, it identifies the worst hour for line congestion or voltage violations
    (over-voltage or under-voltage) and defines the simulation window accordingly.
    If _intertemp_cons is True, all the intervals selected as _timesteps are considered for the simulation window.
    If neither _only_worst_hour and _intertemp_cons are True, the function will consider only the hours with congestion
    or voltage issues.

    Input:
        **_model** (string) - String representing the model type: 'CMVC' (Congestion Management & Voltage Control),
                                'CM' (Congestion Management) or 'VC' (Voltage Control).

        **_timesteps** (List of int) -  List of intervals to evaluate.

        **_v_out** (Dataframe) - Dataframe of the voltage per each simulation intevral and pilot bus.

        **_br_cong** (Dataframe) - Dataframe of the line congestion per each simulation intevral and element congested.

        **_input_root** (string) - Path to the input folder where to save the 'simulation hour' file

        **_v_min** (float, 0.95) - Minimum Operating voltage limitation.

        **_v_max** (float, 1.05) - Maximum Operating voltage limitation.

        **_only_worst_hour** (bool, False) - Boolean value to indicate if only the worst hour should be considered.

        **_intertemp_cons** (bool, True) - Boolean value to indicate if the simulation should consider all the intervals.

    Output:
        **sim_hours** (List of integers) - List of simulation hours.

    Example:
    >>> worst_congestion_hour = 10
    >>> worst_voltage_hour = 15
    >>> # Case 1: Intertemporal constraints enabled (24-hour window)
    >>> sim_hours = get_sim_hours(worst_congestion_hour, worst_voltage_hour, intertemp_cons=True)
    >>> print(sim_hours)  # Output: [3, 4, ..., 14, 15, 16, ..., 26]
    >>> # Case 2: Only worst hour is needed
    >>> sim_hours = get_sim_hours(worst_congestion_hour, worst_voltage_hour, intertemp_cons=False)
    >>> print(sim_hours)  # Output: [15]
    """
    if (_only_worst_hour and not _intertemp_cons) and (_only_worst_hour and _intertemp_cons):
        dv_over = _v_out[_v_out > _v_max] - _v_max
        dv_over_max = dv_over.max(axis=0)
        try:
            dv_over_idxmax = dv_over_max.idxmax()
        except ValueError:
            dv_over_idxmax = -1

        dv_under = _v_out[_v_out != 0][(_v_out < _v_min)] - _v_min
        dv_under_max = dv_under.min(axis=0)
        try:
            dv_under_idxmax = dv_under_max.idxmin()
        except ValueError:
            dv_under_idxmax = -1

        if dv_over_max.max() >= dv_under_max.max():
            # Worst case: Over-voltage
            worst_hour_voltage = dv_over_idxmax
        else:
            # Worst case: Under-voltage
            worst_hour_voltage = dv_under_idxmax

        try:
            worst_hour_branch = _br_cong.max(axis=0).idxmax()
        except ValueError:
            worst_hour_branch = -1

        if _model == 'CMVC':
            # Congestion Management & Voltage Control
            simulation_window = [worst_hour_voltage, worst_hour_branch]
        elif _model == 'VC' or _model == 'CV':
            # Voltage Control
            simulation_window = [worst_hour_voltage]
        else:
            # Congestion Management
            simulation_window = [worst_hour_branch]

    elif _intertemp_cons and not _only_worst_hour:
        simulation_window = [i for i in range(_timesteps[0], _timesteps[1])]

    else:
        voltage_hours = _v_out.columns[(_v_out != 0).any()].tolist()

        branch_hours = _br_cong.columns[(_br_cong != 0).any()].tolist()

        if _model == 'CMVC':
            # Congestion Management & Voltage Control
            simulation_window = np.unique(np.append(voltage_hours, branch_hours)).astype(int)
        elif _model == 'VC' or _model == 'CV':
            # Voltage Control
            simulation_window = np.unique(voltage_hours).astype(int)
        else:
            # Congestion Management
            simulation_window = np.unique(branch_hours).astype(int)

    if len(simulation_window) == 0:
        print('\n---- WARNING: NO CONGESTIONS and OVER/UNDER VOLTAGES DETECTED ----')
        sys.exit()

    io_file.save_cvs(_data=pd.DataFrame(simulation_window), _outroot=_input_root, _filename='HoursToStudy')

    return simulation_window
