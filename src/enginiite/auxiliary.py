import os
import warnings
import importlib

import numpy as np
import pandas as pd
from pathlib import Path
from tqdm.auto import tqdm
from enginiite import file_io as io_file
from enginiite import tolerance_policy
from enginiite.market.models import aggregator_model as aggr
from enginiite.market.models.fsp_utils import match_pp_element

res_fcn = {
    'A': 'load_model',
    'B': 'generator_model',
    'C': 'storage_model',
    'D': 'heatpump_model'
}

res_fcn_profile = {
    'storage': 'storage_model',
    'heatpump': 'heatpump_model'
}


def validate_fsp_data(_net, _df_fsp):
    """Validates that the FSP data is correctly formatted."""
    fsp_mapping = {'A': 'load', 'B': 'sgen', 'C': 'storage', 'D': 'load'}

    for idx, row in tqdm(_df_fsp.iterrows(), desc='Validating FSP data'):
        fsp_type = row['type']
        bus = row['bus']
        name_element = row['name']
        declared_mw_fsp = row['mw']
        declared_mvar_fsp = row['mvar']
        declared_mva_fsp = row['mva']

        if fsp_type not in fsp_mapping:
            raise ValueError(f"FSP type {fsp_type} at index {idx} is invalid.")

        element_category = fsp_mapping[fsp_type]

        if bus not in _net[element_category].bus.tolist():
            raise ValueError(f"Bus ID {bus} not found in {_net[element_category]}.")

        element_id = match_pp_element(_net[element_category], row, element_category)

        p_mw = _net[element_category].loc[element_id, "p_mw"]
        q_mvar = _net[element_category].loc[element_id, "q_mvar"]
        sn_mva = _net[element_category].loc[element_id, "sn_mva"]

        if not np.isclose(p_mw, declared_mw_fsp, atol=1e-3):
            raise ValueError(
                f"Inconsistent MW values for element {element_category} in Network row {element_id}: Network Value = {p_mw}, Declared MW fsp = {declared_mw_fsp}")

        if not np.isclose(q_mvar, declared_mvar_fsp, atol=1e-3):
            raise ValueError(
                f"Inconsistent MVAr values for element {element_category} in Network row {element_id}: Network Value = {q_mvar}, Declared MVAr fsp = {declared_mvar_fsp}")

        if not np.isclose(sn_mva, declared_mva_fsp, atol=1e-3):
            raise ValueError(
                f"Inconsistent MVA values for element {element_category} in Network row {element_id}: Network Value = {sn_mva}, Declared MVA fsp = {declared_mva_fsp}")
    return True


def validate_sens_matrix(_sens_matrix, _ncols, _fsp_data):
    """Validates that the Sensitivity Matrix are correctly formatted."""
    for _fsp_type in _sens_matrix.keys():
        if _fsp_type != 'all':
            for _hour in _sens_matrix[_fsp_type].keys():
                _nrows = _fsp_data[_fsp_type]['n_fsp']
                actual_rows_p, actual_cols_p = _sens_matrix[_fsp_type][_hour]['W'].shape
                actual_rows_q, actual_cols_q = _sens_matrix[_fsp_type][_hour]['R'].shape

                if actual_rows_p != _nrows:
                    raise ValueError(f"Number of FSP in sensitivity matrix P (FSP: {actual_rows_p}) does not match expected number of FSP (expected FSP: {_nrows}).")

                if actual_cols_p != _ncols:
                    raise ValueError(f"Number of columns in sensitivity matrix P ({actual_cols_p}) does not match expected number of columns ({_ncols}).")

                if actual_rows_q != _nrows:
                    raise ValueError(f"Number of FSP in sensitivity matrix Q (FSP: {actual_rows_q}) does not match expected number of FSP (rows) (expected FSP: {_nrows}).")

                if actual_cols_q != _ncols:
                    raise ValueError(f"Number of columns in sensitivity matrix Q ({actual_cols_q}) does not match expected number of columns ({_ncols}).")
    return True


def validate_net_profiles(_net, _dict_profiles, _flag_save=False):
    """Validates that the network profiles are correctly formatted"""
    resource_mapping = {'load': _net.load}

    if not _net.sgen.empty:
        resource_mapping['sgen'] = _net.sgen

    if not _net.storage.empty:
        resource_mapping['storage'] = _net.storage

    if not _net.gen.empty:
        resource_mapping['gen'] = _net.gen

    for element_category in tqdm(resource_mapping.keys(), desc='Validating Network Data'):
        declared_mw = resource_mapping[element_category].p_mw.values
        declared_mvar = resource_mapping[element_category].q_mvar.values
        declared_mva = resource_mapping[element_category].sn_mva.values

        profile_mw = _dict_profiles[element_category + '_prof_p'].values
        profile_mvar = _dict_profiles[element_category + '_prof_q'].values
        profile_mva = np.sqrt(profile_mw ** 2 + profile_mvar ** 2)

        max_mw = profile_mw.max(axis=0)
        max_mvar = profile_mvar.max(axis=0)
        max_mva = profile_mva.max(axis=0)

        if _flag_save:
            if Path('max_values_profiles.xlsx').is_file():
                with pd.ExcelWriter('max_values_profiles.xlsx', engine='openpyxl', mode='a') as writer:
                    pd.DataFrame({'max_mw': max_mw, 'max_mvar': max_mvar, 'max_mva': max_mva}).to_excel(writer, sheet_name=element_category)
            else:
                pd.DataFrame({'max_mw': max_mw, 'max_mvar': max_mvar, 'max_mva': max_mva}).to_excel('max_values_profiles.xlsx', sheet_name=element_category)

        mw_elements = np.where(~np.less_equal(max_mw, declared_mw))[0]
        mvar_elements = np.where(~np.less_equal(max_mvar, declared_mvar))[0]
        mva_elements = np.where(~np.less_equal(max_mva, declared_mva))[0]

        wrong_max_mw = max_mw[mw_elements]
        wrong_max_mvar = max_mvar[mvar_elements]
        wrong_max_mva = max_mva[mva_elements]

        wrong_declared_mw = declared_mw[mw_elements]
        wrong_declared_mvar = declared_mvar[mvar_elements]
        wrong_declared_mva = declared_mva[mva_elements]
        if mw_elements.size > 0:
            raise ValueError(
                f"Mismatch between profile and declared MW for {element_category} in row {mw_elements}: Max P Profile = {wrong_max_mw}, Declared MW Network Value = {wrong_declared_mw}")

        if mvar_elements.size > 0:
            raise ValueError(
                f"Mismatch between profile and declared MVAr for {element_category} in row {mvar_elements}: Max Q Profile = {wrong_max_mvar}, Declared MVAr Network Value={wrong_declared_mvar}")

        if mva_elements.size > 0:
            raise ValueError(
                f"Mismatch between profile and declared MVA for {element_category} in row {mva_elements}: Max S Profile = {wrong_max_mva}, Declared MVA Network Value={wrong_declared_mva}")
    return True


def set_resources(_new_res_fcn):
    """
    This function allows the user to add new fsp modules for fsp resources considered in the platform.
    The keys of the dictionary are the user-define names of the resources, and the values of the dictionary are the
    python file of the resource (without .py). It must be point out that the key of the dictionary of a resource must be
    the equal to the "type" column in the fsp Excel file.
    The python file must be saved in the folder src/enginiite/market/models of the repository.
    """
    if _new_res_fcn is not None:
        global res_fcn
        for _key, _value in _new_res_fcn.items():
            res_fcn[_key] = _value
    return True


def set_resource_profiles(_new_res_fcn_profile):
    """
    This function allows the user to add new resource modules for resource that require calculation of initial profiles.
    The key of the dictionary of a resource must be the equal to the "element_name" column in the network Excel file.
    The python file must be saved in the folder src/enginiite/market/models of the repository.
    """
    if _new_res_fcn_profile is not None:
        global res_fcn_profile
        for _key, _value in _new_res_fcn_profile.items():
            res_fcn_profile[_key] = _value
    return True


def fsp_converter(_net, _ts_res, _fsp_data, _out_root, _hours, _params_dict, _cfg_file, _fsp_tag, _sim_tag, _k_opt=1):
    """
    This function adapts the flexibility service provider resource info into usable data for the local flexibility
    market optimization.

    Input:
        **_net** (dict) - The pandapower format network.

        **_ts_res** (dict) - Dictionary with the timeseries simulation.

        **_fsp_data** (Dataframe) - Dataframe with the fsp data involved in the simulation.

        **_out_root** (string) - Output root where to save files.

        **_hours** (List of integers) - List of hours with network constraint violations.

        **_sim_tag** (string) - Simulation tag.

        **_k_opt** (int, 1) - Margin for bidding below the full capacity - Safe for optimization convergence.

    Output:
        **filename_out** (List of strings) - List of the flexibility service provider file names per resource.

        **bus_out** (List of integers) - List of bus included as flexibility service provider.

    Example:

    >>> import pandas as pd
    >>> import pandapower.networks
    >>> from enginiite.file_io import import_yaml
    >>> net = pandapower.networks.example_multivoltage()
    >>> config_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> fsp_file, fsp_bus = fsp_converter(net, {}, pd.DataFrame([]), 'my_output_root', [1, 2], {}, config_file, 'F01', 'my_simulaion_tag', 1)

    """
    dict_res = res_fcn

    # Aggregated FSPs
    _fsp_data_aggr = _fsp_data.loc[_fsp_data.aggregator_name.notna()].reset_index(drop=True)
    # Not Aggregated FSPs
    _fsp_data_res = _fsp_data.loc[_fsp_data.aggregator_name.isna()].reset_index(drop=True)

    # Name of the page of the dictionary to look after the network
    _net_page = _params_dict['net_page']
    # Name of the page of the dictionary to look after the fsp
    _fsp_page = _params_dict['fsp_page']
    # Additional file names of the fsp that required additional information (passed through file, usually .xslx)
    _fsp_dict_additional_files = _cfg_file[_net_page][_fsp_page]['fsp_additional_filename']
    if _cfg_file[_net_page][_fsp_page]['fsp_additional_filename'] is None:
        _fsp_dict_additional_files = dict()

    _data = dict()
    # Pandapower network
    _data['net'] = _net
    # Timeseries results
    _data['ts_res'] = _ts_res
    # FSP Dataframe of the FSP Resources not Aggregated
    _data['fsp_data'] = _fsp_data_res
    # FSP Dataframe of the FSP Resources Aggregated (For Debugging)
    _data['fsp_data_aggr'] = _fsp_data_aggr
    # FSP Dataframe of the FSP Resources Not Aggregated (For Debugging)
    _data['fsp_data_res'] = _fsp_data_res
    # Output root where to save file of FSP
    _data['out_root'] = _out_root
    # List of hours to evaluate in the Flexibility Market
    _data['hours'] = _hours
    # Simulation Tag
    _data['sim_tag'] = _sim_tag
    # Capability Curve Constraints
    _data['cap_cstr'] = _params_dict['cap_curve_cons']
    # Time granularity interval, default value: 1 [hour]
    _data['dt'] = _params_dict['dt']
    # Intertemporal Constraints
    _data['int_soc'] = _params_dict['intertemp_cons']

    # Network Name
    _data['net_name'] = _cfg_file[_net_page]['net_folder']
    # Multiplier coefficient of the Load.
    _data['scen_factor_load'] = _cfg_file['scen_factor_load']
    # Multiplier coefficient of the Static Generator.
    _data['scen_factor_sgen'] = _cfg_file['scen_factor_sgen']
    # Multiplier coefficient of the Generator.
    _data['scen_factor_gen'] = _cfg_file['scen_factor_gen']
    # Multiplier coefficient of the Storage.
    _data['scen_factor_storage'] = _cfg_file['scen_factor_storage']
    # Coefficient multiplying the battery MVA size
    _data['ess_kmva'] = _params_dict['ess_k_MVA']
    # Active power bid up coefficient.
    _data['kbid_p_up'] = _params_dict['coeff_bid_Pup'][_fsp_tag]
    # Active power bid down coefficient.
    _data['kbid_p_dwn'] = _params_dict['coeff_bid_Pdown'][_fsp_tag]
    # Reactive power bid up coefficient.
    _data['kbid_q_up'] = _params_dict['coeff_bid_Qup'][_fsp_tag]
    # Reactive power bid down coefficient.
    _data['kbid_q_dwn'] = _params_dict['coeff_bid_Qdown'][_fsp_tag]

    filename_out = dict()
    bus_out = dict()

    # Not Aggregated FSPs
    for _i in _fsp_data_res.type.unique():
        list_res = dict_res.get(_i, None)
        # Add additional information for FSP Type
        _data['fsp_additional_file'] = _fsp_dict_additional_files.get(_i, None)
        # Create name of the file FSP
        fsp_filename = 'FSP' + _i + '_init' + _sim_tag

        if list_res is None:
            raise IOError('Resource of type {_class} is unknown.'.format(_class=_i))

        res_lib = importlib.import_module(f'enginiite.market.models.{list_res}')
        filename_res, bus_res = res_lib.fsp_converter(_data=_data, _k_opt=_k_opt, _class_fsp=_i, _fsp_filename=fsp_filename)
        filename_out[_i] = filename_res
        bus_out[_i] = bus_res

    # Aggregated FSPs
    for _i in _fsp_data_aggr.aggregator_name.unique():
        print('\n--- Initialising {_name} bids ---'.format(_name=_i))
        # In case Aggregators are used, add its module to the list of resource modules
        dict_res[_i] = 'aggregator_model'
        set_resources(_new_res_fcn=dict_res)
        # Modify the FSP Data value of Aggregated FSPs counting only those of Aggregator "_i"
        _data['fsp_data'] = _fsp_data_aggr.loc[_fsp_data_aggr.aggregator_name == _i].reset_index(drop=True)
        # Add additional information for FSP Type
        _data['fsp_additional_file_dict'] = _fsp_dict_additional_files
        # Create name of the file FSP
        fsp_filename = 'FSP' + _i + '_init' + _sim_tag

        filename_res, bus_res = aggr.aggregator_converter(_data=_data, _dict_modules=dict_res, _fsp_filename=fsp_filename, _k_opt=_k_opt)
        filename_out[_i] = filename_res
        bus_out[_i] = bus_res
    return filename_out, bus_out


def aggr_bids(_fsp_data, _fsp_file, _out_root, _matrix_root, _hours, _params_dict, _cong_needs, _v_before, _vmin, _vmax,
              _mrk_tag, _sim_tag, _flag_res=True, _flag_model=True):
    # Aggregated FSPs
    _fsp_data_aggr = _fsp_data.loc[_fsp_data.aggregator_name.notna()].reset_index(drop=True)

    dict_res = res_fcn

    _data = dict()
    # Dictionary with Modules of resources
    _data['dict_res'] = dict_res
    # Output root where to save file of FSP
    _data['out_root'] = _out_root
    # Root to the sensitivity matrix
    _data['matrix_root'] = _matrix_root
    # List of hours to evaluate in the Flexibility Market
    _data['hours'] = _hours
    # Congestion needs of the network
    # Non serve, ma forse molti altri dati di input sono inutili
    _data['cong_needs'] = _cong_needs
    # Voltage before the flexibility market
    _data['v_before'] = _v_before
    # Market Tag
    _data['mrk_tag'] = _mrk_tag
    # Simulation Tag
    _data['sim_tag'] = _sim_tag
    # Capability Curve Constraints
    _data['cap_cstr'] = _params_dict['cap_curve_cons']
    # Time granularity interval, default value: 1 [hour]
    _data['dt'] = _params_dict['dt']
    # Intertemporal Constraints
    _data['int_soc'] = _params_dict['intertemp_cons']
    # Include full knowledge of network constraints
    _data['net_cstr_aggr'] = _params_dict['net_cstr_aggr']
    # Congestion Management Factor
    _data['cm_factor'] = _params_dict['cm_factor']
    # Maximum Voltage
    _data['v_max'] = _vmax
    # Minimum Voltage
    _data['v_min'] = _vmin

    for _i in _fsp_data_aggr.aggregator_name.unique():
        # Modify the FSP Data value of Aggregated FSPs counting only those of Aggregator "_i"
        _data['fsp_data'] = _fsp_data_aggr.loc[_fsp_data_aggr.aggregator_name == _i].reset_index(drop=True)
        _filename_aggr = _fsp_file.get(_i, None)
        aggr.define_bids(_aggr_name=_i, _filename_aggr=_filename_aggr, _data=_data, _flag_res=_flag_res, _flag_model=_flag_model)
        a = 1

    return True


def eval_energy_support_res(_ts_res, _pilot_bus, _hours, _in_root, _out_root, _fsp_file, _filename_lfm,
                            _filename_vm_pilot='pilot_bus_vm_post'):
    """
    This function evaluates the resource energy support after the results of the flexibility market.

    Input:
        **_ts_res** (dict) - Dictionary of the timeseries simulation results.

        **_pilot_bus** (List of integers) - List of the selected pilot buses.

        **_hours** (List of integers) - List of hours with congestions.

        **_in_root** (string) - Directory where the input data are saved.

        **_out_root** (string) - Directory where to save the data.

        **_fsp_file** (List of strings) - List of the flexibility service provider file names per resource.

        **_filename_lfm** (string) - Name of the Local Flexibility Market file.

        **_filename_vm_pilot** (string, pilot_bus_vm_post) - Name of the csv file for the bus voltage of the pilot buses.

    Example:

    >>> eval_energy_support_res({}, [0, 1, 2], [1, 2], 'my_input_root', 'my_out_root', {}, 'my_lfm_results_filename.xlsx', 'pilot_bus_vm_post')

    """
    # Save pilot bus voltage in per unit after the market.
    _bus_voltages_post = _ts_res['bus_vm_pu']
    pilot_bus_vm_post = _bus_voltages_post.loc[:, _pilot_bus]
    io_file.save_cvs(_data=pilot_bus_vm_post, _outroot=_out_root, _filename=_filename_vm_pilot)

    for _fsp_type in tqdm(_fsp_file.keys(), desc='Evaluating the support of resources'):
        if _fsp_file[_fsp_type] != 0:
            if Path(os.path.join(_out_root, 'Res_Exploitation.xlsx')).is_file():
                mode_save = 'a'
            else:
                mode_save = 'w'

            xls = pd.ExcelFile(os.path.join(_in_root, _fsp_file[_fsp_type] + '.xlsx'))
            valid_sheets = [sheet for sheet in xls.sheet_names if sheet.endswith(f'Lim_{_fsp_type}')]

            data_fspInit = {sheet: io_file.import_data(_filename=_fsp_file[_fsp_type] + '.xlsx', _root=_in_root, _sheetname=sheet, _index_col=0, _header=0) for sheet in valid_sheets}
            FSPinfo = io_file.import_data(_filename=_fsp_file[_fsp_type] + '.xlsx', _root=_in_root, _sheetname='FSPinfo_' + _fsp_type, _index_col=0)

            dw_u = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='DW_' + _fsp_type + '_U', _index_col=0, _header=0)
            dw_d = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='DW_' + _fsp_type + '_D', _index_col=0, _header=0)

            dr_u = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='DR_' + _fsp_type + '_U', _index_col=0, _header=0)
            dr_d = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='DR_' + _fsp_type + '_D', _index_col=0, _header=0)

            final_w = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='W_' + _fsp_type, _index_col=0, _header=0)
            final_r = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='R_' + _fsp_type, _index_col=0, _header=0)

            for _df in [dw_u, dw_d, dr_u, dr_d, final_w, final_r]:
                if not _df.index.equals(FSPinfo.index) and len(_df.index) == len(FSPinfo.index):
                    _df.index = FSPinfo.index

            fsp_res_category = FSPinfo.res_category.iloc[0]
            if fsp_res_category == 'load':
                den_r_u = data_fspInit['RUB_DLim_' + _fsp_type]
                den_r_d = data_fspInit['RUB_ULim_' + _fsp_type]
                den_w_u = data_fspInit['WLB_ULim_' + _fsp_type]
                den_w_d = data_fspInit['WUB_DLim_' + _fsp_type]
            elif fsp_res_category == 'sgen':
                den_r_u = data_fspInit['RUB_DLim_' + _fsp_type]
                den_r_d = data_fspInit['RUB_ULim_' + _fsp_type]
                den_w_u = data_fspInit['WUB_ULim_' + _fsp_type]
                den_w_d = data_fspInit['WLB_DLim_' + _fsp_type]
            elif fsp_res_category == 'storage':
                den_r_u = data_fspInit['RUB_DLim_' + _fsp_type]
                den_r_d = data_fspInit['RUB_ULim_' + _fsp_type]
                den_w_u = data_fspInit['WUB_ULim_' + _fsp_type]
                den_w_d = data_fspInit['WLB_DLim_' + _fsp_type]
            elif fsp_res_category == 'gen':
                den_r_u = data_fspInit['RUB_DLim_' + _fsp_type]
                den_r_d = data_fspInit['RUB_ULim_' + _fsp_type]
                den_w_u = data_fspInit['WUB_ULim_' + _fsp_type]
                den_w_d = data_fspInit['WLB_DLim_' + _fsp_type]
            else:
                raise UserWarning('FSP Type "{_type}" not defined.'.format(_type=_fsp_type))

            if np.sum(np.sum(dr_d, axis=0)) == 0 and np.sum(np.sum(dr_u, axis=0)) != 0:
                res_exploit_r = (final_r * 100) / den_r_u
            else:
                res_exploit_r = (final_r * 100) / den_r_d

            if np.sum(np.sum(dw_d, axis=0)) == 0 and np.sum(np.sum(dw_u, axis=0)) != 0:
                res_exploit_w = (final_w * 100) / den_w_u
            else:
                res_exploit_w = (final_w * 100) / den_w_d

            # The support (cleared quantity) counts BOTH directions.
            # Before, one direction was kept for the whole FSP class (the downward sheet whenever any
            # downward activation existed), so every upward activation was left out of Support_*.xlsx and of
            # the "Cleared" bars (in one scenario, 10.21 MW shown against 37.32 MW activated).  The U and D
            # sheets hold non-negative magnitudes; the signed net change is the market's DW_/DR_ sheet
            # (load and storage positive downward, generator positive upward, as noted below).
            dw = dw_u.abs() + dw_d.abs()
            dr = dr_u.abs() + dr_d.abs()
            dw_net = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='DW_' + _fsp_type, _index_col=0, _header=0)
            dr_net = io_file.import_data(_filename=Path(_filename_lfm).name, _root=_out_root, _sheetname='DR_' + _fsp_type, _index_col=0, _header=0)
            for _df in [dw_net, dr_net]:
                if not _df.index.equals(FSPinfo.index) and len(_df.index) == len(FSPinfo.index):
                    _df.index = FSPinfo.index
            dw_net = dw_net.reindex(index=dw.index, columns=dw.columns).fillna(0.0)
            dr_net = dr_net.reindex(index=dr.index, columns=dr.columns).fillna(0.0)

            io_file.save_excel(_data=res_exploit_w, _outroot=_out_root, _filename='Res_Exploitation', _mode=mode_save, _sheetname='W_' + _fsp_type)
            io_file.save_excel(_data=res_exploit_r, _outroot=_out_root, _filename='Res_Exploitation', _mode='a', _sheetname='R_' + _fsp_type)

            supp_p = np.zeros(len(dw.index))
            supp_q = np.zeros(len(dr.index))
            supp_s = np.zeros(len(dr.index))
            net_supp_p = np.zeros(len(dw.index))
            net_supp_q = np.zeros(len(dr.index))
            net_supp_s = np.zeros(len(dr.index))
            for i in range(len(dw.index)):
                supp_p[i] = sum(abs(dw.iloc[i, :]))
                supp_q[i] = sum(abs(dr.iloc[i, :]))
                supp_s[i] = np.sqrt((supp_p[i] * supp_p[i]) + (supp_q[i] * supp_q[i]))
                # Load: Positive if downward, Negative if upward
                # Sgen: Negative if downward, Positive if upward
                # Storage: Positive if downward, Negative if upward
                net_supp_p[i] = sum(dw_net.iloc[i, :])  # Signed net (DW_ sheet)
                # Load: Positive if downward, Negatives if upward
                # Sgen: Negative if downward, Positive if upward
                # Storage: Positive if downward, Negative if upward
                net_supp_q[i] = sum(dr_net.iloc[i, :])  # Signed net (DR_ sheet)
                net_supp_s[i] = np.sqrt((net_supp_p[i] * net_supp_p[i]) + (net_supp_q[i] * net_supp_q[i]))

            df_supp_p = pd.DataFrame(supp_p)
            df_supp_p.columns = ['SupportP_' + _fsp_type]
            df_supp_q = pd.DataFrame(supp_q)
            df_supp_q.columns = ['SupportQ_' + _fsp_type]
            df_supp_s = pd.DataFrame(supp_s)
            df_supp_s.columns = ['SupportS_' + _fsp_type]
            df_net_supp_p = pd.DataFrame(net_supp_p)
            df_net_supp_p.columns = ['NetSupportP_' + _fsp_type]
            df_net_supp_q = pd.DataFrame(net_supp_q)
            df_net_supp_q.columns = ['NetSupportQ_' + _fsp_type]
            df_net_supp_s = pd.DataFrame(net_supp_s)
            df_net_supp_s.columns = ['NetSupportS_' + _fsp_type]
            support_res = pd.concat([df_supp_p, df_supp_q, df_supp_s, df_net_supp_p, df_net_supp_q, df_net_supp_s], axis=1)
            io_file.save_excel(_data=support_res, _outroot=_out_root, _filename='Support_' + _fsp_type, _sheetname=_fsp_type)
    return True


def get_list(_startswith_key, _comparing_list):
    """
    This function gets the keys that starts with the value passed as input.

    Input:
        **_startswith_key** (string) - Starting string to which the values will be compared.

        **_comparing_list** (list of strings) - List of values to be compared with.

    Output:
        **list_keys** (list of strings) - List of values that start with the "_startswith_key".

    Example:

        >>> my_list = get_list('DW_', {'D_A': np.zeros(shape=(1,1)), 'DW_A': np.zeros(shape=(1,1))})

    """
    list_keys = [i for i in _comparing_list.keys() if i.startswith(_startswith_key + '_')]
    if len(list_keys) == 0:
        # This value is essential for the "Storage" resource that adopt the "inj" and "ads" key in addition
        list_keys = [i for i in _comparing_list.keys() if i.startswith(_startswith_key)]
    return list_keys


def _check_root(_dir2check):
    """
    This function checks if root exist and in case it doesn't, the function creates it.

    Input:
        **_dir2check** (string) - Directory to check existence

    Example:

        >>> _check_root('my_root2check')

    """
    if not os.path.isdir(_dir2check):
        warnings.warn('Building {_name} path ...'.format(_name=_dir2check))
        os.makedirs(_dir2check)
        return False
    else:
        return True


def _def_dp(_cfg_file, _direction=False):
    """
    This function checks the minimum set-point of the resources and define the delta_p and delta_q for the sensitivity
    factors evaluation. To do this the function increases by one the delta_p and delta_q to remain in the linear
    approximation of the sensitivity factors calculation.

    Input:
        **_cfg_file** (dict) - Yaml configuration file

        **_direction** (Boolean, False) - Select Maximum or Minimum Value of Active Power/Reactive Power of resources
        to


    Output:
        **_dp_net** (float) - Delta Active Power to apply to the sensitivity factors calculation
        **_dq_net** (float) - Delta Reactive Power to apply to the sensitivity factors calculation

    Example:

    >>> from enginiite.file_io import import_yaml
    >>> config_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> dp, dq = _def_dp(_cfg_file)

    """
    _net = io_file.import_network(_cfg_file['network'])
    _load_p = _net.load.p_mw
    _gen_p = _net.gen.p_mw
    _sgen_p = _net.sgen.p_mw
    _batt_p = _net.storage.p_mw

    _load_q = _net.load.q_mvar
    _sgen_q = _net.sgen.q_mvar
    _batt_q = _net.storage.q_mvar

    if _direction:
        _max_p = [max(filter(lambda x: x > 0, _load_p), default=0), max(filter(lambda x: x > 0, _gen_p), default=0),
                  max(filter(lambda x: x > 0, _sgen_p), default=0), max(filter(lambda x: x > 0, _batt_p), default=0)]
        _max_q = [max(filter(lambda x: x > 0, _load_q), default=0), max(filter(lambda x: x > 0, _sgen_q), default=0),
                  max(filter(lambda x: x > 0, _batt_q), default=0)]
        _max_nnzero_p = [i for i in _max_p if i > 0]
        _max_nnzero_q = [j for j in _max_q if j > 0]

        try:
            _exp_max_p = int(('%e' % max(_max_nnzero_p)).partition('-')[2]) + 1
            _exp_max_q = int(('%e' % max(_max_nnzero_q)).partition('-')[2]) + 1
        except ValueError:
            _exp_max_p = 1
            _exp_max_q = 1
        _dp_net = 1 / (10 ** _exp_max_p)
        _dq_net = 1 / (10 ** _exp_max_q)

    else:
        _min_p = [min(filter(lambda x: x > 0, _load_p), default=10000), min(filter(lambda x: x > 0, _gen_p), default=10000),
                  min(filter(lambda x: x > 0, _sgen_p), default=10000), min(filter(lambda x: x > 0, _batt_p), default=10000)]
        _min_q = [min(filter(lambda x: x > 0, _load_q), default=10000), min(filter(lambda x: x > 0, _sgen_q), default=10000),
                  min(filter(lambda x: x > 0, _batt_q), default=10000)]
        _min_nnzero_p = [i for i in _min_p if i > 0]
        _min_nnzero_q = [j for j in _min_q if j > 0]

        try:
            _exp_min_p = int(('%e' % min(_min_nnzero_p)).partition('-')[2]) + 1
            _exp_min_q = int(('%e' % min(_min_nnzero_q)).partition('-')[2]) + 1
        except ValueError:
            _exp_min_p = 1
            _exp_min_q = 1
        _dp_net = 1 / (10 ** _exp_min_p)
        _dq_net = 1 / (10 ** _exp_min_q)
    return _dp_net, _dq_net


def _output_network_tag(_name_network, _sim_tag):
    """Remove a duplicated simulation suffix from the output-only network tag."""
    network = str(_name_network or "").strip("_")
    simulation = str(_sim_tag or "").strip("_")
    # Scenario inputs such as
    # SB_DER_LOC_LOW keep their complete input folder name, but output names
    # use network=SB and simulation_tag=DER_LOC_LOW. Thus the simulation tag is
    # always explicit at the end and appears exactly once.
    suffix = "_" + simulation if simulation else ""
    if suffix and network.endswith(suffix):
        shortened = network[:-len(suffix)].strip("_")
        if shortened:
            return shortened
    return network


def set_paths(_main_root, _name_network, _model_tag, _product_tags, _vl_tags, _fsp_tags, _ess_tag, _sim_tag,
              _in_root='data_in', _out_root='data_out'):
    """
    This function sets the general paths of the project. It will create the directory when they do not exist.
    For general, the developer means the paths that are valid for different scenarios, where for scenarios he
    means different tags of the config file (CMVC, SK02, F03 or even VL01).

    Input:
        **_main_root** (string) - Root of the project.

        **_name_network** (string) - Name of the network.

        **_model_tag** (string) - Tag for the market model.

        **_product_tags** (List of strings) - Tags for the products of the market.

        **_vl_tags** (List of strings) - Tag for the voltage limitations of the market.

        **_fsp_tags** (List of strings) - Tag for the flexibility provided in the market.

        **_ess_tag** (string) - Tag for the Storage capacity flexibility provider.

        **_sim_tag** (string) - Tag for the specific simulation name.

        **_in_root** (string, data_in) - Name of the folder in which the input are saved.

        **_out_root** (string, data_out) - Name of the folder in which the output will be saved.

    Output:
        **_gpath_dict** (dict) - Dictionary containing all the general paths.

    Example:

    >>> import os
    >>> path_dict = set_paths(os.getcwd(), 'my_network', 'CMVC', ['P', 'Q'], ['VL01', 'VL03'], ['F03', 'F05'], 'SK01', '',
    >>>                       'data_in', 'data_out')

    """

    _gpath_dict = dict()
    _gpath_dict['net_name'] = _name_network

    # INPUT PATH SETTINGS
    _input_path = os.path.join(_main_root, _in_root)
    if not os.path.exists(_input_path):
        raise IOError('The "{_name}" directory do not exists.'.format(_name=_input_path))
    _gpath_dict['in_root'] = _input_path

    _root2net = 'network'
    _net_input_path = os.path.join(_input_path, _name_network, _root2net)
    if not os.path.exists(_net_input_path):
        raise IOError('The "{_name}" directory do not exists.'.format(_name=_net_input_path))
    _gpath_dict['net_in_root'] = _net_input_path

    _root2fspfiles = 'fsp_files'
    _fsp_input_path = os.path.join(_input_path, _name_network, _root2fspfiles)
    if not os.path.exists(_fsp_input_path):
        raise IOError('The "{_name}" directory do not exists.'.format(_name=_fsp_input_path))
    _gpath_dict['fsp_in_root'] = _fsp_input_path

    _root2profiles = 'profile'
    _prof_input_path = os.path.join(_input_path, _name_network, _root2profiles)
    if not os.path.exists(_prof_input_path):
        raise IOError('The "{_name}" directory do not exists.'.format(_name=_prof_input_path))
    _gpath_dict['prof_in_root'] = _prof_input_path

    # Input market folder
    _root2mrkinputs = 'market_inputs'
    _mrk_input_path = os.path.join(_input_path, _name_network, _root2mrkinputs)
    _check_root(_mrk_input_path)

    # Input sensitivity matrix folder
    _root2sensmatrix = 'h24SensitivityMatrixes'
    _sensmatrix_path = os.path.join(_mrk_input_path, _root2sensmatrix)
    _check_root(_sensmatrix_path)
    _gpath_dict['sens_matrix_root'] = _sensmatrix_path

    # OUTPUT PATH SETTINGS
    _output_path = os.path.join(_main_root, _out_root)

    _output_network = _output_network_tag(_name_network, _sim_tag)
    _name_tags = [_output_network, _model_tag, _ess_tag, _sim_tag]
    _root2out_net = '_'.join(filter(None, _name_tags))
    _net_output_path = os.path.join(_output_path, _root2out_net)
    _gpath_dict['net_out_root'] = _net_output_path

    # Timeseries simulation output folders
    _root2tsnet_results = 'res_ts_net'
    _ts_output_path = os.path.join(_net_output_path, _root2tsnet_results)
    _check_root(_ts_output_path)
    _gpath_dict['ts_out_root'] = _ts_output_path

    _kpi_tags = ['KPI_results', _output_network, _model_tag, _ess_tag, _sim_tag]
    _root2kpi = '_'.join(filter(None, _kpi_tags))
    _kpi_output_path = os.path.join(_net_output_path, _root2kpi)
    _check_root(_kpi_output_path)
    _gpath_dict['kpi_out_root'] = _kpi_output_path

    # Input market folder
    _gpath_dict['mrk_inputs'] = {_prod: {_vl: dict() for _vl in _vl_tags} for _prod in _product_tags}

    # Output market folder
    _gpath_dict['simulation_tag'] = {_prod: {_vl: dict() for _vl in _vl_tags} for _prod in _product_tags}
    _gpath_dict['mrk_outputs'] = dict()
    _gpath_dict['mrk_outputs']['res_market'] = {_prod: {_vl: dict() for _vl in _vl_tags} for _prod in _product_tags}
    _gpath_dict['mrk_outputs']['ts_postmrk_out_root'] = {_prod: {_vl: dict() for _vl in _vl_tags} for _prod in _product_tags}
    _root2postmrk_tsnet_results = 'FullTS_postMKT'

    # Every result of one simulated case
    # lives in ONE folder, data_out/<bundle>/<case>/.  The per-case market inputs
    # (converted FSP workbooks, the rebased FSP files of each corrective market,
    # the corrective-market sensitivity caches, hours to study, pilot buses) used
    # to be written to data_in/<network>/market_inputs/<model>/<prod>/<vl>/<fsp>/,
    # away from the results they produced.  They are run-time products, not
    # inputs, so they are now written to <case>/market_inputs/.  The reusable
    # pre-market sensitivity cache (sens_matrix_root) stays shared in data_in;
    # each market stage archives the matrices it cleared on inside the case.
    _gpath_dict['case_market_inputs_folder'] = 'market_inputs'
    for _prod in _product_tags:
        for _vl in _vl_tags:
            for _fsp in _fsp_tags:
                # Simulation tag
                _list_tags = [_output_network, _model_tag, _prod, _vl, _fsp, _ess_tag, _sim_tag]
                _simulation_tag = '_'.join(filter(None, _list_tags))
                _gpath_dict['simulation_tag'][_prod][_vl][_fsp] = _simulation_tag
                # Post Market output folders
                _postmrk_output_path = os.path.join(_net_output_path, _simulation_tag)
                _check_root(_postmrk_output_path)
                _gpath_dict['mrk_outputs']['res_market'][_prod][_vl][_fsp] = _postmrk_output_path
                # Case market inputs inside the case folder.
                _fsptag_input_path = os.path.join(_postmrk_output_path, _gpath_dict['case_market_inputs_folder'])
                _check_root(_fsptag_input_path)
                _gpath_dict['mrk_inputs'][_prod][_vl][_fsp] = _fsptag_input_path
                # Timeseries simulation post market output folders
                _ts_postmrk_output_path = os.path.join(_postmrk_output_path, _root2postmrk_tsnet_results)
                _check_root(_ts_postmrk_output_path)
                _gpath_dict['mrk_outputs']['ts_postmrk_out_root'][_prod][_vl][_fsp] = _ts_postmrk_output_path
    return _gpath_dict


def set_params(_cfg_file, _path_dict, _vl_tags, _fsp_tags, _ess_tag):
    """
    This function sets the general parameters of the simulation.
    For general, the developer means the parameters that are valid for different scenarios, where for scenarios he
    means different tags of the config file (CMVC, SK02, F03 or even VL01).

    Input:
        **_cfg_file** (dict) - Yaml configuration file.

        **_path_dict** (string) - Dictionary containing all the paths.

        **_vl_tags** (List of strings) - Tag for the voltage limitations of the market.

        **_fsp_tags** (List of strings) - Tag for the flexibility provided in the market.

        **_ess_tag** (string) - Tag for the Storage capacity flexibility provider.

    Output:
        **_gparams_dict** (dict) - Dictionary containing all the general parameters.

    Example:

    >>> import os
    >>> from enginiite.file_io import import_yaml
    >>> cfg_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> path_dict = set_paths(os.getcwd(), 'my_network', 'CMVC', 'SK01', '', 'data_in', 'data_out')
    >>> params_dict = set_params(cfg_file, path_dict, cfg_file['VLTAG'], cfg_file['FspTAG'], cfg_file['StorageTag'])

    """
    _gparams_dict = dict()

    # Timestep
    time_step = _cfg_file['simulation_window']
    _gparams_dict['timestep'] = time_step
    _gparams_dict['ts_output_file_type'] = _cfg_file['network']['ts_output_file_type']

    # simulation_window can hold the
    # consecutive time steps of one scenario, or a set of independent scenarios
    # executed together only for comparison.  In the second case no market index
    # may pool two windows, because they describe two different markets.
    _gparams_dict['window_as_timesteps'] = bool(
        _cfg_file.get('simulation_window_as_timesteps', True)
    )

    # FSP File Definition
    _net_page = 'network'
    _fsp_page = 'fsp'
    _gparams_dict['net_page'] = _net_page
    _gparams_dict['fsp_page'] = _fsp_page

    _gparams_dict['fsp_file'] = _cfg_file[_net_page][_fsp_page]['fsp_input_filename']

    # Modify Dictionary of FSP Resources
    new_res_fcn = _cfg_file[_net_page]['fsp_models']
    set_resources(_new_res_fcn=new_res_fcn)

    # Modify Dictionary of FSP Resource Profiles
    new_res_fcn_profile = _cfg_file[_net_page]['profile_models']
    set_resource_profiles(_new_res_fcn_profile=new_res_fcn_profile)

    # Consider the sensitivity coefficient in the clearing of the market
    net_in_market = True
    _gparams_dict['net_in_market'] = net_in_market

    # Consider the Capability curve of the resource
    cap_curve_cons = True
    _gparams_dict['cap_curve_cons'] = cap_curve_cons

    # Only for Resource with Inter-temporal Constraints (i.e., storage and heatpump).
    # Consider the Inter-temporal Constraints
    intertemp_cons = _cfg_file['intertemp_cons']
    _gparams_dict['intertemp_cons'] = intertemp_cons

    # In case the inter-temporal constraints are active, this will create a sequence of simulation hours of at least the
    # value passed.
    consecutive_hours = _cfg_file['consecutive_hours']
    _gparams_dict['consec_hours'] = consecutive_hours

    # Evaluate the market only in the worst hour. In case the inter-temporal constraints are active, a simulation
    # window of consecutive_hours will be created with the worst hour at the center.
    only_worst_hour = _cfg_file['only_worst_hour']
    _gparams_dict['only_worst_hour'] = only_worst_hour

    # Full Network Representation. The maximum apparent power constraints (Lines, Transformer - 2W and 3W) are
    # considered for each asset of the network. The maximum and minimum voltage constraints are considered for each bus
    # of the network.
    _gparams_dict['full_net'] = _cfg_file['full_network']

    # Forces the timeseries calculation even if the files already exist
    force_ts = _cfg_file['timeseries_force_1st_calculation']
    _gparams_dict['force_ts'] = force_ts

    # Complete sensitivity caches are
    # reused by default and can be explicitly rebuilt from YAML.
    force_hvm = bool(_cfg_file.get('force_HVM', False))
    _gparams_dict['force_HVM'] = force_hvm

    # Time granularity interval, default value: 1 [hour]
    dt = 1
    _gparams_dict['dt'] = dt

    # Congestion Management
    # Forces the HCM matrices calculation even if the files already exist
    force_hcm = bool(_cfg_file.get('force_HCM', False))
    _gparams_dict['force_HCM'] = force_hcm

    # Check Maximum/Minimum FSP MW value
    delta_p_coeff, delta_q_coeff = _def_dp(_cfg_file, False)
    # Optional override of the
    # perturbation step of the sensitivity power flows.  _def_dp derives it from
    # the smallest NOMINAL element (1e-4 MW / 1e-3 MVAr on SB72), close to the
    # Newton-Raphson tolerance; a robustness study needs to vary it without
    # editing code.  Absent keys keep the derived values, so existing runs are
    # unchanged.
    if _cfg_file.get('sensitivity_delta_p_mw') is not None:
        delta_p_coeff = float(_cfg_file['sensitivity_delta_p_mw'])
    if _cfg_file.get('sensitivity_delta_q_mvar') is not None:
        delta_q_coeff = float(_cfg_file['sensitivity_delta_q_mvar'])
    _gparams_dict['vc_deltaP_coeff'] = delta_p_coeff
    _gparams_dict['vc_deltaQ_coeff'] = delta_q_coeff

    _gparams_dict['cm_deltaP_coeff'] = delta_p_coeff
    _gparams_dict['cm_deltaQ_coeff'] = delta_q_coeff

    # Cost of flexibility not supplied (VOLL)
    beta_cost = _cfg_file['BetaCost']
    _gparams_dict['beta_cost'] = beta_cost

    # Cost of the slack variable for the optimisation
    alpha_cost = _cfg_file['BetaCost']
    _gparams_dict['alpha_cost'] = alpha_cost

    _gparams_dict['only_pilot_busMV'] = _cfg_file['only_pilot_busMV']
    _gparams_dict['vn_kv_mv'] = _cfg_file['vn_kv_mv']
    _gparams_dict['net_cstr_aggr'] = _cfg_file['net_cstr_aggr']

    # Coefficient multiplying the battery MVA size
    try:
        ess_k_mva = int(_ess_tag.split('SK')[-1])
    except ValueError:
        ess_k_mva = 0
    _gparams_dict['ess_k_MVA'] = ess_k_mva

    # Flexibility Market Parameters
    _gparams_dict['mip_focus'] = 2
    _gparams_dict['nnvonvex'] = 2
    _gparams_dict['method'] = 5
    _gparams_dict['mip_gap'] = .00001
    _gparams_dict['flag_lp'] = True
    _gparams_dict['flag_mps'] = False

    if _cfg_file['ModelTAG'] == 'CMVC' or _cfg_file['ModelTAG'] == 'VCCM':
        _gparams_dict['cm_factor'] = -1
        _gparams_dict['mip_gap'] = .00001
    elif _cfg_file['ModelTAG'] == 'CM':
        _gparams_dict['cm_factor'] = -1
        _gparams_dict['mip_gap'] = .00001
    elif _cfg_file['ModelTAG'] == 'VC':
        _gparams_dict['cm_factor'] = 1
        _gparams_dict['mip_gap'] = .000001

    # Allow a scenario YAML to override the
    # solver effort, keeping the values above as the defaults so every existing
    # configuration behaves exactly as before.
    #
    # The default gap of 1e-5 asks Gurobi to prove optimality to 1e-5 relative,
    # which on a market whose procurement is a few thousand euro means proving
    # to a fraction of a cent.  With one battery contributing two binaries per
    # snapshot that becomes the binding cost of the whole study: a set of providers
    # with 35 batteries over 12 snapshots consumed 5.1 CPU-hours in 37 minutes
    # of wall time without closing, while 18 batteries cleared in about 25
    # minutes.  A study that compares sets of providers needs a consistent and
    # affordable optimality criterion, not the tightest possible one.
    for _key, _param in (('mip_gap', 'mip_gap'), ('mip_focus', 'mip_focus'),
                         ('solver_method', 'method')):
        if _key in _cfg_file and _cfg_file[_key] is not None:
            _gparams_dict[_param] = (
                float(_cfg_file[_key]) if _param == 'mip_gap'
                else int(_cfg_file[_key]))

    # Optional wall-clock limit (seconds)
    # and thread count for every market solve.  Absent, Gurobi keeps its own
    # defaults (no time limit, every core), so existing configurations behave
    # exactly as before.  With time_limit a solve stops after that many seconds
    # and keeps its best feasible solution; the gap it reached is written in the
    # Gurobi log of the solve (GReports/gurobi_<market tag>.log).  threads is
    # useful when two runs share the machine.
    _gparams_dict['time_limit'] = (
        float(_cfg_file['time_limit']) if _cfg_file.get('time_limit') is not None else None)
    _gparams_dict['threads'] = (
        int(_cfg_file['threads']) if _cfg_file.get('threads') is not None else None)
    # Print Gurobi's progress table on the
    # console while a market solves (default False keeps the console quiet).
    _gparams_dict['solver_log_to_console'] = bool(_cfg_file.get('solver_log_to_console', False))

    # Basis of the congestion (HCM)
    # sensitivities.  'apparent_power' (default) keeps the original
    # sqrt(max|p|^2 + max|q|^2) definition; 'current' differentiates the branch
    # flow at its current, the basis of s_init and of the AC loading test (see
    # sensitivity_factors._branch_current_mva).
    cm_basis = str(_cfg_file.get('cm_sensitivity_basis', 'apparent_power')).strip().lower()
    if cm_basis not in ('apparent_power', 'current'):
        raise ValueError("cm_sensitivity_basis must be 'apparent_power' or 'current', got %r" % cm_basis)
    _gparams_dict['cm_sensitivity_basis'] = cm_basis

    # inverse-Jacobian exports are
    # optional diagnostics and do not control market sensitivity calculation.
    save_invJ = bool(
        _cfg_file.get(
            'save_inverse_jacobian',
            _cfg_file.get('save_invJ', False)
        )
    )
    _gparams_dict['save_invJ'] = dict()
    _gparams_dict['coeff_bid_Pup'] = dict()
    _gparams_dict['coeff_bid_Pdown'] = dict()
    _gparams_dict['coeff_bid_Qup'] = dict()
    _gparams_dict['coeff_bid_Qdown'] = dict()
    for _fsp in _fsp_tags:
        _gparams_dict['save_invJ'][_fsp] = save_invJ

        # Bid coefficients
        try:
            coeff_bid = int(_fsp.split('F')[-1])
            coeff_bid_Pup = 1 * coeff_bid
            _gparams_dict['coeff_bid_Pup'][_fsp] = coeff_bid_Pup
            coeff_bid_Pdown = 1 * coeff_bid
            _gparams_dict['coeff_bid_Pdown'][_fsp] = coeff_bid_Pdown
            coeff_bid_Qup = 1 * coeff_bid
            _gparams_dict['coeff_bid_Qup'][_fsp] = coeff_bid_Qup
            coeff_bid_Qdown = 1 * coeff_bid
            _gparams_dict['coeff_bid_Qdown'][_fsp] = coeff_bid_Qdown
        except ValueError:
            raise UserWarning('The FSP Tag {_name} is wrongly declared.'.format(_name=_fsp))

    # One canonical policy separates the
    # physical standard, preventive detection limit, and optimization target.
    tolerance = tolerance_policy.build_tolerance_policy(_cfg_file, _vl_tags)
    current_policy = tolerance['current']

    # Tolerance of the Optimisation (w.r.t. to limits defined by model constraints)
    _gparams_dict['dv_tol_opt'] = _cfg_file['tol_v_opt'] / 100
    _gparams_dict['di_tol_opt'] = _cfg_file['tol_i_opt']
    # Technical Tolerance post (w.r.t. to limits defined by Power Flow and KPI)
    _gparams_dict['dv_tol'] = _cfg_file['tol_v'] / 100
    _gparams_dict['di_tol'] = _cfg_file['tol_i']

    line_overload_limit = current_policy['detection_limit_percent']
    _gparams_dict['line_overload_limit'] = line_overload_limit
    trafo_overload_limit = current_policy['detection_limit_percent']
    _gparams_dict['trafo_overload_limit'] = trafo_overload_limit
    _gparams_dict['current_physical_limit'] = current_policy['standard_percent']
    _gparams_dict['current_detection_limit'] = current_policy['detection_limit_percent']
    _gparams_dict['current_optimization_target'] = current_policy['optimization_target_percent']

    # Nonlinear AC validation keeps the
    # detection threshold fixed.  Corrective operating-point market reruns are
    # controlled by one integer knob: max_corrective_market_running.  Zero means
    # audit only; positive values allow that many sequential corrective markets.
    _gparams_dict['ac_validate_post_market'] = bool(
        _cfg_file.get('ac_validate_post_market', True)
    )
    max_corrective_market_running = max(int(_cfg_file.get('max_corrective_market_running', 0)), 0)
    if not _gparams_dict['ac_validate_post_market']:
        max_corrective_market_running = 0
    _gparams_dict['max_corrective_market_running'] = max_corrective_market_running
    _gparams_dict['ac_validation_sensitivity_subfolder'] = str(
        _cfg_file.get(
            'ac_validation_sensitivity_subfolder',
            'ACOperatingPointSensitivity'
        )
    ).strip() or 'ACOperatingPointSensitivity'
    # AC acceptance remains at the configured detection threshold (standard
    # plus tol_i). Revalidation never moves this threshold between iterations.
    _gparams_dict['ac_validation_loading_limit'] = float(
        current_policy['detection_limit_percent']
    )

    _gparams_dict['vbus_max'] = dict()
    _gparams_dict['vbus_min'] = dict()
    _gparams_dict['vbus_max_opt'] = dict()
    _gparams_dict['vbus_min_opt'] = dict()
    for _vl in _vl_tags:
        voltage_policy = tolerance['voltage'][_vl]
        _gparams_dict['vbus_max'][_vl] = voltage_policy['detection_max_pu']
        _gparams_dict['vbus_min'][_vl] = voltage_policy['detection_min_pu']
        # Market constraints receive the
        # explicit tol_v + tol_v_opt band, avoiding compounded percentages.
        _gparams_dict['vbus_max_opt'][_vl] = voltage_policy['optimization_max_pu']
        _gparams_dict['vbus_min_opt'][_vl] = voltage_policy['optimization_min_pu']

    _gparams_dict['tolerance_policy'] = tolerance

    return _gparams_dict
