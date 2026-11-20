import os
import sys
import math
import importlib
import numpy as np
import pandas as pd
import gurobipy as gp
from gurobipy import GRB, tuplelist
from enginiite import file_io as io_file
from enginiite.market import solver_status


def res_params(_n_fsp, _sim_period, _fsp_data):
    """
    Define Input Data of the Load Resource.
    :param _n_fsp: Number of FSP of type Load resource.
    :param _sim_period: List of hours to consider for the study.
    :param _fsp_data: Dictionary of the Data associated
    """
    fsp_data = dict()
    # Save Data that are Impose to GENERATION Convention
    load_conv = ['DR_', 'R_', 'DW_', 'W_']
    if _n_fsp > 0:
        # Reactive Power
        fsp_data['Rinit'] = _fsp_data['Rinit'].iloc[list(range(0, _n_fsp)), _sim_period]
        fsp_data['Winit'] = _fsp_data['Winit'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Reactive Power UPWARD Support Provision [€/MVArh] for each Resource
        fsp_data['RU_cost'] = _fsp_data['R_U_Cost'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Reactive Power DOWNWARD Support Provision [€/MVArh] for each Resource
        fsp_data['RD_cost'] = _fsp_data['R_D_Cost'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Nameplate Apparent Power of the Resources [MVA]
        fsp_data['mva'] = _fsp_data['FSPinfo'].mva.to_numpy()
        # Lower Bound Active Power (Minimum Active Power ABSORPTION Value admitted by the Resource)
        fsp_data['Wlb'] = _fsp_data['WLB_ULim'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound Active Power (Maximum Active Power INJECTION Value admitted by the Resource)
        fsp_data['Wub'] = _fsp_data['WUB_DLim'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Lower Bound Reactive Power Value (Minimum Reactive Power ABSORPTION Value admitted by the Resource)
        fsp_data['Rlb'] = _fsp_data['RUB_ULim'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound Reactive Power Value (Maximum Reactive Power INJECTION Value admitted by the Resource)
        fsp_data['Rub'] = _fsp_data['RUB_DLim'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Active Power UPWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WU_cost'] = _fsp_data['W_U_Cost'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Active Power DOWNWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WD_cost'] = _fsp_data['W_D_Cost'].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cosphi Initial Value
        fsp_data['COSPHILB'] = _fsp_data['COSPHIinit'].iloc[list(range(0, _n_fsp)), _sim_period]
        fsp_data['COSPHIUB'] = _fsp_data['COSPHIinit'].iloc[list(range(0, _n_fsp)), _sim_period]

        # Keep load-convention active/reactive bid intervals feasible before
        # converting to the generation convention. If saturation makes the
        # lower bound larger than the upper bound, collapse the interval to
        # the saturated upper bound. Otherwise the later constraints
        # W_A <= -Wlb and W_A >= -Wub become contradictory.
        _bad_w_interval = fsp_data['Wlb'] > fsp_data['Wub']
        fsp_data['Wlb'] = fsp_data['Wlb'].where(~_bad_w_interval, fsp_data['Wub'])
        _bad_r_interval = fsp_data['Rlb'] > fsp_data['Rub']
        fsp_data['Rlb'] = fsp_data['Rlb'].where(~_bad_r_interval, fsp_data['Rub'])

        # Delta active/reactive flexibility capacities.
        # Capacity magnitudes must never be negative. If an initial profile is already
        # outside a saturated technical bound, the available flexibility in that
        # direction is zero, not a negative number.
        fsp_data['DW_U'] = (fsp_data['Winit'] - fsp_data['Wlb']).clip(lower=0)
        fsp_data['DW_D'] = (fsp_data['Wub'] - fsp_data['Winit']).clip(lower=0)
        fsp_data['DR_U'] = (fsp_data['Rinit'] - fsp_data['Rlb']).clip(lower=0)
        fsp_data['DR_D'] = (fsp_data['Rub'] - fsp_data['Rinit']).clip(lower=0)
        # Impose GENERATION Convention
        fsp_data['Rinit'] = -fsp_data['Rinit']
        fsp_data['Winit'] = -fsp_data['Winit']
        fsp_data['Wlb'] = -fsp_data['Wlb']
        fsp_data['Wub'] = -fsp_data['Wub']
    else:
        fsp_data['mva'] = np.zeros(shape=(1, 1))
        _zero_df = pd.DataFrame(np.zeros(shape=(1, len(_sim_period))))
        fsp_data['Rinit'] = _zero_df
        fsp_data['Winit'] = _zero_df
        fsp_data['RD_cost'] = _zero_df
        fsp_data['RU_cost'] = _zero_df
        fsp_data['COSPHILB'] = _zero_df
        fsp_data['COSPHIUB'] = _zero_df
        fsp_data['WU_cost'] = _zero_df
        fsp_data['WD_cost'] = _zero_df
        fsp_data['DW_U'] = _zero_df
        fsp_data['DW_D'] = _zero_df
        fsp_data['DR_U'] = _zero_df
        fsp_data['DR_D'] = _zero_df
        fsp_data['Wlb'] = _zero_df
        fsp_data['Wub'] = _zero_df
        fsp_data['Rlb'] = _zero_df
        fsp_data['Rub'] = _zero_df
    return fsp_data, load_conv


def define_variables(_grb_model, _n_fsp, _n_t, _contr, _type='A'):
    """
    Define Variables of the Load Resource selecting the more appropriate/updated function.
    :param _grb_model: Object that represents the gurobipy model.
    :param _n_fsp: Number of flexibility service providers.
    :param _n_t: Number of intervals.
    :param _contr: Contribution of these resource type.
    :param _type: Type of resource.
    """
    _vars_dict = load_variables_v1(grb_model=_grb_model, n_fsp=_n_fsp, n_t=_n_t, _contr=_contr, _type=_type)
    return _vars_dict


def load_variables_v0(grb_model, n_fsp, n_t, _contr, _type='A'):
    """Define Variables of the Load Resource."""
    shape_var = (n_fsp, n_t)
    _vars_dict = dict()
    # Delta Reactive Power Exchange [p.u.]
    DR_A = grb_model.addMVar(shape=shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DR_' + _type)
    _vars_dict['DR_' + _type] = DR_A
    # After the Market Reactive Power Exchange
    R_A = grb_model.addMVar(shape=shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='R_' + _type)
    _vars_dict['R_' + _type] = R_A
    # Delta Active Power [p.u.]
    DW_A = grb_model.addMVar(shape=shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DW_' + _type)
    _vars_dict['DW_' + _type] = DW_A
    # After the Market Active Power
    W_A = grb_model.addMVar(shape=shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='W_' + _type)
    _vars_dict['W_' + _type] = W_A
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_A = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='qSMVA_' + _type)
    _vars_dict['qSMVA_' + _type] = qSMVA_A
    # After the Market Active Power Absorption for type A (loads)
    COSPHI_A = grb_model.addMVar(shape=shape_var, lb=0, ub=1, vtype=GRB.CONTINUOUS, name='COSPHI_' + _type)
    _vars_dict['COSPHI_' + _type] = COSPHI_A
    # Companion variables - necessary in gurobi to include ABSOLUTE values in the objective function
    ABS_DR_A = grb_model.addMVar(shape=shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_DR_' + _type)
    _vars_dict['ABS_DR_' + _type] = ABS_DR_A
    ABS_DW_A = grb_model.addMVar(shape=shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_DW_' + _type)
    _vars_dict['ABS_DW_' + _type] = ABS_DW_A
    # Variables for the Asymmetry of the Bids
    # Delta Active Power Upwards Contribution
    DW_A_U = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U')
    _vars_dict['DW_' + _type + '_U'] = DW_A_U
    # Delta Active Power Downwards Contribution
    DW_A_D = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D')
    _vars_dict['DW_' + _type + '_D'] = DW_A_D
    # Delta Reactive Power Upwards Contribution
    DR_A_U = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_U')
    _vars_dict['DR_' + _type + '_U'] = DR_A_U
    # Delta Reactive Power Downwards Contribution
    DR_A_D = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_D')
    _vars_dict['DR_' + _type + '_D'] = DR_A_D
    return _vars_dict


def load_variables_v1(grb_model, n_fsp, n_t, _contr, _type='A'):
    """Define Variables of the Load Resource."""
    shape_var = tuplelist([(_f, _t) for _f in range(n_fsp) for _t in range(n_t)])
    _vars_dict = dict()
    # Delta Reactive Power Exchange [p.u.]
    DR_A = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DR_' + _type)
    _vars_dict['DR_' + _type] = DR_A
    # After the Market Reactive Power Exchange
    R_A = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='R_' + _type)
    _vars_dict['R_' + _type] = R_A
    # Delta Active Power [p.u.]
    DW_A = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DW_' + _type)
    _vars_dict['DW_' + _type] = DW_A
    # After the Market Active Power
    W_A = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='W_' + _type)
    _vars_dict['W_' + _type] = W_A
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_A = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='qSMVA_' + _type)
    _vars_dict['qSMVA_' + _type] = qSMVA_A
    # After the Market Active Power Absorption for type A (loads)
    COSPHI_A = grb_model.addVars(shape_var, lb=0, ub=1, vtype=GRB.CONTINUOUS, name='COSPHI_' + _type)
    _vars_dict['COSPHI_' + _type] = COSPHI_A
    # Companion variables - necessary in gurobi to include ABSOLUTE values in the objective function
    ABS_DR_A = grb_model.addVars(shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_DR_' + _type)
    _vars_dict['ABS_DR_' + _type] = ABS_DR_A
    ABS_DW_A = grb_model.addVars(shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_DW_' + _type)
    _vars_dict['ABS_DW_' + _type] = ABS_DW_A
    # Variables for the Asymmetry of the Bids
    # Delta Active Power Upwards Contribution
    DW_A_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U')
    _vars_dict['DW_' + _type + '_U'] = DW_A_U
    # Delta Active Power Downwards Contribution
    DW_A_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D')
    _vars_dict['DW_' + _type + '_D'] = DW_A_D
    # Delta Reactive Power Upwards Contribution
    DR_A_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_U')
    _vars_dict['DR_' + _type + '_U'] = DR_A_U
    # Delta Reactive Power Downwards Contribution
    DR_A_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_D')
    _vars_dict['DR_' + _type + '_D'] = DR_A_D
    return _vars_dict


def define_constraints(_grb_model, _vars_dict, _fsp_data, _idx_res, _interval, _cap_cstr, _int_soc=False, _dt=1, _type='A'):
    """
    Define Constraints of the Load Resource selecting the more appropriate/updated function.
    :param _grb_model: Object that represents the gurobipy model.
    :param _vars_dict: Dictionary containing the variables of the gurobi model.
    :param _fsp_data: Dictionary containing the resource parameters.
    :param _idx_res: Index of the resource to which the constraints must be added.
    :param _interval: Index of the hour to which the constraints must be added.
    :param _cap_cstr: Boolean value to add the capability curve constraint of the resource.
    :param _int_soc: Boolean value to add the inter-temporal constraint of the resource.
    :param _dt: Delta time of the model
    :param _type: Type of resource.
    """
    _new_grb_model = load_constraints_v1(grb_model=_grb_model, _vars_dict=_vars_dict, fsp_data=_fsp_data, i=_idx_res,
                                         t=_interval, _cap_cstr=_cap_cstr, _type=_type)
    return _new_grb_model


def load_constraints_v0(grb_model, _vars_dict, fsp_data, i, t, _cap_cstr, _type='A'):
    """Define Constraints of the Load Resource."""
    # Extract Variables
    # Delta Reactive Power [p.u.]
    DR_A = _vars_dict['DR_' + _type]
    # After the Market Reactive Power Exchange
    R_A = _vars_dict['R_' + _type]
    # Delta Active Power [p.u.]
    DW_A = _vars_dict['DW_' + _type]
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_A = _vars_dict['qSMVA_' + _type]
    # After the Market Active Power
    W_A = _vars_dict['W_' + _type]
    # After the Market Active Power Absorption for type A (loads)
    COSPHI_A = _vars_dict['COSPHI_' + _type]
    # Variables for the Asymmetry of the Bids
    # Delta Active Power Upwards Contribution
    DW_A_U = _vars_dict['DW_' + _type + '_U']
    # Delta Active Power Downwards Contribution
    DW_A_D = _vars_dict['DW_' + _type + '_D']
    # Delta Reactive Power Upwards Contribution
    DR_A_U = _vars_dict['DR_' + _type + '_U']
    # Delta Reactive Power Downwards Contribution
    DR_A_D = _vars_dict['DR_' + _type + '_D']
    # Absolute value Delta Reactive Power
    ABS_DR_A = _vars_dict['ABS_DR_' + _type]
    # Absolute value Delta Active Power
    ABS_DW_A = _vars_dict['ABS_DW_' + _type]

    _idx_dr = 0
    for x, y in zip(DR_A.tolist(), ABS_DR_A.tolist()):
        _idx_dr_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_dr = 'abs_dr_' + _type + '_#' + str(_idx_dr) + '_t' + str(_idx_dr_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_dr)
            _idx_dr_t += 1
        _idx_dr += 1

    _idx_dw = 0
    for x, y in zip(DW_A.tolist(), ABS_DW_A.tolist()):
        _idx_dw_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_dw = 'abs_dw_' + _type + '_#' + str(_idx_dw) + '_t' + str(_idx_dw_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_dw)
            _idx_dw_t += 1
        _idx_dw += 1

    _name_W = 'C#04_W_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_A[i, t] + fsp_data['Winit'].iloc[i, t] - W_A[i, t] == 0, name=_name_W)
    _name_R = 'C#04_R_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A[i, t] + fsp_data['Rinit'].iloc[i, t] - R_A[i, t] == 0, name=_name_R)

    if fsp_data['Winit'].iloc[i, t] == 0:
        fsp_data['Winit'].iloc[i, t] = sys.float_info.epsilon
    if fsp_data['Rinit'].iloc[i, t] == 0:
        fsp_data['Rinit'].iloc[i, t] = sys.float_info.epsilon

    const_ratio_A = fsp_data['Rinit'].iloc[i, t] / fsp_data['Winit'].iloc[i, t]
    const_phi_A = math.atan(const_ratio_A)
    cosphi_A = math.cos(math.atan(const_ratio_A))
    # DR_U and DR_D are non-negative flexibility magnitudes.
    # Use the magnitude of the Q/P ratio and non-negative active-flexibility
    # capacities. This prevents infeasible constraints such as DR_D <= negative.
    const_ratio_A_abs = abs(const_ratio_A) if np.isfinite(const_ratio_A) else 0.0
    dw_u_cap_A = max(float(fsp_data['DW_U'].iloc[i, t]), 0.0)
    dw_d_cap_A = max(float(fsp_data['DW_D'].iloc[i, t]), 0.0)

    if _cap_cstr:
        _name_q_cstr = 'C#04a_' + _type + '_NORM(SMVA)_' + str(i) + '_t' + str(t)
        grb_model.addConstr(W_A[i, t] ** 2 + R_A[i, t] ** 2 - qSMVA_A[i, t] == 0, name=_name_q_cstr)
        _name_q_cstr2 = 'C#04a_' + _type + '_SMAX_limit' + str(i) + '_t' + str(t)
        grb_model.addConstr(qSMVA_A[i, t] <= fsp_data['mva'][i] ** 2, name=_name_q_cstr2)
        # PF limits:
        _name_pf_limit = 'C#05_R_' + _type + '_limit_fsp_' + str(i) + '_t' + str(t)
        grb_model.addConstr(const_ratio_A * W_A[i, t] - R_A[i, t] == 0, name=_name_pf_limit)

    _name_cosphi = 'C#05_COSPHI_limit_' + _type + str(i) + '_t' + str(t)
    grb_model.addConstr(COSPHI_A[i, t] == cosphi_A, name=_name_cosphi)

    _name_wabs_lb = 'C#06a_Wads_min_FSP_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_A[i, t] - fsp_data['Wlb'].iloc[i, t] <= 0, name=_name_wabs_lb)
    _name_wabs_ub = 'C#06b_Wads_max_FSP_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_A[i, t] - fsp_data['Wub'].iloc[i, t] >= 0, name=_name_wabs_ub)

    # Constrains for the Asymmetry of Bids
    # Definition of Upward and Downward DELTA W contributions
    _name_dw = 'C#07a_DW_' + _type + '_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_A_U[i, t] - DW_A_D[i, t] - DW_A[i, t] == 0, name=_name_dw)
    # Definition of Upward and Downward DELTA R contributions
    _name_dr = 'C#07a_DR_' + _type + '_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A_U[i, t] - DR_A_D[i, t] - DR_A[i, t] == 0, name=_name_dr)

    # Upper Bound Upward DELTA R
    _name_dr_u = 'C#07a_DR_' + _type + '_Up_UB_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A_U[i, t] - const_ratio_A_abs * dw_u_cap_A <= 0, name=_name_dr_u)
    # Upper Bound Downward DELTA R
    _name_dr_d = 'C#07a_DR_' + _type + '_Dw_UB_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A_D[i, t] - const_ratio_A_abs * dw_d_cap_A <= 0, name=_name_dr_d)
    return grb_model


def load_constraints_v1(grb_model, _vars_dict, fsp_data, i, t, _cap_cstr, _type='A'):
    """Define Constraints of the Load Resource."""
    # Extract Variables
    DR_A = _vars_dict['DR_' + _type]
    # After the Market Reactive Power Exchange
    R_A = _vars_dict['R_' + _type]
    # Delta Active Power [p.u.]
    DW_A = _vars_dict['DW_' + _type]
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_A = _vars_dict['qSMVA_' + _type]
    # After the Market Active Power
    W_A = _vars_dict['W_' + _type]
    # After the Market Active Power Absorption for type A (loads)
    COSPHI_A = _vars_dict['COSPHI_' + _type]
    # Variables for the Asymmetry of the Bids
    # Delta Active Power Upwards Contribution
    DW_A_U = _vars_dict['DW_' + _type + '_U']
    # Delta Active Power Downwards Contribution
    DW_A_D = _vars_dict['DW_' + _type + '_D']
    # Delta Reactive Power Upwards Contribution
    DR_A_U = _vars_dict['DR_' + _type + '_U']
    # Delta Reactive Power Downwards Contribution
    DR_A_D = _vars_dict['DR_' + _type + '_D']
    # Absolute value Delta Reactive Power
    ABS_DR_A = _vars_dict['ABS_DR_' + _type]
    # Absolute value Delta Active Power
    ABS_DW_A = _vars_dict['ABS_DW_' + _type]

    for x, y in zip(DR_A.keys(), ABS_DR_A.keys()):
        _name_abs_dr = 'abs_dr_' + _type + '_#' + str(x[0]) + '_t' + str(x[1])
        grb_model.addGenConstrAbs(ABS_DR_A[y], DR_A[x], name=_name_abs_dr)

    for x, y in zip(DW_A.keys(), ABS_DW_A.keys()):
        _name_abs_dw = 'abs_dw_' + _type + '_#' + str(x[0]) + '_t' + str(x[1])
        grb_model.addGenConstrAbs(ABS_DW_A[y], DW_A[x], name=_name_abs_dw)

    _name_W = 'C#04_W_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_A[i, t] + fsp_data['Winit'].iloc[i, t] - W_A[i, t] == 0, name=_name_W)
    _name_R = 'C#04_R_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A[i, t] + fsp_data['Rinit'].iloc[i, t] - R_A[i, t] == 0, name=_name_R)

    if fsp_data['Winit'].iloc[i, t] == 0:
        fsp_data['Winit'].iloc[i, t] = sys.float_info.epsilon
    if fsp_data['Rinit'].iloc[i, t] == 0:
        fsp_data['Rinit'].iloc[i, t] = sys.float_info.epsilon

    const_ratio_A = fsp_data['Rinit'].iloc[i, t] / fsp_data['Winit'].iloc[i, t]
    const_phi_A = math.atan(const_ratio_A)
    cosphi_A = math.cos(math.atan(const_ratio_A))
    # DR_U and DR_D are non-negative flexibility magnitudes.
    # Use the magnitude of the Q/P ratio and non-negative active-flexibility
    # capacities. This prevents infeasible constraints such as DR_D <= negative.
    const_ratio_A_abs = abs(const_ratio_A) if np.isfinite(const_ratio_A) else 0.0
    dw_u_cap_A = max(float(fsp_data['DW_U'].iloc[i, t]), 0.0)
    dw_d_cap_A = max(float(fsp_data['DW_D'].iloc[i, t]), 0.0)

    if _cap_cstr:
        _name_q_cstr = 'C#04a_' + _type + '_NORM(SMVA)_' + str(i) + '_t' + str(t)
        grb_model.addConstr(W_A[i, t] ** 2 + R_A[i, t] ** 2 - qSMVA_A[i, t] == 0, name=_name_q_cstr)
        _name_q_cstr2 = 'C#04a_' + _type + '_SMAX_limit' + str(i) + '_t' + str(t)
        grb_model.addConstr(qSMVA_A[i, t] <= fsp_data['mva'][i] ** 2, name=_name_q_cstr2)
        # PF limits:
        _name_pf_limit = 'C#05_R_' + _type + '_limit_fsp_' + str(i) + '_t' + str(t)
        grb_model.addConstr(const_ratio_A * W_A[i, t] - R_A[i, t] == 0, name=_name_pf_limit)

    _name_cosphi = 'C#05_COSPHI_limit_' + _type + str(i) + '_t' + str(t)
    grb_model.addConstr(COSPHI_A[i, t] == cosphi_A, name=_name_cosphi)

    _name_wabs_lb = 'C#06a_Wads_min_FSP_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_A[i, t] - fsp_data['Wlb'].iloc[i, t] <= 0, name=_name_wabs_lb)
    _name_wabs_ub = 'C#06b_Wads_max_FSP_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_A[i, t] - fsp_data['Wub'].iloc[i, t] >= 0, name=_name_wabs_ub)

    # Constrains for the Asymmetry of Bids
    # Definition of Upward and Downward DELTA W contributions
    _name_dw = 'C#07a_DW_' + _type + '_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_A_U[i, t] - DW_A_D[i, t] - DW_A[i, t] == 0, name=_name_dw)
    # Definition of Upward and Downward DELTA R contributions
    _name_dr = 'C#07a_DR_' + _type + '_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A_U[i, t] - DR_A_D[i, t] - DR_A[i, t] == 0, name=_name_dr)

    # Upper Bound Upward DELTA R
    _name_dr_u = 'C#07a_DR_' + _type + '_Up_UB_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A_U[i, t] - const_ratio_A_abs * dw_u_cap_A <= 0, name=_name_dr_u)
    # Upper Bound Downward DELTA R
    _name_dr_d = 'C#07a_DR_' + _type + '_Dw_UB_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_A_D[i, t] - const_ratio_A_abs * dw_d_cap_A <= 0, name=_name_dr_d)
    return grb_model



def _parse_market_tag(_mrk_tag):
    """Return (market_model, product) from a simulation tag robustly.

    Supports network names containing underscores.
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
        'Cannot parse market model from market tag "{tag}". Expected one of {models}.'
        .format(tag=_mrk_tag, models=sorted(valid_models))
    )


def _load_sens_matrix_aggr(_aggr_name, _hours2study, _matrix_root, _mrk_tag, _sim_tag, _cm_factor=-1):
    """
    Upload Sensitivity Matrix from file.

    :param _res_parameters: Dictionary of the parameters of the fsp per resource category.

    :param _hours2study: List of hours to study.

    :param _matrix_root: Root to where the sensitivity matrix file are saved.

    :param _mrk_scenario: String that represents the tag for market model.

    :param _service: String that represents the tag for product in the market.

    :param _sim_tag: String that represents the specific name of the simulation.

    :param _cm_factor: Congestion Management Factor that change sign to the sensitivity matrix.
    """
    _mrk_scenario, _service = _parse_market_tag(_mrk_tag)

    sens_matrix_cm = {_h: dict() for _h in _hours2study}
    sens_matrix_vc = {_h: dict() for _h in _hours2study}
    for _h in _hours2study:
        t_th = str(_h).zfill(2)
        w_name_tags = ['HCMdSdP_FSP' + _aggr_name, 'h' + t_th, _sim_tag]
        r_name_tags = ['HCMdSdQ_FSP' + _aggr_name, 'h' + t_th, _sim_tag]
        Wfile2read_cm = '_'.join(filter(None, w_name_tags)) + '.csv'
        Rfile2read_cm = '_'.join(filter(None, r_name_tags)) + '.csv'

        w_name_tags_vc = ['HVMP_FSP' + _aggr_name, 'h' + t_th, _sim_tag]
        r_name_tags_vc = ['HVMQ_FSP' + _aggr_name, 'h' + t_th, _sim_tag]

        Wfile2read_vc = '_'.join(filter(None, w_name_tags_vc)) + '.csv'
        Rfile2read_vc = '_'.join(filter(None, r_name_tags_vc)) + '.csv'

        # Aggregator P-only operation also
        # retains Q sensitivities for any power-factor-linked reactive change.
        if _mrk_scenario == 'CM' or _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
            sens_matrix_cm[_h]['W'] = _cm_factor * io_file.import_data(_filename=Wfile2read_cm, _root=_matrix_root, _index_col=0)
            sens_matrix_cm[_h]['R'] = _cm_factor * io_file.import_data(_filename=Rfile2read_cm, _root=_matrix_root, _index_col=0)

        if _mrk_scenario == 'VC' or _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
            sens_matrix_vc[_h]['W'] = io_file.import_data(_filename=Wfile2read_vc, _root=_matrix_root, _index_col=0)
            sens_matrix_vc[_h]['R'] = io_file.import_data(_filename=Rfile2read_vc, _root=_matrix_root, _index_col=0)
    return sens_matrix_cm, sens_matrix_vc


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
    return True


def define_bids(_aggr_name, _filename_aggr, _data, _flag_res=True, _flag_model=True):
    """
    This function optimizes the Aggregator Model. This model runs a techno-economic model in which the Aggregator look
    for the maximum profit according to aggregated resources technical constraints.
    """
    _fsp_data = _data['fsp_data']
    _out_root = _data['out_root']
    _matrix_root = _data['matrix_root']
    _hours = _data['hours']
    _cap_cstr = _data['cap_cstr']
    _dt = _data['dt']
    _int_soc = _data['int_soc']
    _net_cstr_aggr = _data['net_cstr_aggr']
    _dict_res = _data['dict_res']
    _n_t = len(_hours)

    name_model = _aggr_name + '_Model'
    aggr_model = gp.Model(name_model)

    shape_aggr = tuplelist([(1, t) for t in range(_n_t)])
    # Delta Active Power Up Aggregator
    dpA_up = aggr_model.addVars(shape_aggr, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='dpA_up')
    # Delta Active Power Down Aggregator
    dpA_dwn = aggr_model.addVars(shape_aggr, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='dpA_dwn')
    # Delta Reactive Power Up Aggregator
    dqA_up = aggr_model.addVars(shape_aggr, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='dqA_up')
    # Delta Reactive Power Down Aggregator
    dqA_dwn = aggr_model.addVars(shape_aggr, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='dqA_dwn')

    tot_n_fsp = _fsp_data.shape[0]
    shape_aggr_res = tuplelist([(i, h) for i in range(tot_n_fsp) for h in range(_n_t)])
    max_value = 1000
    # Delta Active Power Up Aggregator for each Resource Type
    dpA_res_up = aggr_model.addVars(shape_aggr_res, lb=0, ub=max_value, vtype=GRB.CONTINUOUS, name='dpA_res_up')
    # Delta Active Power Down Aggregator for each Resource Type
    dpA_res_dwn = aggr_model.addVars(shape_aggr_res, lb=0, ub=max_value, vtype=GRB.CONTINUOUS, name='dpA_res_dwn')
    # Delta Reactive Power Up Aggregator for each Resource Type
    dqA_res_up = aggr_model.addVars(shape_aggr_res, lb=0, ub=max_value, vtype=GRB.CONTINUOUS, name='dqA_res_up')
    # Delta Reactive Power Up Aggregator for each Resource Type
    dqA_res_dwn = aggr_model.addVars(shape_aggr_res, lb=0, ub=max_value, vtype=GRB.CONTINUOUS, name='dqA_res_dwn')

    variables = dict()
    res_parameters = {_k: dict() for _k in _fsp_data.type.unique()}
    for _i in _fsp_data.type.unique():
        list_res = _dict_res.get(_i, None)

        if list_res is None:
            raise IOError('Resource of type {_class} is unknown.'.format(_class=_i))

        res_lib = importlib.import_module(f'enginiite.market.models.{list_res}')

        fsp_data = io_file.import_data(_filename=_filename_aggr + '.xlsx', _root=_out_root, _index_col=0)
        n_fsp = fsp_data['FSPinfo_' + _i].bus.to_numpy().shape[0]
        res_parameters[_i]['n_fsp'] = n_fsp
        res_parameters[_i]['fsp_info'] = fsp_data['FSPinfo_' + _i]

        _res_data, _ = res_lib.res_params(_n_fsp=n_fsp, _sim_period=_hours, _fsp_data=fsp_data, _type=_i)

        variable_dict = res_lib.define_variables(_grb_model=aggr_model, _n_fsp=n_fsp, _n_t=_n_t, _contr=GRB.INFINITY, _type=_i)
        variables[_i] = variable_dict

        for t in range(_n_t):
            for i in range(n_fsp):
                _name_max_dpA_res_up = 'max_dpA_up_res' + str(i) + '_t' + str(t)
                aggr_model.addConstr(dpA_res_up[i, t] - _fsp_data.TL_ratio_Pup[i] * variable_dict['DW_' + _i + '_U'][i, t] <= 0, name=_name_max_dpA_res_up)
                _name_max_dpA_res_dwn = 'max_dpA_dwn_res' + str(i) + '_t' + str(t)
                aggr_model.addConstr(dpA_res_dwn[i, t] - _fsp_data.TL_ratio_Pdown[i] * variable_dict['DW_' + _i + '_D'][i, t] <= 0, name=_name_max_dpA_res_dwn)
                _name_max_dqA_res_up = 'max_dqA_up_res' + str(i) + '_t' + str(t)
                aggr_model.addConstr(dqA_res_up[i, t] - _fsp_data.TL_ratio_Qup[i] * variable_dict['DR_' + _i + '_U'][i, t] <= 0, name=_name_max_dqA_res_up)
                _name_max_dqA_res_dwn = 'max_dqA_dwn_res' + str(i) + '_t' + str(t)
                aggr_model.addConstr(dqA_res_dwn[i, t] - _fsp_data.TL_ratio_Qdown[i] * variable_dict['DR_' + _i + '_D'][i, t] <= 0, name=_name_max_dqA_res_dwn)

                res_lib.define_constraints(_grb_model=aggr_model, _vars_dict=variable_dict, _idx_res=i, _interval=t,
                                           _fsp_data=_res_data, _cap_cstr=_cap_cstr, _dt=_dt,
                                           _int_soc=_int_soc, _type=_i)

    for t in range(_n_t):
        _name_dpA_up = 'dpA_up_t' + str(t)
        aggr_model.addConstr(dpA_up[1, t] - dpA_res_up.sum('*', t) == 0, name=_name_dpA_up)
        _name_dpA_dwn = 'dpA_dwn_t' + str(t)
        aggr_model.addConstr(dpA_dwn[1, t] - dpA_res_dwn.sum('*', t) == 0, name=_name_dpA_dwn)
        _name_dqA_up = 'dqA_up_t' + str(t)
        aggr_model.addConstr(dqA_up[1, t] - dqA_res_up.sum('*', t) == 0, name=_name_dqA_up)
        _name_dqA_dwn = 'dqA_dwn_t' + str(t)
        aggr_model.addConstr(dqA_dwn[1, t] - dqA_res_dwn.sum('*', t) == 0, name=_name_dqA_dwn)

    if _net_cstr_aggr:
        _mrk_tag = _data['mrk_tag']
        _sim_tag = _data['sim_tag']
        _cm_factor = _data['cm_factor']
        _mrk_scenario, _ = _parse_market_tag(_mrk_tag)
        sens_k_cm, sens_k_vc = _load_sens_matrix_aggr(_aggr_name=_aggr_name, _hours2study=_hours, _matrix_root=_matrix_root,
                                                      _mrk_tag=_mrk_tag, _sim_tag=_sim_tag, _cm_factor=_cm_factor)
        if _mrk_scenario == 'CM' or _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
            _cong_needs = _data['cong_needs']
            n_cong = _cong_needs.shape[0]
            shape_beta = tuplelist([(j, t) for j in range(n_cong) for t in range(_n_t)])
            beta = aggr_model.addVars(shape_beta, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='beta')
            t_aux = 0
            for _t in _hours:
                for _l in range(n_cong):
                    _name_cong = 'C#01_CM_l' + str(_l) + '_t' + str(_t)
                    k_market = gp.quicksum((sens_k_cm[_t]['W'].iloc[_l, x] * (dpA_res_up[x, t_aux] - dpA_res_dwn[x, t_aux]))
                                           + (sens_k_cm[_t]['R'].iloc[_l, x] * (dqA_res_up[x, t_aux] - dqA_res_dwn[x, t_aux]))
                                           for x in range(tot_n_fsp))
                    # Create Constraints
                    aggr_model.addConstr(_cong_needs.iloc[_l, t_aux] - k_market - beta[_l, t_aux] <= 0, name=_name_cong)
                t_aux += 1

        if _mrk_scenario == 'VC' or _mrk_scenario == 'CMVC' or _mrk_scenario == 'VCCM':
            _vmax = _data['v_max']
            _vmin = _data['v_min']
            _v_before = _data['v_before']
            n_pilot_bus = _v_before.shape[0]
            shape_alpha = tuplelist([(k, t) for k in range(n_pilot_bus) for t in range(_n_t)])
            alpha = aggr_model.addVars(shape_alpha, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='alpha')
            t_aux = 0
            for _t in _hours:
                for _l in range(n_pilot_bus):
                    k_market = gp.quicksum((sens_k_vc[_t]['W'].iloc[_l, x] * (dpA_res_up[x, t_aux] - dpA_res_dwn[x, t_aux]))
                                           + (sens_k_vc[_t]['R'].iloc[_l, x] * (dqA_res_up[x, t_aux] - dqA_res_dwn[x, t_aux]))
                                           for x in range(tot_n_fsp))
                    # Create Constraints
                    if _v_before.iloc[_l, t_aux] > _vmax:
                        _name_cong = 'C#01_Vmax_Bus_l' + str(_l) + '_t' + str(t_aux)
                        aggr_model.addConstr(_v_before.iloc[_l, t_aux] - alpha[_l, t_aux] - k_market >= 0, name=_name_cong)
                    elif _v_before.iloc[_l, t_aux] < _vmin:
                        _name_cong = 'C#01_Vmin_Bus_l' + str(_l) + '_t' + str(t_aux)
                        aggr_model.addConstr(_v_before.iloc[_l, t_aux] - alpha[_l, t_aux] - k_market <= 0, name=_name_cong)
                t_aux += 1

    aggr_price_Wup = np.array(_fsp_data.Pup_cost.max()).repeat(_n_t * tot_n_fsp)
    res_price_Wup = np.array(_fsp_data.Pup_cost).repeat(_n_t)
    cost_Wup = aggr_price_Wup - res_price_Wup
    aggr_coeff_Wup = dict(zip(shape_aggr_res, cost_Wup))

    aggr_price_Wdwn = np.array(_fsp_data.Pdown_cost.max()).repeat(_n_t * tot_n_fsp)
    res_price_Wdwn = np.array(_fsp_data.Pdown_cost).repeat(_n_t)
    cost_Wdwn = aggr_price_Wdwn - res_price_Wdwn
    aggr_coeff_Wdwn = dict(zip(shape_aggr_res, cost_Wdwn))

    aggr_price_Rup = np.array(_fsp_data.Qup_cost.max()).repeat(_n_t * tot_n_fsp)
    res_price_Rup = np.array(_fsp_data.Qup_cost).repeat(_n_t)
    cost_Rup = aggr_price_Rup - res_price_Rup
    aggr_coeff_Rup = dict(zip(shape_aggr_res, cost_Rup))

    aggr_price_Rdwn = np.array(_fsp_data.Qdown_cost.max()).repeat(_n_t * tot_n_fsp)
    res_price_Rdwn = np.array(_fsp_data.Qdown_cost).repeat(_n_t)
    cost_Rdwn = aggr_price_Rdwn - res_price_Rdwn
    aggr_coeff_Rdwn = dict(zip(shape_aggr_res, cost_Rdwn))

    obj_fcn = dpA_res_up.prod(aggr_coeff_Wup) + dpA_res_dwn.prod(aggr_coeff_Wdwn) \
              + dqA_res_up.prod(aggr_coeff_Rup) + dqA_res_dwn.prod(aggr_coeff_Rdwn)
    aggr_model.setObjective(obj_fcn, GRB.MAXIMIZE)

    # Write Model on file to check correctness
    if _flag_model:
        _root_res = name_model
        new_folder = os.path.join(os.path.abspath(_out_root), _root_res)
        if not os.path.exists(new_folder):
            os.makedirs(new_folder)
        aggr_model.write(os.path.join(new_folder, name_model + '.lp'))

    aggr_model.Params.MIPGap = .0000001
    aggr_model.Params.LogToConsole = 0
    aggr_model.optimize()

    _diagnostic(aggr_model)
    status = aggr_model.status
    if status == GRB.OPTIMAL:
        try:
            variables_res = {'Obj': [aggr_model.ObjVal]}
            matrix_dpA_up = np.zeros(shape=(_n_t, 1))
            matrix_dpA_dwn = np.zeros(shape=(_n_t, 1))
            matrix_dqA_up = np.zeros(shape=(_n_t, 1))
            matrix_dqA_dwn = np.zeros(shape=(_n_t, 1))
            matrix_dpA_res_up = np.zeros(shape=(_n_t, tot_n_fsp))
            matrix_dpA_res_dwn = np.zeros(shape=(_n_t, tot_n_fsp))
            matrix_dqA_res_up = np.zeros(shape=(_n_t, tot_n_fsp))
            matrix_dqA_res_dwn = np.zeros(shape=(_n_t, tot_n_fsp))

            for t in range(_n_t):
                matrix_dpA_up[t, 0] = dpA_up[(1, t)].X
                matrix_dpA_dwn[t, 0] = dpA_dwn[(1, t)].X
                matrix_dqA_up[t, 0] = dqA_up[(1, t)].X
                matrix_dqA_dwn[t, 0] = dqA_dwn[(1, t)].X
                for k in range(tot_n_fsp):
                    matrix_dpA_res_up[t, k] = dpA_res_up[(k, t)].X
                    matrix_dpA_res_dwn[t, k] = dpA_res_dwn[(k, t)].X
                    matrix_dqA_res_up[t, k] = dqA_res_up[(k, t)].X
                    matrix_dqA_res_dwn[t, k] = dqA_res_dwn[(k, t)].X

            for _i in _fsp_data.type.unique():
                n_fsp = res_parameters[_i]['n_fsp']
                for _k1, _i1 in variables[_i].items():
                    # Extract the results like a matrix
                    _matrix = np.zeros(shape=(n_fsp, _n_t))
                    for _fsp in range(n_fsp):
                        for _t in range(_n_t):
                            _matrix[_fsp, _t] = _i1[(_fsp, _t)].X
                    variables_res[_k1] = _matrix

            variables_res['dpA_up'] = matrix_dpA_up
            variables_res['dpA_dwn'] = matrix_dpA_dwn
            variables_res['dqA_up'] = matrix_dqA_up
            variables_res['dqA_dwn'] = matrix_dqA_dwn
            variables_res['dpA_res_up'] = matrix_dpA_res_up
            variables_res['dpA_res_dwn'] = matrix_dpA_res_dwn
            variables_res['dqA_res_up'] = matrix_dqA_res_up
            variables_res['dqA_res_dwn'] = matrix_dqA_res_dwn

        except Exception as error:
            raise UserWarning('An error occurred:', type(error).__name__, '–', error)

        if _flag_res:
            _root_res = name_model
            new_folder = os.path.join(os.path.abspath(_out_root), _root_res)
            if not os.path.exists(new_folder):
                os.makedirs(new_folder)
            # Save variables into dictionary

            with pd.ExcelWriter(os.path.join(new_folder, name_model + '_res.xlsx')) as writer:
                if type(variables_res) is dict:
                    for _k, _v in variables_res.items():
                        pd.DataFrame(_v).to_excel(writer, sheet_name=_k)
                else:
                    raise ValueError('Format type {0}.'.format(str(type(variables_res))))

        fsp_info = pd.concat([res_parameters[_i]['fsp_info'] for _i in _fsp_data.type.unique()], axis=1)
        io_file.save_excel(_data=fsp_info, _outroot=_out_root, _filename=_filename_aggr, _sheetname='FSPinfo_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame(variables_res['dpA_up']), _outroot=_out_root, _filename=_filename_aggr, _sheetname='DW_U_Lim_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame(variables_res['dpA_dwn']), _outroot=_out_root, _filename=_filename_aggr, _sheetname='DW_D_Lim_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame(variables_res['dqA_up']), _outroot=_out_root, _filename=_filename_aggr, _sheetname='DR_U_Lim_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame(variables_res['dqA_dwn']), _outroot=_out_root, _filename=_filename_aggr, _sheetname='DR_D_Lim_' + _aggr_name, _mode='a')

        io_file.save_excel(_data=pd.DataFrame([_fsp_data.Pup_cost.max()]), _outroot=_out_root, _filename=_filename_aggr, _sheetname='W_U_Cost_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame([_fsp_data.Pdown_cost.max()]), _outroot=_out_root, _filename=_filename_aggr, _sheetname='W_D_Cost_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame([_fsp_data.Qup_cost.max()]), _outroot=_out_root, _filename=_filename_aggr, _sheetname='R_U_Cost_' + _aggr_name, _mode='a')
        io_file.save_excel(_data=pd.DataFrame([_fsp_data.Qdown_cost.max()]), _outroot=_out_root, _filename=_filename_aggr, _sheetname='R_D_Cost_' + _aggr_name, _mode='a')
    else:
        d = solver_status.status_names()
        raise Warning('Optimization was stopped with status: {_stat}'.format(_stat=d[status]))

    return True


def aggregator_converter(_data, _dict_modules, _fsp_filename, _k_opt=1):
    """
    Adapt the FSP info from different resources aggregated into usable data for the local flexibility market
    optimization.


    :param _data: Dictionary containing all the information useful for the conversion into usable data. The useful data
        are the pandapower network (net), the dictionary with the timeseries simulation (ts_res), the dataframe with the fsp
        data involved in the simulation (fsp_data), the output root where to save files (out_root), the list of hours with
        network constraint violations (hours), the bidding strategy of the fsp element (bid_strat), the multiplier
        coefficient of the load (scen_factor_load), the multiplier coefficient of the generation (scen_factor_gen),
        the active power bid up coefficient (kbid_p_up), the active power bid down coefficient (kbid_p_dwn),
        the reactive power bid up coefficient (kbid_q_up), the reactive power down up coefficient (kbid_q_dwn) and
        the simulation tag (sim_tag).


    :param _k_opt: Margin for bidding below the full capacity - Safe for optimization convergence.

    """
    _filename_res = ''
    _bus_out = list()
    _sim_tag = _data['sim_tag']
    _fsp_data = _data['fsp_data']
    _fsp_dict_additional_files = _data['fsp_additional_file_dict']
    for _i in _fsp_data.type.unique():
        list_res = _dict_modules.get(_i, None)
        # Add additional information for FSP Type
        _data['fsp_additional_file'] = _fsp_dict_additional_files.get(_i, None)
        # Create name of the file FSP

        if list_res is None:
            raise IOError('Resource of type {_class} is unknown.'.format(_class=_i))

        res_lib = importlib.import_module(f'enginiite.market.models.{list_res}')
        _filename_res, bus_res = res_lib.fsp_converter(_data=_data, _k_opt=_k_opt, _class_fsp=_i, _fsp_filename=_fsp_filename)

        _bus_out.extend(bus_res)
    return _filename_res, _bus_out
