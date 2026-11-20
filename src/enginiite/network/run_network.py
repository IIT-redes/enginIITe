import os
import shutil
import plotly
import copy as cp
import numpy as np
import pandas as pd
import pandapower as pp
from tqdm.auto import tqdm
import plotly.graph_objs as go
import matplotlib.pyplot as plt
from enginiite import auxiliary as aux
from enginiite import file_io as io_file
from enginiite.market.models.fsp_utils import match_pp_element
from pandapower.timeseries import DFData
from pandapower.control import ConstControl
from pandapower.plotting.plotly import simple_plotly
from pandapower.timeseries.output_writer import OutputWriter
from pandapower.timeseries.run_time_series import run_timeseries


def _result_value_by_fsp(_results_df, _fsp_label, _fsp_position, _hour):
    """Read market result by FSP name when available, otherwise by row position."""
    if _hour in _results_df.columns:
        hour_col = _hour
    elif str(_hour) in _results_df.columns:
        hour_col = str(_hour)
    else:
        raise KeyError(f"Hour {_hour} not found in market result columns.")

    if _fsp_label in _results_df.index:
        return _results_df.loc[_fsp_label, hour_col]
    return _results_df.iloc[_fsp_position, _results_df.columns.get_loc(hour_col)]


def run_pf_timeseries(_pp_net, _dict_profiles, _time_steps, _out_root, _out_filetype, _all_steps, _force_ts, **kwargs):
    """
    This function runs the timeseries power flow function from pandapower. To do this, the function creates the
    constant controllers of pandapower that read data from a DataSource and write it to the pandapower network.

    Input:
        **_pp_net** (dict) - Pandapower network format.

        **_dict_profiles** (dict) - Dictionary with the dataframe of the profiles.

        **_time_steps** (List of integers) - Number of interval to be evaluated. It can be like a list of two elements,
        the initial and the final timesteps; or it can be a list of integers where each element is a timestep to be
        analyzed.

        **_out_root** (string) - Output directory for the timeseries results.

        **_out_filetype** (string) - Format file type in which the timeseries results are saved. it can be '.csv' and
        '.xlsx'.

        **_all_steps** (bool) - Checks if the timeseries evaluation should be run over all the _time_steps value or only
        on the first and the last.

    Output:
        **_res_dict** (dict) - Dictionary with the results of the timeseries for the output required. Usually the output
        required are the following:

        1. res_bus=['vm_pu', 'va_degree']
        2. res_line=['loading_percent']
        3. res_load=['p_mw', 'q_mvar']
        4. res_sgen=['p_mw', 'q_mvar']
        5. res_gen=['p_mw', 'q_mvar']
        6. res_storage=['p_mw', 'q_mvar']
        7. res_trafo=['loading_percent']
        8. res_trafo3w=['loading_percent']

        These output are the common outputs that pandapower put as available for the elements of the network.

    EXAMPLE:

    >>> import pandas as pd
    >>> import pandapower.networks as pn
    >>> net = pn.case14()
    >>> dict_profiles = {'load_prof_p': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'load_prof_q': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'sgen_prof_p': pd.DataFrame(shape=(24, net.sgen.index))}
    >>> dict_res = run_pf_timeseries(net, dict_profiles, [0, 24], 'my_out_root', '.csv', True, res_load=['p_mw', 'q_mvar'],
    >>>                              res_sgen='q_mvar')

    """

    _outputs = {key: val for key, val in kwargs.items()}
    print('\n----- Time Series Calculation -----')
    if _force_ts:
        if _all_steps:
            t_steps = range(_time_steps[0], _time_steps[1])
        else:
            t_steps = _time_steps

        _elements = None
        _elements_idx = None
        _vars = None
        for _k in _dict_profiles.keys():
            _elements_idx = _dict_profiles[_k].columns
            ds = DFData(_dict_profiles[_k])

            # An 'ext_grid...' profile holds the supply
            # voltage set-point of the external grid per time step (file_io.import_ext_grid_profile).
            if _k.startswith('ext_grid'):
                ConstControl(_pp_net, element='ext_grid', variable='vm_pu', data_source=ds,
                             element_index=_elements_idx, profile_name=_dict_profiles[_k].columns, recycle=False)
                continue

            # Identify the power (Active/Reactive)
            if 'p' == _k.split('_')[-1]:
                _vars = 'p_mw'
            elif 'q' == _k.split('_')[-1]:
                _vars = 'q_mvar'

            # Identify the element (Load/Static Generator/Generator/Storage)
            if 'load' in _k:
                _elements = 'load'
            elif 'sgen' in _k:
                _elements = 'sgen'
            elif 'gen' in _k:
                _elements = 'gen'
            elif 'storage' in _k:
                _elements = 'storage'

            try:
                ConstControl(_pp_net, element=_elements, variable=_vars, data_source=ds, element_index=_elements_idx,
                             profile_name=_dict_profiles[_k].columns, recycle=False)
            except Exception as _ex:
                raise UserWarning(type(_ex).__name__, _ex)

        _create_output_writer(_pp_net, t_steps, _out_root=_out_root, _output_file_type=_out_filetype, _res=_outputs)

        run_timeseries(_pp_net, t_steps, continue_on_divergence=False)

    _res_dict = read_timeseries(_out_root=_out_root, _res=_outputs)
    return _res_dict


def _create_output_writer(_net, _t_steps, _out_root='data_out', _output_file_type='.xlsx', **kwargs):
    """
    This function initialises the Output Writer to save data into files.

    Input:
        **_net** (dict) - Pandapower network format.

        **_t_steps** (List of integers) - Time steps of the simulation.

        **_out_root** (string, data_out) - Output directory.

        **_output_file_type** (string, .xlsx) - File format in which the results are saved

    Output:
        **ow** (Class) - OutputWriter class.

    EXAMPLE:

    >>> import pandapower.networks as pn
    >>> net = pn.case14()
    >>> my_class_ow = _create_output_writer(net, range(0, 24), 'my_result_folder', '.csv', res_load=['p_mw', 'q_mvar'], res_sgen=['q_mvar'])

    """

    ow = OutputWriter(_net, _t_steps, _out_root, _output_file_type, write_time=None, log_variables=list(),
                      csv_separator=',')

    _results_dict = kwargs.get('_res', {})
    for key, val in _results_dict.items():
        for _values in val:
            ow.log_variable(key, _values)
    return ow


def read_timeseries(_out_root, **kwargs):
    """
    This function reads the results of the timeseries analysis.

    Input:
        **_out_root** (string) - Output root in which the files are saved.

    Output:
        **_res_dict** (dict) - Dictionary with the results required to be read.

    Example:

    >>> res_dict = read_timeseries('my_output_folder', res_load=['p_mw', 'q_mvar'], res_sgen=['q_mvar'])

    """

    _results_dict = kwargs.get('_res', {})
    _res_dict = dict()
    for key, val in _results_dict.items():
        for _values in val:
            _key_page = key.split('_')[-1] + '_' + _values
            try:
                _file2read = os.path.join(_out_root, key, _values + '.xlsx')
                _res_dict[_key_page] = pd.read_excel(_file2read, index_col=0)
            except FileNotFoundError:
                _file2read = os.path.join(_out_root, key, _values + '.csv')
                _res_dict[_key_page] = pd.read_csv(_file2read, index_col=0)
                _res_dict[_key_page].columns = _res_dict[_key_page].columns.astype(np.int64)
    return _res_dict


def run_pf_timeseries_snapshot(_pp_net, _dict_profiles, _time_step, _out_root, _out_filetype, **kwargs):
    """
    This function runs a snapshot power flow from pandapower using timeseries engine.

    Input
Input:
        **_pp_net** (dict) - Pandapower network format.

        **_dict_profiles** (dict) - Dictionary with the dataframe of the profiles.

        **_time_steps** (List of integers) - Number of interval to be evaluated. It can be like a list of two elements,
        the initial and the final timesteps; or it can be a list of integers where each element is a timestep to be
        analyzed.

        **_out_root** (string) - Output directory for the timeseries results.

        **_out_filetype** (string) - Format file type in which the timeseries results are saved. it can be '.csv' and
        '.xlsx'.

    Output:
        **_res_dict** (dict) - Dictionary with the results of the timeseries for the output required. Usually the output
        required are the following:

        1. res_bus=['vm_pu', 'va_degree']
        2. res_line=['loading_percent']
        3. res_load=['p_mw', 'q_mvar']
        4. res_sgen=['p_mw', 'q_mvar']
        5. res_gen=['p_mw', 'q_mvar']
        6. res_storage=['p_mw', 'q_mvar']
        7. res_trafo=['loading_percent']
        8. res_trafo3w=['loading_percent']

        These output are the common outputs that pandapower put as available for the elements of the network.

    EXAMPLE:

    >>> import pandas as pd
    >>> import pandapower.networks as pn
    >>> net = pn.case14()
    >>> dict_profiles = {'load_prof_p': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'load_prof_q': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'sgen_prof_p': pd.DataFrame(shape=(24, net.sgen.index))}
    >>> dict_res = run_pf_timeseries(net, dict_profiles, [0, 24], 'my_out_root', '.csv', res_load=['p_mw', 'q_mvar'],
    >>>                              res_sgen='q_mvar')

    """

    _outputs = {key: val for key, val in kwargs.items()}
    t_steps = range(_time_step, _time_step + 1)

    _elements = None
    _elements_idx = None
    _vars = None
    for _k in _dict_profiles.keys():
        ds = DFData(_dict_profiles[_k])
        # supply-voltage profile of the external grid.
        if _k.startswith('ext_grid'):
            ConstControl(_pp_net, element='ext_grid', variable='vm_pu', data_source=ds,
                         element_index=_dict_profiles[_k].columns, profile_name=_dict_profiles[_k].columns,
                         recycle=False)
            continue
        if 'p' == _k.split('_')[-1]:
            _vars = 'p_mw'
            if 'load' in _k:
                _elements = 'load'
                _elements_idx = _pp_net.load.index
            elif 'sgen' in _k:
                _elements = 'sgen'
                _elements_idx = _pp_net.sgen.index
            elif 'gen' in _k:
                _elements = 'gen'
                _elements_idx = _pp_net.gen.index
            elif 'storage' in _k:
                _elements = 'storage'
                _elements_idx = _pp_net.storage.index
        elif 'q' == _k.split('_')[-1]:
            _vars = 'q_mvar'
            if 'load' in _k:
                _elements = 'load'
                _elements_idx = _pp_net.load.index
            elif 'sgen' in _k:
                _elements = 'sgen'
                _elements_idx = _pp_net.sgen.index
            elif 'gen' in _k:
                _elements = 'gen'
                _elements_idx = _pp_net.gen.index
            elif 'storage' in _k:
                _elements = 'storage'
                _elements_idx = _pp_net.storage.index
        try:
            ConstControl(_pp_net, element=_elements, variable=_vars, data_source=ds, element_index=_elements_idx,
                         profile_name=_dict_profiles[_k].columns, recycle=False)
        except Exception as _ex:
            raise UserWarning(type(_ex).__name__, _ex)

    _final_out_root = _out_root + '_snapshot'
    _create_output_writer(_pp_net, t_steps, _out_root=_final_out_root, _output_file_type=_out_filetype, _res=_outputs)

    run_timeseries(_pp_net, t_steps, continue_on_divergence=False)

    _res_dict = read_timeseries(_out_root=_final_out_root, _res=_outputs)

    # Remove additional directory
    shutil.rmtree(_final_out_root)

    return _res_dict


def plot_timeseries(_df2plot, _ylim, _ylabel=None, _title=None, _name_fig='None', _figsize=(10, 5), _plot_legend=False,
                    _labels=None):
    """
    This function plots the results of timeseries analysis.

    Input:
        **_df2plot** (Dataframe) - Dataframe with results to plot.

        **_ylabel** (string, None) - Y-axis label name.

        **_title** (string, None) - Title of the plot.

        **_figsize** (tuple, (10,5)) - Size of the window displaying the plot.

    Example:

    >>> import pandas as pd
    >>> import pandapower.networks as pn
    >>> net = pn.case14()
    >>> dict_profiles = {'load_prof_p': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'load_prof_q': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'sgen_prof_p': pd.DataFrame(shape=(24, net.sgen.index))}
    >>> dict_res = run_pf_timeseries(net, dict_profiles, [0, 24], 'my_out_root', '.csv', res_bus=['vm_pu'])
    >>> plot_timeseries(dict_res['bus_vm_pu'], _ylabel=None, _title=None, _figsize=(10, 5))

    """

    if not _df2plot.empty:
        if _labels is not None:
            _df2plot.columns = _labels
        fig, ax1 = plt.subplots(figsize=_figsize)
        _df2plot.plot(kind='line', ax=ax1)
        ax1.set_xlabel('Timestep', color='mediumblue', fontsize=11)
        ax1.set_ylabel(_ylabel, color='mediumblue', fontsize=11)
        fig.suptitle(_title, fontsize=12, fontweight='bold')
        ax1.set_ylim(_ylim)

        if _plot_legend:
            ax1.legend()
        else:
            ax1.get_legend().remove()

        plt.grid(color='lightgray', alpha=0.5, axis='y')

        fig.savefig(os.path.join(os.getcwd(), _name_fig + '.png'), format='png', dpi=600)
    else:
        fig = 0
    return fig


def change_net_fsp(_net, _hours2study, _timestep, _fsp_file, _ts_res, _root_fsp, _root_results, _simulation_tag):
    """
    This function adapts the initial resource profiles according to the results of the market.
    The new profiles take into account the flexibility accepted in the market.

    Input:
        **_net** (dict) - Pandapower network format.

        **_hours2study** (List of integers) - List of hours to study that present network constraint violations.
        In case the parameters "_int_cons" is True, this list of integers will be neglected,
        and instead the _timestep will be considered.

        **_timestep** (List of integers) - Number of interval to be evaluated. It is a list of two elements,
        the initial and the final timesteps.

        **_fsp_file** (dict) - Dictionary of file for each resource type.

        **_ts_res** (dict) - Dictionary of the timeseries results.

        **_root_fsp** (string) - Folder to the input fsp file.

        **_root_results** (string) - Folder to the results of the market.

        **_simulation_tag** (string) - Market simulation tag.

    Output:
        **dict_profiles_postmkt** (dict) - Dictionary of the timeseries results considering the flexibility accepted
        per resource in the flexibility market.

    Example:

        >>> import pandas as pd
        >>> import pandapower.networks as pn
        >>> net = pn.case14()
        >>> dict_profiles = {'load_p_mw': pd.DataFrame(shape=(24, net.load.index)).T,
        >>>                  'load_q_mvar': pd.DataFrame(shape=(24, net.load.index)).T,
        >>>                  'sgen_p_mw': pd.DataFrame(shape=(24, net.sgen.index)).T}
        >>> fsp_file = {'B': 'my_fsp_file.xlsx'}
        >>> dict_profiles_post_mkt = change_net_fsp(net, [1, 3, 5], [0, 24], fsp_file, dict_profiles, 'my_input_root',
        >>>                                         'my_output_root', 'my_simulation_tag')

    """
    _net_post = cp.deepcopy(_net)
    dict_profiles_postmkt_all = {_k: cp.deepcopy(_value.T) for _k, _value in _ts_res.items() if 'p_mw' in _k or 'q_mvar' in _k}

    for _fsp_type in _fsp_file.keys():
        sheet2read_p = 'W_' + _fsp_type
        sheet2read_q = 'R_' + _fsp_type
        if _fsp_file[_fsp_type] != 0:
            filename_fsp = _fsp_file[_fsp_type] + '.xlsx'
            FSPinfo = io_file.import_data(_filename=filename_fsp, _root=_root_fsp, _sheetname='FSPinfo_' + _fsp_type, _index_col=0)

            filename_res = 'model_results_' + _simulation_tag + '.xlsx'
            FSP_P = io_file.import_data(_filename=filename_res, _root=_root_results, _sheetname=sheet2read_p, _index_col=0)
            FSP_Q = io_file.import_data(_filename=filename_res, _root=_root_results, _sheetname=sheet2read_q, _index_col=0)
            for fsp_pos, i in enumerate(tqdm(FSPinfo.index, desc='FSP {_letter} processing'.format(_letter=_fsp_type))):
                fsp_row = FSPinfo.loc[i]
                _key_fsp_p = aux.get_list(_startswith_key=fsp_row.res_category + '_p_mw', _comparing_list=_ts_res)
                _key_fsp_q = aux.get_list(_startswith_key=fsp_row.res_category + '_q_mvar', _comparing_list=_ts_res)
                _fsp_res_p = dict_profiles_postmkt_all.get(_key_fsp_p[0], None)
                _fsp_res_q = dict_profiles_postmkt_all.get(_key_fsp_q[0], None)

                if fsp_row.res_category == 'load':
                    _net_res = cp.deepcopy(_net_post.load)
                elif fsp_row.res_category == 'sgen':
                    _net_res = cp.deepcopy(_net_post.sgen)
                elif fsp_row.res_category == 'storage':
                    _net_res = cp.deepcopy(_net_post.storage)
                elif fsp_row.res_category == 'gen':
                    _net_res = cp.deepcopy(_net_post.gen)
                else:
                    raise UserWarning('FSP Type "{_type}" not defined.'.format(_type=_fsp_type))

                index_res = match_pp_element(_net_res, fsp_row, fsp_row.res_category)
                for h in _hours2study:
                    _fsp_res_p.loc[index_res, h] = _result_value_by_fsp(FSP_P, i, fsp_pos, h)
                    _fsp_res_q.loc[index_res, h] = _result_value_by_fsp(FSP_Q, i, fsp_pos, h)
        else:
            print('No FSP {_letter} type identified.'.format(_letter=_fsp_type))

    dict_profiles_postmkt = {'_'.join(filter(None, _k.split('_')[0:-1])): cp.deepcopy(_value.loc[:, _hours2study].T)
                             for _k, _value in dict_profiles_postmkt_all.items()}
    return dict_profiles_postmkt


def select_pilot_bus(_net, _bus_voltages, _vbus_outbounds, _fsp_data, _hours, _out_root, _vn_kv_mv=15,
                     _flag_vpilot=False, _flag_only_mv=True, _flag_all_net=False):
    """
    This function selects the pilot buses. Defining the table of Voltage Magnitudes for all active busses and hours to
    study. Slack busses and FALSE busses are eliminated from the pilot buses; only the fsps busses and the busses with
    problems in the HoursToStudy are selected (not true). V pilots are the busses with FSPs and the one with problems.

    Input:
        **_net** (dict) - Pandapower network format.

        **_bus_voltages** (Dataframe) - Dataframe with bus voltage during the hours considered.

        **_vbus_outbounds** (Dataframe) - Dataframe with the buses that are with over and under voltage problems.

        **_fsp_data** (Dataframe) - Dataframe with the fsp data involved in the simulation.

        **_hours** (List of integers) - List of hours with network constraint violations.

        **_out_root** (string) - Output root where to save files.

        **_vn_kv_mv** (int, 15) - Reference voltage for Medium Voltage buses.

        **_flag_vpilot** (bool, False) - Boolean value for saving into csv file the bus voltages.

        **_flag_only_mv** (bool, True) - Boolean value for considering only medium voltage buses.

        **_flag_all_net** (bool, False) - Boolean value for considering all buses in the network.

    Output:
        **_pilot_bus** (List of integers) - List of the pilot buses selected.

        **_pilot_bus_hts** (Dataframe) - Dataframe of the pilot buses voltages in the congested hours.

    Example:

    >>> import pandas as pd
    >>> from enginiite.file_io import import_data
    >>> import pandapower.networks as pn
    >>> net = pn.case14()
    >>> dict_profiles = {'load_prof_p': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'load_prof_q': pd.DataFrame(shape=(24, net.load.index)),
    >>>                  'sgen_prof_p': pd.DataFrame(shape=(24, net.sgen.index))}
    >>> dict_res = run_pf_timeseries(net, dict_profiles, [0, 24], 'my_out_root', '.csv', res_bus=['vm_pu'])
    >>> fsp_data = import_data('my_fsp_file', 'my_fsp_in_root', 1, 'my_fsp_sheetname')
    >>> list_bus, vm_pu_pilot_bus = select_pilot_bus(_net=net, _bus_voltages=dict_res['bus_vm_pu'],
    >>>                                              _vbus_outbounds=pd.DataFrame([0, 4], columns=['Bus']), _fsp_data=fsp_data,
    >>>                                              _hours=[1, 2, 3], _out_root='my_out_root', _vn_kv_mv=25, _flag_vpilot=False,
    >>>                                              _flag_only_mv=True, _flag_all_net=False)

    """

    if _flag_vpilot:
        io_file.save_cvs(_data=_bus_voltages.T, _outroot=_out_root, _filename='VPilotBus_FULLH_FULLBUS')

    # Slack bus index
    _slack = list(_net.ext_grid.bus)
    # Index of not in service buses (sort automatically, if possible)
    _inactive_bus = list(_net.bus.index[_net.bus.in_service == False])
    # Union of "slack bus index" and "index of not in service buses"
    _drop_idx = _inactive_bus + _slack
    # List of index of bus that are over or under voltage of the limits
    _bus_outbounds = [x for x in np.unique(_vbus_outbounds.index)]

    if _flag_all_net:
        _ok_bus = list(set(_net.bus.index.to_list()) - set(_drop_idx))
    else:
        if _flag_only_mv:
            _idx_bus_not_mv = _net.bus.index[_net.bus.vn_kv != _vn_kv_mv].to_list()
            _ok_bus = list(set(_bus_outbounds) - set(_drop_idx) - set(_idx_bus_not_mv))
        else:
            _ok_bus = list(set(_bus_outbounds) - set(_drop_idx))

    fsp_bus = list(_fsp_data.bus)

    _pilot_bus = sorted(set(_ok_bus + fsp_bus), key=int)
    _pilot_bus_hts = _bus_voltages.loc[_hours, _pilot_bus].T
    _pilot_bus_hts.to_csv(os.path.join(_out_root, 'VPilotBus_HTS.csv'), header=True, index=True)
    # only for retro-compatibility
    _pilot_bus_hts.to_csv(os.path.join(_out_root, 'VPilotBus24h.csv'), header=True, index=True)
    return _pilot_bus, _pilot_bus_hts, _bus_outbounds


def check_fsp_pilotbus_position(_file_cfg_name, _pilot_bus, _fsp_bus):
    """
    This function plots the FSP and PilotBuses in the Pandapower Plot of the Network.
    """
    cfg_file = io_file.import_yaml(_yaml_filename=_file_cfg_name, _folder='config')
    net = io_file.import_network(cfg_file['network'])
    pp.runpp(net)
    fig = simple_plotly(net)
    fig.add_trace(go.Scatter(x=net.bus_geodata.loc[_pilot_bus, 'x'],
                             y=net.bus_geodata.loc[_pilot_bus, 'y'],
                             mode='markers'))
    fig.add_trace(go.Scatter(x=net.bus_geodata.loc[_fsp_bus, 'x'],
                             y=net.bus_geodata.loc[_fsp_bus, 'y'],
                             mode='markers', line=dict(color="#ffe476")))
    plotly.offline.plot(fig, filename=os.path.join(os.getcwd(), 'FSP_PilotBus.png'))
    return True
