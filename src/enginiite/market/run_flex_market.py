import os
import importlib

import numpy as np
import pandas as pd
import gurobipy as gp
from gurobipy import GRB, tuplelist
from tqdm.auto import tqdm
from enginiite import auxiliary as aux
from enginiite import file_io as io_file
from enginiite.market import solver_status
from enginiite.market.models import flex_general_model as flx_gen


def _diagnostic(_m):
    """
    Check the model diagnostics.

    :param _m: Model representation by Gurobi.py.
    """
    d = solver_status.status_names()
    status = _m.status
    if status == GRB.UNBOUNDED:
        print(_m.UnbdRay)
        raise Warning('The model cannot be solved because it is unbounded.')
    elif status == GRB.OPTIMAL:
        print('\nThe optimal objective is %g' % _m.ObjVal)
        print('------------------------------------------------------------------------\n')
    elif status == GRB.INF_OR_UNBD:
        # In order to determine if the model is infeasible or unbounded, set the "DualReductions" parameter to 0,
        # call "reset" on the model, and optimize once again.
        _m.Params.DualReductions = 0
        _m.reset()
        _m.Params.InfUnbdInfo = 1
        _m.optimize()
        _diagnostic(_m)
    elif status == GRB.INFEASIBLE:
        print('\nOptimization was stopped with status: ', d[status])
        _m.computeIIS()
        if _m.IISMinimal:
            print('IIS is minimal\n')
        else:
            print('IIS is not minimal\n')
        print('\nThe following constraint(s) cannot be satisfied:')
        for c in _m.getConstrs():
            if c.IISConstr:
                print('%s' % c.ConstrName)
        raise Warning('The model cannot be solved because it is infeasible.')
    elif status == GRB.NUMERIC:
        raise Warning('Optimization was stopped with status: {_stat}'.format(_stat=d[status]))
    # A solve stopped by the optional
    # time_limit keeps its best feasible solution; say so, with the gap reached.
    elif status == GRB.TIME_LIMIT:
        if _m.SolCount == 0:
            raise Warning('The time limit was reached before any feasible solution was found.')
        print('\nTime limit reached: objective %g, optimality gap %.4f %%' % (_m.ObjVal, 100.0 * _m.MIPGap))
    return True

# A corrective market is priced incrementally: every iteration prices its own correction of the residual at the
# FSPs' offers.  The sequence is settled as one market: ac_market_validation.merge_sequential_market_results pays
# the final net position of every FSP.


def _upload_res_params(_fsp_file, _in_root, _sim_period):
    """
    Upload resource parameters from resource models.
    :param _fsp_file: Dictionary of the names of the fsp filex per resource category.
    :param _in_root: Input root for reading fspInfo file.
    :param _sim_period: Number of hours to simulate. Example: hours2study: [5, 11] -> _sim_period: [0, 1]
    """

    # Dictionary of the model library of the fsp resource
    _fsp_lib = aux.res_fcn

    # Dictionary where to save the resource parameters per category
    res_parameters = {_k: dict() for _k in _fsp_file.keys()}
    for _key, _value in tqdm(_fsp_file.items(), desc='Loading Flexibility Service Provider Data'):
        if _value is None:
            raise ValueError('No FSP Type {type} file have been passed.'.format(type=_key))

        # Even when there are no resource of type "_key", put at least one resource with everything as zero.
        res_parameters[_key]['n_fsp'] = 1
        res_parameters[_key]['contrib'] = 0

        n_fsp = 0
        fsp_data = None
        fsp_index = pd.RangeIndex(1)
        if _value != 0:
            fsp_data = io_file.import_data(_filename=_value + '.xlsx', _root=_in_root, _index_col=0)
            n_fsp = fsp_data['FSPinfo_' + _key].bus.to_numpy().shape[0]
            fsp_index = fsp_data['FSPinfo_' + _key].index

        if n_fsp > 0:
            res_parameters[_key]['n_fsp'] = n_fsp
            res_parameters[_key]['contrib'] = 1

        res_lib = importlib.import_module(f'enginiite.market.models.{_fsp_lib[_key]}')
        res_parameters[_key]['data'], res_parameters[_key]['conv'] = res_lib.res_params(_n_fsp=n_fsp, _sim_period=_sim_period, _fsp_data=fsp_data, _type=_key)
        res_parameters[_key]['fsp_index'] = fsp_index
    return res_parameters



def _parse_market_tag(_mrk_tag):
    """Return (market_model, product) from a simulation tag.

    The old code assumed tags had the form <network>_<model>_<product>_...,
    so it used split('_')[1] and split('_')[2]. That breaks when the network
    name itself contains underscores, e.g. netS02_BF_CM_P_...; split('_')[1]
    becomes BF instead of CM.

    We now search the tokens for the first valid market model and take the
    following token as the product. This supports network names with
    underscores, such as net_name_CMVC_P_...
    """
    valid_models = {'CM', 'VC', 'CMVC', 'VCCM'}
    valid_products = {'P', 'Q', 'PQ'}
    parts = [str(x).strip() for x in str(_mrk_tag).split('_') if str(x).strip()]
    for i, token in enumerate(parts):
        if token in valid_models:
            if i + 1 >= len(parts) or parts[i + 1] not in valid_products:
                raise ValueError(
                    'Cannot parse product from market tag "{tag}". Expected one of {products} after model token "{model}".'
                    .format(tag=_mrk_tag, products=sorted(valid_products), model=token)
                )
            return token, parts[i + 1]
    raise ValueError(
        'Cannot parse market model from market tag "{tag}". Expected one of {models}. '
        'Avoid relying on fixed underscore positions because network names may contain underscores.'
        .format(tag=_mrk_tag, models=sorted(valid_models))
    )


def _load_sens_matrix(_res_parameters, _hours2study, _n_cong, _n_pilot_bus, _matrix_root, _mrk_scenario, _product,
                      _sim_tag, _cm_factor=-1):
    """
    Upload Sensitivity Matrix from file.

    :param _res_parameters: Dictionary of the parameters of the fsp per resource category.

    :param _hours2study: List of hours to study.

    :param _n_cong: Number of congestions.

    :param _n_pilot_bus: Number of pilot buses.

    :param _matrix_root: Root to where the sensitivity matrix file are saved.

    :param _mrk_scenario: String that represents the tag for market model.

    :param _product: String that represents the tag for product in the market.

    :param _sim_tag: String that represents the specific name of the simulation.

    :param _cm_factor: Congestion Management Factor that change sign to the sensitivity matrix.
    """
    sens_matrix_cm = {_k: dict() for _k in _res_parameters.keys()}
    sens_matrix_vc = {_k: dict() for _k in _res_parameters.keys()}
    sens_matrix_vc['all'] = pd.DataFrame()
    _message = 'Loading Sensitivity Matrix for "{_model}" Market Model'.format(_model=_mrk_scenario)
    for _h in tqdm(_hours2study, desc=_message):
        t_th = str(_h).zfill(2)
        for _cat in _res_parameters.keys():
            if _mrk_scenario == 'CM':
                sens_matrix_cm[_cat][_h] = dict()
                shape_zeros_matrix = _n_cong
                w_name_tags = ['HCMdSdP_FSP' + _cat, 'h' + t_th, _sim_tag]
                r_name_tags = ['HCMdSdQ_FSP' + _cat, 'h' + t_th, _sim_tag]
                Wfile2read = '_'.join(filter(None, w_name_tags)) + '.csv'
                Rfile2read = '_'.join(filter(None, r_name_tags)) + '.csv'

                if _res_parameters[_cat]['contrib'] > 0:
                    # P-only products
                    # retain HCMdSdQ because constant-power-factor loads have
                    # nonzero DR when their active power changes.
                    sens_matrix_cm[_cat][_h]['W'] = _cm_factor * io_file.import_data(_filename=Wfile2read,
                                                                                     _root=_matrix_root,
                                                                                     _index_col=0)
                    sens_matrix_cm[_cat][_h]['R'] = _cm_factor * io_file.import_data(_filename=Rfile2read,
                                                                                     _root=_matrix_root,
                                                                                     _index_col=0)
                else:
                    sens_matrix_cm[_cat][_h]['W'] = pd.DataFrame(np.zeros(shape_zeros_matrix))
                    sens_matrix_cm[_cat][_h]['R'] = pd.DataFrame(np.zeros(shape_zeros_matrix))
            elif _mrk_scenario == 'VC':
                sens_matrix_vc[_cat][_h] = dict()
                # Upload all the remaining Sensitivity matrix
                shape_zeros_matrix = _n_pilot_bus
                w_name_tags_vc = ['HVMP_FSP' + _cat, 'h' + t_th, _sim_tag]
                r_name_tags_vc = ['HVMQ_FSP' + _cat, 'h' + t_th, _sim_tag]
                Wfile2read = '_'.join(filter(None, w_name_tags_vc)) + '.csv'
                Rfile2read = '_'.join(filter(None, r_name_tags_vc)) + '.csv'

                if _res_parameters[_cat]['contrib'] > 0:
                    # P-only voltage
                    # constraints include HVMQ times the linked load DR value.
                    sens_matrix_vc[_cat][_h]['W'] = io_file.import_data(_filename=Wfile2read, _root=_matrix_root,
                                                                        _index_col=0)
                    sens_matrix_vc[_cat][_h]['R'] = io_file.import_data(_filename=Rfile2read, _root=_matrix_root,
                                                                        _index_col=0)
                else:
                    sens_matrix_vc[_cat][_h]['W'] = pd.DataFrame(np.zeros(shape_zeros_matrix))
                    sens_matrix_vc[_cat][_h]['R'] = pd.DataFrame(np.zeros(shape_zeros_matrix))
            elif _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
                sens_matrix_cm[_cat][_h] = dict()
                sens_matrix_vc[_cat][_h] = dict()
                # Upload all the remaining Sensitivity matrix
                shape_zeros_matrix_cm = _n_cong
                shape_zeros_matrix_vc = _n_pilot_bus
                w_name_tags = ['HCMdSdP_FSP' + _cat, 'h' + t_th, _sim_tag]
                r_name_tags = ['HCMdSdQ_FSP' + _cat, 'h' + t_th, _sim_tag]
                Wfile2read_cm = '_'.join(filter(None, w_name_tags)) + '.csv'
                Rfile2read_cm = '_'.join(filter(None, r_name_tags)) + '.csv'
                w_name_tags_vc = ['HVMP_FSP' + _cat, 'h' + t_th, _sim_tag]
                r_name_tags_vc = ['HVMQ_FSP' + _cat, 'h' + t_th, _sim_tag]
                Wfile2read_vc = '_'.join(filter(None, w_name_tags_vc)) + '.csv'
                Rfile2read_vc = '_'.join(filter(None, r_name_tags_vc)) + '.csv'

                if _res_parameters[_cat]['contrib'] > 0:
                    # Combined CMVC
                    # models always load both physical P and Q sensitivities;
                    # inactive product variables remain zero by their bounds.
                    sens_matrix_cm[_cat][_h]['W'] = _cm_factor * io_file.import_data(_filename=Wfile2read_cm,
                                                                                     _root=_matrix_root,
                                                                                     _index_col=0)
                    sens_matrix_cm[_cat][_h]['R'] = _cm_factor * io_file.import_data(_filename=Rfile2read_cm,
                                                                                     _root=_matrix_root,
                                                                                     _index_col=0)
                    sens_matrix_vc[_cat][_h]['W'] = io_file.import_data(_filename=Wfile2read_vc, _root=_matrix_root,
                                                                        _index_col=0)
                    sens_matrix_vc[_cat][_h]['R'] = io_file.import_data(_filename=Rfile2read_vc, _root=_matrix_root,
                                                                        _index_col=0)
                else:
                    sens_matrix_cm[_cat][_h]['W'] = pd.DataFrame(np.zeros(shape_zeros_matrix_cm))
                    sens_matrix_cm[_cat][_h]['R'] = pd.DataFrame(np.zeros(shape_zeros_matrix_cm))
                    sens_matrix_vc[_cat][_h]['W'] = pd.DataFrame(np.zeros(shape_zeros_matrix_vc))
                    sens_matrix_vc[_cat][_h]['R'] = pd.DataFrame(np.zeros(shape_zeros_matrix_vc))
            else:
                raise ValueError('The Market Model "{model}" do not exist.'.format(model=_mrk_scenario))
        if _mrk_scenario == 'VC' or _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
            # Upload Sensitivity Matrix that contains all
            pii_name_tags = ['HVMPii', 'h' + t_th, _sim_tag]
            file2read = '_'.join(filter(None, pii_name_tags)) + '.csv'
            HVPii_h = io_file.import_data(_filename=file2read, _root=_matrix_root, _index_col=0)
            sens_matrix_vc['all'] = pd.concat([sens_matrix_vc['all'], HVPii_h], axis=1)

    if _mrk_scenario == 'VC' or _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
        # Update columns with hours to study
        sens_matrix_vc['all'].columns = _hours2study
    return sens_matrix_cm, sens_matrix_vc


def _var_indexing(_grb_model, _res_parameters, _n_pb, _n_assets, _n_t):
    """
    Define variables and save them into dictionary shared across multiple methods of the class.
    :param _grb_model: Gurobipy model.
    :param _res_parameters: Dictionary of all resource parameters
    :param _n_pb: Number of Pilot Buses.
    :param _n_assets: Number of network lines.
    :param _n_t: Number of hours to study.
    """
    # Dictionary where to save the variables
    variables = dict()

    # General Variables
    _vars, list_general_vars = flx_gen.general_variables(_grb_model, _n_pb, _n_assets, _n_t)
    variables.update(_vars)

    # Dictionary of the model library of the fsp resource
    _fsp_lib = aux.res_fcn

    for _key in tqdm(_res_parameters.keys(), desc='Loading Flexibility Service Provider Variables'):
        res_contr = _res_parameters[_key]['contrib'] * GRB.INFINITY
        n_fsp = _res_parameters[_key]['n_fsp']

        res_lib = importlib.import_module(f'enginiite.market.models.{_fsp_lib[_key]}')
        variable_dict = res_lib.define_variables(_grb_model=_grb_model, _n_fsp=n_fsp, _n_t=_n_t, _contr=res_contr, _type=_key)
        variables[_key] = variable_dict
    return variables, list_general_vars


def _resolve_voltage_optimization_limits(_vmin, _vmax, _dv_tol_opt, _vmin_opt=None, _vmax_opt=None):
    """Return the explicit canonical optimization limits supplied by the caller."""
    # The market must not reconstruct or
    # compound optimization tolerances from the detection band.
    if _vmin_opt is None or _vmax_opt is None:
        raise ValueError(
            'Explicit _vmin_opt and _vmax_opt are required; calculate them from '
            'the scenario standard limits and tol_v + tol_v_opt.'
        )
    vmin_opt = float(_vmin_opt)
    vmax_opt = float(_vmax_opt)
    if vmin_opt > vmax_opt:
        raise ValueError(
            'Invalid voltage optimization band: minimum {vmin} exceeds maximum {vmax}.'
            .format(vmin=vmin_opt, vmax=vmax_opt)
        )
    return vmin_opt, vmax_opt


def _hour_column(_frame, _hour, _local_t):
    """
    Column position of hour _hour in a per-hour market input
    (s_init, ds_tol, cong_needs: rows = assets, columns = studied hours).  The label is matched as int, str or
    number; a table without hour labels falls back to the local position _local_t of the hour in the split.
    """
    if _frame is None or not hasattr(_frame, 'columns'):
        return _local_t
    cols = list(_frame.columns)
    for key in (_hour, str(_hour)):
        if key in cols:
            return cols.index(key)
    numeric = pd.to_numeric(pd.Index(cols), errors='coerce')
    hit = np.where(numeric == float(_hour))[0]
    if len(hit):
        return int(hit[0])
    return _local_t


def _cons_indexing(_grb_model, _vars, _res_parameters, _sens_matrix_cm, _sens_matrix_vc, _hours, _hours_vc, _hours_cm,
                   _s_init, _s_max, _ds_tol, _cong_needs, _cong_assets, _pilot_bus, _v_before, _vmin, _vmax, _dv_tol_opt,
                   _outbounds_bus, _mrk_scenario, _net_mrk, _cap_cstr, _int_soc, _dt, _vmin_opt=None, _vmax_opt=None,
                   _assets_by_hour=None, _buses_by_hour=None):
    """
    Define constraints of the Local Flexibility Market.
    :param _grb_model: Gurobu py model.
    :param _vars: Dictionary of the variables of the model.
    :param _res_parameters: Dictionary of the resource parameters.
    :param _sens_matrix_cm: Sensitivity Coefficient matrix for congestion management.
    :param _sens_matrix_vc: Sensitivity Coefficient matrix for voltage control.
    :param _hours: List of hours to study.
    :param _pilot_bus: List of Pilot buses.
    :param _v_before: Dataframe of the oltage before the market clearing.
    :param _vmin: Minimum Voltage in p.u.
    :param _vmax: Maximum Voltage in p.u.
    :param _dv_tol_opt: Delta Voltage tolerance for the optimisation.
    :param _mrk_scenario: String representing the market scenario
    :param _net_mrk: Boolean value for including network constraints in the market model.
    :param _cap_cstr: Boolean value for including resource capability constraints in the market model.
    :param _int_soc: Boolean value for including battery inter-temporal constraints in the market model.
    :param _dt: Delta time of the model.
    :param _assets_by_hour: {hour: asset names} of the branches each
        independent scenario monitors.  None (one scenario over consecutive time steps) constrains every represented
        branch in every hour, as before.
    :param _buses_by_hour: {hour: bus indices} that carry the voltage
        band of each independent scenario.  None keeps the band on every pilot bus.
    """
    # General Constraints of the Flexibility Market
    beta = _vars['beta']
    va = _vars['VA']
    alpha_dV = _vars['alpha_DVpu']
    alpha_primo = _vars['alpha_primo']

    vb = _v_before

    # Use the explicit voltage band based
    # on tol_v + tol_v_opt instead of compounding tol_v_opt onto detection limits.
    vmin_optimization, vmax_optimization = _resolve_voltage_optimization_limits(
        _vmin, _vmax, _dv_tol_opt, _vmin_opt, _vmax_opt
    )

    flx_gen.general_constraints(_grb_model=_grb_model, _vars_dict=_vars)

    # Dictionary of the model library of the fsp resource
    _fsp_lib = aux.res_fcn

    n_t = len(_hours)
    # Specific Constraints for Resource Model
    for _key in tqdm(_res_parameters.keys(), desc='Loading Flexibility Service Provider Constraints'):
        res_contr = _res_parameters[_key]['contrib']
        n_fsp = _res_parameters[_key]['n_fsp']
        if res_contr > 0:
            # Check if the resource is available in the network.
            # If not, do not create constraints.
            for t in range(n_t):
                for i in range(n_fsp):
                    res_lib = importlib.import_module(f'enginiite.market.models.{_fsp_lib[_key]}')
                    res_lib.define_constraints(_grb_model=_grb_model, _vars_dict=_vars[_key], _idx_res=i, _interval=t,
                                               _fsp_data=_res_parameters[_key]['data'], _cap_cstr=_cap_cstr, _dt=_dt,
                                               _int_soc=_int_soc, _type=_key)

    # Network Constraints
    # NOTE: .iloc[a, b] acccess the dataframe knowing that a -> row and b -> column.

    # TODO: check that this section of the code works for the Aggregator case.
    #  The Aggregator is considered as a single entity but it can be composed by multiple buses.
    #  Will it work anyway?

    t_aux = 0
    for _t in _hours:
        # _s_init, _ds_tol and _cong_needs hold EVERY studied
        # hour (columns labelled by hour) while t_aux restarts at 0 in every split of consecutive_hours.  Read
        # them by the hour label; the position t_aux is kept only for a table without hour labels, so every
        # split of consecutive_hours reads the loading and need of its own hours.
        _c_si = _hour_column(_s_init, _t, t_aux)
        _c_ds = _hour_column(_ds_tol, _t, t_aux)
        _c_cn = _hour_column(_cong_needs, _t, t_aux)
        # ------------ Constraints Congestion Management ------------
        if 'CM' in _mrk_scenario:
            for _pos, _idx in enumerate(_s_max.index):
                # With independent scenarios a scenario constrains
                # only the branches IT monitors (outside the operational limits in that scenario, plus those its
                # own corrective iterations add).  The represented set is the union over all scenarios, so without
                # this a branch overloaded in one scenario was also held to the optimisation target in every other
                # scenario.  C#08a and C#08b themselves are unchanged.
                if _assets_by_hour is not None and str(_idx) not in _assets_by_hour.get(_t, ()):
                    continue
                if _net_mrk:
                    # Market with sensitivity factors
                    k_market = gp.quicksum(
                        # In a corrective iteration H is evaluated at the new AC operating point and the FSP
                        # files are rebased there, so H acts directly on the activation of this iteration.
                        gp.quicksum((_sens_matrix_cm[_key][_t]['W'].iloc[x, _pos]
                                     * _vars[_key]['DW_' + _key][x, t_aux])
                                    + (_sens_matrix_cm[_key][_t]['R'].iloc[x, _pos]
                                       * _vars[_key]['DR_' + _key][x, t_aux])
                                    for x in range(_res_parameters[_key]['n_fsp']))
                        for _key in _res_parameters.keys())
                else:
                    # Market without sensitivity factors
                    _coeff_k = 1
                    k_market = gp.quicksum(
                        gp.quicksum(
                            (_coeff_k * _vars[_key]['DW_' + _key][x, t_aux]) + (_coeff_k * _vars[_key]['DR_' + _key][x, t_aux])
                            for x in range(_res_parameters[_key]['n_fsp']))
                        for _key in _res_parameters.keys())

                if _idx not in _cong_assets:
                    # Not Congested Assets
                    _name_eq_beta_zero = 'C#08c_Zerobeta_l' + str(_pos) + '_t' + str(_t)

                    _name_eq = 'C#08a_Smax_l' + str(_pos) + '_t' + str(_t)   # - beta[_pos, t_aux] is added below
                    _grb_model.addConstr(_s_init.iloc[_pos, _c_si] - k_market - beta[_pos, t_aux]<= _s_max.iloc[_pos, 0] - _ds_tol.iloc[_pos, _c_ds], name=_name_eq)
                else:
                    # Congested Assets
                    if _t in _hours_cm:
                        _name_eq = 'C#08a_Smax_l' + str(_pos) + '_t' + str(_t)
                        _grb_model.addConstr(_s_init.iloc[_pos, _c_si] - k_market - beta[_pos, t_aux] <= _s_max.iloc[_pos, 0] - _ds_tol.iloc[_pos, _c_ds], name=_name_eq)

                        _name_cong = 'C#08b_CM_l' + str(_pos) + '_t' + str(_t)
                        _grb_model.addConstr(_cong_needs.iloc[_pos, _c_cn] - k_market - beta[_pos, t_aux] <= 0, name=_name_cong)
                    else:
                        _name_eq = 'C#08a_Smax_l' + str(_pos) + '_t' + str(_t)  # - beta[_pos, t_aux] added
                        _grb_model.addConstr(_s_init.iloc[_pos, _c_si] - k_market - beta[_pos, t_aux]<= _s_max.iloc[_pos, 0] - _ds_tol.iloc[_pos, _c_ds], name=_name_eq)

        # ------------ Constraints Voltage Control ------------
        if 'VC' in _mrk_scenario:
            for _l in range(len(_pilot_bus)):
                if _net_mrk:
                    # Market with sensitivity factors
                    k_market = gp.quicksum(
                        gp.quicksum(
                            (_sens_matrix_vc[_key][_t]['W'].iloc[x, _l]
                             * _vars[_key]['DW_' + _key][x, t_aux])
                            + (_sens_matrix_vc[_key][_t]['R'].iloc[x, _l]
                               * _vars[_key]['DR_' + _key][x, t_aux])
                            for x in range(_res_parameters[_key]['n_fsp']))
                        for _key in _res_parameters.keys())
                else:
                    # Market without sensitivity factors
                    _coeff_k = 1
                    k_market = gp.quicksum(
                        gp.quicksum(
                            (_coeff_k * _vars[_key]['DW_' + _key][x, t_aux]) + (_coeff_k * _vars[_key]['DR_' + _key][x, t_aux])
                            for x in range(_res_parameters[_key]['n_fsp']))
                        for _key in _res_parameters.keys())
                # Create Constraints
                # With independent scenarios the optimisation band
                # (C#02) holds only at the buses the scenario monitors (its FSP buses and its own buses outside the
                # operational limits).  The voltage equations C#01 and C#Alpha_primo are unchanged and still written
                # for every pilot bus, so VA stays the linear prediction everywhere.
                if _buses_by_hour is None or int(_pilot_bus[_l]) in _buses_by_hour.get(_t, ()):
                    _name_cong = 'C#02a_Vmax_Bus_n' + str(_l) + '_t' + str(t_aux)
                    _grb_model.addConstr(va[_l, t_aux] - vmin_optimization >= 0, name=_name_cong)
                    _name_cong = 'C#02b_Vmin_Bus_n' + str(_l) + '_t' + str(t_aux)
                    _grb_model.addConstr(va[_l, t_aux] - vmax_optimization <= 0, name=_name_cong)

                vm_value = vb.loc[_t, _pilot_bus[_l]]
                # Ensure scalar indexing
                if isinstance(vm_value, pd.Series):
                    # Take the first index if multiple values. This means that more fsp are on the same bus.
                    # But being on the same bus means having the same Voltage.
                    # Therefore, taking the first do not lead to different results.
                    vm_value = vb.loc[_t, _pilot_bus[_l]].iloc[0]

                if vm_value > _vmax:
                    _name_cong = 'C#01_VMAX_Bus_n' + str(_l) + '_t' + str(t_aux)
                    _grb_model.addConstr(va[_l, t_aux] - vm_value - alpha_dV[_l, t_aux] - k_market >= 0, name=_name_cong)
                elif vm_value < _vmin:
                    _name_cong = 'C#01_VMIN_Bus_n' + str(_l) + '_t' + str(t_aux)
                    _grb_model.addConstr(va[_l, t_aux] - vm_value - alpha_dV[_l, t_aux] - k_market <= 0, name=_name_cong)
                else:
                    _name_cong = 'C#01_V_Bus_n' + str(_l) + '_t' + str(t_aux)
                    _grb_model.addConstr(va[_l, t_aux] - vm_value - alpha_dV[_l, t_aux] - k_market == 0, name=_name_cong)

                _name_cong = 'C#Alpha_primo_n' + str(_l) + '_t' + str(t_aux)
                h_ii = _sens_matrix_vc['all'].iloc[_l, t_aux]
                # Avoid NaN / Inf in Gurobi when the diagonal voltage sensitivity is zero,
                # extremely small, or missing.
                if pd.isna(h_ii) or (not np.isfinite(h_ii)) or abs(h_ii) < 1e-9:
                    print(
                        'WARNING: invalid or near-zero HVMPii value in alpha_primo constraint. '
                        'Using alpha_primo = alpha_DVpu instead. '
                        f'pilot_bus_index={_l}, local_t={t_aux}, hour={_t}, h_ii={h_ii}'
                    )
                    _grb_model.addConstr(
                        alpha_primo[_l, t_aux] == alpha_dV[_l, t_aux],
                        name=_name_cong
                    )
                else:
                    _grb_model.addConstr(
                        alpha_primo[_l, t_aux] == alpha_dV[_l, t_aux] / h_ii,
                        name=_name_cong
                    )  # to this line is for avoiding devision by sero in sensitivity
        if 'CM' not in _mrk_scenario and 'VC' not in _mrk_scenario:
            raise ValueError('The Market Model "{model}" do not exist.'.format(model=_mrk_scenario))
        t_aux += 1
    return _grb_model


def _obj_indexing(_grb_model, _vars, _res_parameters, _alpha_cost, _beta_cost, _sens_matrix_vc, _n_pb, _n_assets,
                  _n_t, _mrk_scenario, _net_mrk):
    """
    Define Objective of the Local Flexibility Market.
    :param _grb_model: Gurobi py model.
    :param _vars: Dictionary of the variables of the model.
    :param _res_parameters: Dictionary of the resource parameters.
    :param _alpha_cost: Cost of Voltage Control Slack Variables.
    :param _beta_cost: Cost of Congestion Management Slack Variables.
    :param _sens_matrix_vc: Sensitivity Coefficient matrix for voltage control.
    :param _n_t: Number of hours to study.
    :param _n_cm: Number of the congestions.
    :param _n_pb: Number of Pilot buses.
    :param _mrk_scenario: String representing the market scenario
    :param _net_mrk: Boolean value for including network constraints in the market model.
    """
    obj_fcn = dict()

    if 'CM' in _mrk_scenario:
        # Beta Slack Variable - Objective Function Cost
        ABS_beta = _vars['ABS_beta']
        obj_fcn_beta = gp.quicksum(
            gp.quicksum(
                ABS_beta[_l, t] * _beta_cost
                for _l in range(_n_assets))
            for t in range(_n_t))
        obj_fcn['beta'] = obj_fcn_beta

    if 'VC' in _mrk_scenario:
        # Alpha Slack Variable - Objective Function Cost
        ABS_alpha_primo = _vars['ABS_alpha_primo']
        obj_fcn_alpha = gp.quicksum(
            gp.quicksum(ABS_alpha_primo[j, t] * _alpha_cost for j in range(_n_pb))
            for t in range(_n_t))
        obj_fcn['alpha'] = obj_fcn_alpha

    if 'CM' not in _mrk_scenario and 'VC' not in _mrk_scenario:
        raise ValueError('The Market Model "{model}" do not exist.'.format(model=_mrk_scenario))

    # Dictionary of the model library of the fsp resource
    _fsp_lib = aux.res_fcn

    # Contribution of Resource - Objective Function Cost
    for _key in tqdm(_res_parameters.keys(), desc='Loading Flexibility Service Provider Objective Functions'):
        n_fsp = _res_parameters[_key]['n_fsp']
        # Every market, main or corrective, prices its own activation (incremental pricing).

        dw_u_list = aux.get_list(_startswith_key='DW_' + _key + '_U', _comparing_list=_vars[_key])
        dw_d_list = aux.get_list(_startswith_key='DW_' + _key + '_D', _comparing_list=_vars[_key])
        dr_u_list = aux.get_list(_startswith_key='DR_' + _key + '_U', _comparing_list=_vars[_key])
        dr_d_list = aux.get_list(_startswith_key='DR_' + _key + '_D', _comparing_list=_vars[_key])

        wu_cost_list = aux.get_list(_startswith_key='WU_', _comparing_list=_res_parameters[_key]['data'])
        wd_cost_list = aux.get_list(_startswith_key='WD_', _comparing_list=_res_parameters[_key]['data'])
        ru_cost_list = aux.get_list(_startswith_key='RU_', _comparing_list=_res_parameters[_key]['data'])
        rd_cost_list = aux.get_list(_startswith_key='RD_', _comparing_list=_res_parameters[_key]['data'])

        # The objective below pairs the
        # j-th activation variable with the j-th price frame BY POSITION.  That
        # is correct today only because the two naming conventions happen to
        # sort alike -- storage yields [DW_C_U_inj, DW_C_U_ads] against
        # [WU_inj_cost, WU_ads_cost].  If either convention ever drifts, the
        # pairing would silently charge one sub-direction at another's price,
        # or drop a term entirely, and the market would still solve.  Fail
        # loudly instead: a mispriced objective is far worse than a crash.
        for _vars_list, _cost_list, _label in (
                (dw_u_list, wu_cost_list, 'active upward'),
                (dw_d_list, wd_cost_list, 'active downward'),
                (dr_u_list, ru_cost_list, 'reactive upward'),
                (dr_d_list, rd_cost_list, 'reactive downward')):
            if len(_vars_list) != len(_cost_list):
                raise ValueError(
                    'Resource class {t}: {n_v} {lab} activation variables {v} but '
                    '{n_c} price frames {c}. They are paired by position, so the '
                    'objective cannot be built safely.'.format(
                        t=_key, lab=_label, n_v=len(_vars_list), v=_vars_list,
                        n_c=len(_cost_list), c=_cost_list))
        obj_fcn[_key] = gp.quicksum(
            gp.quicksum(
                gp.quicksum(
                    _vars[_key][dw_u_list[_j]][i, t] * _res_parameters[_key]['data'][wu_cost_list[_j]].iloc[i, t] for _j
                    in range(len(dw_u_list)))
                + gp.quicksum(
                    _vars[_key][dw_d_list[_j]][i, t] * _res_parameters[_key]['data'][wd_cost_list[_j]].iloc[i, t] for _j
                    in range(len(dw_d_list)))
                + gp.quicksum(
                    _vars[_key][dr_u_list[_j]][i, t] * _res_parameters[_key]['data'][ru_cost_list[_j]].iloc[i, t] for _j
                    in range(len(dr_u_list)))
                + gp.quicksum(
                    _vars[_key][dr_d_list[_j]][i, t] * _res_parameters[_key]['data'][rd_cost_list[_j]].iloc[i, t] for _j
                    in range(len(dr_d_list)))
                for i in range(n_fsp))
            for t in range(_n_t))

    # Set Objective Function
    _grb_model.setObjective(gp.quicksum(obj_fcn[_k] for _k in obj_fcn.keys()), GRB.MINIMIZE)
    return _grb_model


def _save_vars_tuple(_grb_model, _vars, _res_parameters, _list_general_vars, _hours, _n_assets, _pilot_bus,
                     _round_vars=3):
    """
    Save tuple variables of optimisation model into Dataframes.
    """
    # Dictionary of the results
    _results = dict()
    _results['ObjValue'] = pd.DataFrame({'ObjValue': [_grb_model.ObjVal]})
    for _k, _i in _vars.items():
        try:
            if _k in _list_general_vars:
                if 'beta' not in _k:
                    # Extract the results like a matrix (Voltage Control General variables)
                    _matrix = np.zeros(shape=(len(_pilot_bus), len(_hours)))
                    for _np in range(len(_pilot_bus)):
                        for _t in range(len(_hours)):
                            _matrix[_np, _t] = _i[(_np, _t)].X
                else:
                    # Extract the results like a matrix (Congestion Management General variables)
                    _matrix = np.zeros(shape=(_n_assets, len(_hours)))
                    for _c in range(_n_assets):
                        for _t in range(len(_hours)):
                            _matrix[_c, _t] = _i[(_c, _t)].X
                # Save as Dataframe
                _results[_k] = pd.DataFrame(_matrix, columns=_hours)
            else:
                n_fsp = _res_parameters[_k]['n_fsp']
                fsp_index = _res_parameters[_k].get('fsp_index', pd.RangeIndex(n_fsp))
                res_conv = [_val + _k for _val in _res_parameters[_k]['conv']]
                for _k1, _i1 in _vars[_k].items():
                    # Extract the results like a matrix
                    _matrix = np.zeros(shape=(n_fsp, len(_hours)))
                    for _fsp in range(n_fsp):
                        for _t in range(len(_hours)):
                            _matrix[_fsp, _t] = _i1[(_fsp, _t)].X
                    ''' # we are going to Save each variable with the correct physical interpretation:
                    1. qSMVA is converted back to MVA, RATIO_* is kept dimensionless and used to
                    2. compute COSPHI_*, only res_conv variables are sign-flipped for reporting,
                    3. and all remaining variables keep their original optimization sign. so below code block is commented and the new revised one is inserted instead>
                    if _k1 in res_conv:
                        _results[_k1] = pd.DataFrame(-_matrix, columns=_hours)
                    # elif _k1.split('_')[0] == 'qSMVA':
                    elif 'qSMVA' in _k1:
                        W = _results['W_' + _k]
                        R = _results['R_' + _k]
                        smva_calc = np.sqrt(W.to_numpy() ** 2 + R.to_numpy() ** 2)
                        _results['SMVA_' + _k] = pd.DataFrame(np.sqrt(_matrix), columns=_hours)
                        _results['SMVA_' + _k + '_calc'] = pd.DataFrame(smva_calc, columns=_hours)
                    # elif _k1 == 'RATIO_' + _list_fsp_cat[1] or _k1 == 'RATIO_' + _list_fsp_cat[2]:
                    elif 'RATIO_' in res_conv:
                        RATIO = _matrix
                        _results[_k1] = pd.DataFrame(RATIO, columns=_hours)
                        cos_phi = np.cos(np.arctan(RATIO))
                        _results['COSPHI_' + _k] = pd.DataFrame(cos_phi, columns=_hours)
                    else:
                        _results[_k1] = pd.DataFrame(_matrix, columns=_hours)
                    '''
                    if 'qSMVA' in _k1:
                        _results['SMVA_' + _k] = pd.DataFrame(np.sqrt(_matrix), index=fsp_index, columns=_hours)

                        if ('W_' + _k) in _results and ('R_' + _k) in _results:
                            W = _results['W_' + _k]
                            R = _results['R_' + _k]
                            smva_calc = np.sqrt(W.to_numpy() ** 2 + R.to_numpy() ** 2)
                            _results['SMVA_' + _k + '_calc'] = pd.DataFrame(smva_calc, index=fsp_index, columns=_hours)

                    elif 'RATIO_' in _k1:
                        RATIO = _matrix
                        _results[_k1] = pd.DataFrame(RATIO, index=fsp_index, columns=_hours)
                        cos_phi = np.cos(np.arctan(RATIO))
                        _results['COSPHI_' + _k] = pd.DataFrame(cos_phi, index=fsp_index, columns=_hours)

                    elif _k1 in res_conv:
                        _results[_k1] = pd.DataFrame(-_matrix, index=fsp_index, columns=_hours)
                    else:
                        _results[_k1] = pd.DataFrame(_matrix, index=fsp_index, columns=_hours)
        except gp.GurobiError:
            pass
    return _results


def _save_mrk_res_excel(_results, _out_root, _filename, _extension='.xlsx'):
    """
    Save market results into Excel files.

    :param _results: Dictionary market results to be saved.

    :param _out_root: Root to where the market results will be saved.

    :param _filename: Name of the file excel that contains the market results.

    :param _extension: Extension of the file excel.
    """
    with pd.ExcelWriter(os.path.join(_out_root, _filename + _extension)) as writer:
        if type(_results) is dict:
            for _k, _v in _results.items():
                try:
                    _v.to_excel(writer, sheet_name=_k)
                except AttributeError:
                    pd.DataFrame(_v).to_excel(writer, sheet_name=_k)
        else:
            raise ValueError('Format type "{_out}" not supported.'.format(_out=str(type(_results))))
    return True


def _divide_chunks(_hours, _n):
    # looping till length l
    for i in range(0, len(_hours), _n):
        yield _hours[i:i + _n]


def _merge_results(_dict_res):
    _final_res_dict = dict()
    _flag_first = True
    for _key in _dict_res.keys():
        if _flag_first:
            for _key_res in _dict_res[_key]:
                _final_res_dict[_key_res] = _dict_res[_key][_key_res]
            _flag_first = False
        else:
            for _key_res in _dict_res[_key]:
                if 'Obj' in _key_res:
                    _final_res_dict[_key_res] = pd.DataFrame(
                        _final_res_dict[_key_res]['ObjValue'] + _dict_res[_key][_key_res]['ObjValue'])
                else:
                    _final_res_dict[_key_res] = pd.concat([_final_res_dict[_key_res], _dict_res[_key][_key_res]],
                                                          axis=1)
    return _final_res_dict


def flex_market(_fsp_file, _hours, _pilot_asset, _pilot_bus, _in_root, _out_root, _matrix_root, _v_before, _vmin, _vmax,
                _dv_tol_opt, _outbounds_bus, _smax, _sinit, _ds_tol, _cong_needs, _cong_assets, _consec_h, _alpha_cost, _beta_cost,
                _mrk_tag, _sim_tag, **kwargs):
    """
    Run the Local Flexibility Market.
    """
    defaults = {
        '_consec_h': 24,
        '_hours_vc': None,
        '_hours_cm': None,
        '_filename': 'model_results_',
        '_cm_factor': -1,
        '_mip_focus': 2,
        '_mip_gap': 0.00001,
        # Optional solve limits (None = Gurobi default).
        '_time_limit': None,
        '_threads': None,
        '_log_console': False,  # Live Gurobi log on the console
        #'_nonconvex': 2, # The typo> "_nnvonvex" is used consistently in the call, but the default dictionary is inconsistent.
        '_nnvonvex': 2,
        '_method': 5,
        '_net_mrk': True,
        '_cap_cstr': True,
        '_int_soc': True,
        '_dt': 1,
        '_flag_lp': False,
        '_flag_mps': False,
        '_vmin_opt': None,
        '_vmax_opt': None,
        # Independent-scenario mode.  The two sets name what each
        # scenario monitors (see _cons_indexing).  _hour_positions gives, for every entry of _hours, its column
        # position in the FSP workbooks, which hold every studied hour: a corrective iteration that re-clears only
        # some scenarios must read THEIR offers, not the first columns of the workbook.
        '_assets_by_hour': None,
        '_buses_by_hour': None,
        '_hour_positions': None,
    }

    # Merge default values with kwargs feed it by the user
    params = {**defaults, **kwargs}

    _mrk_scenario, _product = _parse_market_tag(_mrk_tag)

    _n_assets = len(_smax)

    n_pilot_bus = len(_pilot_bus)

    split_hours = list(_divide_chunks(_hours, _consec_h))

    # Positions of the hours in the FSP workbooks.
    if params['_hour_positions'] is not None:
        _idx_hours = [int(position) for position in params['_hour_positions']]
        if len(_idx_hours) != len(_hours):
            raise ValueError('_hour_positions must give one workbook position per hour: %d positions for %d hours.'
                             % (len(_idx_hours), len(_hours)))
    else:
        _idx_hours = list(range(0, len(_hours)))
    split_idx = list(_divide_chunks(_idx_hours, _consec_h))

    total_res_data = dict()
    _count = 0
    for _s_interval, _s_idx in zip(split_hours, split_idx):
        n_t = len(_s_interval)
        # A one-hour problem of a partial corrective iteration is
        # named by its position among the studied hours, so its Gurobi log is appended to the log of the same
        # scenario's earlier solve and not to the log of whichever scenario happens to come first.
        _split_name = (str(_s_idx[0]) if params['_hour_positions'] is not None and len(_s_idx) == 1
                       else str(_count))

        # Upload resource parameters-
        params_fps = _upload_res_params(_fsp_file, _in_root, _s_idx)

        # Upload Sensitivity Matrix for specific hours
        if params['_net_mrk']:
            cm_matrix, vc_matrix = _load_sens_matrix(_res_parameters=params_fps, _hours2study=_s_interval,
                                                     _n_cong=_n_assets, _n_pilot_bus=n_pilot_bus,
                                                     _matrix_root=_matrix_root, _mrk_scenario=_mrk_scenario,
                                                     _product=_product, _sim_tag=_sim_tag, _cm_factor=params['_cm_factor'])

            aux.validate_sens_matrix(_sens_matrix=cm_matrix, _ncols=_n_assets, _fsp_data=params_fps)
            aux.validate_sens_matrix(_sens_matrix=vc_matrix, _ncols=n_pilot_bus, _fsp_data=params_fps)
        else:
            cm_matrix, vc_matrix = 0, 0

        # Define the Gurobi Model
        lfm_model = gp.Model(_mrk_scenario + _product + '_MarketModel_split' + _split_name)

        # Define Variables
        vars_dict, _list_general_vars = _var_indexing(_grb_model=lfm_model, _res_parameters=params_fps,
                                                      _n_pb=n_pilot_bus, _n_assets=_n_assets, _n_t=n_t)

        # Define Constraints
        lfm_model = _cons_indexing(_grb_model=lfm_model, _vars=vars_dict, _res_parameters=params_fps,
                                   _sens_matrix_cm=cm_matrix, _sens_matrix_vc=vc_matrix, _hours=_s_interval,
                                   _hours_vc=params['_hours_vc'], _hours_cm=params['_hours_cm'], _s_init=_sinit,
                                   _s_max=_smax, _ds_tol=_ds_tol, _cong_needs=_cong_needs, _cong_assets=_cong_assets, _pilot_bus=_pilot_bus,
                                   _v_before=_v_before, _vmin=_vmin, _vmax=_vmax, _dv_tol_opt=_dv_tol_opt,
                                   _outbounds_bus=_outbounds_bus, _mrk_scenario=_mrk_scenario, _net_mrk=params['_net_mrk'],
                                   _cap_cstr=params['_cap_cstr'], _int_soc=params['_int_soc'], _dt=params['_dt'],
                                   _vmin_opt=params['_vmin_opt'], _vmax_opt=params['_vmax_opt'],
                                   _assets_by_hour=params['_assets_by_hour'],
                                   _buses_by_hour=params['_buses_by_hour'])

        # Objective Function
        lfm_model = _obj_indexing(_grb_model=lfm_model, _vars=vars_dict, _res_parameters=params_fps,
                                  _alpha_cost=_alpha_cost, _beta_cost=_beta_cost, _sens_matrix_vc=vc_matrix,
                                  _n_pb=n_pilot_bus, _n_assets=_n_assets, _n_t=n_t, _mrk_scenario=_mrk_scenario,
                                  _net_mrk=params['_net_mrk'])

        lfm_model.setParam(GRB.Param.MIPFocus, params['_mip_focus'])
        lfm_model.setParam(GRB.Param.MIPGap, params['_mip_gap'])
        lfm_model.setParam(GRB.Param.NonConvex, params['_nnvonvex'])
        lfm_model.setParam(GRB.Param.Method, params['_method'])
        # Optional solve limits from the YAML
        # (time_limit, threads); absent they are not set and Gurobi's defaults apply.
        if params['_time_limit'] is not None:
            lfm_model.setParam(GRB.Param.TimeLimit, params['_time_limit'])
        if params['_threads'] is not None:
            lfm_model.setParam(GRB.Param.Threads, params['_threads'])

        # Save model
        dir2check = os.path.join(_out_root, 'GReports')
        # Every solve writes its Gurobi log (incumbent, bound and gap over time) next to the LP report; a
        # corrective solve of the same case is appended to the same file.
        os.makedirs(dir2check, exist_ok=True)
        lfm_model.setParam(GRB.Param.LogFile, os.path.join(
            dir2check, 'gurobi_' + _mrk_tag + '_split' + _split_name + '.log'))
        if params['_flag_lp']:
            if not os.path.isdir(dir2check):
                os.makedirs(dir2check)

            _name_lp = 'report_case_lp_' + _mrk_tag + '_split' + _split_name + '.lp'
            lfm_model.write(os.path.join(dir2check, _name_lp))

        if params['_flag_mps']:
            if not os.path.isdir(dir2check):
                os.makedirs(dir2check)

            _name_mps = 'report_case_mps_' + _mrk_tag + '_split' + _split_name + '.mps'
            lfm_model.write(os.path.join(dir2check, _name_mps))

        # Solve multi-scenario model
        # Say that the solve has started and where its progress is written; with solver_log_to_console the
        # Gurobi progress table is also printed live.
        lfm_model.Params.LogToConsole = 1 if params['_log_console'] else 0
        print('Solving the market with Gurobi (%d constraints, %d variables); progress: %s'
              % (lfm_model.NumConstrs, lfm_model.NumVars,
                 os.path.join(dir2check, 'gurobi_' + _mrk_tag + '_split' + _split_name + '.log')), flush=True)
        lfm_model.optimize()

        # Check model status
        _diagnostic(lfm_model)

        # Save results into Results Dictionary
        _res_data = _save_vars_tuple(_grb_model=lfm_model, _vars=vars_dict, _res_parameters=params_fps,
                                     _list_general_vars=_list_general_vars, _hours=_s_interval, _n_assets=_n_assets,
                                     _pilot_bus=_pilot_bus, _round_vars=3)

        total_res_data[_count] = _res_data
        _count += 1

    # Merge Results
    final_res_data = _merge_results(total_res_data)
    # Save results into Excel file
    filename = params['_filename'] + _mrk_tag
    _save_mrk_res_excel(_results=final_res_data, _out_root=_out_root, _filename=filename)
    return [os.path.join(_out_root, filename + '.xlsx')]
