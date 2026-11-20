import os
import math
import re
import warnings
import copy as cp
import numpy as np
import pandas as pd
import pandapower as pp
from pathlib import Path
import matplotlib.pyplot as plt
from enginiite import auxiliary as aux
from enginiite import file_io as io_file
from enginiite import tolerance_policy
from pandapower.plotting import fuse_geodata
from enginiite.kpis import plot_kpis as plt_kpi
from pandapower.plotting import draw_collections
from pandapower.plotting.plotly import pf_res_plotly
from pandapower.plotting import create_bus_collection
from pandapower.plotting import create_line_collection
from pandapower.plotting import create_trafo_collection
from pandapower.plotting import create_generic_coordinates
warnings.filterwarnings('ignore')
plt.ion()


def _check_consis(_value1, _value2):
    """
    Check consistency between kpi inputs requested from the user and config file inputs.

    :param _value1: kpi inputs requested from the user.

    :param _value2: config file inputs.
    """
    _tmp = list()
    for _val in _value1:
        if _val in _value2:
            _tmp.append(_val)
        else:
            print('The value {_value} is not simulated. It will be omitted in the KPI results'.format(_value=_val))

    if len(_tmp) == 0:
        _tmp = _value2
        print('The KPI results will consider the following scenario: {_value}'.format(_value=_tmp))
    return _tmp


def _get_scenario_names(_name_net, _mrk_model, _mrk_products, _mrk_vl, _mrk_fsps, _mrk_ess, _sim_tag):
    """
    Extract the names of the scenarios that the user want to analyse. The names are extracted from the combination
    of network name, market model, market products, market voltage violation limits, market service providers,
    market power batteries and market simulation tag.

    :param _name_net: Network name (string)

    :param _mrk_model: Market model (string)

    :param _mrk_products: Market products (list of strings)

    :param _mrk_vl: Voltage Limits of the market (list of strings)

    :param _mrk_fsps: Product service availability (list of strings)

    :param _sim_tag: Simulation tag (string)

    :return _list_of_scenarios: List of possible scenarios that are going to be evaluated for the kpi.
    """
    _list_of_scenarios = list()
    for _prod in _mrk_products:
        for _vl in _mrk_vl:
            for _fsp in _mrk_fsps:
                _filename = '_'.join(filter(None, [_name_net, _mrk_model, _prod, _vl, _fsp, _mrk_ess, _sim_tag]))
                _list_of_scenarios.append(_filename)
    return _list_of_scenarios


def _scenario_market_tags(_scenario_name, _in_dict):
    """Resolve product/VL/FSP without assuming underscore-free outer tags."""
    # Scenario IDs such as DER_LOC_LOW
    # are valid tags, so positional underscore splitting is not reliable.
    roots = (
        _in_dict.get('paths', {})
        .get('mrk_outputs', {})
        .get('ts_postmrk_out_root', {})
    )
    for product, vl_roots in roots.items():
        for voltage_limit, fsp_roots in vl_roots.items():
            for fsp_tag in fsp_roots:
                if f"_{product}_{voltage_limit}_{fsp_tag}_" in _scenario_name:
                    return product, voltage_limit, fsp_tag
    fallback = re.search(r"_(PQ|P|Q)_(VL\d+)_(F\d+)_", str(_scenario_name))
    if fallback:
        return fallback.groups()
    raise ValueError(f"Cannot resolve market tags from scenario name {_scenario_name!r}")


def _set_kpi_params(_cfg_file, _paths, _fsp_file, _prods, _vls, _fsps):
    """
    Define parameters useful for the evaluation of the KPI.

    :param _cfg_file: Yaml configuration file.

    :param _paths: Dictionary with all the paths for each specific scenario.

    :param _fsp_file: Dictionary of file for each resource type.

    :param _prods: List of products that the user want to analyse in the KPI evaluation.

    :param _vls: List of voltage limits that the user want to analyse in the KPI evaluation.

    :param _fsps: List of fsp availability that the user want to analyse in the KPI evaluation.
    """
    # KPIs configuration parameter
    _data_dict = dict()

    # Pandapower network
    net = io_file.import_network(_cfg_file['network'])

    # Network name under analysis
    name_net = _cfg_file['network']['net_folder']
    # Market Model under analysis
    mrk_model = _cfg_file['ModelTAG']
    # Products under analysis (Selected from the kpi settings dictionary)
    mrk_products = _check_consis(_prods, _cfg_file['ProductTAG'])
    # Voltage Limitations under analysis (Selected from the kpi settings dictionary)
    mrk_vl = _check_consis(_vls, _cfg_file['VLTAG'])
    # FSP under analysis (Selected from the kpi settings dictionary)
    mrk_fsps = _check_consis(_fsps, _cfg_file['FspTAG'])
    # Market ESS under analysis
    mrk_ess = _cfg_file['StorageTag']
    # Simulation tag
    sim_tag = _cfg_file['simulation_tag']

    # Scenarios that will be considered in the KPI results
    scenarios = _get_scenario_names(name_net, mrk_model, mrk_products, mrk_vl, mrk_fsps, mrk_ess, sim_tag)

    # Voltage Limitation Enlargement Gaps
    dV = tolerance_policy.VOLTAGE_SCENARIO_DELTAS
    dV_color = {'VL01': 'red', 'VL02': 'blue', 'VL03': 'green', 'VL04': 'red'}
    # Maximum and Minimum Voltage Limitation of pre market
    vbus_min_pre = [0.95 - dV.get(_vl, 0) for _vl in mrk_vl]
    vbus_max_pre = [1.05 + dV.get(_vl, 0) for _vl in mrk_vl]
    # Maximum Current Limitation in percentage before the market
    i_max_perc_pre = 100
    # Core physical KPIs use the same
    # scenario standard before and after market. Preventive and optimization
    # thresholds are stored separately instead of widening the physical band.
    tolerance = tolerance_policy.build_tolerance_policy(_cfg_file, mrk_vl)
    current_policy = tolerance['current']
    i_max_perc_post = current_policy['standard_percent']
    vbus_min_post = list(vbus_min_pre)
    vbus_max_post = list(vbus_max_pre)

    # Check if the FSP category exist
    for _fsp_type in _fsp_file.keys():
        if _fsp_file[_fsp_type] != 0:
            _data_dict['flat_' + _fsp_type] = True
        else:
            _data_dict['flat_' + _fsp_type] = False

    # Slack Variable Costs (Congestion Management - beta, and Voltage Control - alpha)
    _data_dict['cost_alpha'] = float(_cfg_file['BetaCost'])
    _data_dict['cost_beta'] = float(_cfg_file['BetaCost'])
    # Pandapower Network
    _data_dict['network'] = cp.deepcopy(net)
    # Scenarios under analysis
    _data_dict['scenarios_selected'] = scenarios
    # Voltage Limits of the market
    _data_dict['vl_lims'] = mrk_vl
    # Color for the Voltage Limits
    _data_dict['vl_colors'] = dV_color
    # Pre market
    _data_dict['vbus_max_pre'] = vbus_max_pre
    _data_dict['vbus_min_pre'] = vbus_min_pre
    _data_dict['i_max_perc_pre'] = i_max_perc_pre
    # Post market
    _data_dict['vbus_max_post'] = vbus_max_post
    _data_dict['vbus_min_post'] = vbus_min_post
    _data_dict['i_max_perc_post'] = i_max_perc_post
    _data_dict['current_thresholds'] = current_policy
    _data_dict['voltage_thresholds'] = tolerance['voltage']
    _data_dict['mrk_ess'] = mrk_ess
    _data_dict['sim_tag'] = sim_tag

    # Paths for directories
    _data_dict['paths'] = _paths

    # Dots per Inch of KPI result figures
    dpi_img = 600
    _data_dict['dpi_img'] = dpi_img
    return _data_dict


def _load_res_net_pre(_in_dict, _scenarios):
    """
    Load data of the network before the market.

    :param _in_dict: Dictionary with all the information for evaluating the kpis.

    :param _scenarios: List of string of names of the scenarios that the user want to analyse.
    """
    _net = _in_dict['network']
    _fsp_file = _in_dict['fsp_file']
    _kpi_path = _in_dict['paths']
    _root2timeseries_res = _kpi_path['ts_out_root']
    _in_dict['lines_ldg_perc_pre'] = dict()
    _in_dict['trafos_ldg_perc_pre'] = dict()
    _in_dict['trafos3w_ldg_perc_pre'] = dict()
    _in_dict['bus_vmpu_pre'] = dict()

    for name_tab in _scenarios:
        # Lines Data
        path_file_line = os.path.join(_root2timeseries_res, 'res_line')
        loading_percent_line = io_file.import_data(_filename='loading_percent.csv', _root=path_file_line, _index_col=0)
        _in_dict['lines_ldg_perc_pre'][name_tab] = _coerce_numeric_axis_labels(loading_percent_line.T)

        # Trafos Data
        if not _net.trafo.empty:
            path_file_trafos = os.path.join(_root2timeseries_res, 'res_trafo')
            loading_percent_trafos = io_file.import_data(_filename='loading_percent.csv', _root=path_file_trafos,
                                                         _index_col=0)
            _in_dict['trafos_ldg_perc_pre'][name_tab] = _coerce_numeric_axis_labels(loading_percent_trafos.T)

        # Trafos 3Winding Data
        if not _net.trafo3w.empty:
            path_file_trafos3W = os.path.join(_root2timeseries_res, 'res_trafo3w')
            loading_percent_trafos3W = io_file.import_data(_filename='loading_percent.csv', _root=path_file_trafos3W,
                                                           _index_col=0)
            _in_dict['trafos3w_ldg_perc_pre'][name_tab] = _coerce_numeric_axis_labels(loading_percent_trafos3W.T)

        # Bus Data
        path_file_bus = os.path.join(_root2timeseries_res, 'res_bus')
        vm_pu_bus = io_file.import_data(_filename='vm_pu.csv', _root=path_file_bus, _index_col=0)
        _in_dict['bus_vmpu_pre'][name_tab] = _coerce_numeric_axis_labels(vm_pu_bus.T)

    return _in_dict


def _load_res_net_post(_in_dict, _scenarios):
    """
    Load data after the market.

    :param _in_dict: Dictionary with all the information for evaluating the kpis.

    :param _scenarios: List of string of names of the scenarios that the user want to analyse.
    """
    _net = _in_dict['network']
    _kpi_path = _in_dict['paths']
    _in_dict['lines_ldg_perc_post'] = dict()
    _in_dict['trafos_ldg_perc_post'] = dict()
    _in_dict['trafos3w_ldg_perc_post'] = dict()
    _in_dict['bus_vmpu_post'] = dict()

    for name_tab in _scenarios:
        _prod, _vl, _fsp = _scenario_market_tags(name_tab, _in_dict)
        _root2timeseries_postmrk_res = _kpi_path['mrk_outputs']['ts_postmrk_out_root'][_prod][_vl][_fsp]

        # Lines Data
        path_file_line = os.path.join(_root2timeseries_postmrk_res, 'res_line')
        loading_percent_line = io_file.import_data(_filename='loading_percent.csv', _root=path_file_line, _index_col=0)
        _in_dict['lines_ldg_perc_post'][name_tab] = _coerce_numeric_axis_labels(loading_percent_line.T)

        # Trafos Data
        if not _net.trafo.empty:
            path_file_trafos = os.path.join(_root2timeseries_postmrk_res, 'res_trafo')
            loading_percent_trafos = io_file.import_data(_filename='loading_percent.csv', _root=path_file_trafos,
                                                         _index_col=0)
            _in_dict['trafos_ldg_perc_post'][name_tab] = _coerce_numeric_axis_labels(loading_percent_trafos.T)

        if not _net.trafo3w.empty:
            path_file_trafos3w = os.path.join(_root2timeseries_postmrk_res, 'res_trafo3w')
            loading_percent_trafos3w = io_file.import_data(_filename='loading_percent.csv', _root=path_file_trafos3w,
                                                           _index_col=0)
            _in_dict['trafos3w_ldg_perc_post'][name_tab] = _coerce_numeric_axis_labels(loading_percent_trafos3w.T)

        # Bus Data
        path_file_bus = os.path.join(_root2timeseries_postmrk_res, 'res_bus')
        vm_pu_bus = io_file.import_data(_filename='vm_pu.csv', _root=path_file_bus, _index_col=0)
        _in_dict['bus_vmpu_post'][name_tab] = _coerce_numeric_axis_labels(vm_pu_bus.T)
    return _in_dict


def _load_offered_quantity(_in_dict, _scenarios):
    """
    Load offered Quantity in the Market.

    :param _in_dict: Dictionary with all the information for evaluating the kpis.

    :param _scenarios: List of string of names of the scenarios that the user want to analyse.
    """
    _fsp_file = _in_dict['fsp_file']
    _kpi_path = _in_dict['paths']['mrk_inputs']
    _root2timeseries_res = _in_dict['paths']['ts_out_root']
    _in_dict['offered_quantity'] = dict()
    _sheet2read_R = ['RUB_', 'RLB_']
    _sheet2read_W = ['WUB_', 'WLB_']
    _sheet2read = cp.deepcopy(_sheet2read_R)
    _sheet2read.extend(_sheet2read_W)

    for name_tab in _scenarios:
        _in_dict['offered_quantity'][name_tab] = {'R': 0, 'W': 0}
        _prod, _vl, _fsp = _scenario_market_tags(name_tab, _in_dict)
        _root2fspinit_file = _kpi_path[_prod][_vl][_fsp]
        for fsp_type in _fsp_file.keys():
            _filename = 'FSP' + fsp_type + '_init' + name_tab + '.xlsx'
            expected_path = os.path.join(_root2fspinit_file, _filename)
            if not os.path.exists(expected_path):
                # Result folders use the
                # shortened output network tag, while legacy KPI scenario names
                # may retain the complete input network tag. Resolve the one
                # actual FSP workbook by its market and simulation suffix.
                suffix = '_' + '_'.join(
                    filter(None, [
                        _prod, _vl, _fsp,
                        _in_dict.get('mrk_ess', ''),
                        _in_dict.get('sim_tag', ''),
                    ])
                ) + '.xlsx'
                candidates = sorted(
                    Path(_root2fspinit_file).glob('FSP' + fsp_type + '_init*.xlsx')
                )
                matches = [path for path in candidates if path.name.endswith(suffix)]
                if len(matches) != 1:
                    raise FileNotFoundError(
                        'Could not uniquely resolve the offered-quantity FSP workbook. '
                        f'Expected {expected_path}; matching candidates={matches}'
                    )
                _filename = matches[0].name
            # Close the workbook handle
            # immediately after reading sheet names so that Windows, or a cloud-sync client, does
            # not keep FSP files locked during cleanup or replacement.
            with pd.ExcelFile(os.path.join(_root2fspinit_file, _filename)) as xls:
                list_sheets = {_key: 0 for _key in xls.sheet_names}
            for _sheet in _sheet2read:
                list2read = aux.get_list(_startswith_key=_sheet, _comparing_list=list_sheets)
                for _element in list2read:
                    offered_quantity = io_file.import_data(_filename=_filename, _root=_root2fspinit_file, _sheetname=_element, _index_col=0)
                    if _sheet in _sheet2read_R:
                        init_R = io_file.import_data(_filename=_filename, _root=_root2fspinit_file, _sheetname='Rinit_' + fsp_type, _index_col=0)
                        _in_dict['offered_quantity'][name_tab]['R'] += offered_quantity.abs().subtract(init_R.abs()).abs().sum().sum()
                    elif _sheet in _sheet2read_W:
                        init_W = io_file.import_data(_filename=_filename, _root=_root2fspinit_file, _sheetname='Winit_' + fsp_type, _index_col=0)
                        _in_dict['offered_quantity'][name_tab]['W'] += offered_quantity.abs().subtract(init_W.abs()).abs().sum().sum()
    return _in_dict


def _load_cleared_quantity(_in_dict, _scenarios):
    """
    Load cleared quantity of the Market.

    :param _in_dict: Dictionary with all the information for evaluating the kpis.

    :param _scenarios: List of string of names of the scenarios that the user want to analyse.
    """
    _fsp_file = _in_dict['fsp_file']
    _kpi_path = _in_dict['paths']['mrk_outputs']['res_market']
    _in_dict['cleared_quantity'] = dict()

    for name_tab in _scenarios:
        _in_dict['cleared_quantity'][name_tab] = {'R': 0, 'W': 0}
        _prod, _vl, _fsp = _scenario_market_tags(name_tab, _in_dict)
        _root2res_file = _kpi_path[_prod][_vl][_fsp]
        for fsp_type in _fsp_file.keys():
            _filename = 'Support_' + fsp_type + '.xlsx'
            cleared_quantity = io_file.import_data(_filename=_filename, _root=_root2res_file, _sheetname=fsp_type, _index_col=0)
            _in_dict['cleared_quantity'][name_tab]['R'] += cleared_quantity['SupportQ_' + fsp_type].abs().sum()
            _in_dict['cleared_quantity'][name_tab]['W'] += cleared_quantity['SupportP_' + fsp_type].abs().sum()
    return _in_dict


def max_mat_df(_input_df):
    """
    Extract the maximum value, the row (node) and the column (hour) in the dataframe passed as input.

    :param _input_df: Dataframe with nodes as rows and hours as columns.
    """
    df = _input_df.fillna(value=0)
    if not pd.DataFrame(df).empty:
        max_val = df.values.max()
        # Coordinates of all maximum values
        max_coords = list(zip(*np.where(df.values == max_val)))
        # Row and column names corresponding to each coordinates
        max_names = [(df.index[r], df.columns[c]) for r, c in max_coords]
        max_val = max_val
        node = max_names[0][0]
        hour = max_names[0][1]
    else:
        max_val = 'Empty'
        node = 'Empty'
        hour = 'Empty'
    return float(max_val), int(node), int(hour)


def _coerce_numeric_axis_labels(_df):
    """Return a copy whose index/columns are numeric when all labels are numeric.

    Pandapower time-series CSVs are often read with element indices as strings
    (for example columns '0', '1', '2'). After transposing, these become row
    labels. KPI code then looks up actual bus/line labels such as 2. Without
    this normalization, .loc[2, hour] fails even though row '2' exists.
    Non-numeric labels are left unchanged.
    """
    df = pd.DataFrame(_df).copy()
    for axis in (0, 1):
        labels = df.index if axis == 0 else df.columns
        numeric = pd.to_numeric(pd.Index(labels), errors='coerce')
        if len(labels) > 0 and pd.notna(numeric).all():
            # Preserve integer-like labels as int so bus 2 matches row label 2.
            if np.all(np.isclose(numeric.astype(float), np.round(numeric.astype(float)))):
                new_labels = pd.Index(numeric.astype(int))
            else:
                new_labels = pd.Index(numeric.astype(float))
            if axis == 0:
                df.index = new_labels
            else:
                df.columns = new_labels
    return df


def _safe_table_value(_df, row_label, col_label, table_name='table'):
    """Robust label lookup with clear diagnostics for KPI tables."""
    df = _coerce_numeric_axis_labels(_df)
    row = int(row_label) if isinstance(row_label, (np.integer, int)) or str(row_label).isdigit() else row_label
    col = int(col_label) if isinstance(col_label, (np.integer, int)) or str(col_label).isdigit() else col_label
    if row not in df.index:
        raise KeyError(
            f"{table_name}: row label {row!r} not found. Available labels sample: {list(df.index[:10])}. "
            "This usually means element labels and positional indices are being mixed, or CSV labels were not normalized."
        )
    if col not in df.columns:
        raise KeyError(
            f"{table_name}: column label {col!r} not found. Available labels sample: {list(df.columns[:10])}."
        )
    return df.loc[row, col]


def eval_hosting_capacity(_net, _data):
    """
    Evaluate the hosting capacity increase in the network.

    :param _net: Pandapower network

    :param _data: Dictionary with all the information for evaluating the hosting capacity.
    """
    # Data inputs
    vpu_table = _coerce_numeric_axis_labels(_data['vpu_table'])
    ip_line_table = _coerce_numeric_axis_labels(_data['Ipline_table'])
    ip_trafo_table = _coerce_numeric_axis_labels(_data['Iptrafo_table'])
    ip_trafo3w_table = _coerce_numeric_axis_labels(_data['Iptrafo3w_table'])
    hc_info = _data['HC_info']
    vmax = _data['vbus_max_V']
    imax = _data['i_max_perc']

    # Hosting Capacity from Voltage in buses
    if not pd.DataFrame(hc_info).empty:
        dvdp = float(hc_info.HV_m)
        v_base = _net.bus.loc[hc_info.index[0], 'vn_kv']
        v_node = float(hc_info.maxV_val)
        hc_v = (vmax - v_node) * v_base / dvdp  # MVA
    else:
        hc_v = np.inf
        v_node = np.inf

    # Hosting Capacity from lines
    if not pd.DataFrame(ip_line_table).empty:
        line_loading_perc = ip_line_table.max().max()
        max_value_columns = ip_line_table.max()
        hours_max_loading_line = max_value_columns.idxmax()
        index_row_max = ip_line_table.idxmax(axis=0)
        lines = index_row_max[hours_max_loading_line]

        line_idx = int(lines)
        from_bus = _net.line.loc[line_idx, 'from_bus']
        max_i_ka = _net.line.loc[line_idx, 'max_i_ka']
        df = _net.line.loc[line_idx, 'df']
        parallel = _net.line.loc[line_idx, 'parallel']
        vn_line = _net.bus.loc[from_bus, 'vn_kv']
        voltage_line = vn_line * _safe_table_value(vpu_table, from_bus, hours_max_loading_line, table_name='vpu_table')
        hc_i = math.sqrt(3) * (((imax - line_loading_perc) / 100) * max_i_ka * df * parallel * voltage_line)
    else:
        hc_i = np.inf
        lines = np.inf
        hours_max_loading_line = np.inf
        line_loading_perc = np.inf

    # Hosting Capacity from Transformers 2 windings
    if not pd.DataFrame(ip_trafo_table).empty:
        trafo_loading_perc, trafos, hours_max_loading_trafo = max_mat_df(ip_trafo_table)
        hc_trafo = ((imax - trafo_loading_perc) / 100) * _net.trafo.loc[int(trafos), 'sn_mva']
    else:
        hc_trafo = np.inf
        trafos = np.inf
        hours_max_loading_trafo = np.inf
        trafo_loading_perc = np.inf

    # Hosting Capacity from Transformers 3 windings
    if not pd.DataFrame(ip_trafo3w_table).empty:
        trafo3w_loading_perc, trafos3w, hours_max_loading_trafo3w = max_mat_df(ip_trafo3w_table)
        hc_trafo3w = ((imax - trafo3w_loading_perc) / 100) * _net.trafo3w.loc[int(trafos3w), 'sn_hv_mva']
    else:
        hc_trafo3w = np.inf
        trafos3w = np.inf
        hours_max_loading_trafo3w = np.inf
        trafo3w_loading_perc = np.inf

    tmp_hc = [hc_v, hc_i, hc_trafo, hc_trafo3w]
    comp = [v_node, lines, trafos, trafos3w]
    type_column = ['Node', 'Line', 'Trafo', 'Trafo3W']
    ind = tmp_hc.index(min(tmp_hc))
    hosting_cap = min(tmp_hc)

    # Results
    hc_res = dict()
    hc_res['Hosting Capacity [MVA]'] = round(hosting_cap, 3)
    hc_res['Type component'] = type_column[ind]
    hc_res['ID component'] = comp[ind]

    if not pd.DataFrame(hc_info).empty:
        hc_res['VC HC [MVA]'] = round(hc_v, 3)
        hc_res['VC Vmax [pu]'] = round(v_node, 3)
        hc_res['VC Node'] = hc_info.index[0]
        hc_res['VC hour'] = int(hc_info.maxV_hour)

    if not pd.DataFrame(ip_line_table).empty:
        hc_res['CM HC_L [MVA]'] = round(hc_i, 3)
        hc_res['CM perc_Load_L [%]'] = round(line_loading_perc, 3)
        hc_res['CM ID line'] = int(lines)
        hc_res['CM line_hour'] = hours_max_loading_line

    if not pd.DataFrame(ip_trafo_table).empty:
        hc_res['CM HC_T [MVA]'] = round(hc_trafo, 3)
        hc_res['CM perc_Load_T [%]'] = round(trafo_loading_perc, 3)
        hc_res['CM ID trafo'] = int(trafos)
        hc_res['CM trafo_hour'] = hours_max_loading_trafo

    if not pd.DataFrame(ip_trafo3w_table).empty:
        hc_res['CM HC_T3W [MVA]'] = round(hc_trafo3w, 3)
        hc_res['CM perc_Load_T3W [%]'] = round(trafo3w_loading_perc, 3)
        hc_res['CM ID trafo3W'] = int(trafos3w)
        hc_res['CM trafo3W_hour'] = hours_max_loading_trafo3w
    return hc_res


def increase_hc(_in_dict):
    """
    Evaluate the increase in the hosting capacity for each scenario.
    It requires the function eval_hosting_capacity(_net, _data), to calculate the increase in Hosting Capacity
    for an entire study. Increase in Hosting Capacity is calculated as the difference between post-market
    and pre-market.

    :param _in_dict: Dictionary with all the information for evaluating the kpis.
    """
    net = _in_dict['network']
    v_limits = _in_dict['vl_lims']
    scenarios = _in_dict['scenarios_selected']
    # Pre-market data
    lines_ldg_perc_pre = _in_dict['lines_ldg_perc_pre']
    trafos_ldg_perc_pre = _in_dict['trafos_ldg_perc_pre']
    trafos3w_ldg_perc_pre = _in_dict['trafos3w_ldg_perc_pre']
    bus_vmpu_pre = _in_dict['bus_vmpu_pre']
    hc_pre = _in_dict['hc_pre']
    vbus_max_pre = _in_dict['vbus_max_pre']
    i_max_perc_pre = _in_dict['i_max_perc_pre']
    # Post-market data
    lines_ldg_perc_post = _in_dict['lines_ldg_perc_post']
    trafos_ldg_perc_post = _in_dict['trafos_ldg_perc_post']
    trafos3w_ldg_perc_post = _in_dict['trafos3w_ldg_perc_post']
    bus_vmpu_post = _in_dict['bus_vmpu_post']
    hc_post = _in_dict['hc_post']
    vbus_max_post = _in_dict['vbus_max_post']
    i_max_perc_post = _in_dict['i_max_perc_post']

    v_lims = {market: idx for idx, market in enumerate(v_limits)}
    hc_res_pre = dict()
    hc_res_post = dict()
    ihc_res = dict()
    pihc_res = dict()
    null_var = dict()

    for name_tab in scenarios:
        _, _vl_type, _ = _scenario_market_tags(name_tab, _in_dict)

        _data_pre = dict()
        _data_post = dict()

        # Before Market
        _data_pre['vpu_table'] = bus_vmpu_pre[name_tab]
        _data_pre['Ipline_table'] = lines_ldg_perc_pre[name_tab]
        _data_pre['Iptrafo_table'] = trafos_ldg_perc_pre[name_tab] if trafos_ldg_perc_pre else null_var
        _data_pre['Iptrafo3w_table'] = trafos3w_ldg_perc_pre[name_tab] if trafos3w_ldg_perc_pre else null_var
        _data_pre['HC_info'] = hc_pre[name_tab] if not pd.DataFrame(hc_pre).empty else hc_pre
        _data_pre['vbus_max_V'] = vbus_max_pre[v_lims[_vl_type] if _vl_type in v_lims else None]
        _data_pre['i_max_perc'] = i_max_perc_pre

        hc_res_pre[name_tab] = eval_hosting_capacity(_net=net, _data=_data_pre)

        # After Market
        _data_post['vpu_table'] = bus_vmpu_post[name_tab]
        _data_post['Ipline_table'] = lines_ldg_perc_post[name_tab]
        _data_post['Iptrafo_table'] = trafos_ldg_perc_post[name_tab] if trafos_ldg_perc_post else null_var
        _data_post['Iptrafo3w_table'] = trafos3w_ldg_perc_post[name_tab] if trafos3w_ldg_perc_post else null_var
        _data_post['HC_info'] = hc_post[name_tab] if not pd.DataFrame(hc_post).empty else hc_post
        _data_post['vbus_max_V'] = vbus_max_post[v_lims[_vl_type] if _vl_type in v_lims else None]
        _data_post['i_max_perc'] = i_max_perc_post

        hc_res_post[name_tab] = eval_hosting_capacity(_net=net, _data=_data_post)

    ihc_res['Increase Hosting Capacity [MVA]'] = pd.DataFrame(hc_res_post).T['Hosting Capacity [MVA]'] - \
                                                 pd.DataFrame(hc_res_pre).T['Hosting Capacity [MVA]']
    pihc_res['Percentage of IHC [%]'] = (ihc_res['Increase Hosting Capacity [MVA]'] / pd.DataFrame(hc_res_pre).T[
        'Hosting Capacity [MVA]'].abs()) * 100

    ihc_res = pd.DataFrame(ihc_res)
    pihc_res = pd.DataFrame(pihc_res)
    hc_res_post = pd.DataFrame(hc_res_post)
    hc_res_pre = pd.DataFrame(hc_res_pre)

    return hc_res_pre, hc_res_post, ihc_res, pihc_res


def _congestion_transition_counts(_table_pre, _table_post, _threshold):
    """Classify each aligned asset-hour cell as resolved, persistent, or new."""
    pre = pd.DataFrame(_table_pre).apply(pd.to_numeric, errors='coerce')
    post = pd.DataFrame(_table_post).apply(pd.to_numeric, errors='coerce')
    pre, post = pre.align(post, join='outer', axis=None)
    # Post-market power flow may contain only the studied hours. Unsimulated
    # cells retain their pre-market state rather than becoming false resolutions.
    post = post.combine_first(pre)
    pre_violation = pre.gt(_threshold).fillna(False)
    post_violation = post.gt(_threshold).fillna(False)

    # Congestion transitions are evaluated
    # cell by cell, so new violations cannot be mistaken for unresolved old ones.
    resolved = int((pre_violation & ~post_violation).to_numpy().sum())
    persistent = int((pre_violation & post_violation).to_numpy().sum())
    new = int((~pre_violation & post_violation).to_numpy().sum())
    return {
        'pre': resolved + persistent,
        'post': persistent + new,
        'resolved': resolved,
        'persistent': persistent,
        'new': new,
        'net_resolved': resolved - new,
    }


def eval_avoided_congestion(_data_pre, _data_post, _round_val=3):
    """
    Evaluate the avoided congestion in the network between the pre- and post-market.

    :param _data_pre: Dictionary with all the information pre-market for evaluating the avoided congestions.

    :param _data_post: Dictionary with all the information post-market for evaluating the avoided congestions.

    :param _round_val: Value to which all value are rounded.
    """
    ip_line_table_pre = _data_pre['Ipline_table']
    ip_trafo_table_pre = _data_pre['Iptrafo_table']
    ip_trafo3w_table_pre = _data_pre['Iptrafo3w_table']
    imax_pre = _data_pre['i_max_perc']

    ip_line_table_post = _data_post['Ipline_table']
    ip_trafo_table_post = _data_post['Iptrafo_table']
    ip_trafo3w_table_post = _data_post['Iptrafo3w_table']
    imax_post = _data_post['i_max_perc']

    line_status = _congestion_transition_counts(ip_line_table_pre, ip_line_table_post, imax_pre)
    trafo_status = _congestion_transition_counts(ip_trafo_table_pre, ip_trafo_table_post, imax_pre)
    trafo3w_status = _congestion_transition_counts(ip_trafo3w_table_pre, ip_trafo3w_table_post, imax_pre)

    # Congestion Management lines
    n_pre_lines = line_status['pre']
    n_post_lines = line_status['post']

    # Congestion Management transformers
    n_pre_trafo = trafo_status['pre']
    n_post_trafo = trafo_status['post']

    # Congestion Management trafos3W
    n_pre_trafo3w = trafo3w_status['pre']
    n_post_trafo3w = trafo3w_status['post']
    n_pre_total = n_pre_lines + n_pre_trafo + n_pre_trafo3w
    n_post_total = n_post_lines + n_post_trafo + n_post_trafo3w
    try:
        avoided_congestion = ((n_pre_total - n_post_total) / n_pre_total) * 100
    except ZeroDivisionError:
        avoided_congestion = 0

    # Results
    avoided_congestion_res = dict()
    avoided_congestion_res['AvoidCongestions [%]'] = round(avoided_congestion, _round_val)
    avoided_congestion_res['n_pre_Total [u]'] = round(n_pre_total, _round_val)
    avoided_congestion_res['n_post_Total [u]'] = round(n_post_total, _round_val)

    avoided_congestion_res['n_pre_L [u]'] = round(n_pre_lines, _round_val)
    avoided_congestion_res['n_post_L [u]'] = round(n_post_lines, _round_val)
    avoided_congestion_res['AvoidCong_L[u]'] = round(n_pre_lines, _round_val) - round(n_post_lines, _round_val)

    avoided_congestion_res['n_pre_T [u]'] = round(n_pre_trafo, _round_val)
    avoided_congestion_res['n_post_T [u]'] = round(n_post_trafo, _round_val)
    avoided_congestion_res['AvoidCong_T[u]'] = round(n_pre_trafo, _round_val) - round(n_post_trafo, _round_val)

    avoided_congestion_res['n_pre_T3w [u]'] = round(n_pre_trafo3w, _round_val)
    avoided_congestion_res['n_post_T3w [u]'] = round(n_post_trafo3w, _round_val)
    avoided_congestion_res['AvoidCong_T3w[u]'] = round(n_pre_trafo3w, _round_val) - round(n_post_trafo3w, _round_val)

    # Internal transition fields are consumed by avoided_cong and excluded from
    # the legacy standard-detail block to avoid repeated Excel columns.
    avoided_congestion_res['_ResolvedCong_Total [u]'] = (
        line_status['resolved'] + trafo_status['resolved'] + trafo3w_status['resolved']
    )
    avoided_congestion_res['_PersistentCong_Total [u]'] = (
        line_status['persistent'] + trafo_status['persistent'] + trafo3w_status['persistent']
    )
    avoided_congestion_res['_NewCong_Total [u]'] = (
        line_status['new'] + trafo_status['new'] + trafo3w_status['new']
    )

    return avoided_congestion_res


def avoided_cong(_in_dict, _scenarios):
    """
    Evaluate the Avoided Congestion Problems - Lines and Transformers (2 windings and 3 windings).

    :param _in_dict: Dictionary with all the information for evaluating the avoided congestions.

    :param _scenarios: List of string of names of the scenarios that the user want to analyse.
    """

    lines_ldg_perc_pre = _in_dict['lines_ldg_perc_pre']
    trafos_ldg_perc_pre = _in_dict['trafos_ldg_perc_pre']
    trafos3w_ldg_perc_pre = _in_dict['trafos3w_ldg_perc_pre']
    lines_ldg_perc_post = _in_dict['lines_ldg_perc_post']
    trafos_ldg_perc_post = _in_dict['trafos_ldg_perc_post']
    trafos3w_ldg_perc_post = _in_dict['trafos3w_ldg_perc_post']
    current = _in_dict.get('current_thresholds', {
        'standard_percent': 100.0,
        'detection_limit_percent': _in_dict['i_max_perc_pre'],
        'optimization_target_percent': _in_dict['i_max_perc_post'],
    })
    thresholds = (
        ('standard', current['standard_percent']),
        ('detection', current['detection_limit_percent']),
        ('optimization', current['optimization_target_percent']),
    )

    avoided_cong_res = dict()
    null_var = dict()

    for name_tab in _scenarios:
        _data_pre = dict()
        _data_post = dict()

        _data_pre['Ipline_table'] = lines_ldg_perc_pre[name_tab]
        _data_pre['Iptrafo_table'] = trafos_ldg_perc_pre[name_tab] if trafos_ldg_perc_pre else null_var
        _data_pre['Iptrafo3w_table'] = trafos3w_ldg_perc_pre[name_tab] if trafos3w_ldg_perc_pre else null_var
        _data_post['Ipline_table'] = lines_ldg_perc_post[name_tab]
        _data_post['Iptrafo_table'] = trafos_ldg_perc_post[name_tab] if trafos_ldg_perc_post else null_var
        _data_post['Iptrafo3w_table'] = trafos3w_ldg_perc_post[name_tab] if trafos3w_ldg_perc_post else null_var

        # Avoided congestion is reported
        # side-by-side at the standard, detection, and optimization thresholds.
        row = {}
        standard_detail = None
        for threshold_name, threshold in thresholds:
            _data_pre['i_max_perc'] = threshold
            _data_post['i_max_perc'] = threshold
            detail = eval_avoided_congestion(_data_pre=_data_pre, _data_post=_data_post, _round_val=3)
            row['AvoidCongestion_' + threshold_name + ' [%]'] = detail['AvoidCongestions [%]']
            row['Threshold_' + threshold_name + ' [%]'] = round(threshold, 5)
            row['AvoidCongestion_' + threshold_name + ' [u]'] = detail['n_pre_Total [u]'] - detail['n_post_Total [u]']
            row['ResolvedCongestion_' + threshold_name + ' [u]'] = detail['_ResolvedCong_Total [u]']
            row['PersistentCongestion_' + threshold_name + ' [u]'] = detail['_PersistentCong_Total [u]']
            row['NewCongestion_' + threshold_name + ' [u]'] = detail['_NewCong_Total [u]']
            if threshold_name == 'standard':
                standard_detail = detail
        if standard_detail:
            # Keep the detailed standard
            # counts, but do not repeat the already reported standard summary.
            repeated = {'AvoidCongestions [%]'}
            row.update({
                key: value for key, value in standard_detail.items()
                if not key.startswith('_') and key not in repeated
            })
        avoided_cong_res[name_tab] = row

    avoided_cong_res = pd.DataFrame(avoided_cong_res).T
    return avoided_cong_res


def eval_avoided_voltage_violation(_data_pre, _data_post, _round_val=3):
    """
    Evaluate the avoided congestion in the network between the pre- and post-market.

    :param _data_pre: Dictionary with all the information pre-market for evaluating the avoided voltage violations.

    :param _data_post: Dictionary with all the information post-market for evaluating the avoided voltage violations.

    :param _round_val: Value to which all value are rounded.
    """
    # Data inputs
    vpu_table_pre = _data_pre['vpu_table']
    vmax_pre = _data_pre['vbus_max']
    vmin_pre = _data_pre['vbus_min']

    vpu_table_post = _data_post['vpu_table']
    vmax_post = _data_post['vbus_max']
    vmin_post = _data_post['vbus_min']

    # Voltage Violations from nodes
    # Pre-Market
    n_pre_under = np.count_nonzero((vpu_table_pre < vmin_pre) & (vpu_table_pre > 0.1))
    n_pre_over = np.count_nonzero(vpu_table_pre > vmax_pre)
    n_pre = n_pre_under + n_pre_over

    # Post-Market
    n_post_under = np.count_nonzero((vpu_table_post < vmin_post) & (vpu_table_post > 0.1))
    n_post_over = np.count_nonzero(vpu_table_post > vmax_post)
    n_post = n_post_under + n_post_over

    try:
        avoided_voltage_violation = ((n_pre - n_post) / n_pre) * 100
    except ZeroDivisionError:
        avoided_voltage_violation = 0

    # Results
    avoided_voltage_violation_res = dict()
    avoided_voltage_violation_res['AvoidVoltageViolations [%]'] = round(avoided_voltage_violation, _round_val)
    avoided_voltage_violation_res['AvoidVoltageViolations [u]'] = round(n_pre, _round_val) - round(n_post, _round_val)

    avoided_voltage_violation_res['n_pre_B [u]'] = round(n_pre, _round_val)
    avoided_voltage_violation_res['n_post_B [u]'] = round(n_post, _round_val)

    avoided_voltage_violation_res['n_pre_B_Under [u]'] = round(n_pre_under, _round_val)
    avoided_voltage_violation_res['n_post_B_Under [u]'] = round(n_post_under, _round_val)

    avoided_voltage_violation_res['n_pre_B_Over [u]'] = round(n_pre_over, _round_val)
    avoided_voltage_violation_res['n_post_B_Over [u]'] = round(n_post_over, _round_val)

    return avoided_voltage_violation_res


def avoided_voltage_violations(_in_dict):
    """
    Evaluate the Avoided Voltage Violations - Buses.

    :param _in_dict: Dictionary with all the information for evaluating the avoided voltage violations.
    """
    v_limits = _in_dict['vl_lims']
    scenarios = _in_dict['scenarios_selected']

    bus_vmpu_pre = _in_dict['bus_vmpu_pre']
    bus_vmpu_post = _in_dict['bus_vmpu_post']
    voltage_thresholds = _in_dict.get('voltage_thresholds', {})

    avoided_voltage_viol_res = dict()
    v_lims = {market: idx for idx, market in enumerate(v_limits)}

    for name_tab in scenarios:
        _, _vl_type, _ = _scenario_market_tags(name_tab, _in_dict)
        _data_pre = dict()
        _data_post = dict()

        _data_pre['vpu_table'] = bus_vmpu_pre[name_tab]
        _data_post['vpu_table'] = bus_vmpu_post[name_tab]
        policy = voltage_thresholds.get(_vl_type) or tolerance_policy.voltage_limits(_vl_type)
        thresholds = (
            ('standard', policy['standard_min_pu'], policy['standard_max_pu']),
            ('detection', policy['detection_min_pu'], policy['detection_max_pu']),
            ('optimization', policy['optimization_min_pu'], policy['optimization_max_pu']),
        )
        # Each avoided-voltage result uses
        # the same named band before and after market, with its limits displayed.
        row = {}
        standard_detail = None
        for threshold_name, lower, upper in thresholds:
            _data_pre['vbus_min'] = lower
            _data_pre['vbus_max'] = upper
            _data_post['vbus_min'] = lower
            _data_post['vbus_max'] = upper
            detail = eval_avoided_voltage_violation(_data_pre=_data_pre, _data_post=_data_post, _round_val=3)
            row['AvoidVoltage_' + threshold_name + ' [%]'] = detail['AvoidVoltageViolations [%]']
            row['ThresholdMin_' + threshold_name + ' [pu]'] = round(lower, 6)
            row['ThresholdMax_' + threshold_name + ' [pu]'] = round(upper, 6)
            row['AvoidVoltage_' + threshold_name + ' [u]'] = detail['AvoidVoltageViolations [u]']
            if threshold_name == 'standard':
                standard_detail = detail
        if standard_detail:
            # Retain the standard-band
            # diagnostic counts without duplicating the adjacent avoided KPIs.
            repeated = {'AvoidVoltageViolations [%]', 'AvoidVoltageViolations [u]'}
            row.update({key: value for key, value in standard_detail.items() if key not in repeated})
        avoided_voltage_viol_res[name_tab] = row

    avoided_voltage_viol_res = pd.DataFrame(avoided_voltage_viol_res).T
    return avoided_voltage_viol_res


def bid_quantities(_in_dict):
    offered_q = _in_dict['offered_quantity']
    cleared_q = _in_dict['cleared_quantity']
    scenarios = _in_dict['scenarios_selected']
    bid_q_p = dict()
    bid_q_q = dict()

    for name_tab in scenarios:
        bid_q_q[name_tab] = [cleared_q[name_tab]['R'], offered_q[name_tab]['R']]
        bid_q_p[name_tab] = [cleared_q[name_tab]['W'], offered_q[name_tab]['W']]

    final_bid_q_q = pd.DataFrame().from_dict(bid_q_q).T
    final_bid_q_q.columns = ['Cleared', 'Offered']
    final_bid_q_p = pd.DataFrame().from_dict(bid_q_p).T
    final_bid_q_p.columns = ['Cleared', 'Offered']
    return final_bid_q_p, final_bid_q_q


def load_fsp_result(_in_dict, _scenario, _prefix='model_results'):
    """
    Upload the flexibility market results from folders.

    :param _in_dict: Dictionary with all the paths for importing the flexibility market results.

    :param _scenario: String representing the specific scenario to read.

    :param _prefix: Prefix of the excel file with the flexibility market results.
    """
    path_market_out = _in_dict['path_MkOut']

    result_filename = _prefix + '_' + _scenario + '.xlsx'
    root2file = os.path.join(path_market_out, result_filename)
    if not os.path.exists(root2file):
        # Resolve the non-duplicated
        # market result filename stored in the already-selected output folder.
        candidates = sorted(Path(path_market_out).glob(_prefix + '_*.xlsx'))
        if len(candidates) != 1:
            raise FileNotFoundError(
                f'Could not uniquely resolve market result workbook for {_scenario}: {candidates}'
            )
        root2file = str(candidates[0])
        result_filename = candidates[0].name
    with pd.ExcelFile(root2file) as xl_file:
        list_sheets = xl_file.sheet_names
    dict_res = {_k: dict() for _k in _in_dict['fsp_file'].keys()}

    for _fsp_type in _in_dict['fsp_file'].keys():
        if _in_dict['flat_' + _fsp_type]:
            tabs = ['DW_' + _fsp_type + '_U', 'DW_' + _fsp_type + '_D', 'DW_' + _fsp_type, 'W_' + _fsp_type,
                    'DR_' + _fsp_type + '_U', 'DR_' + _fsp_type + '_D', 'DR_' + _fsp_type, 'R_' + _fsp_type]
            sheet2load = list()
            for j in tabs:
                sheet2load.extend(i for i in list_sheets if i.startswith(j))
            dict_res[_fsp_type] = io_file.import_data(_filename=result_filename,
                                                      _root=path_market_out, _sheetname=sheet2load, _index_col=0)

    # Load Flexibility not supplied,
    tabs2read = ['ABS_alpha_primo', 'ABS_beta', 'ObjValue']
    dict_others = io_file.import_data(_filename=result_filename, _root=path_market_out,
                                      _sheetname=tabs2read, _index_col=0)

    return dict_res, dict_others


def load_data_costs(_in_dict, _scenario, _prefix='_init'):
    """
    Upload the flexibility market costs from folders.

    :param _in_dict: Dictionary with all the paths for importing the flexibility market results.

    :param _scenario: String representing the specific scenario to read.

    :param _prefix: Prefix of the Excel file with the flexibility market results.
    """
    path_market_in = _in_dict['path_MkIn']

    dict_res = {_k: dict() for _k in _in_dict['fsp_file'].keys()}

    for _fsp_type in _in_dict['fsp_file'].keys():
        if _in_dict['flat_' + _fsp_type]:
            file2read = 'FSP' + _fsp_type + _prefix + _scenario + '.xlsx'
            root2file = os.path.join(path_market_in, file2read)
            if not os.path.exists(root2file):
                # Select the base FSP
                # cost-definition workbook, not the corrective ACOP workbook
                # produced by optional sequential AC validation.
                candidates = sorted(
                    path for path in Path(path_market_in).glob('FSP' + _fsp_type + _prefix + '*.xlsx')
                    if '_ACOP' not in path.stem
                )
                if len(candidates) != 1:
                    raise FileNotFoundError(
                        f'Could not uniquely resolve FSP input workbook for {_scenario}: {candidates}'
                    )
                file2read = candidates[0].name
                root2file = str(candidates[0])
            with pd.ExcelFile(root2file) as xl_file:
                list_sheets = xl_file.sheet_names
            tabs = ['FSPinfo',
                    'Winit', 'WLB_ULim', 'WLB_DLim', 'WUB_ULim', 'WUB_DLim', 'W_U_', 'W_D_',
                    'Rinit', 'RLB_ULim', 'RLB_DLim', 'RUB_ULim', 'RUB_DLim', 'R_U_', 'R_D_'
                    ]
            sheet2load = list()
            for j in tabs:
                sheet2load.extend(i for i in list_sheets if i.startswith(j))
            dict_res[_fsp_type] = io_file.import_data(_filename=file2read, _root=path_market_in, _sheetname=sheet2load,
                                                      _index_col=0)

    return dict_res


def eval_flexibility_costs(_in_dict, _dict_res, _dict_others, _dict_costs, _round_val=3):
    """
    Evaluate the costs for the request of flexibility.

    :param _in_dict: Dictionary with all the information pre-market for evaluating the avoided voltage violations.

    :param _dict_res: Dictionary with all the information about the flexibility provided by each resource.

    :param _dict_others: Dictionary with all the information about the general flexibility market parameter.

    :param _dict_costs: Dictionary with all the information about the costs for flexibility by each resource.

    :param _round_val: Value to which all value are rounded.
    """
    df_zeros_22 = pd.DataFrame(0, index=range(2), columns=range(2))
    fsp_costs = dict()
    ac_fm_w = dict()
    ac_fm_r = dict()
    for _fsp_type in _in_dict['fsp_file'].keys():
        if _in_dict['flat_' + _fsp_type]:
            ###############################
            # Upward Active Power
            _key2use_p_up = aux.get_list(_startswith_key='DW_' + _fsp_type + '_U', _comparing_list=_dict_res[_fsp_type])
            if len(_key2use_p_up) == 1:
                # Load [Type A] and Generator [Type B]
                fsp_costs['DW_' + _fsp_type + '_U_total'] = np.sum(
                    np.sum(_dict_res[_fsp_type][_key2use_p_up[0]], axis=0))
            elif len(_key2use_p_up) == 2:
                # Storage [Type C]
                fsp_costs['DW_' + _fsp_type + '_U_total'] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_up[1]], fill_value=0),
                    axis=0))

            # Downward Active Power
            _key2use_p_dwn = aux.get_list(_startswith_key='DW_' + _fsp_type + '_D', _comparing_list=_dict_res[_fsp_type])
            if len(_key2use_p_dwn) == 1:
                fsp_costs['DW_' + _fsp_type + '_D_total'] = np.sum(
                    np.sum(_dict_res[_fsp_type][_key2use_p_dwn[0]], axis=0))
            elif len(_key2use_p_dwn) == 2:
                # Storage [Type C]
                fsp_costs['DW_' + _fsp_type + '_D_total'] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_p_dwn[0]].add(_dict_res[_fsp_type][_key2use_p_dwn[1]], fill_value=0),
                    axis=0))

            if len(_key2use_p_up) == 1 and len(_key2use_p_dwn) == 1:
                ac_fm_w[_fsp_type] = _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_dwn[0]],
                                                                                fill_value=0)
            elif len(_key2use_p_up) == 2 and len(_key2use_p_dwn) == 1:
                ac_fm_w[_fsp_type] = _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_up[1]],
                                                                                fill_value=0).add(
                    _dict_res[_fsp_type][_key2use_p_dwn[0]], fill_value=0)
            elif len(_key2use_p_up) == 1 and len(_key2use_p_dwn) == 2:
                ac_fm_w[_fsp_type] = _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_dwn[0]],
                                                                                fill_value=0).add(
                    _dict_res[_fsp_type][_key2use_p_dwn[1]], fill_value=0)
            else:
                ac_fm_w[_fsp_type] = _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_up[1]],
                                                                                fill_value=0).add(
                    _dict_res[_fsp_type][_key2use_p_dwn[0]], fill_value=0).add(_dict_res[_fsp_type][_key2use_p_dwn[1]],
                                                                               fill_value=0)

            # Active Power
            if len(_key2use_p_up) == 1 and len(_key2use_p_dwn) == 1:
                fsp_costs['W_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_dwn[0]], fill_value=0),
                    axis=0))
            elif len(_key2use_p_up) == 2 and len(_key2use_p_dwn) == 1:
                fsp_costs['W_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_up[1]],
                                                               fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_p_dwn[0]], fill_value=0), axis=0))
            elif len(_key2use_p_up) == 1 and len(_key2use_p_dwn) == 2:
                fsp_costs['W_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_p_up[0]].add(_dict_res[_fsp_type][_key2use_p_dwn[0]],
                                                               fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_p_dwn[1]], fill_value=0), axis=0))
            else:
                fsp_costs['W_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_p_up[0]].add(
                        _dict_res[_fsp_type][_key2use_p_up[1]], fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_p_dwn[0]], fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_p_dwn[1]], fill_value=0),
                    axis=0))

            ###############################
            # Upward Reactive Power
            _key2use_q_up = aux.get_list(_startswith_key='DR_' + _fsp_type + '_U', _comparing_list=_dict_res[_fsp_type])
            if len(_key2use_q_up) == 1:
                # Load [Type A], Generator [Type B] and Storage [Type C]
                fsp_costs['DR_' + _fsp_type + '_U_total'] = np.sum(
                    np.sum(_dict_res[_fsp_type][_key2use_q_up[0]], axis=0))
            elif len(_key2use_q_up) == 2:
                # Future development for Storage (Reactive power upward and downward)
                fsp_costs['DR_' + _fsp_type + '_U_total'] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_up[1]], fill_value=0),
                    axis=0))

            # Downward Reactive Power
            _key2use_q_dwn = aux.get_list(_startswith_key='DR_' + _fsp_type + '_D', _comparing_list=_dict_res[_fsp_type])
            if len(_key2use_q_dwn) == 1:
                # Load [Type A], Generator [Type B] and Storage [Type C]
                fsp_costs['DR_' + _fsp_type + '_D_total'] = np.sum(
                    np.sum(_dict_res[_fsp_type][_key2use_q_dwn[0]], axis=0))
            elif len(_key2use_q_dwn) == 2:
                # Future development for Storage (Reactive power upward and downward)
                fsp_costs['DR_' + _fsp_type + '_D_total'] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_q_dwn[0]].add(_dict_res[_fsp_type][_key2use_q_dwn[1]], fill_value=0),
                    axis=0))

            if len(_key2use_q_up) == 1 and len(_key2use_q_dwn) == 1:
                ac_fm_r[_fsp_type] = _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_dwn[0]],
                                                                                fill_value=0)
            elif len(_key2use_q_up) == 2 and len(_key2use_q_dwn) == 1:
                ac_fm_r[_fsp_type] = _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_up[1]],
                                                                                fill_value=0).add(
                    _dict_res[_fsp_type][_key2use_q_dwn[0]], fill_value=0)
            elif len(_key2use_q_up) == 1 and len(_key2use_q_dwn) == 2:
                ac_fm_r[_fsp_type] = _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_dwn[0]],
                                                                                fill_value=0).add(
                    _dict_res[_fsp_type][_key2use_q_dwn[1]], fill_value=0)
            else:
                ac_fm_r[_fsp_type] = _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_up[1]],
                                                                                fill_value=0).add(
                    _dict_res[_fsp_type][_key2use_q_dwn[0]], fill_value=0).add(_dict_res[_fsp_type][_key2use_q_dwn[1]],
                                                                               fill_value=0)

            # Reactive Power
            if len(_key2use_q_up) == 1 and len(_key2use_q_dwn) == 1:
                # Load [Type A], Generator [Type B] and Storage [Type C]
                fsp_costs['R_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_dwn[0]], fill_value=0),
                    axis=0))
            elif len(_key2use_q_up) == 2 and len(_key2use_q_dwn) == 1:
                fsp_costs['R_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_up[1]],
                                                               fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_q_dwn[0]], fill_value=0), axis=0))
            elif len(_key2use_q_up) == 1 and len(_key2use_q_dwn) == 2:
                fsp_costs['R_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_q_up[0]].add(_dict_res[_fsp_type][_key2use_q_dwn[0]],
                                                               fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_q_dwn[1]], fill_value=0), axis=0))
            else:
                # Future development for Storage (Reactive power upward and downward)
                fsp_costs['R_' + _fsp_type] = np.sum(np.sum(
                    _dict_res[_fsp_type][_key2use_q_up[0]].add(
                        _dict_res[_fsp_type][_key2use_q_up[1]], fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_q_dwn[0]], fill_value=0).add(
                        _dict_res[_fsp_type][_key2use_q_dwn[1]], fill_value=0),
                    axis=0))

            ###############################
            # Active power Upward costs
            _key2use_p_up_cost = aux.get_list(_startswith_key='W_U_', _comparing_list=_dict_costs[_fsp_type])
            if len(_key2use_p_up_cost) == 1:
                res_dw_u = (_dict_res[_fsp_type][_key2use_p_up[0]] * _dict_costs[_fsp_type][
                    _key2use_p_up_cost[0]]).dropna(axis=1)
                fsp_costs['DW_' + _fsp_type + '_U_Cost'] = np.sum(np.sum(res_dw_u, axis=0))
            elif len(_key2use_p_up_cost) == 2:
                res_dw_u_1 = (_dict_res[_fsp_type][_key2use_p_up[0]] * _dict_costs[_fsp_type][
                    _key2use_p_up_cost[0]]).dropna(axis=1)
                res_dw_u_2 = (_dict_res[_fsp_type][_key2use_p_up[1]] * _dict_costs[_fsp_type][
                    _key2use_p_up_cost[1]]).dropna(axis=1)
                fsp_costs['DW_' + _fsp_type + '_U_Cost'] = np.sum(
                    np.sum(res_dw_u_1.add(res_dw_u_2, fill_value=0), axis=0))

            # Active power Downward costs
            _key2use_p_dwn_cost = aux.get_list(_startswith_key='W_D_', _comparing_list=_dict_costs[_fsp_type])
            if len(_key2use_p_dwn_cost) == 1:
                res_dw_d = (_dict_res[_fsp_type][_key2use_p_dwn[0]] * _dict_costs[_fsp_type][
                    _key2use_p_dwn_cost[0]]).dropna(axis=1)
                fsp_costs['DW_' + _fsp_type + '_D_Cost'] = np.sum(np.sum(res_dw_d, axis=0))
            elif len(_key2use_p_dwn_cost) == 2:
                res_dw_d_1 = (_dict_res[_fsp_type][_key2use_p_dwn[0]] * _dict_costs[_fsp_type][
                    _key2use_p_dwn_cost[0]]).dropna(axis=1)
                res_dw_d_2 = (_dict_res[_fsp_type][_key2use_p_dwn[1]] * _dict_costs[_fsp_type][
                    _key2use_p_dwn_cost[1]]).dropna(axis=1)
                fsp_costs['DW_' + _fsp_type + '_D_Cost'] = np.sum(
                    np.sum(res_dw_d_1.add(res_dw_d_2, fill_value=0), axis=0))

            # Reactive power Upward costs
            _key2use_q_up_cost = aux.get_list(_startswith_key='R_U_', _comparing_list=_dict_costs[_fsp_type])
            if len(_key2use_q_up_cost) == 1:
                res_dr_u = (_dict_res[_fsp_type][_key2use_q_up[0]] * _dict_costs[_fsp_type][
                    _key2use_q_up_cost[0]]).dropna(axis=1)
                fsp_costs['DR_' + _fsp_type + '_U_Cost'] = np.sum(np.sum(res_dr_u, axis=0))
            elif len(_key2use_q_up_cost) == 2:
                res_dr_u_1 = (_dict_res[_fsp_type][_key2use_q_up[0]] * _dict_costs[_fsp_type][
                    _key2use_q_up_cost[0]]).dropna(axis=1)
                res_dr_u_2 = (_dict_res[_fsp_type][_key2use_q_up[1]] * _dict_costs[_fsp_type][
                    _key2use_q_up_cost[1]]).dropna(axis=1)
                fsp_costs['DR_' + _fsp_type + '_U_Cost'] = np.sum(
                    np.sum(res_dr_u_1.add(res_dr_u_2, fill_value=0), axis=0))

            # Reactive power Downward costs
            _key2use_q_dwn_cost = aux.get_list(_startswith_key='R_D_', _comparing_list=_dict_costs[_fsp_type])
            if len(_key2use_q_dwn_cost) == 1:
                res_dr_d = (_dict_res[_fsp_type][_key2use_q_dwn[0]] * _dict_costs[_fsp_type][
                    _key2use_q_dwn_cost[0]]).dropna(axis=1)
                fsp_costs['DR_' + _fsp_type + '_D_Cost'] = np.sum(np.sum(res_dr_d, axis=0))
            elif len(_key2use_q_dwn_cost) == 2:
                res_dr_d_1 = (_dict_res[_fsp_type][_key2use_q_dwn[0]] * _dict_costs[_fsp_type][
                    _key2use_q_dwn_cost[0]]).dropna(axis=1)
                res_dr_d_2 = (_dict_res[_fsp_type][_key2use_q_dwn[1]] * _dict_costs[_fsp_type][
                    _key2use_q_dwn_cost[1]]).dropna(axis=1)
                fsp_costs['DR_' + _fsp_type + '_D_Cost'] = np.sum(
                    np.sum(res_dr_d_1.add(res_dr_d_2, fill_value=0), axis=0))

            ###############################
            # Active Power
            if len(_key2use_p_up_cost) == 1:
                fsp_costs['C_FM_' + _fsp_type + '_W_Total'] = np.sum(
                    np.sum(res_dw_u.add(res_dw_d, fill_value=0), axis=0))
            elif len(_key2use_p_up_cost) == 2:
                fsp_costs['C_FM_' + _fsp_type + '_W_Total'] = np.sum(np.sum(
                    res_dw_u_1.add(res_dw_u_2, fill_value=0).add(res_dw_d_1, fill_value=0).add(res_dw_d_2,
                                                                                               fill_value=0), axis=0))

            # Reactive Power
            if len(_key2use_q_up_cost) == 1:
                fsp_costs['C_FM_' + _fsp_type + '_R_Total'] = np.sum(
                    np.sum(res_dr_u.add(res_dr_d, fill_value=0), axis=0))
            elif len(_key2use_q_up_cost) == 2:
                fsp_costs['C_FM_' + _fsp_type + '_R_Total'] = np.sum(np.sum(
                    res_dr_u_1.add(res_dr_u_2, fill_value=0).add(res_dr_d_1, fill_value=0).add(res_dr_d_2,
                                                                                               fill_value=0), axis=0))

        else:
            # Power
            fsp_costs['DW_' + _fsp_type + '_U_total'] = 0
            fsp_costs['DW_' + _fsp_type + '_D_total'] = 0
            fsp_costs['W_' + _fsp_type] = 0

            fsp_costs['DR_' + _fsp_type + '_U_total'] = 0
            fsp_costs['DR_' + _fsp_type + '_D_total'] = 0
            fsp_costs['R_' + _fsp_type] = 0

            # Costs
            fsp_costs['DW_' + _fsp_type + '_U_Cost'] = 0
            fsp_costs['DW_' + _fsp_type + '_D_Cost'] = 0
            fsp_costs['DR_' + _fsp_type + '_U_Cost'] = 0
            fsp_costs['DR_' + _fsp_type + '_D_Cost'] = 0

            fsp_costs['C_FM_' + _fsp_type + '_W_Total'] = 0
            fsp_costs['C_FM_' + _fsp_type + '_R_Total'] = 0

            ac_fm_w[_fsp_type] = df_zeros_22
            ac_fm_r[_fsp_type] = df_zeros_22

        ###############################
        # Average Active Power Cost
        fsp_costs['DW_' + _fsp_type + '_Net_Cost_Avg'] = fsp_costs['C_FM_' + _fsp_type + '_W_Total'] / fsp_costs[
            'W_' + _fsp_type] if round(fsp_costs['W_' + _fsp_type], _round_val) != 0 else 0
        fsp_costs['DW_' + _fsp_type + '_U_Cost_Avg'] = fsp_costs['DW_' + _fsp_type + '_U_Cost'] / fsp_costs[
            'DW_' + _fsp_type + '_U_total'] if round(fsp_costs['DR_' + _fsp_type + '_U_total'], _round_val) != 0 else 0
        fsp_costs['DW_' + _fsp_type + '_D_Cost_Avg'] = fsp_costs['DW_' + _fsp_type + '_D_Cost'] / fsp_costs[
            'DW_' + _fsp_type + '_D_total'] if round(fsp_costs['DR_' + _fsp_type + '_D_total'], _round_val) != 0 else 0

        # Average Reactive Power Cost
        fsp_costs['DR_' + _fsp_type + '_Net_Cost_Avg'] = fsp_costs['C_FM_' + _fsp_type + '_R_Total'] / fsp_costs[
            'R_' + _fsp_type] if round(fsp_costs['R_' + _fsp_type], _round_val) != 0 else 0
        fsp_costs['DR_' + _fsp_type + '_U_Cost_Avg'] = fsp_costs['DR_' + _fsp_type + '_U_Cost'] / fsp_costs[
            'DR_' + _fsp_type + '_U_total'] if round(fsp_costs['DR_' + _fsp_type + '_U_total'], _round_val) != 0 else 0
        fsp_costs['DR_' + _fsp_type + '_D_Cost_Avg'] = fsp_costs['DR_' + _fsp_type + '_D_Cost'] / fsp_costs[
            'DR_' + _fsp_type + '_D_total'] if round(fsp_costs['DR_' + _fsp_type + '_D_total'], _round_val) != 0 else 0

    # Active Power of all resources
    w_total = sum([fsp_costs['W_' + _fsp_type] for _fsp_type in _in_dict['fsp_file'].keys()])
    # Reactive Power of all resources
    r_total = sum([fsp_costs['R_' + _fsp_type] for _fsp_type in _in_dict['fsp_file'].keys()])

    # Active Power total cost for flexibility market
    c_fm_w = sum([fsp_costs['C_FM_' + _fsp_type + '_W_Total'] for _fsp_type in _in_dict['fsp_file'].keys()])
    # Reactive Power total cost for flexibility market
    c_fm_r = sum([fsp_costs['C_FM_' + _fsp_type + '_R_Total'] for _fsp_type in _in_dict['fsp_file'].keys()])

    # Flexibility Activated
    res_actived_flex_w = pd.DataFrame()
    res_actived_flex_r = pd.DataFrame()
    for _fsp_type in _in_dict['fsp_file'].keys():
        res_actived_flex_w = res_actived_flex_w.add(ac_fm_w[_fsp_type], fill_value=0, )
        res_actived_flex_r = res_actived_flex_r.add(ac_fm_r[_fsp_type], fill_value=0)
    ac_fm_w_total = np.sum(np.sum(res_actived_flex_w, axis=0))
    ac_fm_r_total = np.sum(np.sum(res_actived_flex_r, axis=0))

    # Cost alpha Total
    alpha = np.sum(np.sum(np.abs(_dict_others['ABS_alpha_primo'])), axis=0)
    cost_alpha_total = alpha * _in_dict['cost_alpha']

    # Cost beta Total
    beta = np.sum(np.sum(_dict_others['ABS_beta']), axis=0)
    cost_beta_total = beta * _in_dict['cost_beta']

    # Totals
    fsp_costs['ActivePower_Total [MW]'] = round(w_total, _round_val)
    fsp_costs['ReactivePower_Total [MVAR]'] = round(r_total, _round_val)
    fsp_costs['C_FM_ActivePower [Eur]'] = round(c_fm_w, _round_val)
    fsp_costs['C_FM_ActivePower_Avg [Eur/MW]'] = round(c_fm_w / ac_fm_w_total, _round_val) if ac_fm_w_total.round(_round_val) != 0 else 0
    fsp_costs['C_FM_ReactivePower [Eur]'] = round(c_fm_r, _round_val)
    fsp_costs['C_FM_ReactivePower_Avg [Eur/MVAR]'] = round(c_fm_r / ac_fm_r_total, _round_val) if ac_fm_r_total.round(_round_val) != 0 else 0

    # Flexibility no supplied
    fsp_costs['Alpha [MW]'] = float(alpha)
    fsp_costs['Cost_Alpha_Total'] = cost_alpha_total
    fsp_costs['Cost_Alpha_Avg'] = cost_alpha_total / alpha if round(alpha, _round_val) != 0 else 0

    fsp_costs['Beta [MVA]'] = float(beta)
    fsp_costs['Cost_Beta_Total'] = cost_beta_total
    fsp_costs['Cost_Beta_Avg'] = cost_beta_total / beta if round(beta, _round_val) != 0 else 0

    fsp_costs['ObjValue'] = _dict_others['ObjValue'].ObjValue.round(_round_val).to_list()[0]

    return fsp_costs


def cost_flexibility(_in_dict):
    """
    Evaluate the cost af all the flexibility service activations.

    :param _in_dict: Dictionary with all the information for evaluating the avoided voltage violations.
    """
    scenarios = _in_dict['scenarios_selected']
    kpi_path = _in_dict['paths']

    flex_activated = dict()
    dict_fsp = dict()
    dict_costs = dict()
    for name_tab in scenarios:
        _prod, _vl, _fsp = _scenario_market_tags(name_tab, _in_dict)
        _in_dict['path_MkOut'] = kpi_path['mrk_outputs']['res_market'][_prod][_vl][_fsp]
        _in_dict['path_MkIn'] = kpi_path['mrk_inputs'][_prod][_vl][_fsp]

        dict_fsp[name_tab], dict_others = load_fsp_result(_in_dict=_in_dict, _scenario=name_tab)
        dict_costs[name_tab] = load_data_costs(_in_dict=_in_dict, _scenario=name_tab)

        flex_activated[name_tab] = eval_flexibility_costs(_in_dict=_in_dict, _dict_res=dict_fsp[name_tab],
                                                          _dict_others=dict_others, _dict_costs=dict_costs[name_tab])
    return flex_activated, dict_fsp, dict_costs


def build_final_table(_in_dict):
    """
    Build final results table.
    The objective value and the total cost are different since the slack variables of the voltage (alpha) is written
    differently in the market. In the market, it is written as:
        -> (ABS_alpha_primo / sens_matrix_vc['all']) * alpha_cost        (if net_in_market parameters is not active)
        -> ABS_alpha_primo * alpha_cost * 1000                           (if net_in_market parameters is active)

    :param _in_dict: Dictionary with all the information for building the final table in terms of costs and volumes.
    """

    final_res_table = {
        'ObjValue [Eur]': pd.DataFrame(_in_dict).T['ObjValue'],
        'CostBeta_Total [Eur]': pd.DataFrame(_in_dict).T['Cost_Beta_Total'],
        'CostAlpha_Total [Eur]': pd.DataFrame(_in_dict).T['Cost_Alpha_Total'],
        'TotalActivePower [MW]': pd.DataFrame(_in_dict).T['ActivePower_Total [MW]'],
        'ActivePowerCost [Eur]': pd.DataFrame(_in_dict).T['C_FM_ActivePower [Eur]'],
        'TotalReactivePower [MVAR]': pd.DataFrame(_in_dict).T['ReactivePower_Total [MVAR]'],
        'ReactivePowerCost [Eur]': pd.DataFrame(_in_dict).T['C_FM_ReactivePower [Eur]'],
        'TotalCost [Eur]': pd.DataFrame(_in_dict).T['Cost_Beta_Total'] + pd.DataFrame(_in_dict).T['Cost_Alpha_Total']
                           + pd.DataFrame(_in_dict).T['C_FM_ActivePower [Eur]'] + pd.DataFrame(_in_dict).T['C_FM_ReactivePower [Eur]']
    }
    return pd.DataFrame(final_res_table)


def eval_statistics_volume_flex(_in_dict, _dict_res, _dict_costs, _scenario, _round_val=6):
    """
    Evaluate the statistics behind the volume of flexibility offered.

    :param _in_dict: Dictionary with all the information pre-market for evaluating the avoided voltage violations.

    :param _dict_res: Dictionary with all the information about the flexibility provided by each resource.

    :param _dict_costs: Dictionary with all the information about the costs for flexibility by each resource.

    :param _scenario: String representing the specific scenario to read.

    :param _round_val: Value to which all value are rounded.
    """
    flex_res = dict()
    for _fsp_type in _in_dict['fsp_file'].keys():
        if _in_dict['flat_' + _fsp_type]:
            w_init = _dict_costs[_fsp_type]['Winit_' + _fsp_type]
            r_init = _dict_costs[_fsp_type]['Rinit_' + _fsp_type]

            w_ub_ulim = _dict_costs[_fsp_type].get('WUB_ULim_' + _fsp_type, pd.DataFrame())
            w_ub_dlim = _dict_costs[_fsp_type].get('WUB_DLim_' + _fsp_type, pd.DataFrame())
            w_lb_ulim = _dict_costs[_fsp_type].get('WLB_ULim_' + _fsp_type, pd.DataFrame())
            w_lb_dlim = _dict_costs[_fsp_type].get('WLB_DLim_' + _fsp_type, pd.DataFrame())
            r_ub_ulim = _dict_costs[_fsp_type].get('RUB_ULim_' + _fsp_type, pd.DataFrame())
            r_ub_dlim = _dict_costs[_fsp_type].get('RUB_DLim_' + _fsp_type, pd.DataFrame())
            r_lb_ulim = _dict_costs[_fsp_type].get('RLB_ULim_' + _fsp_type, pd.DataFrame())
            r_lb_dlim = _dict_costs[_fsp_type].get('RLB_DLim_' + _fsp_type, pd.DataFrame())

            dw_upward = _dict_res[_fsp_type]['DW_' + _fsp_type + '_U']
            dw_dwnward = _dict_res[_fsp_type]['DW_' + _fsp_type + '_D']

            dr_upward = _dict_res[_fsp_type]['DR_' + _fsp_type + '_U']
            dr_dwnward = _dict_res[_fsp_type]['DR_' + _fsp_type + '_U']

            # Active Power
            stat_w_init = w_init.apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)

            # fixme: to check for future developments.
            #  As of now, it consider that the reactive power is only upward for all resources.
            if w_lb_ulim.empty is False and w_ub_ulim.empty is True:
                # Load
                stat_w_offered_upward = (w_init - w_lb_ulim).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
                stat_r_offered_upward = (r_init - r_ub_ulim).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
            elif w_lb_ulim.empty is True and w_ub_ulim.empty is False:
                # Generator and Storage
                stat_w_offered_upward = (w_ub_ulim - w_init).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
                stat_r_offered_upward = (r_ub_ulim - r_init).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)

            if w_ub_dlim.empty is False and w_lb_dlim.empty is True:
                # Load
                stat_w_offered_dwnward = (w_ub_dlim - w_init).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
                stat_r_offered_dwnward = (r_ub_dlim - r_init).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
            elif w_ub_dlim.empty is True and w_lb_dlim.empty is False:
                # Generator and Storage
                stat_w_offered_dwnward = (w_init - w_lb_dlim).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
                stat_r_offered_dwnward = (r_init - r_ub_dlim).apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)

            stat_w_cleared_upward = dw_upward.apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
            stat_w_cleared_dwnward = dw_dwnward.apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)

            # Reactive Power
            stat_r_init = r_init.apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)

            stat_r_cleared_upward = dr_upward.apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)
            stat_r_cleared_dwnward = dr_dwnward.apply(['mean', 'std', 'max', 'min', 'sum'], axis=1)

            flex_res['ST_Winit_' + _fsp_type] = round(stat_w_init, _round_val)
            flex_res['ST_WOffered_' + _fsp_type + '_U'] = round(stat_w_offered_upward, _round_val)
            flex_res['ST_WOffered_' + _fsp_type + '_D'] = round(stat_w_offered_dwnward, _round_val)
            flex_res['ST_WCleared_' + _fsp_type + '_U'] = round(stat_w_cleared_upward, _round_val)
            flex_res['ST_WCleared_' + _fsp_type + '_D'] = round(stat_w_cleared_dwnward, _round_val)

            flex_res['ST_Rinit_' + _fsp_type] = round(stat_r_init, _round_val)
            flex_res['ST_ROffered_' + _fsp_type + '_U'] = round(stat_r_offered_upward, _round_val)
            flex_res['ST_ROffered_' + _fsp_type + '_D'] = round(stat_r_offered_dwnward, _round_val)
            flex_res['ST_RCleared_' + _fsp_type + '_U'] = round(stat_r_cleared_upward, _round_val)
            flex_res['ST_RCleared_' + _fsp_type + '_D'] = round(stat_r_cleared_dwnward, _round_val)
    return flex_res


def volume_flex_offered(_in_dict, _dict_res, _dict_costs):
    """
    Evaluate the volume of flexibility offered.

    :param _in_dict: Dictionary with all the information for evaluating the volume of flexibility offered.

    :param _dict_res: Dictionary with all the information about the flexibility provided by each resource.

    :param _dict_costs: Dictionary with all the information about the costs for flexibility by each resource.
    """
    scenarios = _in_dict['scenarios_selected']

    flex_q = dict()
    for name_tab in scenarios:
        flex_q[name_tab] = eval_statistics_volume_flex(_in_dict=_in_dict, _dict_res=_dict_res[name_tab],
                                                       _dict_costs=_dict_costs[name_tab], _scenario=name_tab)

    return flex_q


def increase_hc_plots(_df_res, _scenarios, _title, _y_lim):
    """
    Prepare the plots for the Increase Hosting Capacity.
    The plots are subdivided per Voltage Violation Scenarios.

    :param _df_res: Dataframe of the Increase Hosting Capacity to be plotted.

    :param _scenarios: Scenario to be analyzed.

    :param _title: Title of the figure.

    :param _y_lim: Limits of the y-axis.
    """
    fig_size = (10, 8)
    filtered_df_res = _df_res.loc[_scenarios]
    titles = ['KPI: Increased Hosting Capacity', _title]
    name_net_fig = 'Cases'
    labels = [name_net_fig, filtered_df_res.columns[0]]
    fig = plt_kpi.bar_increase_hc(filtered_df_res, fig_size, titles, labels, _y_lim)
    return fig


def _avoidance_plot_tables(_frame, _unit_columns, _percent_columns,
                           _legacy_unit_columns, _legacy_percent_column):
    """Return threshold-aware plot tables, with support for legacy KPI files."""
    # KPI plotting follows the current
    # three-threshold schema but can still open results generated by older runs.
    unit_columns = [column for column in _unit_columns if column in _frame.columns]
    percent_columns = [column for column in _percent_columns if column in _frame.columns]

    if not unit_columns:
        unit_columns = [column for column in _legacy_unit_columns if column in _frame.columns]
    if not percent_columns and _legacy_percent_column in _frame.columns:
        percent_columns = [_legacy_percent_column]

    missing_groups = []
    if not unit_columns:
        missing_groups.append('avoided-count columns')
    if not percent_columns:
        missing_groups.append('avoided-percentage columns')
    if missing_groups:
        raise KeyError(
            'Cannot prepare avoided-violation plot: missing ' + ', '.join(missing_groups)
            + '. Available columns: ' + ', '.join(map(str, _frame.columns))
        )

    rename_map = {
        'AvoidCongestion_standard [u]': 'Standard',
        'AvoidCongestion_detection [u]': 'Detection',
        'AvoidCongestion_optimization [u]': 'Optimization',
        'AvoidCongestion_tol_i [u]': 'Detection (tol_i)',
        'AvoidCongestion_tol_i_opt [u]': 'Optimization (tol_i + tol_i_opt)',
        'AvoidCongestion_standard [%]': 'Standard',
        'AvoidCongestion_detection [%]': 'Detection',
        'AvoidCongestion_optimization [%]': 'Optimization',
        'AvoidCongestion_tol_i [%]': 'Detection (tol_i)',
        'AvoidCongestion_tol_i_opt [%]': 'Optimization (tol_i + tol_i_opt)',
        'AvoidVoltage_standard [u]': 'Standard',
        'AvoidVoltage_detection [u]': 'Detection',
        'AvoidVoltage_optimization [u]': 'Optimization',
        'AvoidVoltage_tol_v [u]': 'Detection (tol_v)',
        'AvoidVoltage_tol_v_opt [u]': 'Optimization (tol_v + tol_v_opt)',
        'AvoidVoltage_standard [%]': 'Standard',
        'AvoidVoltage_detection [%]': 'Detection',
        'AvoidVoltage_optimization [%]': 'Optimization',
        'AvoidVoltage_tol_v [%]': 'Detection (tol_v)',
        'AvoidVoltage_tol_v_opt [%]': 'Optimization (tol_v + tol_v_opt)',
        'AvoidCong_L[u]': 'Lines',
        'AvoidCong_T[u]': 'Trafo_2windings',
        'AvoidCong_T3w[u]': 'Trafo_3windings',
        'AvoidCongestions [%]': 'Overall',
        'AvoidVoltageViolations [u]': 'Overall',
        'AvoidVoltageViolations [%]': 'Overall',
    }
    count_table = _frame.loc[:, unit_columns].copy().rename(columns=rename_map)
    percentage_table = _frame.loc[:, percent_columns].copy().rename(columns=rename_map)
    return count_table, percentage_table


def avoided_cong_plots(_df_res, _scenarios, _title, _y_lim):
    """
    Prepare the plots for the avoided congestions.

    :param _df_res: Dataframe of the Increase Hosting Capacity to be plotted.

    :param _scenarios: Scenario to be analyzed.

    :param _title: Title of the figure.

    :param _y_lim: Limits of the y-axis.
    """
    figsize = (10, 8)

    filtered_df_res = _df_res.loc[_scenarios]

    name_net_fig = 'Cases'
    titles = ['KPI: Avoided Congestions', _title]
    labels = [name_net_fig,
              'Avoided congestion count [asset x hour]',
              'Avoided congestion [%]',
              'Overall [%]']
    df1, df2 = _avoidance_plot_tables(
        filtered_df_res,
        _unit_columns=[
            'AvoidCongestion_standard [u]',
            'AvoidCongestion_detection [u]',
            'AvoidCongestion_optimization [u]',
        ],
        _percent_columns=[
            'AvoidCongestion_standard [%]',
            'AvoidCongestion_detection [%]',
            'AvoidCongestion_optimization [%]',
        ],
        _legacy_unit_columns=['AvoidCong_L[u]', 'AvoidCong_T[u]', 'AvoidCong_T3w[u]'],
        _legacy_percent_column='AvoidCongestions [%]',
    )

    fig = plt_kpi.bar_avoid_violations(df1, df2, figsize, titles, labels, _y_lim)
    return fig


def bid_quantities_plots(_df_res, _scenarios, _title, _y_lim, _product='P'):
    """
    Prepare the plots for the bid quantities plot.

    :param _df_res: Dataframe of the Increase Hosting Capacity to be plotted.

    :param _scenarios: Scenario to be analyzed.

    :param _title: Title of the figure.

    :param _y_lim: Limits of the y-axis.

    :param _product: 'P' for the active power product (default) or 'Q' for the reactive power product. It sets the
        label of the volume axis.
    """
    axis_labels = {'P': 'Volume of Active Power Product [MWh]', 'Q': 'Volume of Reactive Power Product [MVArh]'}
    if _product not in axis_labels:
        raise ValueError("_product must be 'P' or 'Q', got %r." % (_product,))
    figsize = (10, 8)

    filtered_df_res = _df_res.loc[_scenarios]

    name_net_fig = 'Cases'
    titles = ['KPI: Bid Quantities', _title]
    labels = [name_net_fig, axis_labels[_product]]

    fig = plt_kpi.bar_bid_quantities(filtered_df_res, figsize, titles, labels, _y_lim)
    return fig


def avoided_cong_3dplots(_df_res, _scenarios, _title):
    """
    Prepare the 3D plots for the avoided congestions.

    :param _df_res: Dataframe of the Increase Hosting Capacity to be plotted.

    :param _scenarios: Scenario to be analyzed.

    :param _title: Title of the figure.
    """
    figsize = (10, 8)
    titles = ['KPI: Avoided Congestions [%]', _title]

    filtered_df_res = _df_res.loc[_scenarios]

    percent_column = ('AvoidCongestion_standard [%]'
                      if 'AvoidCongestion_standard [%]' in filtered_df_res.columns
                      else 'AvoidCongestions [%]')
    z_values = filtered_df_res[percent_column].values.tolist()
    product_tag = np.unique([i.split('_')[2] for i in _scenarios])
    fsp_tag = list()

    # Build dictionary for plot (Comparison of 3 market product: ['P', 'Q', 'PQ'])
    mrk_products = ['P', 'Q', 'PQ']
    x = {_prod: list() for _prod in mrk_products}
    y = {_prod: list() for _prod in mrk_products}
    dz = {_prod: list() for _prod in mrk_products}
    _1st_mrk_product = 0
    value_x = 0
    value_y = 0
    idx_z = 0
    label_pos = []
    for _tag in _scenarios:
        fsp_tag.append('_'.join(_tag.split('_')[3:]))
        if _1st_mrk_product != _tag.split('_')[2]:
            _1st_mrk_product = _tag.split('_')[2]
            value_x += 2
            value_y = 1

        _mrk_product = _tag.split('_')[2]
        x[_mrk_product].append(value_x)
        y[_mrk_product].append(value_y)
        dz[_mrk_product].append(z_values[idx_z])
        value_y += 2
        idx_z += 1
        label_pos.append(value_x + 0.5)

    label_pos = np.unique(label_pos)
    fsp_tag = np.unique(fsp_tag).tolist()
    fig = plt_kpi.bar3d_avoid_violations(_x=x, _y=y, _dz=dz, _figsize=figsize, _mrk_products=product_tag, _fsps=fsp_tag,
                                         _label_pos=label_pos, _zlabel='AvoidCongestions [%]', _titles=titles)
    return fig


def avoided_cong_element_3dplots(_df_res, _scenarios, _title):
    """
    Prepare the 3D plots for the number of avoided congestions.

    :param _df_res: Dataframe of the Increase Hosting Capacity to be plotted.

    :param _scenarios: Scenario to be analyzed.

    :param _title: Title of the figure.
    """
    figsize = (10, 8)
    titles = ['KPI: Avoided Congestions', _title]

    filtered_df_res = _df_res.loc[_scenarios]

    z_values = filtered_df_res[['AvoidCong_L[u]', 'AvoidCong_T[u]', 'AvoidCong_T3w[u]']].values
    product_tag = np.unique([i.split('_')[2] for i in _scenarios])
    fsp_tag = list()

    # Build dictionary for plot
    # (Comparison of 3 market product: ['P', 'Q', 'PQ'] and comparison of 3 elements: ['Line', 'Trafo', 'Trafo3w'])
    mrk_products = ['P', 'Q', 'PQ']
    keys_element = ['Line', 'Trafo', 'Trafo3w']
    x = {_prod: {_elem: list() for _elem in keys_element} for _prod in mrk_products}
    y = {_prod: {_elem: list() for _elem in keys_element} for _prod in mrk_products}
    dz = {_prod: {_elem: list() for _elem in keys_element} for _prod in mrk_products}
    _1st_mrk_product = 0
    value_x = 0
    value_y = 1
    idx_z = 0
    label_pos = []
    for _tag in _scenarios:
        fsp_tag.append('_'.join(_tag.split('_')[3:]))
        if _1st_mrk_product != _tag.split('_')[2]:
            _1st_mrk_product = _tag.split('_')[2]
            value_x += 5
            value_y = 1

        _mrk_product = _tag.split('_')[2]

        _value_elem = 0
        for _elem in keys_element:
            x[_mrk_product][_elem].append(value_x + _value_elem)
            y[_mrk_product][_elem].append(value_y)
            dz[_mrk_product][_elem].append(z_values[idx_z, _value_elem])
            _value_elem += 1

        value_y += 2
        idx_z += 1
        label_pos.append(value_x + 1.5)

    label_pos = np.unique(label_pos)
    fsp_tag = np.unique(fsp_tag).tolist()
    fig = plt_kpi.bar3d_avoid_violations_element(_x=x, _y=y, _dz=dz, _figsize=figsize, _mrk_products=product_tag,
                                                 _key_elem=keys_element, _fsps=fsp_tag, _label_pos=label_pos,
                                                 _zlabel='Number of restriction avoided [element x hour]', _titles=titles)
    return fig


def avoided_voltage_viol_plots(_df_res, _scenarios, _title, _y_lim):
    """
    Prepare Avoided Voltage Violations plot.

    :param _df_res: Dataframe of the Increase Hosting Capacity to be plotted.

    :param _scenarios: Scenario to be analyzed.

    :param _title: Title of the figure.

    :param _y_lim: Limits of the y-axis.
    """
    figsize = (10, 8)

    filtered_df_res = _df_res.loc[_scenarios]

    name_net_fig = 'Cases'
    titles = ['KPI: Avoided Voltage Violations', _title]
    labels = [name_net_fig, 'Avoided voltage-violation count [bus x hour]',
              'Avoided voltage violations [%]',
              'Overall [%]']
    df1, df2 = _avoidance_plot_tables(
        filtered_df_res,
        _unit_columns=[
            'AvoidVoltage_standard [u]',
            'AvoidVoltage_detection [u]',
            'AvoidVoltage_optimization [u]',
        ],
        _percent_columns=[
            'AvoidVoltage_standard [%]',
            'AvoidVoltage_detection [%]',
            'AvoidVoltage_optimization [%]',
        ],
        _legacy_unit_columns=['AvoidVoltageViolations [u]'],
        _legacy_percent_column='AvoidVoltageViolations [%]',
    )

    fig = plt_kpi.bar_avoid_violations(df1, df2, figsize, titles, labels, _y_lim)

    return fig


def plot_kpi(_in_dict, _kpi2plot, _path_kpi_res, _simulation_tag, _draw_plots=True, _draw_net=False):
    """
    Prepare the data to be plotted.

    :param _in_dict: Dictionary with all the information for plotting the kpi.

    :param _kpi2plot: Dictionary with the kpi to be plotted.

    :param _path_kpi_res: Root to the folder in which the kpi will be saved.

    :param _simulation_tag: String that represent the simulation tag, composed by the name od the network, the market
     model and the storage tag.

    :param _draw_plots: Boolean value (True/False) plot graphs.

    :param _draw_net: Boolean value (True/False) plot network and save.
    """
    scenarios = _in_dict['scenarios_selected']
    dpi_img = _in_dict['dpi_img']
    products_list = _in_dict['products_list']
    voltage_list = _in_dict['voltage_list']

    # "interactive mode": Plotting no longer blocks: matplotlib.pyplot.ion()
    # https://stackoverflow.com/questions/64064016/dont-stop-at-plt-show-in-vs-code

    if _draw_plots:
        ihc_res = _kpi2plot['ihc_res']
        pihc_res = _kpi2plot['pihc_res']
        avoided_cong_res = _kpi2plot['avoided_cong_res']
        avoided_voltage_viol_res = _kpi2plot['avoided_voltage_viol_res']
        w_bid_res = _kpi2plot['w_bid_q']
        r_bid_res = _kpi2plot['r_bid_q']

        max_value = ihc_res[list(ihc_res.keys())[0]].max()
        ylim = [-0.1, max_value + 0.5]
        fig = increase_hc_plots(_df_res=ihc_res, _scenarios=scenarios, _title=_simulation_tag, _y_lim=ylim)
        fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_IHC[MVA]_Results.png'), format='png', dpi=dpi_img)
        print(fig)
        plt.ion()
        plt.close()

        ylim = [-20, 140]
        fig = increase_hc_plots(_df_res=pihc_res, _scenarios=scenarios, _title=_simulation_tag, _y_lim=ylim)
        fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_IHC[%]_Results.png'), format='png', dpi=dpi_img)
        print(fig)
        plt.ion()
        plt.close()

        # Avoided restrictions: Congestions in lines, trafos and Voltage Violations in Buses plots
        # Automatic limits retain negative
        # avoided values (post-market deterioration) and values above 100%.
        ylim = [[], []]
        fig = avoided_cong_plots(_df_res=avoided_cong_res, _scenarios=scenarios, _title=_simulation_tag, _y_lim=ylim)
        fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_AvCongest.png'), format='png', dpi=dpi_img)
        print(fig)
        plt.ion()
        plt.close()

        # Bid Quantities Plot: Offered and Cleared in the Market Active Power
        ylim = [[], [0, 100]]
        fig = bid_quantities_plots(_df_res=w_bid_res, _scenarios=scenarios, _title=_simulation_tag, _y_lim=ylim, _product='P')
        fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_bidQuantities_P.png'), format='png', dpi=dpi_img)
        print(fig)
        plt.ion()
        plt.close()

        # Bid Quantities Plot: Offered and Cleared in the Market Reactive Power
        ylim = [[], [0, 100]]
        fig = bid_quantities_plots(_df_res=r_bid_res, _scenarios=scenarios, _title=_simulation_tag, _y_lim=ylim, _product='Q')
        fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_bidQuantities_Q.png'), format='png', dpi=dpi_img)
        print(fig)
        plt.ion()
        plt.close()

        ylim = [[], []]
        fig = avoided_voltage_viol_plots(_df_res=avoided_voltage_viol_res, _scenarios=scenarios, _title=_simulation_tag, _y_lim=ylim)
        fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_AvVoltViolat.png'), format='png', dpi=dpi_img)
        print(fig)
        plt.ion()
        plt.close()

        # Density and Histograms Plots Active Power
        for _prod in products_list:
            for _vl in voltage_list:
                fig = plt_kpi.density_plot_bus(_data=_in_dict, _scenarios=scenarios, _title=_simulation_tag, _product2use=_prod, _vl2use=_vl)
                fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_DensityBus_' + _prod + '_' + _vl + '.png'), format='png', dpi=dpi_img)
                print(fig)
                plt.ion()
                plt.close()

                ylim = [[], []]
                xlim = [0.85, 1.15]
                fig = plt_kpi.histogram_plot_bus(_data=_in_dict, _scenarios=scenarios, _title=_simulation_tag, _xlim=xlim, _ylim=ylim, _product2use=_prod, _vl2use=_vl)
                fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_HistoBus_' + _prod+ '_' + _vl + '.png'), format='png', dpi=dpi_img)
                print(fig)
                plt.ion()
                plt.close()

                fig = plt_kpi.density_plot_lines(_data=_in_dict, _scenarios=scenarios, _title=_simulation_tag, _product2use=_prod, _vl2use=_vl)
                fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_DensityLines_' + _prod + '_' + _vl + '.png'), format='png', dpi=dpi_img)
                print(fig)
                plt.ion()
                plt.close()

                ylim = [[], []]
                xlim = []
                fig = plt_kpi.histogram_plot_lines(_data=_in_dict, _scenarios=scenarios, _title=_simulation_tag, _xlim=xlim, _ylim=ylim, _product2use=_prod, _vl2use=_vl)
                fig.savefig(os.path.join(_path_kpi_res, _simulation_tag + '_HistoLines_' + _prod + '_' + _vl + '.png'), format='png', dpi=dpi_img)
                print(fig)
                plt.ion()
                plt.close()

    if _draw_net:
        _net = _in_dict['network']
        pf_res_plotly(_net)
        # plot with topology and no power flow results
        pp.plotting.plotly.simple_plotly(_net, respect_switches=True, use_line_geodata=None, on_map=False,
                                         projection=None, map_style='basic', figsize=1, aspectratio='auto',
                                         line_width=1, bus_size=10, ext_grid_size=20.0, bus_color='blue',
                                         line_color='grey', trafo_color='green', ext_grid_color='yellow')
        # plot with no topology for lines and power flow results
        pp.plotting.plotly.simple_plotly(_net, respect_switches=True, use_line_geodata=False, on_map=False,
                                         projection=None, map_style='basic', figsize=1, aspectratio='auto',
                                         line_width=1, bus_size=10, ext_grid_size=20.0, bus_color='blue',
                                         line_color='grey', trafo_color='green', ext_grid_color='yellow')
        # plot with single line diagram of the line diagrams
        colors = ["b", "g", "r", "c", "y"]
        net_nogeo = _net.deepcopy()
        net_nogeo.bus_geodata.drop(net_nogeo.bus_geodata.index, inplace=True)
        net_nogeo.line_geodata.drop(net_nogeo.line_geodata.index, inplace=True)
        create_generic_coordinates(net_nogeo, respect_switches=True)
        fuse_geodata(net_nogeo)
        bc = create_bus_collection(net_nogeo, net_nogeo.bus.index, size=.08, color=colors[0], zorder=10)
        tlc, tpc = create_trafo_collection(net_nogeo, net_nogeo.trafo.index, color=colors[1])
        lcd = create_line_collection(net_nogeo, net_nogeo.line.index, color=colors[1], linewidths=0.5,
                                     use_bus_geodata=True)
        sc = create_bus_collection(net_nogeo, net_nogeo.ext_grid.bus.values, patch_type="rect", size=.3,
                                   color=colors[4], zorder=11)
        draw_collections([lcd, bc, tlc, tpc, sc], figsize=(12, 10))
    return True


def evaluate_kpis(_cfg_file, _paths, _fsp_file, _prods, _vls, _fsps, _draw_plots=True, _draw_net=False):
    """
    Function for evaluating the KPI.

    :param _cfg_file: Yaml configuration file.

    :param _paths: Dictionary with all the paths for each specific scenario.

    :param _fsp_file: Dictionary of file for each resource type.

    :param _prods: List of products that the user want to analyse in the KPI evaluation.

    :param _vls: List of voltage limits that the user want to analyse in the KPI evaluation.

    :param _fsps: List of fsp availability that the user want to analyse in the KPI evaluation.

    :param _draw_plots: Boolean value (True/False) plot graphs.

    :param _draw_net: Boolean value (True/False) plot network and save.
    """

    # TODO: _fsp_file is only used through its keys. Improve the input of the function.
    _kpi_params = _set_kpi_params(_cfg_file=_cfg_file, _paths=_paths, _fsp_file=_fsp_file, _prods=_prods, _vls=_vls, _fsps=_fsps)
    _kpi_params['path_KPIresults'] = _paths['kpi_out_root']
    _kpi_params['draw_plots'] = _draw_plots
    _kpi_params['draw_net'] = _draw_net
    _kpi_params['fsp_file'] = _fsp_file
    _kpi_params['products_list'] = _cfg_file['ProductTAG']
    _kpi_params['voltage_list'] = _cfg_file['VLTAG']

    # Load data of pre-market
    _kpi_params = _load_res_net_pre(_kpi_params, _kpi_params['scenarios_selected'])
    # Load data of post-market
    _kpi_params = _load_res_net_post(_kpi_params, _kpi_params['scenarios_selected'])
    # Load offered quantity in the market
    _kpi_params = _load_offered_quantity(_kpi_params, _kpi_params['scenarios_selected'])
    # Load cleared quantity of the market
    _kpi_params = _load_cleared_quantity(_kpi_params, _kpi_params['scenarios_selected'])

    _kpi_params['hc_pre'] = list()
    _kpi_params['hc_post'] = list()
    # Bid Quantities
    w_bid_quantities, r_bid_quantities = bid_quantities(_kpi_params)

    # Increased hosting capacity
    hc_res_pre, hc_res_post, ihc_res, pihc_res = increase_hc(_kpi_params)

    # Avoided Congestion Problems (Lines and Trafos)
    avoided_cong_res = avoided_cong(_kpi_params, _kpi_params['scenarios_selected'])

    # Avoided Voltage Violations (Buses)
    avoided_voltage_viol_res = avoided_voltage_violations(_kpi_params)

    # FSPs Flexibility Activated and Costs
    flex_all, dict_res, dict_cost = cost_flexibility(_kpi_params)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_rows', None)
    pd.options.display.float_format = '{:.2f}'.format

    # Model Results
    overall_res = build_final_table(flex_all)

    file_workbook = Path(_paths['kpi_out_root']).name.split('_', 2)[2]
    io_file.save_excel(_data=overall_res, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='Overall_Results')
    io_file.save_excel(_data=pd.DataFrame(flex_all), _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='FlexALL', _mode='a')
    io_file.save_excel(_data=avoided_voltage_viol_res, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='AvoidVoltageViol_Results', _mode='a')
    io_file.save_excel(_data=avoided_cong_res, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='AvoidCongestions_Results', _mode='a')
    io_file.save_excel(_data=pihc_res, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='pIHC_Results', _mode='a')
    io_file.save_excel(_data=ihc_res, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='IHC_Results', _mode='a')
    io_file.save_excel(_data=hc_res_post, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='HC_Results_post', _mode='a')
    io_file.save_excel(_data=hc_res_pre, _filename=file_workbook, _outroot=_paths['kpi_out_root'],
                       _sheetname='HC_Results_pre', _mode='a')

    # Volumes of flexibility for each FSP
    volume_flex_stats = volume_flex_offered(_kpi_params, dict_res, dict_cost)
    for _k in volume_flex_stats.keys():
        _idx = 0
        mode_write = 'w'
        for _h in volume_flex_stats[_k].keys():
            if _idx > 0:
                mode_write = 'a'
            io_file.save_excel(_data=volume_flex_stats[_k][_h], _filename='KPI_VolFlex_' + _k,
                               _outroot=_paths['kpi_out_root'], _sheetname=_h, _mode=mode_write)
            _idx += 1

    _kpi2plot = {
        'ihc_res': ihc_res,
        'pihc_res': pihc_res,
        'avoided_cong_res': avoided_cong_res,
        'avoided_voltage_viol_res': avoided_voltage_viol_res,
        'w_bid_q': w_bid_quantities,
        'r_bid_q': r_bid_quantities
    }
    # KPI plots follow the same master
    # visualization switch as the rest of the platform, while KPI workbooks are
    # still always produced.
    plot_kpi(_in_dict=_kpi_params, _kpi2plot=_kpi2plot, _path_kpi_res=_paths['kpi_out_root'], _simulation_tag=file_workbook, _draw_plots=_draw_plots, _draw_net=_draw_net)

    print('\nKPI calculation complete.')
    return True
