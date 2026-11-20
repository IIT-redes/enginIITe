import os
import yaml
import pathlib
import warnings
import importlib
import copy as cp
import pandas as pd
import pandapower as pp
import enginiite.auxiliary as aux


def import_yaml(_yaml_filename, _folder, **kwargs):
    """
    This function imports the yaml configuration file.

    Input:
        **_yaml_filename** (string) - Yaml network file input inside the config folder.

        **_folder** (string) - Folder in which the yaml config files are saved.

    Output:
        **_config_file** (dict) - config network file data.

    Example:

    >>> my_config_yaml_file = import_yaml('my_yaml_file.yaml', 'my_folder')

    """

    additional_kwargs = {key: val for key, val in kwargs.items()}

    # utf-8-sig accepts ordinary UTF-8
    # and strips the Windows BOM that otherwise turns the first YAML key into
    # "\ufeffsimulation_tag" and makes valid scenario configurations fail.
    with open(
        os.path.join(os.getcwd(), _folder, _yaml_filename),
        'r',
        encoding='utf-8-sig',
    ) as _filename:
        _config_file = yaml.safe_load(_filename)
    return _config_file


def import_network(_net_data, _in_root='data_in', _folder='network', **kwargs):
    """
    This function imports the electrical network from Excel file according to pandapower format.

    Input:
        **_net_data** (dict) - Dictionary with the network input from Yaml file.

        **_in_root** (string, 'data_in') - Root in which the network file is saved.

        **_folder** (string, 'network') - Folder in which the .xlsx network file is saved.

    Output:
        **net** (attrdict) - Pandapower network.

    Example:

    >>> cfg_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> my_pandapower_network = import_network(cfg_file['network'])

    """
    additional_kwargs = {key: val for key, val in kwargs.items()}
    file_extension = _net_data['net_filename'].split('.')[-1]
    _net_name = _net_data['net_folder']
    _net_filename = _net_data['net_filename']
    _root2network = os.path.join(os.getcwd(), _in_root, _net_name, _folder, _net_filename)
    if file_extension == 'xlsx':
        net = pp.from_excel(_root2network)
    else:
        raise ValueError('The format {0} is not supported.'.format(file_extension))
    return cp.deepcopy(net)


def import_fsp_data(_fsp_data, _in_root='data_in', _folder='fsp_files', **kwargs):
    """
    This function imports the FSP Input Data from Excel file.

    Input:
        **_fsp_data** (dict) - Dictionary with the fsp input from Yaml file.

        **_in_root** (string, 'data_in') - Root in which the fsp files are saved.

        **_folder** (string, 'fsp_files') - Folder in which the .xlsx fsp files are saved.

    Output:
        **fsp_data** (attrdict) - FSP dictionary data.

    Example:

    >>> cfg_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> my_fsp_data = import_fsp_data(cfg_file['network'])
"""
    additional_kwargs = {key: val for key, val in kwargs.items()}
    _net_name = _fsp_data['net_folder']
    _files2read = _fsp_data['fsp']['fsp_input_filename']
    _root2fsps = os.path.join(os.getcwd(), _in_root, _net_name, _folder)
    _sheetname = _fsp_data['fsp']['fsp_sheetname']

    a = {_k: import_data(_filename=_files2read[_k], _root=_root2fsps, _header=1, _sheetname=_sheetname) for _k, _v in _files2read.items()}

    type_values_lists = [set(df["type"].unique()) for df in a.values()]
    if all(type_values_lists[0] == type_values for type_values in type_values_lists):
        type_values = list(type_values_lists[0])
    else:
        raise ValueError("Inconsistent 'type' values found across FSP Files")

    return cp.deepcopy(a), type_values


def read_file_profiles(_root2file, _timestep, **kwargs):
    """
    This function reads the file of profiles for specific time intervals.
    This function allows two file extensions: i) .csv and ii) .xlsx.
    In case of .xlsx, this function requires that the name of the file and the name of the sheet
    that contains the profiles are the same.

    Input:
        **_filename** (string) - Filename to be read.

        **_timestep** (list of integers) - Time intervals to be analysed.

    Output:
        **df_prof** (dict) - Dictionary with the profile values.

    Example:

    >>> import os
    >>> file2read = os.path.join(os.getcwd(), 'my_folder', 'my_profile_file.xlsx')
    >>> my_dictionary_profiles_from_file = read_file_profiles(file2read, [0, 24])

    """
    additional_kwargs = {key: val for key, val in kwargs.items()}
    _file_ext = pathlib.Path(_root2file).suffix
    _file_name = pathlib.Path(_root2file).stem
    if _file_ext == '.xlsx':
        _sheet = pd.ExcelFile(_root2file).sheet_names[0]
        if _sheet != _file_name:
            _mess = 'The sheet of the file Excel must be equal to the name of the file.' \
                    ' Correct the name "{_sheet}".'.format(_sheet=_sheet)
            raise ValueError(_mess)
        df_prof = pd.read_excel(_root2file, sheet_name=_sheet, index_col=0).iloc[range(_timestep[0], _timestep[1])]
    elif _file_ext == '.csv':
        df_prof = pd.read_csv(_root2file, index_col=0).iloc[range(_timestep[0], _timestep[1])]
    else:
        raise ValueError('The extension "{_ext}" is not supported.'.format(_ext=_file_ext))
    return df_prof


def import_norm_profiles(_root2file, _timestep, _res_pp, _product, **kwargs):
    """
    This function imports the normalized profiles of specific resources.

    Input:
        **_root2file** (string) - Path to the file to be read.

        **_timestep** (list of integers) - Time intervals to be analysed.

        **_res_pp** (Dataframe) - Dataframe of the resources to which the normalized profiles are applied.
        The Dataframe must be configured like the resource Dataframe of pandapower network.

        **_product** (string) - Type of market product. It can be 'p' or 'q'.

    Output:
        **df_product** (Dataframe) - Dataframe of the profiles.

    Example:

    >>> import os
    >>> import pandapower.networks
    >>> file2read = os.path.join(os.getcwd(), 'my_folder', 'my_profile_file.xlsx')
    >>> net = pandapower.networks.example_multivoltage()
    >>> my_normalized_dataframe_profile = import_norm_profiles(file2read, [0, 24], net.load, 'p')

    """
    additional_kwargs = {key: val for key, val in kwargs.items()}
    norm_df_prof = read_file_profiles(_root2file=_root2file, _timestep=_timestep, _add_args=additional_kwargs)

    dict_product = dict()
    _cp_res_pp = cp.deepcopy(_res_pp)
    for _res in _cp_res_pp.itertuples():
        _prof_cat = _res.norm_profile
        if _product == 'p':
            dict_product[_res.Index] = norm_df_prof[_prof_cat] * _res.p_mw
        if _product == 'q':
            dict_product[_res.Index] = norm_df_prof[_prof_cat] * _res.q_mvar

    df_product = pd.DataFrame().from_dict(dict_product)
    return df_product


def import_ext_profiles(_root2inputs, _timestep, _res_pp, **kwargs):
    """
    This function imports the profiles from an external module that evaluates the profile according to the user
    preferencies.

    Input:
        **_root2inputs** (string) - Path to the input parameters file to be read.

        **_timestep** (list of integers) - Time intervals to be analysed.

        **_res_pp** (Dataframe) - Dataframe of the resources to which the external module evaluation are applied.
        The Dataframe must be configured like the resource Dataframe of pandapower network.

    Output:
        **res_category_prof_p** (Dataframe) - Dataframe of the Active Power profiles.

        **res_category_prof_q** (Dataframe) - Dataframe of the Reactive Power profiles.

    Example:

    >>> import os
    >>> import pandapower.networks
    >>> file2read = os.path.join(os.getcwd(), 'my_folder', 'my_profile_file.xlsx')
    >>> net = pandapower.networks.example_multivoltage()
    >>> P_dataframe_profile, Q_dataframe_profile = import_ext_profiles(file2read, [0, 24], net.load)

    """
    additional_kwargs = {key: val for key, val in kwargs.items()}
    res_category_prof_p = pd.DataFrame([], columns=_res_pp.index)
    res_category_prof_q = pd.DataFrame([], columns=_res_pp.index)
    dict_res_profiles = aux.res_fcn_profile
    list_names = _res_pp.element_name.unique()
    for res_name in list_names:
        index_res = _res_pp[_res_pp['element_name'] == res_name].index
        element_pp_res = _res_pp.loc[index_res, :].reset_index(inplace=False)
        res_model = dict_res_profiles.get(res_name, None)
        if res_model is None:
            raise IOError('External module of resource named "{_class}" is unknown.'.format(_class=res_name))

        res_lib = importlib.import_module(f'enginiite.market.models.{res_model}')
        res_prof_p, res_prof_q = res_lib.define_profiles(_root2inputs=_root2inputs, _pp_res=element_pp_res, _timestep=_timestep)
        res_category_prof_p[index_res] = res_prof_p
        res_category_prof_q[index_res] = res_prof_q
    return res_category_prof_p, res_category_prof_q


def import_profiles(_pp_net, _net_data, _timestep, _in_root='data_in', _folder_prof='profile', _folder_ext='fsp_files', **kwargs):
    """
    This function imports the network profiles for all the resources included in the network.
    In case a resource category is not present in the network file, this resource category will be skipped.

    Input:
        **_pp_net** (dict) - The pandapower format network.

        **_net_data** (dict) - Dictionary with the network input from Yaml file.

        **_timestep** (list of integers) - Time intervals to be analysed.

        **_in_root** (string, data_in) - Root in which the input files are saved.

        **_folder_prof** (string, profile) - Root in which the input profile files are saved.

        **_folder_ext** (string, fsp_files) - Root in which the input parameters of fsp, and the input parameters for
        the evaluation of the profiles from an external module are saved.

    Output:
        **dict_profiles** (dict) - Dictionary with the profiles.

    Example:

    >>> import pandapower.networks
    >>> net = pandapower.networks.example_multivoltage()
    >>> cfg_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> dictionary_profiles = import_profiles(net, cfg_file['network'], [0, 24], 'data_in', 'profile', 'fsp_files')

    """
    additional_kwargs = {key: val for key, val in kwargs.items()}
    _net_name = _net_data['net_folder']
    _profile_data = _net_data['profile']
    dict_profiles = dict()
    for _res, _v in _profile_data.items():
        if not _pp_net[_res].empty:
            denorm_res = _pp_net[_res][_pp_net[_res]['denorm_profile'].notnull()]
            norm_res = _pp_net[_res][_pp_net[_res]['norm_profile'].notnull()]
            ext_res = _pp_net[_res][_pp_net[_res]['internal_profile'].notnull()]

            for _product, _filename in _v.items():
                _key = _res + '_prof_' + _product
                dict_profiles[_key] = pd.DataFrame()
                if not denorm_res.empty:
                    # Path to the Denormalized Profiles File
                    _root2file = os.path.join(os.getcwd(), _in_root, _net_name, _folder_prof, _filename['denorm'])
                    my_df_prof = read_file_profiles(_root2file=_root2file, _timestep=_timestep,
                                                    _add_args=additional_kwargs)
                    dict_profiles[_key] = pd.concat([dict_profiles[_key], my_df_prof], axis=1)

                if not norm_res.empty:
                    # Path to the Normalized Profiles File
                    _root2file = os.path.join(os.getcwd(), _in_root, _net_name, _folder_prof, _filename['norm'])
                    my_df_prof = import_norm_profiles(_root2file=_root2file, _timestep=_timestep, _res_pp=norm_res,
                                                      _product=_product, _add_args=additional_kwargs)
                    dict_profiles[_key] = pd.concat([dict_profiles[_key], my_df_prof], axis=1)

                # Transform column into integer
                dict_profiles[_key].columns = dict_profiles[_key].columns.astype(int)

            if not ext_res.empty:
                _key = list()
                _list_filename = list()
                for _product, _filename in _v.items():
                    _key.append(_res + '_prof_' + _product)
                    _list_filename.append(_filename['internal'])
                if _list_filename.count(_list_filename[0]) <= 1:
                    # If the input parameters file is different for P and Q raise Error
                    raise UserWarning('The input parameter files for resource "{_res}" are different for all the'
                                      ' products. Please use a unique input parameter files for all the products.'.format(_res=_res))
                # Path to the Input Parameters File for the external definition of profiles
                _root2file = os.path.join(os.getcwd(), _in_root, _net_name, _folder_ext, _list_filename[0])
                my_df_prof_p, my_df_prof_q = import_ext_profiles(_root2inputs=_root2file, _timestep=_timestep, _res_pp=ext_res)
                for _k in _key:
                    if _k.split('_')[-1] == 'p':
                        dict_profiles[_k] = pd.concat([dict_profiles[_k], my_df_prof_p], axis=1)
                    elif _k.split('_')[-1] == 'q':
                        dict_profiles[_k] = pd.concat([dict_profiles[_k], my_df_prof_q], axis=1)
                    else:
                        raise UserWarning('Product name "{_prod}" not known.'.format(_prod=_k.split('_')[-1]))

                    # Transform column into integer
                    dict_profiles[_k].columns = dict_profiles[_k].columns.astype(int)
        else:
            warnings.warn('The resource category {_res_cat} is skipped since '
                          'it is not included in the network file.'.format(_res_cat=_res))

    return dict_profiles


def import_profiles_s01(_cfg_file, _pp_net, _timestep, _in_root='data_in', _folder='profile', **kwargs):
    """
    This function imports the network profiles for the initial scenario for all the resources categories included
    in the network. The resource categories are: 1) load, 2) gen, 3) sgen and 4) storage. It is important to point out
    that in the config file, the scenario factors for each category included in the network must be defined.
    The scenario factors are: 1) scen_factor_load, 2) scen_factor_gen, 3) scen_factor_sgen and 4) scen_factor_storage.

    Input:
        **_cfg_file** (dict) - Dictionary with the network input from Yaml file.

        **_pp_net** (dict) - The pandapower format network.

        **_timestep** (list of integers) - Time intervals to be analysed.

        **_in_root** (string, data_in) - Root in which the input files are saved.

        **_folder** (string, profile) - Folder in which the xlsx network files are saved.

    Output:
        **dict_profiles_s01** (dict) - Dictionary with the profile values.

    Example:

    >>> import pandapower.networks
    >>> net = pandapower.networks.example_multivoltage()
    >>> cfg_file = import_yaml('my_yaml_file.yaml', 'my_folder')
    >>> dictionary_profiles_scenario01 = import_profiles_s01(cfg_file['network'], net, [0, 24], 'data_in', 'profile')

    """
    additional_kwargs = {key: val for key, val in kwargs.items()}
    dict_profiles = import_profiles(_pp_net=_pp_net, _net_data=_cfg_file['network'], _timestep=_timestep,
                                    _in_root=_in_root, _folder=_folder, _add_args=additional_kwargs)

    dict_profiles_s01 = cp.deepcopy(dict_profiles)
    for _key, _value in dict_profiles_s01.items():
        try:
            if 'load' in _key:
                dict_profiles_s01[_key] = _value * _cfg_file['scen_factor_load']
            elif 'sgen' in _key:
                dict_profiles_s01[_key] = _value * _cfg_file['scen_factor_sgen']
            elif 'gen' in _key:
                dict_profiles_s01[_key] = _value * _cfg_file['scen_factor_gen']
            elif 'storage' in _key:
                dict_profiles_s01[_key] = _value * _cfg_file['scen_factor_storage']
        except Exception as _:
            raise UserWarning('{_res} profiles or scenario factor not found.'.format(_res=_key))
    return dict_profiles_s01


def import_ext_grid_profile(_cfg_file, _pp_net, _timestep, _in_root='data_in', _folder_prof='profile'):
    """
    Optional supply-voltage profile of the external grid.

    The upstream (110 kV) voltage is part of each operating background (the HV/MV transformer tap is fixed), so
    a package may give one ext_grid voltage set-point per time step.  The file named by
    cfg['network']['ext_grid_profile'] lives in the profile folder, has the same layout as the other profile
    files (sheet named like the file stem, index = time step, one column per ext_grid index) and holds vm_pu
    values (absolute, not multipliers).  Without the key the network-file set-point is used at every step.

    Output:
        **DataFrame** (rows = time steps, columns = ext_grid index) or None.
    """
    _filename = _cfg_file['network'].get('ext_grid_profile')
    if not _filename:
        return None
    _root2file = os.path.join(os.getcwd(), _in_root, _cfg_file['network']['net_folder'], _folder_prof, _filename)
    _df = read_file_profiles(_root2file=_root2file, _timestep=_timestep, _add_args={})
    _df.columns = _df.columns.astype(int)
    _unknown = [c for c in _df.columns if c not in _pp_net.ext_grid.index]
    if _unknown:
        raise UserWarning('ext_grid profile columns {c} are not ext_grid indices of the network.'.format(c=_unknown))
    if ((_df < 0.8) | (_df > 1.2)).any().any():
        raise UserWarning('ext_grid profile must hold voltage set-points in pu (0.8-1.2).')
    return _df


def import_data(_filename, _root, _sheetname=None, _index_col=None, _header=0):
    """
    This function imports the data from file passed as input.
    Two extension of files are available: i) .csv and ii) .xlsx.

    Input:
        **_filename** (string) - Name of the file to import (format .csv or .xlsx).

        **_root** (string) - Full directory in which the file is saved.

        **_sheetname** (string, None) - If .xlsx extension is selected, it represents the name of the sheet in which
        the information are saved (only xlsx file).

        **_index_col** (int, None) - Column(s) to use as row label(s), denoted either by column labels or column indices.

        **_header** (int, 0) - Row number(s) containing column labels and marking the start of the data.

    Output:
        **_tmp_data** (Dataframe) - Dataframe with the information contained in the file passed.

    Example:

    >>> import os
    >>> my_root = os.path.join(os.getcwd(), 'my_folder')
    >>> my_dataframe_data = import_data('my_file.xlsx', my_root, 'my_sheet', 0, 0)

    """
    if _filename is None:
        raise ValueError('No filename have been passed.')
    if _root is None:
        raise ValueError('No root to filename have been passed.')

    _tmp_data = None
    _ext = pathlib.Path(_filename).suffix
    if _ext == '.csv':
        _tmp_data = pd.read_csv(os.path.join(_root, _filename), index_col=_index_col, header=_header)
    elif _ext == '.xlsx':
        _tmp_data = pd.read_excel(os.path.join(_root, _filename), index_col=_index_col, header=_header, sheet_name=_sheetname)
    return _tmp_data


def save_excel(_data, _outroot, _filename, _sheetname, _mode='w', _extension='.xlsx'):
    """
    This function saves results into Excel files.

    Input:
        **_data** (Dataframe) - Dataframe to be saved.

        **_outroot** (string) - Output path to folder where to save input dataframe.

        **_filename** (string) - Name of the Excel file to be saved.

        **_sheetname** (string) - Name od the sheet of the Excel file to be saved.

        **_mode** (string, w) - File mode to use (write: 'w' or append: 'a').

        **_extension** (string, .xlsx) - Extension of the Excel file.

    Example:

    >>> import pandas as pd
    >>> my_empty_dataframe = pd.DataFrame()
    >>> save_excel(my_empty_dataframe, 'my_path_to_folder', 'my_filename', 'my_sheetname', 'w', '.xlsx')

    """
    if not isinstance(_data, pd.DataFrame):
        raise ValueError('Format type {0} not supported.'.format(str(type(_data))))
    root2file = os.path.join(_outroot, _filename + _extension)
    if _mode != 'a':
        with pd.ExcelWriter(root2file, engine='openpyxl', mode=_mode) as writer:
            _data.to_excel(writer, sheet_name=_sheetname)
    else:
        with pd.ExcelWriter(root2file, engine='openpyxl', mode=_mode, if_sheet_exists='replace') as writer:
            _data.to_excel(writer, sheet_name=_sheetname)
    return True


def save_cvs(_data, _outroot, _filename, _extension='.csv'):
    """
    This function saves results into Comma Separated Values files.

    Input:
        **_data** (Dataframe) - Dataframe to be saved.

        **_outroot** (string) - Output path to folder where to save input dataframe.

        **_filename** (string) - Name of the Excel file to be saved.

        **_extension** (string, .csv) - Extension of the CSV file.

    Example:

    >>> import pandas as pd
    >>> my_empty_dataframe = pd.DataFrame()
    >>> save_cvs(my_empty_dataframe, 'my_path_to_folder', 'my_filename', '.csv')

    """
    if not isinstance(_data, pd.DataFrame):
        raise ValueError('Format type {0} not supported.'.format(str(type(_data))))
    root2file = os.path.join(_outroot, _filename + _extension)
    _data.to_csv(root2file, encoding='utf-8')
    return True
