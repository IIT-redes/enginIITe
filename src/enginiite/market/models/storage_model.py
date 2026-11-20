import os
import math
import pathlib
import logging
import numpy as np
import pandas as pd
import gurobipy as gp
from tqdm.auto import tqdm
from gurobipy import GRB, tuplelist
from enginiite import file_io as io_file
from enginiite.market import solver_status
from enginiite.market.models.fsp_utils import fsp_bus_series, fsp_frame, fsp_labels, match_pp_element
from enginiite.market.models import headroom as headroom_lib


def _eval_asybid(_n_fsp, _simperiod, _fsp_data, _type='C'):
    """Evaluate the symmetry of bid for the Flexibility Service Provider type C (Storage)."""
    _fsp_data['DW_U_inj'] = np.zeros((_n_fsp, len(_simperiod)))
    _fsp_data['DW_D_inj'] = np.zeros((_n_fsp, len(_simperiod)))
    _fsp_data['DW_U_ads'] = np.zeros((_n_fsp, len(_simperiod)))
    _fsp_data['DW_D_ads'] = np.zeros((_n_fsp, len(_simperiod)))
    for t in range(len(_simperiod)):
        for i in range(_n_fsp):
            if _fsp_data['Winit'].iloc[i, t] >= 0:
                # Generator
                _fsp_data['DW_U_inj'][i, t] = _fsp_data['Wub'].iloc[i, t] - _fsp_data['Winit'].iloc[i, t]
                _fsp_data['DW_D_inj'][i, t] = min([_fsp_data['Winit'].iloc[i, t], _fsp_data['Winit'].iloc[i, t] - _fsp_data['Wlb'].iloc[i, t]])
                _fsp_data['DW_U_ads'][i, t] = 0
                _fsp_data['DW_D_ads'][i, t] = abs(min([0, _fsp_data['Wlb'].iloc[i, t]]))
            else:
                # Load
                _fsp_data['DW_U_inj'][i, t] = max([_fsp_data['Wub'].iloc[i, t] - _fsp_data['Winit'].iloc[i, t], _fsp_data['Wub'].iloc[i, t]])
                _fsp_data['DW_D_inj'][i, t] = 0
                _fsp_data['DW_U_ads'][i, t] = abs(min([_fsp_data['Winit'].iloc[i, t], _fsp_data['Wub'].iloc[i, t] - _fsp_data['Winit'].iloc[i, t]]))
                _fsp_data['DW_D_ads'][i, t] = abs(_fsp_data['Wlb'].iloc[i, t] - _fsp_data['Winit'].iloc[i, t])
    # Storage bid-capacity components are magnitudes used by non-negative
    # up/down variables. Keep them non-negative even when input bounds are
    # saturated or inconsistent with the initial operating point.
    for _key in ['DW_U_inj', 'DW_D_inj', 'DW_U_ads', 'DW_D_ads']:
        _fsp_data[_key] = np.maximum(_fsp_data[_key], 0)
    return _fsp_data


def res_params(_n_fsp, _sim_period, _fsp_data, _type='C'):
    """
    Define Input Data of the Load Resource.
    :param _n_fsp: Number of FSP of type Load resource.
    :param _sim_period: List of hours to consider for the study.
    :param _fsp_data: Dictionary of the Data associated
    """
    fsp_data = dict()
    # Save Data that are Impose to GENERATION Convention and can be changed to LOAD Convention
    ess_conv = ['DR_', 'R_', 'DW_', 'W_', 'Winj_', 'Wads_', 'RATIO_'] # Wads_C is internally negative absorption and should be reported as a positive charging magnitude.
    if _n_fsp > 0:
        # Reactive Power
        fsp_data['Rinit'] = _fsp_data['Rinit_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Active Power
        fsp_data['Winit'] = _fsp_data['Winit_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Nameplate Apparent Power of the Resources [MVA]
        fsp_data['mva'] = _fsp_data['FSPinfo_' + _type].mva.to_numpy()
        # Cost for Reactive Power UPWARD Support Provision [€/MVArh] for each Resource
        fsp_data['RU_cost'] = _fsp_data['R_U_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Reactive Power DOWNWARD Support Provision [€/MVArh] for each Resource
        fsp_data['RD_cost'] = _fsp_data['R_D_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Lower Bound Active Power (Minimum Active Power ABSORPTION Value admitted by the Resource)
        fsp_data['Wub'] = _fsp_data['WUB_ULim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound Active Power (Maximum Active Power INJECTION Value admitted by the Resource)
        fsp_data['Wlb'] = _fsp_data['WLB_DLim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Value Quantity for the Upward Offer
        fsp_data['Rub'] = _fsp_data['RUB_ULim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Value Quantity for the Upward Offer
        fsp_data['Rlb'] = _fsp_data['RUB_DLim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Lower Bound Cosphi Value (Minimum Cosphi Value admitted by the Resource)
        fsp_data['COSPHILB'] = _fsp_data['COSPHILB_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound Cosphi Value (Maximum Cosphi Value admitted by the Resource)
        fsp_data['COSPHIUB'] = _fsp_data['COSPHIUB_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # SoC Initial Value
        fsp_data['SoCinit'] = _fsp_data['SoCinit_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Efficiency in Injective Active Power
        fsp_data['NI_inj'] = _fsp_data['NIinj_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Efficiency in Absorbing Active Power
        fsp_data['NI_ads'] = _fsp_data['NIads_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Efficiency in Reactive Power Exchange
        fsp_data['NI_q'] = _fsp_data['NIq_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # INJECTION Cost for Active Power UPWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WU_inj_cost'] = _fsp_data['W_U_inj_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # INJECTION Cost for Active Power DOWNWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WD_inj_cost'] = _fsp_data['W_D_inj_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # ABSORPTION Cost for Active Power UPWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WU_ads_cost'] = _fsp_data['W_U_ads_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # ABSORPTION Cost for Active Power DOWNWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WD_ads_cost'] = _fsp_data['W_D_ads_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Lower Bound SoC Value
        fsp_data['SoC_lb'] = _fsp_data['SoCLB_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound SoC Value
        fsp_data['SoC_ub'] = _fsp_data['SoCUB_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Lower Bound Tanphi
        fsp_data['TANPHI_LB'] = np.tan(np.arccos(fsp_data['COSPHIUB']))
        # Upper Bound Tanphi
        fsp_data['TANPHI_UB'] = np.tan(np.arccos(fsp_data['COSPHILB']))
        # Evaluate the Asymmetry of Bids
        fsp_data = _eval_asybid(_n_fsp, _sim_period, fsp_data, _type)
    else:
        fsp_data['mva'] = np.zeros(shape=(1, 1))
        _zero_df = pd.DataFrame(np.zeros(shape=(1, len(_sim_period))))
        fsp_data['Rinit'] = _zero_df
        fsp_data['Winit'] = _zero_df
        fsp_data['RD_cost'] = _zero_df
        fsp_data['RU_cost'] = _zero_df
        fsp_data['Wub'] = _zero_df
        fsp_data['Wlb'] = _zero_df
        fsp_data['Rub'] = _zero_df
        fsp_data['Rlb'] = _zero_df
        fsp_data['COSPHILB'] = _zero_df
        fsp_data['COSPHIUB'] = _zero_df
        fsp_data['TANPHI_LB'] = _zero_df
        fsp_data['TANPHI_UB'] = _zero_df
        fsp_data['SoC_lb'] = _zero_df
        fsp_data['SoC_ub'] = _zero_df
        fsp_data['SoCinit'] = _zero_df
        fsp_data['NI_inj'] = _zero_df
        fsp_data['NI_ads'] = _zero_df
        fsp_data['NI_q'] = _zero_df
        fsp_data['WU_inj_cost'] = _zero_df
        fsp_data['WD_inj_cost'] = _zero_df
        fsp_data['WU_ads_cost'] = _zero_df
        fsp_data['WD_ads_cost'] = _zero_df
        fsp_data['DW_U_inj'] = _zero_df
        fsp_data['DW_D_inj'] = _zero_df
        fsp_data['DW_U_ads'] = _zero_df
        fsp_data['DW_D_ads'] = _zero_df
    return fsp_data, ess_conv


def define_variables(_grb_model, _n_fsp, _n_t, _contr, _type='C'):
    """
    Define Variables of the Load Resource selecting the more appropriate/updated function.
    :param _grb_model: Object that represents the gurobipy model.
    :param _n_fsp: Number of flexibility service providers.
    :param _n_t: Number of intervals.
    :param _contr: Contribution of these resource type.
    :param _type: Type of resource.
    """
    _vars_dict = storage_variables_v1(grb_model=_grb_model, n_fsp=_n_fsp, n_t=_n_t, _contr=_contr, _type=_type)
    return _vars_dict


def storage_variables_v0(grb_model, n_fsp, n_t, _contr, _type='C'):
    """Define Variables of the Storage Resource."""
    shape_var = (n_fsp, n_t)
    _vars_dict = dict()
    # Delta Reactive Power Exchange [p.u.]
    DR_C = grb_model.addMVar(shape=shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DR_' + _type)
    _vars_dict['DR_' + _type] = DR_C
    # After the Market Reactive Power Exchange
    R_C = grb_model.addMVar(shape=shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='R_' + _type)
    _vars_dict['R_' + _type] = R_C
    # Delta Active Power [p.u.]
    DW_C = grb_model.addMVar(shape=shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DW_' + _type)
    _vars_dict['DW_' + _type] = DW_C
    # Delta Active Power Absorption for type C (batteries) [p.u.]
    DWads_C = grb_model.addMVar(shape=shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DWads_' + _type)
    _vars_dict['DWads_' + _type] = DWads_C
    # Delta Active Power Injection for type C (batteries) [p.u.]
    DWinj_C = grb_model.addMVar(shape=shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DWinj_' + _type)
    _vars_dict['DWinj_' + _type] = DWinj_C
    # variable: active power adsorption (in per unit) for batteries (type C)
    Wads_C = grb_model.addMVar(shape=shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='Wads_' + _type)
    _vars_dict['Wads_' + _type] = Wads_C
    # variable: active power injection (in per unit) for batteries (type C)
    Winj_C = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='Winj_' + _type)
    _vars_dict['Winj_' + _type] = Winj_C
    # variable: after the market State of Charge for batteries (type C) [energy KWh]
    SOC_C = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='SOC_' + _type)
    _vars_dict['SOC_' + _type] = SOC_C
    # After the Market Active Power
    W_C = grb_model.addMVar(shape=shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='W_' + _type)
    _vars_dict['W_' + _type] = W_C
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    RATIO_C = grb_model.addMVar(shape=shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='RATIO_' + _type)
    _vars_dict['RATIO_' + _type] = RATIO_C
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_C = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='qSMVA_' + _type)
    _vars_dict['qSMVA_' + _type] = qSMVA_C
    # Companion variables - necessary in gurobi to include ABSOLUTE values in the objective function
    ABS_DR_C = grb_model.addMVar(shape=shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_DR_' + _type)
    _vars_dict['ABS_DR_' + _type] = ABS_DR_C
    ABS_R_C = grb_model.addMVar(shape=shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_R_' + _type)
    _vars_dict['ABS_R_' + _type] = ABS_R_C
    ABS_DWads_C = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ABS_DWads_' + _type)
    _vars_dict['ABS_DWads_' + _type] = ABS_DWads_C
    ABS_DWinj_C = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ABS_DWinj_' + _type)
    _vars_dict['ABS_DWinj_' + _type] = ABS_DWinj_C
    ABS_RATIO_C = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ABS_RATIO_' + _type)
    _vars_dict['ABS_RATIO_' + _type] = ABS_RATIO_C
    # Variables for the Asymmetry of the Bids
    DW_C_U = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U')
    _vars_dict['DW_' + _type + '_U'] = DW_C_U
    DW_C_D = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D')
    _vars_dict['DW_' + _type + '_D'] = DW_C_D
    DW_C_U_inj = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U_inj')
    _vars_dict['DW_' + _type + '_U_inj'] = DW_C_U_inj
    DW_C_D_inj = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D_inj')
    _vars_dict['DW_' + _type + '_D_inj'] = DW_C_D_inj
    DW_C_U_ads = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U_ads')
    _vars_dict['DW_' + _type + '_U_ads'] = DW_C_U_ads
    DW_C_D_ads = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D_ads')
    _vars_dict['DW_' + _type + '_D_ads'] = DW_C_D_ads
    DR_C_U = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_U')
    _vars_dict['DR_' + _type + '_U'] = DR_C_U
    DR_C_D = grb_model.addMVar(shape=shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_D')
    _vars_dict['DR_' + _type + '_D'] = DR_C_D
    # Binary Variables
    b1_C = grb_model.addMVar(shape=shape_var, vtype=GRB.BINARY, name='b1_' + _type)
    _vars_dict['b1_' + _type] = b1_C
    b2_C = grb_model.addMVar(shape=shape_var, vtype=GRB.BINARY, name='b2_' + _type)
    _vars_dict['b2_' + _type] = b2_C
    b3_C = grb_model.addMVar(shape=shape_var, vtype=GRB.BINARY, name='b3_' + _type)
    _vars_dict['b3_' + _type] = b3_C
    b4_C = grb_model.addMVar(shape=shape_var, vtype=GRB.BINARY, name='b4_' + _type)
    _vars_dict['b4_' + _type] = b4_C
    return _vars_dict


def storage_variables_v1(grb_model, n_fsp, n_t, _contr, _type='C'):
    """Define Variables of the Storage Resource."""
    shape_var = tuplelist([(_f, _t) for _f in range(n_fsp) for _t in range(n_t)])
    _vars_dict = dict()
    # Delta Reactive Power Exchange [p.u.]
    DR_C = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DR_' + _type)
    _vars_dict['DR_' + _type] = DR_C
    # After the Market Reactive Power Exchange
    R_C = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='R_' + _type)
    _vars_dict['R_' + _type] = R_C
    # Delta Active Power [p.u.]
    DW_C = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DW_' + _type)
    _vars_dict['DW_' + _type] = DW_C
    # Delta Active Power Absorption for type C (batteries) [p.u.]
    DWads_C = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DWads_' + _type)
    _vars_dict['DWads_' + _type] = DWads_C
    # Delta Active Power Injection for type C (batteries) [p.u.]
    DWinj_C = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DWinj_' + _type)
    _vars_dict['DWinj_' + _type] = DWinj_C
    # variable: active power adsorption (in per unit) for batteries (type C)
    Wads_C = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='Wads_' + _type)
    _vars_dict['Wads_' + _type] = Wads_C
    # variable: active power injection (in per unit) for batteries (type C)
    Winj_C = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='Winj_' + _type)
    _vars_dict['Winj_' + _type] = Winj_C
    # variable: after the market State of Charge for batteries (type C) [energy KWh]
    SOC_C = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='SOC_' + _type)
    _vars_dict['SOC_' + _type] = SOC_C
    # After the Market Active Power
    W_C = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='W_' + _type)
    _vars_dict['W_' + _type] = W_C
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    RATIO_C = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='RATIO_' + _type)
    _vars_dict['RATIO_' + _type] = RATIO_C
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_C = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='qSMVA_' + _type)
    _vars_dict['qSMVA_' + _type] = qSMVA_C
    # Companion variables - necessary in gurobi to include ABSOLUTE values in the objective function
    ABS_DR_C = grb_model.addVars(shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_DR_' + _type)
    _vars_dict['ABS_DR_' + _type] = ABS_DR_C
    ABS_R_C = grb_model.addVars(shape_var, lb=0, ub=_contr, vtype=GRB.CONTINUOUS, name='ABS_R_' + _type)
    _vars_dict['ABS_R_' + _type] = ABS_R_C
    ABS_DWads_C = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ABS_DWads_' + _type)
    _vars_dict['ABS_DWads_' + _type] = ABS_DWads_C
    ABS_DWinj_C = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ABS_DWinj_' + _type)
    _vars_dict['ABS_DWinj_' + _type] = ABS_DWinj_C
    ABS_RATIO_C = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ABS_RATIO_' + _type)
    _vars_dict['ABS_RATIO_' + _type] = ABS_RATIO_C
    # Variables for the Asymmetry of the Bids
    DW_C_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U')
    _vars_dict['DW_' + _type + '_U'] = DW_C_U
    DW_C_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D')
    _vars_dict['DW_' + _type + '_D'] = DW_C_D
    DW_C_U_inj = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U_inj')
    _vars_dict['DW_' + _type + '_U_inj'] = DW_C_U_inj
    DW_C_D_inj = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D_inj')
    _vars_dict['DW_' + _type + '_D_inj'] = DW_C_D_inj
    DW_C_U_ads = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U_ads')
    _vars_dict['DW_' + _type + '_U_ads'] = DW_C_U_ads
    DW_C_D_ads = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D_ads')
    _vars_dict['DW_' + _type + '_D_ads'] = DW_C_D_ads
    DR_C_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_U')
    _vars_dict['DR_' + _type + '_U'] = DR_C_U
    DR_C_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_D')
    _vars_dict['DR_' + _type + '_D'] = DR_C_D
    # Binary Variables
    b1_C = grb_model.addVars(shape_var, vtype=GRB.BINARY, name='b1_' + _type)
    _vars_dict['b1_' + _type] = b1_C
    b2_C = grb_model.addVars(shape_var, vtype=GRB.BINARY, name='b2_' + _type)
    _vars_dict['b2_' + _type] = b2_C
    b3_C = grb_model.addVars(shape_var, vtype=GRB.BINARY, name='b3_' + _type)
    _vars_dict['b3_' + _type] = b3_C
    b4_C = grb_model.addVars(shape_var, vtype=GRB.BINARY, name='b4_' + _type)
    _vars_dict['b4_' + _type] = b4_C
    return _vars_dict


def define_constraints(_grb_model, _vars_dict, _fsp_data, _idx_res, _interval, _cap_cstr, _int_soc=True, _dt=1, _type='C'):
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
    grb_model = storage_constraints_v1(grb_model=_grb_model, _vars_dict=_vars_dict, fsp_data=_fsp_data, i=_idx_res,
                                       t=_interval, _cap_cstr=_cap_cstr, _int_soc=_int_soc, _dt=_dt, _type=_type)
    return grb_model


def storage_constraints_v0(grb_model, _vars_dict, fsp_data, i, t, _cap_cstr, _int_soc, _dt=1, _type='C'):
    """Define Constraints of the Storage Resource."""
    # Delta Reactive Power Exchange [p.u.]
    DR_C = _vars_dict['DR_' + _type]
    # Absolute values of Delta Reactive Power Exchange
    ABS_DR_C = _vars_dict['ABS_DR_' + _type]
    # After the Market Reactive Power Exchange
    R_C = _vars_dict['R_' + _type]
    # Delta Active Power [p.u.]
    DW_C = _vars_dict['DW_' + _type]
    # After the Market Active Power
    W_C = _vars_dict['W_' + _type]
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_C = _vars_dict['qSMVA_' + _type]
    # variable: active power adsorption (in per unit) for batteries (type C)
    Wads_C = _vars_dict['Wads_' + _type]
    # variable: Delta active power adsorption (in per unit) for batteries (type C)
    DWads_C = _vars_dict['DWads_' + _type]
    # variable: Absolute values of Delta active power adsorption for batteries (type C)
    ABS_DWads_C = _vars_dict['ABS_DWads_' + _type]
    # variable: active power injection (in per unit) for batteries (type C)
    Winj_C = _vars_dict['Winj_' + _type]
    # variable: Delta active power injection (in per unit) for batteries (type C)
    DWinj_C = _vars_dict['DWinj_' + _type]
    # variable: Absolute values of Delta active power injection for batteries (type C)
    ABS_DWinj_C = _vars_dict['ABS_DWinj_' + _type]
    # variable: after the market State of Charge for batteries (type C) [energy KWh]
    SOC_C = _vars_dict['SOC_' + _type]
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    RATIO_C = _vars_dict['RATIO_' + _type]
    # Companion variables - necessary in gurobi to include ABSOLUTE values in the objective function
    ABS_R_C = _vars_dict['ABS_R_' + _type]
    ABS_RATIO_C = _vars_dict['ABS_RATIO_' + _type]
    # Variables for the Asymmetry of the Bids
    DW_C_U = _vars_dict['DW_' + _type + '_U']
    DW_C_D = _vars_dict['DW_' + _type + '_D']
    DW_C_U_inj = _vars_dict['DW_' + _type + '_U_inj']
    DW_C_D_inj = _vars_dict['DW_' + _type + '_D_inj']
    DW_C_U_ads = _vars_dict['DW_' + _type + '_U_ads']
    DW_C_D_ads = _vars_dict['DW_' + _type + '_D_ads']
    DR_C_U = _vars_dict['DR_' + _type + '_U']
    DR_C_D = _vars_dict['DR_' + _type + '_D']
    # Binary Variables
    b1_C = _vars_dict['b1_' + _type]
    b2_C = _vars_dict['b2_' + _type]
    b3_C = _vars_dict['b3_' + _type]
    b4_C = _vars_dict['b4_' + _type]

    _idx_dr = 0
    for x, y in zip(DR_C.tolist(), ABS_DR_C.tolist()):
        _idx_dr_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_dr = 'abs_dr_' + _type + '_#' + str(_idx_dr) + '_t' + str(_idx_dr_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_dr)
            _idx_dr_t += 1
        _idx_dr += 1

    _idx_dWads = 0
    for x, y in zip(DWads_C.tolist(), ABS_DWads_C.tolist()):
        _idx_dWads_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_wads = 'abs_wads_' + _type + '_#' + str(_idx_dWads) + '_t' + str(_idx_dWads_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_wads)
            _idx_dWads_t += 1
        _idx_dWads += 1

    _idx_dWinj = 0
    for x, y in zip(DWinj_C.tolist(), ABS_DWinj_C.tolist()):
        _idx_dWinj_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_winj = 'abs_winj_' + _type + '_#' + str(_idx_dWinj) + '_t' + str(_idx_dWinj_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_winj)
            _idx_dWinj_t += 1
        _idx_dWinj += 1

    _idx_ratio = 0
    for x, y in zip(RATIO_C.tolist(), ABS_RATIO_C.tolist()):
        _idx_ratio_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_ratio = 'abs_ratio_' + _type + '_#' + str(_idx_ratio) + '_t' + str(_idx_ratio_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_ratio)
            _idx_ratio_t += 1
        _idx_ratio += 1

    _idx_r = 0
    for x, y in zip(R_C.tolist(), ABS_R_C.tolist()):
        _idx_r_t = 0
        for x1, y1 in zip(x, y):
            _name_abs_r = 'abs_r_' + _type + '_#' + str(_idx_r) + '_t' + str(_idx_r_t)
            grb_model.addGenConstrAbs(y1, x1, name=_name_abs_r)
            _idx_r += 1
        _idx_r += 1

    _name_W = 'C#05c_W_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_C[i, t] - DW_C[i, t] - fsp_data['Winit'].iloc[i, t] == 0, name=_name_W)
    # TODO: The following constraint can be rewritten as: R - Dr - Rinit = 0,
    #  since moving all terms from the left-hand side to the right-hand side will change their sign
    #  and the constraint result remains unchanged.
    _name_R = 'C#05_R_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(-R_C[i, t] + DR_C[i, t] + fsp_data['Rinit'].iloc[i, t] == 0, name=_name_R)

    if _cap_cstr:
        _name_q_cstr = 'C#05a_' + _type + '_NORM(SMVA)_' + str(i) + '_t' + str(t)
        grb_model.addConstr(W_C[i, t] ** 2 + R_C[i, t] ** 2 - qSMVA_C[i, t] == 0, name=_name_q_cstr)
        _name_q_cstr2 = 'C#05a_' + _type + '_SMAX_limit' + str(i) + '_t' + str(t)
        grb_model.addConstr(qSMVA_C[i, t] - fsp_data['mva'][i] ** 2 <= 0, name=_name_q_cstr2)
        # Power Factor limits
        _name_pf_limit = 'C#05b_TANPHI_' + _type + '_' + str(i) + '_t' + str(t)
        grb_model.addConstr(W_C[i, t] * RATIO_C[i, t] - R_C[i, t] == 0, name=_name_pf_limit)
        _name_tan_lb = 'C#05b_TANPHI_' + _type + '_LowerLimit_' + str(i) + '_t' + str(t)
        grb_model.addConstr(ABS_RATIO_C[i, t] - fsp_data['TANPHI_LB'].iloc[i, t] >= 0, name=_name_tan_lb)
        _name_tan_ub = 'C#05b_TANPHI_' + _type + '_UpperLimit_' + str(i) + '_t' + str(t)
        grb_model.addConstr(ABS_RATIO_C[i, t] - fsp_data['TANPHI_UB'].iloc[i, t] <= 0, name=_name_tan_ub)

    # Model with Upper and Lower Bounds for Q/P=TanPhi Ratio
    # FSPC_WUB stays on the far right in the x-axis - zero is included in FSPC_WLB < 0 < FSPC_WUB
    _name_w_ub = 'C#05b_W_' + _type + '_UpperLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_C[i, t] - fsp_data['Wub'].iloc[i, t] <= 0, name=_name_w_ub)
    # FSPC_WUB stays on the fart left in the x-axis - zero is included in FSPC_WLB < 0 < FSPC_WUB
    _name_w_lb = 'C#05b_W_' + _type + '_LowerLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_C[i, t] - fsp_data['Wlb'].iloc[i, t] >= 0, name=_name_w_lb)

    # Definition of Upward and Downward Delta R contributions
    _name_dr = 'C#07a_DR_C_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_C_U[i, t] - DR_C_D[i, t] - DR_C[i, t] == 0, name=_name_dr)
    # FSPC_WUB stays on the far right in the x-axis - zero is included in FSPC_WLB<0<FSPC_WUB
    _name_r_ub = 'C#05b_R_' + _type + '_UpperLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(R_C[i, t] - fsp_data['Rub'].iloc[i, t] <= 0, name=_name_r_ub)
    # FSPC_WUB stays on the fart left in the x-axis - zero is included in FSPC_WLB<0<FSPC_WUB
    _name_r_lb = 'C#05b_R_' + _type + '_LowerLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(R_C[i, t] - fsp_data['Rlb'].iloc[i, t] >= 0, name=_name_r_lb)

    if _int_soc:
        if t == 0:
            _name_soc_t0 = 'C#05_FSP_' + _type + '_SoC_update_tx_' + str(i) + '_t' + str(t)
            grb_model.addConstr((fsp_data['SoCinit'].iloc[i, t] + (-Wads_C[i, t] * fsp_data['NI_ads'].iloc[i, t] * b2_C[i, t]
                                  - b1_C[i, t] * Winj_C[i, t] / fsp_data['NI_inj'].iloc[i, t]
                                - ABS_R_C[i, t] * (1 - fsp_data['NI_q'].iloc[i, t])) * _dt) - SOC_C[i, t] == 0, name=_name_soc_t0)
        else:
            _name_soc_t = 'C#05_FSP_' + _type + '_SoC_update_tx_' + str(i) + '_t' + str(t)
            grb_model.addConstr((SOC_C[i, t - 1] + (-Wads_C[i, t] * fsp_data['NI_ads'].iloc[i, t] * b2_C[i, t]
                                  - b1_C[i, t] * Winj_C[i, t] / fsp_data['NI_inj'].iloc[i, t]
                                  - ABS_R_C[i, t] * (1 - fsp_data['NI_q'].iloc[i, t])) * _dt) - SOC_C[i, t] == 0, name=_name_soc_t)

        # TODO: this constraints can be removed if we set the upper and lower bounds of SoC
        #  at the moment when we create the variable SoC
        _name_soc_min = 'C#05a_FSP_' + _type + '_SoC_LB_' + str(i) + '_t' + str(t)
        grb_model.addConstr(SOC_C[i, t] - fsp_data['SoC_lb'].iloc[i, t] >= 0, name=_name_soc_min)
        _name_soc_max = 'C#05b_FSP_' + _type + '_SoC_UB_' + str(i) + '_t' + str(t)
        grb_model.addConstr(SOC_C[i, t] - fsp_data['SoC_ub'].iloc[i, t] <= 0, name=_name_soc_max)

    # Constrains for the Asymmetry of Bids
    # Definition of Upward and Downward DELTA W contributions
    _name_dw = 'C#07a_DW_' + _type + '_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_C_U[i, t] - DW_C_D[i, t] - DW_C[i, t] == 0, name=_name_dw)
    # Binary Constraints for W output
    _name_w_binary = 'C#05a_' + _type + '_Winjetting_' + str(i) + '_t' + str(t)
    grb_model.addConstr((Winj_C[i, t] * b1_C[i, t] + Wads_C[i, t] * b2_C[i, t]) - W_C[i, t] == 0, name=_name_w_binary)
    _name_b12 = 'C#05a_' + _type + '_b1+b2_' + str(i) + '_t' + str(t)
    grb_model.addConstr(b1_C[i, t] + b2_C[i, t] == 1, name=_name_b12)

    _name_winj_max = 'C#05a_Winj_' + _type + '_boundB01_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Winj_C[i, t] - b1_C[i, t] * fsp_data['Wub'].iloc[i, t] <= 0, name=_name_winj_max)
    _name_winj_min = 'C#05a_Winj_' + _type + '_boundB02_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Winj_C[i, t] >= 0, name=_name_winj_min)
    _name_wads_max = 'C#05a_Wads_' + _type + '_boundB03_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wads_C[i, t] <= 0, name=_name_wads_max)
    _name_wads_min = 'C#05a_Wads_' + _type + '_boundB04_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wads_C[i, t] - b2_C[i, t] * fsp_data['Wlb'].iloc[i, t] >= 0, name=_name_wads_min)

    # Electric Vehicle Asymmetry bid mode ON
    # Differentiated Cost of Downward and Upward Flexibility Between Generation and Consumption
    if fsp_data['Winit'].iloc[i, t] >= 0:
        _name_dw_d_cond = 'C#05a_DW_' + _type + '_D_Condition_' + str(i) + '_t' + str(t)
        grb_model.addConstr(
            (DW_C_D_inj[i, t] * b3_C[i, t] + (DW_C_D_ads[i, t] + fsp_data['Winit'].iloc[i, t]) * b4_C[i, t])
            - DW_C_D[i, t] == 0, name=_name_dw_d_cond)
        _name_b34 = 'C#05a_' + _type + '_b3+b4_' + str(i) + '_t' + str(t)
        grb_model.addConstr(b3_C[i, t] + b4_C[i, t] == 1, name=_name_b34)

        _name_dWinj_true = 'C#05a_DW_' + _type + '_D_inj_TRUE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], True, DW_C_D_inj[i, t], GRB.EQUAL, fsp_data['Winit'].iloc[i, t], name=_name_dWinj_true)
        _name_dWinj_false = 'C#05a_DW_' + _type + '_D_inj_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_D_inj[i, t] - DW_C_D[i, t], GRB.EQUAL, 0, name=_name_dWinj_false)
        _name_dWads_false = 'C#05a_DW_' + _type + '_D_ads_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_D_ads[i, t], GRB.EQUAL, 0, name=_name_dWads_false)

        _name_dWinj_eq = 'C#05a_DW_' + _type + '_U_inj_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_U_inj[i, t] - DW_C_U[i, t] == 0, name=_name_dWinj_eq)
        _name_dWads_eq = 'C#05a_DW_' + _type + '_U_ads_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_U_ads[i, t] == 0, name=_name_dWads_eq)
    else:
        _name_dw_u_cond = 'C#05a_DW_' + _type + '_U_Condition_' + str(i) + '_t' + str(t)
        grb_model.addConstr(
            (DW_C_U_ads[i, t] * b3_C[i, t] + (DW_C_U_inj[i, t] + abs(fsp_data['Winit'].iloc[i, t])) * b4_C[i, t])
            - DW_C_U[i, t] == 0, name=_name_dw_u_cond)
        _name_b34 = 'C#05a_' + _type + '_b3+b4_' + str(i) + '_t' + str(t)
        grb_model.addConstr(b3_C[i, t] + b4_C[i, t] == 1, name=_name_b34)

        _name_dWads_true = 'C#05a_DW_' + _type + '_U_ads_TRUE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], True, DW_C_U_ads[i, t], GRB.EQUAL, -fsp_data['Winit'].iloc[i, t], name=_name_dWads_true)
        _name_dWads_false = 'C#05a_DW_' + _type + '_U_ads_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_U_ads[i, t] - DW_C_U[i, t], GRB.EQUAL, 0, name=_name_dWads_false)
        _name_dWinj_false = 'C#05a_DW_' + _type + '_U_inj_c02_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_U_inj[i, t], GRB.EQUAL, 0, name=_name_dWinj_false)

        _name_dWads_eq = 'C#05a_DW_' + _type + '_U_ads_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_D_ads[i, t] - DW_C_D[i, t] == 0, name=_name_dWads_eq)
        _name_dWinj_eq = 'C#05a_DW_' + _type + '_U_inj_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_D_inj[i, t] == 0, name=_name_dWinj_eq)

    # fixme: 'TO FORCE THE SOLUTION WHEN ONLY P OR ONLY Q AND VOID FLAT SOLUTIONS'.
    #  Why only available for the VC market?
    if fsp_data['Wlb'].iloc[i, t] == fsp_data['Wub'].iloc[i, t]:
        _name_onlyQ_dW_u = 'C#06a_C_force_onlyQ_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_U[i, t] == 0, name=_name_onlyQ_dW_u)
        _name_onlyQ_dW_d = 'C#06b_C_force_onlyQ_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_D[i, t] == 0, name=_name_onlyQ_dW_d)
    if fsp_data['Rub'].iloc[i, t] == fsp_data['Rlb'].iloc[i, t]:
        _name_onlyP_dR_u = 'C#06a_C_force_onlyP_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DR_C_U[i, t] == 0, name=_name_onlyP_dR_u)
        _name_onlyP_dR_d = 'C#06b_C_force_onlyP_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DR_C_D[i, t] == 0, name=_name_onlyP_dR_d)
    return grb_model


def storage_constraints_v1(grb_model, _vars_dict, fsp_data, i, t, _cap_cstr, _int_soc, _dt=1, _type='C'):
    """Define Constraints of the Storage Resource."""
    # Delta Reactive Power Exchange [p.u.]
    DR_C = _vars_dict['DR_' + _type]
    # Absolute values Delta Reactive Power Exchange
    ABS_DR_C = _vars_dict['ABS_DR_' + _type]
    # After the Market Reactive Power Exchange
    R_C = _vars_dict['R_' + _type]
    # Delta Active Power [p.u.]
    DW_C = _vars_dict['DW_' + _type]
    # After the Market Active Power
    W_C = _vars_dict['W_' + _type]
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    qSMVA_C = _vars_dict['qSMVA_' + _type]
    # variable: active power adsorption (in per unit) for batteries (type C)
    Wads_C = _vars_dict['Wads_' + _type]
    # variable: Delta active power adsorption (in per unit) for batteries (type C)
    DWads_C = _vars_dict['DWads_' + _type]
    # variable: Absolute values of Delta active power adsorption for batteries (type C)
    ABS_DWads_C = _vars_dict['ABS_DWads_' + _type]
    # variable: active power injection (in per unit) for batteries (type C)
    Winj_C = _vars_dict['Winj_' + _type]
    # variable: Delta active power injection (in per unit) for batteries (type C)
    DWinj_C = _vars_dict['DWinj_' + _type]
    # variable: Absolute values of Delta active power injection for batteries (type C)
    ABS_DWinj_C = _vars_dict['ABS_DWinj_' + _type]
    # variable: after the market State of Charge for batteries (type C) [energy KWh]
    SOC_C = _vars_dict['SOC_' + _type]
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    RATIO_C = _vars_dict['RATIO_' + _type]
    # Companion variables - necessary in gurobi to include ABSOLUTE values in the objective function
    ABS_R_C = _vars_dict['ABS_R_' + _type]
    ABS_RATIO_C = _vars_dict['ABS_RATIO_' + _type]
    # Variables for the Asymmetry of the Bids
    DW_C_U = _vars_dict['DW_' + _type + '_U']
    DW_C_D = _vars_dict['DW_' + _type + '_D']
    DW_C_U_inj = _vars_dict['DW_' + _type + '_U_inj']
    DW_C_D_inj = _vars_dict['DW_' + _type + '_D_inj']
    DW_C_U_ads = _vars_dict['DW_' + _type + '_U_ads']
    DW_C_D_ads = _vars_dict['DW_' + _type + '_D_ads']
    DR_C_U = _vars_dict['DR_' + _type + '_U']
    DR_C_D = _vars_dict['DR_' + _type + '_D']
    # Binary Variables
    b1_C = _vars_dict['b1_' + _type]
    b2_C = _vars_dict['b2_' + _type]
    b3_C = _vars_dict['b3_' + _type]
    b4_C = _vars_dict['b4_' + _type]

    _name_abs_dr = 'abs_dr_' + _type + '_#' + str(i) + '_t' + str(t)
    grb_model.addGenConstrAbs(ABS_DR_C[i, t], DR_C[i, t], name=_name_abs_dr)

    _name_abs_wads = 'abs_wads_' + _type + '_#' + str(i) + '_t' + str(t)
    grb_model.addGenConstrAbs(ABS_DWads_C[i, t], DWads_C[i, t], name=_name_abs_wads)

    _name_abs_winj = 'abs_winj_' + _type + '_#' + str(i) + '_t' + str(t)
    grb_model.addGenConstrAbs(ABS_DWinj_C[i, t], DWinj_C[i, t], name=_name_abs_winj)

    _name_abs_ratio = 'abs_ratio_' + _type + '_#' + str(i) + '_t' + str(t)
    grb_model.addGenConstrAbs(ABS_RATIO_C[i, t], RATIO_C[i, t], name=_name_abs_ratio)

    _name_abs_r = 'abs_r_' + _type + '_#' + str(i) + '_t' + str(t)
    grb_model.addGenConstrAbs(ABS_R_C[i, t], R_C[i, t], name=_name_abs_r)

    _name_W = 'C#05c_W_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_C[i, t] - DW_C[i, t] - fsp_data['Winit'].iloc[i, t] == 0, name=_name_W)
    # TODO: The following constraint can be rewritten as: R - Dr - Rinit = 0,
    #  since moving all terms from the left-hand side to the right-hand side will change their sign
    #  and the constraint result remains unchanged.
    _name_R = 'C#05_R_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(-R_C[i, t] + DR_C[i, t] + fsp_data['Rinit'].iloc[i, t] == 0, name=_name_R)

    if _cap_cstr:
        _name_q_cstr = 'C#05a_' + _type + '_NORM(SMVA)_' + str(i) + '_t' + str(t)
        grb_model.addConstr(W_C[i, t] ** 2 + R_C[i, t] ** 2 - qSMVA_C[i, t] == 0, name=_name_q_cstr)
        _name_q_cstr2 = 'C#05a_' + _type + '_SMAX_limit' + str(i) + '_t' + str(t)
        grb_model.addConstr(qSMVA_C[i, t] - fsp_data['mva'][i] ** 2 <= 0, name=_name_q_cstr2)
        # Power Factor limits
        _name_pf_limit = 'C#05b_TANPHI_' + _type + '_' + str(i) + '_t' + str(t)
        grb_model.addConstr(W_C[i, t] * RATIO_C[i, t] - R_C[i, t] == 0, name=_name_pf_limit)
        _name_tan_lb = 'C#05b_TANPHI_' + _type + '_LowerLimit_' + str(i) + '_t' + str(t)
        grb_model.addConstr(ABS_RATIO_C[i, t] - fsp_data['TANPHI_LB'].iloc[i, t] >= 0, name=_name_tan_lb)
        _name_tan_ub = 'C#05b_TANPHI_' + _type + '_UpperLimit_' + str(i) + '_t' + str(t)
        grb_model.addConstr(ABS_RATIO_C[i, t] - fsp_data['TANPHI_UB'].iloc[i, t] <= 0, name=_name_tan_ub)

    # Model with Upper and Lower Bounds for Q/P=TanPhi Ratio
    # FSPC_WUB stays on the far right in the x-axis - zero is included in FSPC_WLB < 0 < FSPC_WUB
    _name_w_ub = 'C#05b_W_' + _type + '_UpperLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_C[i, t] - fsp_data['Wub'].iloc[i, t] <= 0, name=_name_w_ub)
    # FSPC_WUB stays on the fart left in the x-axis - zero is included in FSPC_WLB < 0 < FSPC_WUB
    _name_w_lb = 'C#05b_W_' + _type + '_LowerLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(W_C[i, t] - fsp_data['Wlb'].iloc[i, t] >= 0, name=_name_w_lb)

    # Definition of Upward and Downward Delta R contributions
    _name_dr = 'C#07a_DR_C_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_C_U[i, t] - DR_C_D[i, t] - DR_C[i, t] == 0, name=_name_dr)
    # FSPC_WUB stays on the far right in the x-axis - zero is included in FSPC_WLB < 0 < FSPC_WUB
    _name_r_ub = 'C#05b_R_' + _type + '_UpperLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(R_C[i, t] - fsp_data['Rub'].iloc[i, t] <= 0, name=_name_r_ub)
    # FSPC_WUB stays on the fart left in the x-axis - zero is included in FSPC_WLB < 0 < FSPC_WUB
    _name_r_lb = 'C#05b_R_' + _type + '_LowerLimit_' + str(i) + '_t' + str(t)
    grb_model.addConstr(R_C[i, t] - fsp_data['Rlb'].iloc[i, t] >= 0, name=_name_r_lb)

    if _int_soc:
        if t == 0:
            _name_soc_t0 = 'C#05_FSP_' + _type + '_SoC_update_tx_' + str(i) + '_t' + str(t)
            grb_model.addConstr((fsp_data['SoCinit'].iloc[i, t] + (-Wads_C[i, t] * fsp_data['NI_ads'].iloc[i, t] * b2_C[i, t]
                                  - b1_C[i, t] * Winj_C[i, t] / fsp_data['NI_inj'].iloc[i, t]
                                - ABS_R_C[i, t] * (1 - fsp_data['NI_q'].iloc[i, t])) * _dt) - SOC_C[i, t] == 0, name=_name_soc_t0)
        else:
            _name_soc_t = 'C#05_FSP_' + _type + '_SoC_update_tx_' + str(i) + '_t' + str(t)
            grb_model.addConstr((SOC_C[i, t - 1] + (-Wads_C[i, t] * fsp_data['NI_ads'].iloc[i, t] * b2_C[i, t]
                                  - b1_C[i, t] * Winj_C[i, t] / fsp_data['NI_inj'].iloc[i, t]
                                  - ABS_R_C[i, t] * (1 - fsp_data['NI_q'].iloc[i, t])) * _dt) - SOC_C[i, t] == 0, name=_name_soc_t)

        _name_soc_min = 'C#05a_FSP_' + _type + '_SoC_LB_' + str(i) + '_t' + str(t)
        grb_model.addConstr(SOC_C[i, t] - fsp_data['SoC_lb'].iloc[i, t] >= 0, name=_name_soc_min)
        _name_soc_max = 'C#05b_FSP_' + _type + '_SoC_UB_' + str(i) + '_t' + str(t)
        grb_model.addConstr(SOC_C[i, t] - fsp_data['SoC_ub'].iloc[i, t] <= 0, name=_name_soc_max)

    # Constrains for the Asymmetry of Bids
    # Definition of Upward and Downward DELTA W contributions
    _name_dw = 'C#07a_DW_' + _type + '_Up&Down_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_C_U[i, t] - DW_C_D[i, t] - DW_C[i, t] == 0, name=_name_dw)
    # Binary Constraints for W output
    _name_w_binary = 'C#05a_' + _type + '_Winjetting_' + str(i) + '_t' + str(t)
    grb_model.addConstr((Winj_C[i, t] * b1_C[i, t] + Wads_C[i, t] * b2_C[i, t]) - W_C[i, t] == 0, name=_name_w_binary)
    _name_b12 = 'C#05a_' + _type + '_b1+b2_' + str(i) + '_t' + str(t)
    grb_model.addConstr(b1_C[i, t] + b2_C[i, t] == 1, name=_name_b12)

    _name_winj_max = 'C#05a_Winj_' + _type + '_boundB01_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Winj_C[i, t] - b1_C[i, t] * fsp_data['Wub'].iloc[i, t] <= 0, name=_name_winj_max)
    _name_winj_min = 'C#05a_Winj_' + _type + '_boundB02_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Winj_C[i, t] >= 0, name=_name_winj_min)
    _name_wads_max = 'C#05a_Wads_' + _type + '_boundB03_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wads_C[i, t] <= 0, name=_name_wads_max)
    _name_wads_min = 'C#05a_Wads_' + _type + '_boundB04_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wads_C[i, t] - b2_C[i, t] * fsp_data['Wlb'].iloc[i, t] >= 0, name=_name_wads_min)

    # Electric Vehicle Asymmetry bid mode ON
    # Differentiated Cost of Downward and Upward Flexibility Between Generation and Consumption
    if fsp_data['Winit'].iloc[i, t] >= 0:
        _name_dw_d_cond = 'C#05a_DW_' + _type + '_D_Condition_' + str(i) + '_t' + str(t)
        grb_model.addConstr(
            (DW_C_D_inj[i, t] * b3_C[i, t] + (DW_C_D_ads[i, t] + fsp_data['Winit'].iloc[i, t]) * b4_C[i, t])
            - DW_C_D[i, t] == 0, name=_name_dw_d_cond)
        _name_b34 = 'C#05a_' + _type + '_b3+b4_' + str(i) + '_t' + str(t)
        grb_model.addConstr(b3_C[i, t] + b4_C[i, t] == 1, name=_name_b34)

        _name_dWinj_true = 'C#05a_DW_' + _type + '_D_inj_TRUE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], True, DW_C_D_inj[i, t], GRB.EQUAL, fsp_data['Winit'].iloc[i, t], name=_name_dWinj_true)
        _name_dWinj_false = 'C#05a_DW_' + _type + '_D_inj_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_D_inj[i, t] - DW_C_D[i, t], GRB.EQUAL, 0, name=_name_dWinj_false)
        _name_dWads_false = 'C#05a_DW_' + _type + '_D_ads_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_D_ads[i, t], GRB.EQUAL, 0, name=_name_dWads_false)

        _name_dWinj_eq = 'C#05a_DW_' + _type + '_U_inj_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_U_inj[i, t] - DW_C_U[i, t] == 0, name=_name_dWinj_eq)
        _name_dWads_eq = 'C#05a_DW_' + _type + '_U_ads_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_U_ads[i, t] == 0, name=_name_dWads_eq)
    else:
        _name_dw_u_cond = 'C#05a_DW_' + _type + '_U_Condition_' + str(i) + '_t' + str(t)
        grb_model.addConstr(
            (DW_C_U_ads[i, t] * b3_C[i, t] + (DW_C_U_inj[i, t] + abs(fsp_data['Winit'].iloc[i, t])) * b4_C[i, t])
            - DW_C_U[i, t] == 0, name=_name_dw_u_cond)
        _name_b34 = 'C#05a_' + _type + '_b3+b4_' + str(i) + '_t' + str(t)
        grb_model.addConstr(b3_C[i, t] + b4_C[i, t] == 1, name=_name_b34)

        _name_dWads_true = 'C#05a_DW_' + _type + '_U_ads_TRUE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], True, DW_C_U_ads[i, t], GRB.EQUAL, -fsp_data['Winit'].iloc[i, t], name=_name_dWads_true)
        _name_dWads_false = 'C#05a_DW_' + _type + '_U_ads_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_U_ads[i, t] - DW_C_U[i, t], GRB.EQUAL, 0, name=_name_dWads_false)
        _name_dWinj_false = 'C#05a_DW_' + _type + '_U_inj_c02_FALSE' + str(i) + '_t' + str(t)
        grb_model.addGenConstrIndicator(b4_C[i, t], False, DW_C_U_inj[i, t], GRB.EQUAL, 0, name=_name_dWinj_false)

        _name_dWads_eq = 'C#05a_DW_' + _type + '_U_ads_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_D_ads[i, t] - DW_C_D[i, t] == 0, name=_name_dWads_eq)
        _name_dWinj_eq = 'C#05a_DW_' + _type + '_U_inj_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_D_inj[i, t] == 0, name=_name_dWinj_eq)

    # fixme: 'TO FORCE THE SOLUTION WHEN ONLY P OR ONLY Q AND VOID FLAT SOLUTIONS'.
    #  Why only available for the VC market?
    if fsp_data['Wlb'].iloc[i, t] == fsp_data['Wub'].iloc[i, t]:
        _name_onlyQ_dW_u = 'C#06a_C_force_onlyQ_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_U[i, t] == 0, name=_name_onlyQ_dW_u)
        _name_onlyQ_dW_d = 'C#06b_C_force_onlyQ_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DW_C_D[i, t] == 0, name=_name_onlyQ_dW_d)
    if fsp_data['Rub'].iloc[i, t] == fsp_data['Rlb'].iloc[i, t]:
        _name_onlyP_dR_u = 'C#06a_C_force_onlyP_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DR_C_U[i, t] == 0, name=_name_onlyP_dR_u)
        _name_onlyP_dR_d = 'C#06b_C_force_onlyP_' + str(i) + '_t' + str(t)
        grb_model.addConstr(DR_C_D[i, t] == 0, name=_name_onlyP_dR_d)

    return grb_model


def fsp_converter(_data, _k_opt=1, _class_fsp='storage', _fsp_filename=''):
    """
    Adapt the fsp storage info into usable data for the local flexibility market optimization.


    :param _data: Dictionary containing all the information useful for the conversion into usable data. The useful data
        are the pandapower network (net), the dictionary with the timeseries simulation (ts_res), the dataframe with the fsp
        data involved in the simulation (fsp_data), the output root where to save files (out_root), the list of hours with
        network constraint violations (hours), the bidding strategy of the fsp element (bid_strat), the multiplier
        coefficient of the load (scen_factor_load), the multiplier coefficient of the generation (scen_factor_gen),
        the nominal power of the storage (ess_kmva), the active power bid up coefficient (kbid_p_up),
        the active power bid down coefficient (kbid_p_dwn), the reactive power bid up coefficient (kbid_q_up),
        the reactive power down up coefficient (kbid_q_dwn) and the simulation tag (sim_tag).


    :param _k_opt: Margin for bidding below the full capacity - Safe for optimization convergence.


    :param _class_fsp: String that define the name of the fsp typology.
    """
    warning_fsp = False

    # Pandapower network
    _net = _data['net']
    # Dictionary with the timeseries simulation.
    _ts_res = _data['ts_res']
    # Dataframe with the fsp data involved in the simulation.
    _fsp_data = _data['fsp_data']
    # Output root where to save files.
    _out_root = _data['out_root']
    # List of hours with network constraint violations.
    _hours = _data['hours']
    # Multiplier coefficient of the load.
    _scen_factor_storage = _data['scen_factor_storage']
    # Nominal power of the storage
    _ess_kmva = _data['ess_kmva']
    # Active power bid up coefficient.
    _kbid_p_up = _data['kbid_p_up']
    # Active power bid down coefficient.
    _kbid_p_dwn = _data['kbid_p_dwn']
    # Reactive power bid up coefficient.
    _kbid_q_up = _data['kbid_q_up']
    # Reactive power bid down coefficient.
    _kbid_q_dwn = _data['kbid_q_dwn']
    # Simulation tag.
    _sim_tag = _data['sim_tag']

    mode_xlsx = 'w'
    res_cat = 'storage'

    load_p_premkt = _ts_res['storage_p_mw'].T
    load_q_premkt = _ts_res['storage_q_mvar'].T
    class_fsp_df = _fsp_data.loc[_fsp_data.type == _class_fsp].reset_index(drop=True)
    labels = fsp_labels(class_fsp_df, _class_fsp)

    n_load_fsp = len(class_fsp_df.id)

    class_fsp_df.mva = class_fsp_df.mva * _scen_factor_storage * _ess_kmva
    class_fsp_df.Pup = class_fsp_df.Pup * _kbid_p_up
    class_fsp_df.Pdown = class_fsp_df.Pdown * _kbid_p_dwn
    class_fsp_df.Qup = class_fsp_df.Qup * _kbid_q_up
    class_fsp_df.Qdown = class_fsp_df.Qdown * _kbid_q_dwn

    _n_hours = len(_hours)
    shape_init = (n_load_fsp, _n_hours)
    cosphi_init = np.zeros(shape=shape_init)
    # cosphi_lb is the MINIMUM power factor a converter may run at, so the reactive ceiling it implies is
    # S * sin(acos(cosphi_lb)) = 0.980 * S at 0.2.
    cosphi_lb = 0.2 * np.ones(shape=shape_init)
    cosphi_ub = 1.0 * np.ones(shape=shape_init)
    soc_init = np.zeros(shape=shape_init)
    soc_lb = np.zeros(shape=shape_init)
    soc_ub = np.zeros(shape=shape_init)

    ni_inj = 0.99 * np.ones(shape=shape_init)
    ni_abs = 0.99 * np.ones(shape=shape_init)
    ni_q = 0.99 * np.ones(shape=shape_init)

    r_ub_dlim = np.zeros(shape=shape_init)
    r_ub_ulim = np.zeros(shape=shape_init)
    w_lb_dlim = np.zeros(shape=shape_init)
    w_ub_ulim = np.zeros(shape=shape_init)
    # Audit trail for headroom bidding.
    headroom_report = headroom_lib.HeadroomDiagnostics(shape_init)

    fsp_p_up_cost = class_fsp_df.Pup_cost.to_numpy().repeat(_n_hours).reshape(shape_init)
    fsp_p_dwn_cost = class_fsp_df.Pdown_cost.to_numpy().repeat(_n_hours).reshape(shape_init)
    fsp_q_up_cost = class_fsp_df.Qup_cost.to_numpy().repeat(_n_hours).reshape(shape_init)
    fsp_q_dwn_cost = class_fsp_df.Qdown_cost.to_numpy().repeat(_n_hours).reshape(shape_init)
    fsp_mva = class_fsp_df.mva.to_numpy().repeat(_n_hours).reshape(shape_init)

    # Float arrays.  The operating point of
    # every hour is copied into these arrays below; seeded from an integer column
    # (a sheet whose mw/mvar placeholders are whole numbers) they would truncate
    # it to whole MW / MVAr without any warning.
    fsp_w_init = class_fsp_df.mw.to_numpy(dtype=float).repeat(_n_hours).reshape(shape_init)
    fsp_r_init = class_fsp_df.mvar.to_numpy(dtype=float).repeat(_n_hours).reshape(shape_init)

    for i in tqdm(range(n_load_fsp), desc='Initialising Battery bids (Batteries follow the generation convention)'):
        _idx = match_pp_element(_net.storage, class_fsp_df.iloc[i], 'storage')
        # Changing to generation convention
        fsp_w_init[i, :] = -load_p_premkt.loc[_idx, _hours].to_numpy()
        fsp_r_init[i, :] = -load_q_premkt.loc[_idx, _hours].to_numpy()
        soc_init[i, :] = ((_net.storage.loc[_idx, 'soc_percent'] / 100) * _net.storage.loc[_idx, 'max_e_mwh'])
        soc_lb[i, :] = _net.storage.loc[_idx, 'min_e_mwh']
        soc_ub[i, :] = _net.storage.loc[_idx, 'max_e_mwh']

        _strategy = str(class_fsp_df.bidding_strategy[i])
        _use_headroom = headroom_lib.is_headroom(_strategy)
        if _strategy == headroom_lib.STRATEGY_INITIAL:
            w_ref = fsp_w_init
        else:
            # _bid_strat == 'mva_value' (headroom_value ignores the reference
            # entirely: it sizes from the technical envelope instead).
            w_ref = fsp_mva

        # The converter rating and the
        # offered rating are different numbers -- a 6 MVA battery in this
        # network declares max_p_mw = 1.5 -- so the envelope honours whichever
        # binds first.  Generation convention: positive injects (discharge).
        _sto_row = _net.storage.loc[_idx]
        _offered = abs(headroom_lib.numeric(class_fsp_df.mva.iloc[i], 0.0))
        _p_disch_max = min(headroom_lib.first_finite(_sto_row.get('max_p_mw'), _offered), _offered)
        _p_chg_min = max(headroom_lib.first_finite(_sto_row.get('min_p_mw'), -_offered), -_offered)
        _q_max_tech = headroom_lib.numeric(_sto_row.get('max_q_mvar'))
        _q_min_tech = headroom_lib.numeric(_sto_row.get('min_q_mvar'))
        _fsp_name = class_fsp_df['name'].iloc[i]

        for h in range(_n_hours):
            # Initial Cosphi
            if fsp_w_init[i, h] == 0:
                cosphi_init[i, h] = 0
            else:
                cosphi_init[i, h] = math.cos(math.atan(fsp_r_init[i, h] / fsp_w_init[i, h]))

            if _use_headroom:
                # Energy limits gate power limits: a battery at its floor
                # cannot offer more discharge, one at its ceiling cannot offer
                # more charge.  Without this the bid would be power-feasible
                # and energy-infeasible.
                _disch_cap = _p_disch_max
                _chg_cap = _p_chg_min
                if soc_init[i, h] <= soc_lb[i, h]:
                    _disch_cap = min(_disch_cap, fsp_w_init[i, h])
                if soc_init[i, h] >= soc_ub[i, h]:
                    _chg_cap = max(_chg_cap, fsp_w_init[i, h])

                _w_lo, _w_hi, _w_dn_av, _w_up_av = headroom_lib.headroom_bounds(
                    fsp_w_init[i, h], _chg_cap, _disch_cap,
                    class_fsp_df.Pup.iloc[i], class_fsp_df.Pdown.iloc[i])
                w_ub_ulim[i, h] = _w_hi
                w_lb_dlim[i, h] = _w_lo

                _q_circle, _clipped = headroom_lib.safe_sqrt_capability(
                    class_fsp_df.mva.iloc[i], fsp_w_init[i, h],
                    _fsp_name, _hours[h], _k_opt)
                _q_hi_tech = min(_q_circle, _q_max_tech) if not math.isnan(_q_max_tech) else _q_circle
                _q_lo_tech = max(-_q_circle, _q_min_tech) if not math.isnan(_q_min_tech) else -_q_circle
                _r_lo, _r_hi, _r_dn_av, _r_up_av = headroom_lib.headroom_bounds(
                    fsp_r_init[i, h], _q_lo_tech, _q_hi_tech,
                    class_fsp_df.Qup.iloc[i], class_fsp_df.Qdown.iloc[i])
                r_ub_ulim[i, h] = _r_hi
                r_ub_dlim[i, h] = _r_lo

                headroom_report.record(
                    i, h, p_min=_chg_cap, p_max=_disch_cap,
                    q_min=_q_lo_tech, q_max=_q_hi_tech,
                    p_down_avail=_w_dn_av, p_up_avail=_w_up_av,
                    q_down_avail=_r_dn_av, q_up_avail=_r_up_av,
                    clipped=_clipped)
                if _clipped:
                    warning_fsp = True
                continue

            # In generation convention upward is always MORE injection, so the magnitude of the reference
            # scales the offer: under 'initial_value' w_ref carries the sign of the operating point, under
            # 'mva_value' it is the rating, always positive.
            _ref_mag = abs(w_ref[i, h])
            if class_fsp_df.Pup.iloc[i] > 0:
                w_ub_ulim[i, h] = fsp_w_init[i, h] + (class_fsp_df.Pup.iloc[i] * _ref_mag)
            else:
                w_ub_ulim[i, h] = fsp_w_init[i, h]

            if class_fsp_df.Pdown.iloc[i] > 0:
                w_lb_dlim[i, h] = fsp_w_init[i, h] - (class_fsp_df.Pdown.iloc[i] * _ref_mag)
            else:
                w_lb_dlim[i, h] = fsp_w_init[i, h]
            # A battery cannot charge
            # beyond its rating.  The S-circle constraint already stops the
            # dispatch there, so this only corrects the bid file and the offered
            # flexibility read from it.
            w_lb_dlim[i, h] = headroom_lib.floor_lower_bound(w_lb_dlim[i, h], fsp_w_init[i, h], -_offered)

            if fsp_r_init[i, h] >= 0:
                # If storage is generating (generation convention is used) (Injecting Reactive)
                if class_fsp_df.Qdown.iloc[i] > 0:
                    # The capability root
                    # was unguarded, so a profile with |P| above the declared
                    # MVA raised ValueError: math domain error and killed the
                    # run.  Identical result when the argument is valid.
                    r1 = headroom_lib.safe_sqrt_capability(
                        class_fsp_df.mva.iloc[i], fsp_w_init[i, h],
                        _fsp_name, _hours[h])[0]
                    r_ub_dlim[i, h] = -((class_fsp_df.Qdown.iloc[i] * (r1 - abs(fsp_r_init[i, h]))) + abs(fsp_r_init[i, h]))
                else:
                    r_ub_dlim[i, h] = fsp_r_init[i, h]

                if class_fsp_df.Qup.iloc[i] > 0:
                    # The capability root
                    # was unguarded, so a profile with |P| above the declared
                    # MVA raised ValueError: math domain error and killed the
                    # run.  Identical result when the argument is valid.
                    r1 = headroom_lib.safe_sqrt_capability(
                        class_fsp_df.mva.iloc[i], fsp_w_init[i, h],
                        _fsp_name, _hours[h])[0]
                    r_ub_ulim[i, h] = (class_fsp_df.Qup.iloc[i] * (r1 - abs(fsp_r_init[i, h]))) + abs(fsp_r_init[i, h])
                else:
                    r_ub_ulim[i, h] = fsp_r_init[i, h]
            else:
                # If storage is consuming (generation convention is used) (Absorbing Reactive)
                if class_fsp_df.Qup.iloc[i] > 0:
                    # The capability root
                    # was unguarded, so a profile with |P| above the declared
                    # MVA raised ValueError: math domain error and killed the
                    # run.  Identical result when the argument is valid.
                    r1 = headroom_lib.safe_sqrt_capability(
                        class_fsp_df.mva.iloc[i], fsp_w_init[i, h],
                        _fsp_name, _hours[h])[0]
                    r_ub_ulim[i, h] = (class_fsp_df.Qup.iloc[i] * (r1 - abs(fsp_r_init[i, h]))) + abs(fsp_r_init[i, h])
                else:
                    r_ub_ulim[i, h] = fsp_r_init[i, h]

                if class_fsp_df.Qdown.iloc[i] > 0:
                    # The capability root
                    # was unguarded, so a profile with |P| above the declared
                    # MVA raised ValueError: math domain error and killed the
                    # run.  Identical result when the argument is valid.
                    r1 = headroom_lib.safe_sqrt_capability(
                        class_fsp_df.mva.iloc[i], fsp_w_init[i, h],
                        _fsp_name, _hours[h])[0]
                    r_ub_dlim[i, h] = -((class_fsp_df.Qdown.iloc[i] * (r1 - abs(fsp_r_init[i, h]))) + abs(fsp_r_init[i, h]))
                else:
                    r_ub_dlim[i, h] = fsp_r_init[i, h]

            if abs(w_ub_ulim[i, h]) > (class_fsp_df.mva.iloc[i] * cosphi_ub[i, h]):
                warning_fsp = True
                if w_ub_ulim[i, h] > 0:
                    w_ub_ulim[i, h] = class_fsp_df.mva.iloc[i] * cosphi_ub[i, h] * _k_opt
                else:
                    w_ub_ulim[i, h] = -class_fsp_df.mva.iloc[i] * cosphi_ub[i, h] * _k_opt

            if abs(r_ub_ulim[i, h]) > (class_fsp_df.mva.iloc[i] * math.sin(math.acos(cosphi_lb[i, h]))):
                warning_fsp = True
                if r_ub_ulim[i, h] > 0:
                    r_ub_ulim[i, h] = class_fsp_df.mva.iloc[i] * math.sin(math.acos(cosphi_lb[i, h])) * _k_opt
                else:
                    r_ub_ulim[i, h] = -class_fsp_df.mva.iloc[i] * math.sin(math.acos(cosphi_lb[i, h])) * _k_opt

            if abs(w_lb_dlim[i, h]) > (class_fsp_df.mva.iloc[i] * cosphi_ub[i, h]):
                warning_fsp = True
                if w_lb_dlim[i, h] > 0:
                    w_lb_dlim[i, h] = class_fsp_df.mva.iloc[i] * cosphi_ub[i, h] * _k_opt
                else:
                    w_lb_dlim[i, h] = -class_fsp_df.mva.iloc[i] * cosphi_ub[i, h] * _k_opt

            # Clamp the reactive lower bound to the converter's reactive ceiling, keeping its sign.
            if abs(r_ub_dlim[i, h]) > (class_fsp_df.mva.iloc[i] * math.sin(math.acos(cosphi_lb[i, h]))):
                warning_fsp = True
                if r_ub_dlim[i, h] > 0:
                    r_ub_dlim[i, h] = class_fsp_df.mva.iloc[i] * math.sin(math.acos(cosphi_lb[i, h])) * _k_opt
                else:
                    r_ub_dlim[i, h] = -class_fsp_df.mva.iloc[i] * math.sin(math.acos(cosphi_lb[i, h])) * _k_opt

        if warning_fsp:
            logging.warning('Storage Sn capacity saturated for some item')

    if n_load_fsp > 0:
        resource_category = pd.DataFrame([res_cat for _ in range(n_load_fsp)], columns=['res_category'])
        fsp_info = pd.concat([class_fsp_df.id, class_fsp_df.name, class_fsp_df.bus, class_fsp_df.mva, resource_category], axis=1)
        fsp_info.index = labels

        _path2file = os.path.join(_out_root, _fsp_filename + '.xlsx')
        if os.path.exists(_path2file):
            mode_xlsx = 'a'

        io_file.save_excel(_data=fsp_info, _outroot=_out_root, _filename=_fsp_filename, _sheetname='FSPinfo_' + _class_fsp, _mode=mode_xlsx)

        io_file.save_excel(_data=fsp_frame(fsp_p_up_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='W_U_inj_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_p_up_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='W_U_ads_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_p_dwn_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='W_D_inj_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_p_dwn_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='W_D_ads_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_q_up_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='R_U_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_q_dwn_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='R_D_Cost_' + _class_fsp, _mode='a')

        io_file.save_excel(_data=fsp_frame(fsp_w_init, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='Winit_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_r_init, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='Rinit_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(cosphi_init, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='COSPHIinit_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(cosphi_lb, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='COSPHILB_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(cosphi_ub, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='COSPHIUB_' + _class_fsp, _mode='a')

        io_file.save_excel(_data=fsp_frame(r_ub_dlim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='RUB_DLim_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(r_ub_ulim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='RUB_ULim_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(w_ub_ulim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='WUB_ULim_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(w_lb_dlim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='WLB_DLim_' + _class_fsp, _mode='a')

        # Technical limits, the room
        # they left and any clipping, written only when headroom bidding ran.
        for _sheet, _array in headroom_report.sheets(_class_fsp).items():
            io_file.save_excel(_data=fsp_frame(_array, labels, _hours), _outroot=_out_root,
                               _filename=_fsp_filename, _sheetname=_sheet, _mode='a')

        io_file.save_excel(_data=fsp_frame(soc_init, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='SoCinit_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(soc_lb, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='SoCLB_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(soc_ub, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='SoCUB_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(ni_inj, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='NIinj_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(ni_abs, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='NIads_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(ni_q, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='NIq_' + _class_fsp, _mode='a')
    else:
        _fsp_filename = 0
    return _fsp_filename, fsp_bus_series(class_fsp_df, labels)


def define_profiles(_root2inputs, _pp_res, _timestep):
    """
    Optimise the Storage profiles using the Day-Ahead Market Prices and Day-Ahead Load and Generation Profiles.
    Consider the fact that we are neglecting the network, therefore we consider all the resources like a Virtual
    Power Plant. Maximise the Social Welfare of the VPN.
    """
    ess_res_p, ess_res_q = 0, 0
    # Read initial data
    price_params = _read_input_params(_root2inputs, _sheetname='price_params', _index_col=0, _header=0)
    storage_params = _read_input_params(_root2inputs, _sheetname='storage_params', _index_col=0, _header=0)

    _flag_model = False
    _flag_res = False
    _dt = 1
    _interval = _timestep[1] - _timestep[0]

    # Create a New Gurobi-py Model
    name_model = 'Storage_initial_profiles_model'
    ess_model = gp.Model(name_model)

    n_ess = _pp_res.shape[0]

    mva = _pp_res.sn_mva
    soc0 = (_pp_res.soc_percent / 100) * _pp_res.max_e_mwh
    soc_min = _pp_res.min_e_mwh
    soc_max = _pp_res.max_e_mwh
    socm = np.multiply(np.array(soc_min).reshape((n_ess, 1)), np.ones((n_ess, _interval)))
    socM = np.multiply(np.array(soc_max).reshape((n_ess, 1)), np.ones((n_ess, _interval)))
    s_ess = np.multiply(np.array(mva).reshape((n_ess, 1)), np.ones((n_ess, _interval)))
    tan_ub = np.tan(np.arccos(storage_params.cos_phi_min))
    tan_lb = np.tan(np.arccos(storage_params.cos_phi_max))

    shape_ess = tuplelist([(k, t) for k in range(n_ess) for t in range(_interval)])
    # After the Market Reactive Power Exchange
    q_ess = ess_model.addVars(shape_ess, lb=-s_ess, ub=s_ess, vtype=GRB.CONTINUOUS, name='q_ess')
    # variable: active power adsorption (in per unit) for batteries (type C)
    p_abs = ess_model.addVars(shape_ess, lb=-s_ess, ub=0, vtype=GRB.CONTINUOUS, name='p_abs')
    # variable: active power injection (in per unit) for batteries (type C)
    p_inj = ess_model.addVars(shape_ess, lb=0, ub=s_ess, vtype=GRB.CONTINUOUS, name='p_inj')
    # variable: after the market State of Charge for batteries (type C) [energy KWh]
    soc = ess_model.addVars(shape_ess, lb=socm, ub=socM, vtype=GRB.CONTINUOUS, name='soc')
    # After the Market Active Power
    p_ess = ess_model.addVars(shape_ess, lb=-s_ess, ub=s_ess, vtype=GRB.CONTINUOUS, name='p_ess')
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    ratio = ess_model.addVars(shape_ess, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='ratio')
    abs_ratio = ess_model.addVars(shape_ess, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='abs_ratio')
    # Companion variables - necessary in gurobi to include the QUADRATIC constraints
    abs_q = ess_model.addVars(shape_ess, lb=0, ub=s_ess, vtype=GRB.CONTINUOUS, name='abs_q')
    # Binary Variables
    b1 = ess_model.addVars(shape_ess, vtype=GRB.BINARY, name='b1')
    b2 = ess_model.addVars(shape_ess, vtype=GRB.BINARY, name='b2')

    for k in range(n_ess):
        ess_model.addConstr(soc[k, _interval - 1] >= soc0[k], name='fin_soc' + str(k))
        for t in range(_interval):

            _name_abs_ratio = 'abs_ratio_#' + str(k) + '_t' + str(t)
            ess_model.addGenConstrAbs(abs_ratio[k, t], ratio[k, t], name=_name_abs_ratio)

            _name_abs_r = 'abs_r_#' + str(k) + '_t' + str(t)
            ess_model.addGenConstrAbs(abs_q[k, t], q_ess[k, t], name=_name_abs_r)

            _name_q_cstr = 'C#05a_NORM(SMVA)_' + str(k) + '_t' + str(t)
            ess_model.addConstr(p_ess[k, t] ** 2 + q_ess[k, t] ** 2 - mva[k] ** 2 <= 0, name=_name_q_cstr)

            # Power Factor limits
            _name_pf_limit = 'C#05b_TANPHI_' + str(k) + '_t' + str(t)
            ess_model.addConstr(p_ess[k, t] * ratio[k, t] - q_ess[k, t] == 0, name=_name_pf_limit)
            _name_tan_lb = 'C#05b_TANPHI_LowerLimit_' + str(k) + '_t' + str(t)
            ess_model.addConstr(abs_ratio[k, t] - tan_lb[k] >= 0, name=_name_tan_lb)
            _name_tan_ub = 'C#05b_TANPHI_UpperLimit_' + str(k) + '_t' + str(t)
            ess_model.addConstr(abs_ratio[k, t] - tan_ub[k] <= 0, name=_name_tan_ub)

            name_soc_cstr = 'soc' + str(k) + '_t' + str(t)
            if t == 0:
                ess_model.addConstr((soc0[k] + (-p_abs[k, t] * storage_params.ni_abs[k] * b2[k, t] - b1[k, t] * p_inj[k, t] / storage_params.ni_inj[k] - abs_q[k, t] * (1 - storage_params.ni_q[k])) * _dt) - soc[k, t] == 0,
                                    name=name_soc_cstr)
            else:
                ess_model.addConstr((soc[k, t - 1] + (-p_abs[k, t] * storage_params.ni_abs[k] * b2[k, t] - b1[k, t] * p_inj[k, t] / storage_params.ni_inj[k] - abs_q[k, t] * (1 - storage_params.ni_q[k])) * _dt) - soc[k, t] == 0,
                                    name=name_soc_cstr)

            # Binary Constraints for W output
            _name_w_binary = 'C#05a_Winjetting_' + str(k) + '_t' + str(t)
            ess_model.addConstr((p_inj[k, t] * b1[k, t] + p_abs[k, t] * b2[k, t]) - p_ess[k, t] == 0, name=_name_w_binary)
            _name_b12 = 'C#05a_b1+b2_' + str(k) + '_t' + str(t)
            ess_model.addConstr(b1[k, t] + b2[k, t] == 1, name=_name_b12)

            _name_winj_max = 'C#05a_Winj_boundB01_' + str(k) + '_t' + str(t)
            ess_model.addConstr(p_inj[k, t] - b1[k, t] * mva[k] <= 0, name=_name_winj_max)
            _name_winj_min = 'C#05a_Winj_boundB02_' + str(k) + '_t' + str(t)
            ess_model.addConstr(p_inj[k, t] >= 0, name=_name_winj_min)
            _name_wads_max = 'C#05a_Wads_boundB03_' + str(k) + '_t' + str(t)
            ess_model.addConstr(p_abs[k, t] <= 0, name=_name_wads_max)
            _name_wads_min = 'C#05a_Wads_boundB04_' + str(k) + '_t' + str(t)
            ess_model.addConstr(-b2[k, t] * mva[k] - p_abs[k, t] <= 0, name=_name_wads_min)

    import_coeff = dict(zip(shape_ess, price_params['Import Prices']))
    export_coeff = dict(zip(shape_ess, price_params['Export Prices']))
    obj_fcn = p_abs.prod(import_coeff) + p_inj.prod(export_coeff)
    ess_model.setObjective(obj_fcn, GRB.MAXIMIZE)
    # NOTE: The results of the EMS of the battery are going to be in MWh

    # Write Model on file to check correctness
    if _flag_model:
        _root_res = 'Storage_Profiles'
        path2folder = os.path.dirname(os.path.abspath(_root2inputs))
        new_folder = os.path.join(path2folder, _root_res)
        if not os.path.exists(new_folder):
            os.makedirs(new_folder)
        ess_model.write(os.path.join(new_folder, name_model + '.lp'))

    # Optimise
    ess_model.Params.LogToConsole = 0
    ess_model.optimize()
    status = ess_model.status
    if status == GRB.OPTIMAL:
        try:
            variables = {'Obj': [ess_model.ObjVal]}
            matrix_pess = np.zeros(shape=(_interval, n_ess))
            matrix_pabs = np.zeros(shape=(_interval, n_ess))
            matrix_pinj = np.zeros(shape=(_interval, n_ess))
            matrix_qess = np.zeros(shape=(_interval, n_ess))
            matrix_absq = np.zeros(shape=(_interval, n_ess))
            matrix_soc = np.zeros(shape=(_interval, n_ess))
            matrix_ratio = np.zeros(shape=(_interval, n_ess))
            matrix_absratio = np.zeros(shape=(_interval, n_ess))
            for k in range(n_ess):
                for t in range(_interval):
                    matrix_pess[t, k] = p_ess[(k, t)].X
                    matrix_pabs[t, k] = p_abs[(k, t)].X
                    matrix_pinj[t, k] = p_inj[(k, t)].X
                    matrix_qess[t, k] = q_ess[(k, t)].X
                    matrix_absq[t, k] = abs_q[(k, t)].X
                    matrix_soc[t, k] = soc[(k, t)].X
                    matrix_ratio[t, k] = ratio[(k, t)].X
                    matrix_absratio[t, k] = abs_ratio[(k, t)].X
            variables['P_ess'] = matrix_pess
            variables['P_abs'] = matrix_pabs
            variables['P_inj'] = matrix_pinj
            variables['Q_ess'] = matrix_qess
            variables['|Q|'] = matrix_absq
            variables['SoC'] = matrix_soc
            variables['Ratio'] = matrix_ratio
            variables['|Ratio|'] = matrix_absratio
        except Exception as error:
            raise UserWarning('An error occurred:', type(error).__name__, '–', error)

        if _flag_res:
            _root_res = 'Storage_Profiles'
            path2folder = os.path.dirname(os.path.abspath(_root2inputs))
            new_folder = os.path.join(path2folder, _root_res)
            if not os.path.exists(new_folder):
                os.makedirs(new_folder)
            # Save variables into dictionary

            with pd.ExcelWriter(os.path.join(new_folder, name_model + '_res.xlsx')) as writer:
                if type(variables) is dict:
                    for _k, _v in variables.items():
                        pd.DataFrame(_v).to_excel(writer, sheet_name=_k)
                else:
                    raise ValueError('Format type {0}.'.format(str(type(variables))))

        ess_res_p = pd.DataFrame(variables['P_ess'])
        ess_res_q = pd.DataFrame(variables['Q_ess'])
    else:
        d = solver_status.status_names()
        raise Warning('Optimization was stopped with status: {_stat}'.format(_stat=d[status]))

    return ess_res_p, ess_res_q


def _read_input_params(_root2file, _sheetname=None, _index_col=None, _header=0):
    """
    This function imports the data from file passed as input.
    Two extension of files are available: i) .csv and ii) .xlsx.

    Input:
        **_root2file** (string) - Name of the file to import (format .csv or .xlsx).

        **_sheetname** (string, None) - If .xlsx extension is selected, it represents the name of the sheet in which
         the information are saved (only xlsx file).

        **_index_col** (int, None) - Column(s) to use as row label(s), denoted either by column labels or column indices.

        **_header** (int, 0) - Row number(s) containing column labels and marking the start of the data.

    Output:
        **_tmp_data** (Dataframe) - Dataframe with the information contained in the file passed.

    Example:

    >>> import os
    >>> my_root = os.path.join(os.getcwd(), 'my_folder', 'my_file.xlsx')
    >>> _read_input_params(my_root, 'my_sheet', 0, 0)

    """
    _file_name = pathlib.Path(_root2file).stem
    if _file_name is None:
        raise ValueError('No filename have been passed.')

    _tmp_data = None
    _ext = pathlib.Path(_root2file).suffix
    if _ext == '.csv':
        _tmp_data = pd.read_csv(_root2file, index_col=_index_col, header=_header)
    elif _ext == '.xlsx':
        _sheet = pd.ExcelFile(_root2file).sheet_names
        if _sheetname not in _sheet:
            raise ValueError('The sheetname {_sheetname} passed do not exist.".'.format(_sheetname=_sheetname))
        _tmp_data = pd.read_excel(_root2file, index_col=_index_col, header=_header, sheet_name=_sheetname)
    return _tmp_data
