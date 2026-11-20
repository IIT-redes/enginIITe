import os
import pathlib
import numpy as np
import pandas as pd
import gurobipy as gp
from tqdm.auto import tqdm
from gurobipy import GRB, tuplelist
from enginiite import file_io as io_file
from enginiite.market import solver_status
from enginiite.market.models.fsp_utils import fsp_bus_series, fsp_frame, fsp_labels, match_pp_element
from enginiite.market.models import headroom as headroom_lib  # Legacy floor


def res_params(_n_fsp, _sim_period, _fsp_data, _type='D'):
    """
    Define Input Data of the Load Resource.
    :param _n_fsp: Number of FSP of type Load resource.
    :param _sim_period: List of hours to consider for the study.
    :param _fsp_data: Dictionary of the Data associated
    """
    fsp_data = dict()
    # Save Data that are Impose to GENERATION Convention
    hp_conv = ['DR_', 'R_', 'DW_', 'W_']
    if _n_fsp > 0:
        # Reactive Power
        fsp_data['Rinit'] = _fsp_data['Rinit_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        fsp_data['Winit'] = _fsp_data['Winit_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Reactive Power UPWARD Support Provision [€/MVArh] for each Resource
        fsp_data['RU_cost'] = _fsp_data['R_U_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Reactive Power DOWNWARD Support Provision [€/MVArh] for each Resource
        fsp_data['RD_cost'] = _fsp_data['R_D_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Nameplate Apparent Power of the Resources [MVA]
        fsp_data['mva'] = _fsp_data['FSPinfo_' + _type].mva.to_numpy()
        # Lower Bound Active Power (Minimum Active Power ABSORPTION Value admitted by the Resource)
        fsp_data['Wlb'] = _fsp_data['WLB_ULim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound Active Power (Maximum Active Power INJECTION Value admitted by the Resource)
        fsp_data['Wub'] = _fsp_data['WUB_DLim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Lower Bound Reactive Power Value (Minimum Reactive Power ABSORPTION Value admitted by the Resource)
        fsp_data['Rlb'] = _fsp_data['RUB_ULim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Upper Bound Reactive Power Value (Maximum Reactive Power INJECTION Value admitted by the Resource)
        fsp_data['Rub'] = _fsp_data['RUB_DLim_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Active Power UPWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WU_cost'] = _fsp_data['W_U_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Cost for Active Power DOWNWARD Support Provision [€/MVAh] for each Resource
        fsp_data['WD_cost'] = _fsp_data['W_D_Cost_' + _type].iloc[list(range(0, _n_fsp)), _sim_period]
        # Initial Parameter Temperatures
        fsp_data['T_params'] = _fsp_data['T_params_' + _type]
        # Initial Heatpump Parameters
        fsp_data['HP_params'] = _fsp_data['HP_params_' + _type]

        # Delta Active Power Upward (Generation Convention)
        fsp_data['DW_U'] = fsp_data['Winit'] - fsp_data['Wlb']
        # Delta Active Power Downward (Generation Convention)
        fsp_data['DW_D'] = fsp_data['Wub'] - fsp_data['Winit']
        # Delta Reactive Power Upward
        fsp_data['DR_U'] = fsp_data['Rinit'] - fsp_data['Rlb']
        # Delta Reactive Power Downward
        fsp_data['DR_D'] = fsp_data['Rub'] - fsp_data['Rinit']
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
    return fsp_data, hp_conv


def define_variables(_grb_model, _n_fsp, _n_t, _contr, _type='D'):
    """
    Define Variables of the Load Resource selecting the more appropriate/updated function.
    :param _grb_model: Object that represents the gurobipy model.
    :param _n_fsp: Number of flexibility service providers.
    :param _n_t: Number of intervals.
    :param _contr: Contribution of these resource type.
    :param _type: Type of resource.
    """
    _vars_dict = hp_variables(grb_model=_grb_model, n_fsp=_n_fsp, n_t=_n_t, _contr=_contr, _type=_type)
    return _vars_dict


def hp_variables(grb_model, n_fsp, n_t, _contr, _type='D'):
    """Define Variables of the Load Resource."""
    shape_var = tuplelist([(_f, _t) for _f in range(n_fsp) for _t in range(n_t)])
    _vars_dict = dict()
    # Delta Reactive Power Exchange [p.u.]
    DR_D = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DR_' + _type)
    _vars_dict['DR_' + _type] = DR_D
    # After the Market Reactive Power Exchange
    R_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='R_' + _type)
    _vars_dict['R_' + _type] = R_D
    # Delta Active Power Exchange [p.u.]
    DW_D = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DW_' + _type)
    _vars_dict['DW_' + _type] = DW_D
    # Delta Active Power Heating [p.u.]
    DWheat_D = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DWheat_' + _type)
    _vars_dict['DWheat_' + _type] = DWheat_D
    # Delta Active Power Cooling [p.u.]
    DWcool_D = grb_model.addVars(shape_var, lb=-_contr, ub=_contr, vtype=GRB.CONTINUOUS, name='DWcool_' + _type)
    _vars_dict['DWcool_' + _type] = DWcool_D
    # After the Market Active Power
    W_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='W_' + _type)
    _vars_dict['W_' + _type] = W_D
    # After the Market Active Power Heating
    Wheat_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='Wheat_' + _type)
    _vars_dict['Wheat_' + _type] = Wheat_D
    # After the Market Active Power Cooling
    Wcool_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=0, vtype=GRB.CONTINUOUS, name='Wcool_' + _type)
    _vars_dict['Wcool_' + _type] = Wcool_D

    # Delta Active Power Heating Upwards Contribution
    DWheat_D_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DWheat_' + _type + '_U')
    _vars_dict['DWheat_' + _type + '_U'] = DWheat_D_U
    # Delta Active Power Heating Downwards Contribution
    DWheat_D_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DWheat_' + _type + '_D')
    _vars_dict['DWheat_' + _type + '_D'] = DWheat_D_D
    # Delta Active Power Cooling Upwards Contribution
    DWcool_D_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DWcool_' + _type + '_U')
    _vars_dict['DWcool_' + _type + '_U'] = DWcool_D_U
    # Delta Active Power Cooling Downwards Contribution
    DWcool_D_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DWcool_' + _type + '_D')
    _vars_dict['DWcool_' + _type + '_D'] = DWcool_D_D

    # Delta Active Power Upwards Contribution
    DW_D_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_U')
    _vars_dict['DW_' + _type + '_U'] = DW_D_U
    # Delta Active Power Downwards Contribution
    DW_D_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DW_' + _type + '_D')
    _vars_dict['DW_' + _type + '_D'] = DW_D_D
    # Delta Reactive Power Upwards Contribution
    DR_D_U = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_U')
    _vars_dict['DR_' + _type + '_U'] = DR_D_U
    # Delta Reactive Power Downwards Contribution
    DR_D_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='DR_' + _type + '_D')
    _vars_dict['DR_' + _type + '_D'] = DR_D_D

    # Heat/Cool generated by the pump [kWh]
    Q_hp_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='Q_hp_' + _type)
    _vars_dict['Q_hp_' + _type] = Q_hp_D
    # Effective heat/cool entering the residence [kWh]
    Q_in_D = grb_model.addVars(shape_var, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='Q_in_' + _type)
    _vars_dict['Q_in_' + _type] = Q_in_D
    # Temperature inside the residence [°C]
    T_in_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='T_in' + _type)
    _vars_dict['T_in_' + _type] = T_in_D
    # Temperature of the wall [°C]
    T_w_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='T_w_' + _type)
    _vars_dict['T_w_' + _type] = T_w_D
    # Temperature of the roof [°C]
    T_r_D = grb_model.addVars(shape_var, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='T_r_' + _type)
    _vars_dict['T_r_' + _type] = T_r_D
    # Binary Variables for Heating or Cooling
    x_heat = grb_model.addVars(shape_var, vtype=GRB.BINARY, name='x_heat')
    _vars_dict['x_heat'] = x_heat
    x_cool = grb_model.addVars(shape_var, vtype=GRB.BINARY, name='x_cool')
    _vars_dict['x_cool'] = x_cool
    return _vars_dict


def define_constraints(_grb_model, _vars_dict, _fsp_data, _idx_res, _interval, _cap_cstr, _int_soc=False, _dt=1, _type='D'):
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
    _new_grb_model = hp_constraints(grb_model=_grb_model, _vars_dict=_vars_dict, fsp_data=_fsp_data, i=_idx_res,
                                         t=_interval, _cap_cstr=_cap_cstr, _type=_type)
    return _new_grb_model


def hp_constraints(grb_model, _vars_dict, fsp_data, i, t, _cap_cstr, _type='D'):
    """Define Constraints of the Load Resource."""
    # Extract Variables
    # Delta Reactive Power [p.u.]
    DR_D = _vars_dict['DR_' + _type]
    # After the Market Reactive Power Exchange
    R_D = _vars_dict['R_' + _type]
    # Delta Active Power [p.u.]
    DW_D = _vars_dict['DW_' + _type]
    # Delta Active Power Heating [p.u.]
    DWheat_D = _vars_dict['DWheat_' + _type]
    # Delta Active Power Cooling [p.u.]
    DWcool_D = _vars_dict['DWcool_' + _type]
    # After the Market Active Power
    W_D = _vars_dict['W_' + _type]
    # After the Market Active Power Heating
    Wheat_D = _vars_dict['Wheat_' + _type]
    # After the Market Active Power Cooling
    Wcool_D = _vars_dict['Wcool_' + _type]

    # Delta Active Power Heating Upwards Contribution
    DWheat_D_U = _vars_dict['DWheat_' + _type + '_U']
    # Delta Active Power Heating Downwards Contribution
    DWheat_D_D = _vars_dict['DWheat_' + _type + '_D']
    # Delta Active Power Cooling Upwards Contribution

    DWcool_D_U = _vars_dict['DWcool_' + _type + '_U']
    # Delta Active Power Cooling Downwards Contribution
    DWcool_D_D = _vars_dict['DWcool_' + _type + '_D']

    # Delta Active Power Upwards Contribution
    DW_D_U = _vars_dict['DW_' + _type + '_U']
    # Delta Active Power Downwards Contribution
    DW_D_D = _vars_dict['DW_' + _type + '_D']
    # Delta Reactive Power Upwards Contribution
    DR_D_U = _vars_dict['DR_' + _type + '_U']
    # Delta Reactive Power Downwards Contribution
    DR_D_D = _vars_dict['DR_' + _type + '_D']

    # Heat/Cool generated by the pump [kWh]
    Q_hp_D = _vars_dict['Q_hp_' + _type]
    # Effective heat/cool entering the residence [kWh]
    Q_in_D = _vars_dict['Q_in_' + _type]
    # Temperature inside the residence [°C]
    T_in_D = _vars_dict['T_in_' + _type]
    # Temperature of the wall [°C]
    T_w_D = _vars_dict['T_w_' + _type]
    # Temperature of the roof [°C]
    T_r_D = _vars_dict['T_r_' + _type]
    # Binary Variables for Heating or Cooling
    x_heat = _vars_dict['x_heat']
    x_cool = _vars_dict['x_cool']

    _name_Wheat = 'C#01_Wheat_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DWheat_D[i, t] + x_heat[i, t] * fsp_data['Winit'].iloc[i, t] - Wheat_D[i, t] == 0, name=_name_Wheat)
    _name_Wcool = 'C#01_Wcool_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DWcool_D[i, t] + x_cool[i, t] * fsp_data['Winit'].iloc[i, t] - Wcool_D[i, t] == 0, name=_name_Wcool)

    _name_DWheat = 'C#02_DWheat_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DWheat_D_U[i, t] - DWheat_D_D[i, t] - DWheat_D[i, t] == 0, name=_name_DWheat)
    _name_DWcool = 'C#02_DWcool_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DWcool_D_U[i, t] - DWcool_D_D[i, t] - DWcool_D[i, t] == 0, name=_name_DWcool)

    _name_DWhp = 'C#02_DWhp_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DW_D_U[i, t] - DW_D_D[i, t] - DW_D[i, t] == 0, name=_name_DWhp)

    _name_DWhp_up_pr = 'C#02_DWhp_Up_pr_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr((10 ** -6) * DWheat_D_U[i, t] + (10 ** -6) * DWcool_D_U[i, t] - DW_D_U[i, t] == 0, name=_name_DWhp_up_pr)
    _name_DWhp_dwn_pr = 'C#02_DWhp_Down_pr_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr((10 ** -6) * DWheat_D_D[i, t] + (10 ** -6) * DWcool_D_D[i, t] - DW_D_D[i, t] == 0, name=_name_DWhp_dwn_pr)

    _name_Whp = 'C#03_Whp_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr((10 ** -6) * Wheat_D[i, t] + (10 ** -6) * Wcool_D[i, t] - W_D[i, t] == 0, name=_name_Whp)

    _name_Wheat_max = 'C#04_Wheat_max_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wheat_D[i, t] - x_heat[i, t] * fsp_data['Wlb'].iloc[i, t] <= 0, name=_name_Wheat_max)
    _name_Wheat_min = 'C#04_Wheat_min_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wheat_D[i, t] - x_heat[i, t] * fsp_data['Wub'].iloc[i, t] >= 0, name=_name_Wheat_min)

    _name_Wcool_max = 'C#05_Wcool_max_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wcool_D[i, t] - x_cool[i, t] * fsp_data['Wlb'].iloc[i, t] <= 0, name=_name_Wcool_max)
    _name_Wcool_min = 'C#05_Wcool_min_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wcool_D[i, t] - x_cool[i, t] * fsp_data['Wub'].iloc[i, t] >= 0, name=_name_Wcool_min)

    # The upward and downward deviation caps are not imposed in this model.

    _name_DReq = 'C#06_DReq_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_D_U[i, t] - DR_D_D[i, t] - DR_D[i, t] == 0, name=_name_DReq)
    _name_DR = 'C#07_DR_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(DR_D[i, t] == 0, name=_name_DR)
    _name_R = 'C#07_R_' + _type + '_' + str(i) + '_t' + str(t)
    grb_model.addConstr(R_D[i, t] == 0, name=_name_R)

    _name_heatcool_hp = 'C#08_HeatCool_hp' + str(i) + '_t' + str(t)
    grb_model.addConstr(Wheat_D[i, t] * fsp_data['HP_params'].COP[i] - Wcool_D[i, t] * fsp_data['HP_params'].COP[i] + Q_hp_D[i, t] == 0, name=_name_heatcool_hp)

    _name_heatcool_in = 'C#08_HeatCool_internal_hp' + str(i) + '_t' + str(t)
    grb_model.addConstr(Q_hp_D[i, t] - Q_in_D[i, t] - x_heat[i, t] * (fsp_data['T_params'].Qloss[t] - fsp_data['T_params'].Qrad[t])
                        - x_cool[i, t] * (-fsp_data['T_params'].Qloss[t] + fsp_data['T_params'].Qrad[t]) == 0, name=_name_heatcool_in)

    if t == 0:
        _name_t_in = 'C#09_T_internal_hp' + str(i) + '_t' + str(t)
        grb_model.addConstr(T_in_D[i, t] - fsp_data['HP_params'].Tin_0[i] == 0, name=_name_t_in)

        _name_t_w = 'C#09_T_wall_hp' + str(i) + '_t' + str(t)
        grb_model.addConstr(T_w_D[i, t] - fsp_data['HP_params'].Twall_0[i] == 0, name=_name_t_w)

        _name_t_r = 'C#09_T_roof_hp' + str(i) + '_t' + str(t)
        grb_model.addConstr(T_r_D[i, t] - fsp_data['HP_params'].Troof_0[i] == 0, name=_name_t_r)
    else:
        _name_t_in = 'C#09_T_internal_hp' + str(i) + '_t' + str(t)
        c_roof_in = (fsp_data['HP_params'].Resistance_Roof_in[i] / fsp_data['HP_params'].Capacitance_Air[i])
        c_window = (fsp_data['HP_params'].Resistance_Window[i] / fsp_data['HP_params'].Capacitance_Air[i])
        c_wall_in = (fsp_data['HP_params'].Resistance_Wall_in[i] / fsp_data['HP_params'].Capacitance_Air[i])
        grb_model.addConstr(
            T_in_D[i, t] == T_in_D[i, t - 1] + c_roof_in * (T_r_D[i, t - 1] - T_in_D[i, t - 1])
            + c_window * (fsp_data['T_params'].Tout[t - 1] - T_in_D[i, t - 1]) + c_wall_in * (T_w_D[i, t - 1] - T_in_D[i, t - 1])
            + (Q_in_D[i, t - 1]) / fsp_data['HP_params'].Capacitance_Air[i], name=_name_t_in)

        _name_t_w = 'C#09_T_wall_hp' + str(i) + '_t' + str(t)
        c_wall_out = (fsp_data['HP_params'].Resistance_Wall_out[i] / fsp_data['HP_params'].Capacitance_Air[i])
        c_wall_in = (fsp_data['HP_params'].Resistance_Wall_in[i] / fsp_data['HP_params'].Capacitance_Wall[i])
        grb_model.addConstr(
            T_w_D[i, t] == T_w_D[i, t - 1] + c_wall_out * (fsp_data['T_params'].Tout[t - 1] - T_w_D[i, t - 1]) + c_wall_in * (T_in_D[i, t - 1] - T_w_D[i, t - 1]), name=_name_t_w)

        _name_t_r = 'C#09_T_roof_hp' + str(i) + '_t' + str(t)
        c_roof_out = (fsp_data['HP_params'].Resistance_Roof_out[i] / fsp_data['HP_params'].Capacitance_Roof[i])
        c_roof_in = (fsp_data['HP_params'].Resistance_Roof_in[i] / fsp_data['HP_params'].Capacitance_Roof[i])
        grb_model.addConstr(
            T_r_D[i, t] == T_r_D[i, t - 1] + c_roof_out * (fsp_data['HP_params'].Tneighbour[i] - T_r_D[i, t - 1]) + c_roof_in * (T_in_D[i, t - 1] - T_r_D[i, t - 1]),
            name=_name_t_r)

    _name_max_t_int = 'C#09_T_internal_max_hp' + str(i) + '_t' + str(t)
    grb_model.addConstr(T_in_D[i, t] - fsp_data['HP_params'].Tmax[i] <= 0, name=_name_max_t_int)

    _name_min_t_int = 'C#09_T_internal_min_hp' + str(i) + '_t' + str(t)
    grb_model.addConstr(T_in_D[i, t] - fsp_data['HP_params'].Tmin[i] >= 0, name=_name_min_t_int)

    _name_xheatcool = 'C#10_binary_heating_cooling_hp' + str(i) + '_t' + str(t)
    grb_model.addConstr(x_heat[i, t] + x_cool[i, t] == 1, name=_name_xheatcool)

    return grb_model


def define_profiles(_root2inputs, _pp_res, _timestep):
    """
    Optimise the Storage profiles using the Day-Ahead Market Prices and Day-Ahead Load and Generation Profiles.
    Consider the fact that we are neglecting the network, therefore we consider all the resources like a Virtual
    Power Plant. Maximise the Social Welfare of the VPN.
    """
    hp_res_p, hp_res_q = 0, 0

    # Read initial data
    price_params = _read_input_params(_root2inputs, _sheetname='price_params', _index_col=0, _header=0)
    temp_params = _read_input_params(_root2inputs, _sheetname='temperature_params', _index_col=0, _header=0)
    hp_params = _read_input_params(_root2inputs, _sheetname='res_params', _index_col=0, _header=0)

    _flag_model = True
    _flag_res = True
    _dt = 1
    _interval = _timestep[1] - _timestep[0]

    # Create a New Gurobi-py Model
    name_model = 'Heatpump_initial_profiles_model'
    hp_model = gp.Model(name_model)

    n_hp = _pp_res.shape[0]

    va = _pp_res.sn_mva * 1e6

    shape_hp = tuplelist([(k, t) for k in range(n_hp) for t in range(_interval)])
    # Effective power consumption for heating/cooling of the Heat pump [MWh]
    p_hp = hp_model.addVars(shape_hp, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='p_hp')
    # Heat pump consumption for heating [W]
    p_heat = hp_model.addVars(shape_hp, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='p_heat')
    # Heat pump consumption for cooling [W]
    p_cool = hp_model.addVars(shape_hp, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='p_cool')
    # Effective heat/cool entering the residence [Wh]
    q_in = hp_model.addVars(shape_hp, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='q_in')
    # Heat/Cool generated by the pump [Wh]
    q_hp = hp_model.addVars(shape_hp, lb=0, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='q_hp')
    # Temperature inside the residence [°C]
    t_in = hp_model.addVars(shape_hp, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='t_in')
    # Temperature of the wall [°C]
    t_w = hp_model.addVars(shape_hp, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='t_w')
    # Temperature of the roof [°C]
    t_r = hp_model.addVars(shape_hp, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name='t_r')
    # Binary Variables for Heating or Cooling
    x_heat = hp_model.addVars(shape_hp, vtype=GRB.BINARY, name='x_heat')
    x_cool = hp_model.addVars(shape_hp, vtype=GRB.BINARY, name='x_cool')

    for k in range(n_hp):
        for t in range(_interval):
            _name_p_eq = 'power_eq_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(p_hp[k, t] - (10 ** -6) * p_heat[k, t] - (10 ** -6) * p_cool[k, t] == 0, name=_name_p_eq)

            _name_hp_p_eq = 'heating_cooling_power_eq_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(p_heat[k, t] * hp_params.COP[k] - p_cool[k, t] * hp_params.COP[k] - q_hp[k, t] == 0, name=_name_hp_p_eq)

            _name_max_p_heat = 'max_p_heating_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(p_heat[k, t] - x_heat[k, t] * va[k] <= 0, name=_name_max_p_heat)

            _name_max_p_cool = 'max_p_cooling_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(p_cool[k, t] - x_cool[k, t] * va[k] <= 0, name=_name_max_p_cool)

            _name_hp_eq = 'heating_cooling_eq_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(q_hp[k, t] - q_in[k, t] - x_heat[k, t] * (temp_params.Qloss[t] - temp_params.Qrad[t])
                               - x_cool[k, t] * (-temp_params.Qloss[t] + temp_params.Qrad[t]) == 0, name=_name_hp_eq)

            if t == 0:
                _name_t_in = 't_internal_eq_hp' + str(k) + '_t' + str(t)
                hp_model.addConstr(t_in[k, t] - hp_params.Tin_0[k] == 0, name=_name_t_in)

                _name_t_w = 't_wall_eq_hp' + str(k) + '_t' + str(t)
                hp_model.addConstr(t_w[k, t] - hp_params.Twall_0[k] == 0, name=_name_t_w)

                _name_t_r = 't_roof_eq_hp' + str(k) + '_t' + str(t)
                hp_model.addConstr(t_r[k, t] - hp_params.Troof_0[k] == 0, name=_name_t_r)
            else:
                _name_t_in = 't_internal_eq_hp' + str(k) + '_t' + str(t)
                hp_model.addConstr(t_in[k, t] == t_in[k, t-1] + (hp_params.Resistance_Roof_in[k] / hp_params.Capacitance_Air[k]) * (t_r[k, t-1] - t_in[k, t-1])
                                   + (hp_params.Resistance_Window[k] / hp_params.Capacitance_Air[k]) * (temp_params.Tout[t-1] - t_in[k, t-1])
                                   + (hp_params.Resistance_Wall_in[k] / hp_params.Capacitance_Air[k]) * (t_w[k, t-1] - t_in[k, t-1])
                                   + q_in[k, t-1] / hp_params.Capacitance_Air[k], name=_name_t_in)

                _name_t_w = 't_wall_eq_hp' + str(k) + '_t' + str(t)
                hp_model.addConstr(t_w[k, t] == t_w[k, t-1] + (hp_params.Resistance_Wall_out[k] / hp_params.Capacitance_Air[k]) * (temp_params.Tout[t-1] - t_w[k, t-1])
                                   + (hp_params.Resistance_Wall_in[k] / hp_params.Capacitance_Wall[k]) * (t_in[k, t-1] - t_w[k, t-1]), name=_name_t_w)

                _name_t_r = 't_roof_eq_hp' + str(k) + '_t' + str(t)
                hp_model.addConstr(t_r[k, t] == t_r[k, t-1] + (hp_params.Resistance_Roof_out[k] / hp_params.Capacitance_Roof[k]) * (hp_params.Tneighbour[k] - t_r[k, t-1])
                                   + (hp_params.Resistance_Roof_in[k] / hp_params.Capacitance_Roof[k]) * (t_in[k, t-1] - t_r[k, t-1]), name=_name_t_r)

            _name_max_t_int = 'max_t_internal_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(t_in[k, t] - hp_params.Tmax[k] <= 0, name=_name_max_t_int)

            _name_min_t_int = 'min_t_internal_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(t_in[k, t] - hp_params.Tmin[k] >= 0, name=_name_min_t_int)

            _name_xheatcool = 'binary_heating_cooling_hp' + str(k) + '_t' + str(t)
            hp_model.addConstr(x_heat[k, t] + x_cool[k, t] == 1, name=_name_xheatcool)

    costs_coeff = dict(zip(shape_hp, price_params['Electricity_Costs']))
    obj_fcn = p_heat.prod(costs_coeff) + p_cool.prod(costs_coeff)
    hp_model.setObjective(obj_fcn, GRB.MAXIMIZE)

    # Write Model on file to check correctness
    if _flag_model:
        _root_res = 'Heatpump_Profiles'
        path2folder = os.path.dirname(os.path.abspath(_root2inputs))
        new_folder = os.path.join(path2folder, _root_res)
        if not os.path.exists(new_folder):
            os.makedirs(new_folder)
        hp_model.write(os.path.join(new_folder, name_model + '.lp'))

    # Optimise
    hp_model.Params.MIPGap = .0000001
    hp_model.Params.LogToConsole = 0
    hp_model.optimize()
    status = hp_model.status
    if status == GRB.OPTIMAL:
        try:
            variables = {'Obj': [hp_model.ObjVal]}
            matrix_p_hp = np.zeros(shape=(_interval, n_hp))
            matrix_p_heat = np.zeros(shape=(_interval, n_hp))
            matrix_p_cool = np.zeros(shape=(_interval, n_hp))
            matrix_q_in = np.zeros(shape=(_interval, n_hp))
            matrix_q_hp = np.zeros(shape=(_interval, n_hp))
            matrix_t_in = np.zeros(shape=(_interval, n_hp))
            matrix_t_w = np.zeros(shape=(_interval, n_hp))
            matrix_t_r = np.zeros(shape=(_interval, n_hp))
            for k in range(n_hp):
                for t in range(_interval):
                    matrix_p_hp[t, k] = p_hp[(k, t)].X
                    matrix_p_heat[t, k] = p_heat[(k, t)].X
                    matrix_p_cool[t, k] = p_cool[(k, t)].X
                    matrix_q_in[t, k] = q_in[(k, t)].X
                    matrix_q_hp[t, k] = q_hp[(k, t)].X
                    matrix_t_in[t, k] = t_in[(k, t)].X
                    matrix_t_w[t, k] = t_w[(k, t)].X
                    matrix_t_r[t, k] = t_r[(k, t)].X
            variables['P_hp'] = matrix_p_hp
            variables['P_heat'] = matrix_p_heat
            variables['P_cool'] = matrix_p_cool
            variables['Q_internal'] = matrix_q_in
            variables['Q_hp'] = matrix_q_hp
            variables['T_internal'] = matrix_t_in
            variables['T_wall'] = matrix_t_w
            variables['T_roof'] = matrix_t_r
        except Exception as error:
            raise UserWarning('An error occurred:', type(error).__name__, '–', error)

        if _flag_res:
            _root_res = 'Heatpump_Profiles'
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

        hp_res_p = pd.DataFrame(variables['P_hp'])
        hp_res_q = pd.DataFrame(np.zeros(shape=(_interval, n_hp)))
    else:
        d = solver_status.status_names()
        raise Warning('Optimization was stopped with status: {_stat}'.format(_stat=d[status]))

    return hp_res_p, hp_res_q


def fsp_converter(_data, _k_opt=1, _class_fsp='heatpump', _fsp_filename=''):
    """
    Adapt the fsp load info into usable data for the local flexibility market optimization.


    :param _data: Dictionary containing all the information useful for the conversion into usable data. The useful data
        are the pandapower network (net), the dictionary with the timeseries simulation (ts_res), the dataframe with the fsp
        data involved in the simulation (fsp_data), the output root where to save files (out_root), the list of hours with
        network constraint violations (hours), the bidding strategy of the fsp element (bid_strat), the multiplier
        coefficient of the load (scen_factor_load), the multiplier coefficient of the generation (scen_factor_gen),
        the active power bid up coefficient (kbid_p_up), the active power bid down coefficient (kbid_p_dwn),
        the reactive power bid up coefficient (kbid_q_up), the reactive power down up coefficient (kbid_q_dwn) and
        the simulation tag (sim_tag).


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
    _scen_factor_load = _data['scen_factor_load']
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
    # Network Name
    _net_name = _data['net_name']
    # File FSP for Additional Information
    _fsp_file_add = _data['fsp_additional_file']

    mode_xlsx = 'w'
    res_cat = 'load'

    # Trasform the MW values into W values
    load_p_premkt = _ts_res['load_p_mw'].T * (10 ** 6)
    load_q_premkt = _ts_res['load_q_mvar'].T * (10 ** 6)
    class_fsp_df = _fsp_data.loc[_fsp_data.type == _class_fsp].reset_index(drop=True)
    labels = fsp_labels(class_fsp_df, _class_fsp)

    n_hp_fsp = len(class_fsp_df.id)

    class_fsp_df.mva = class_fsp_df.mva * _scen_factor_load
    class_fsp_df.Pup = class_fsp_df.Pup * _kbid_p_up
    class_fsp_df.Pdown = class_fsp_df.Pdown * _kbid_p_dwn
    class_fsp_df.Qup = class_fsp_df.Qup * _kbid_q_up
    class_fsp_df.Qdown = class_fsp_df.Qdown * _kbid_q_dwn

    _n_hours = len(_hours)
    shape_init = (n_hp_fsp, _n_hours)

    r_ub_dlim = np.zeros(shape=shape_init)
    r_ub_ulim = np.zeros(shape=shape_init)
    w_lb_ulim = np.zeros(shape=shape_init)
    w_ub_dlim = np.zeros(shape=shape_init)

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

    # Read initial data
    _in_root = 'data_in'
    _folder_ext = 'fsp_files'
    _root2file = os.path.join(os.getcwd(), _in_root, _net_name, _folder_ext, _fsp_file_add)
    temperature_params = _read_input_params(_root2file, _sheetname='temperature_params', _index_col=0, _header=0)
    hp_params = _read_input_params(_root2file, _sheetname='res_params', _index_col=0, _header=0)

    for i in tqdm(range(n_hp_fsp), desc='Initialising HP bids (Heatpump follow the load convention)'):
        _idx = match_pp_element(_net.load, class_fsp_df.iloc[i], 'load')
        fsp_w_init[i, :] = load_p_premkt.loc[_idx, _hours].to_numpy()
        fsp_r_init[i, :] = load_q_premkt.loc[_idx, _hours].to_numpy()

        if class_fsp_df.bidding_strategy[i] == 'initial_value':
            w_ref = fsp_w_init
        else:
            # _bid_strat == 'mva_value':
            w_ref = fsp_mva

        for h in range(_n_hours):
            # Active power lower bound upward limit
            if class_fsp_df.Pup.iloc[i] > 0:
                w_lb_ulim[i, h] = fsp_w_init[i, h] - ((class_fsp_df.Pup.iloc[i]) * w_ref[i, h])
            else:
                w_lb_ulim[i, h] = fsp_w_init[i, h]
            # A heat pump cannot be curtailed
            # below zero consumption.  The market's W_D <= 0 already stops the
            # dispatch there, so this only corrects the bid file and the offered
            # flexibility read from it.
            w_lb_ulim[i, h] = headroom_lib.floor_lower_bound(w_lb_ulim[i, h], fsp_w_init[i, h], 0.0)

            # Active power upper bound downward limit
            if class_fsp_df.Pdown.iloc[i] > 0:
                w_ub_dlim[i, h] = fsp_w_init[i, h] + ((class_fsp_df.Pdown.iloc[i]) * w_ref[i, h])
            else:
                w_ub_dlim[i, h] = fsp_w_init[i, h]

    if n_hp_fsp > 0:
        resource_category = pd.DataFrame([res_cat for _ in range(n_hp_fsp)], columns=['res_category'])
        fsp_info = pd.concat([class_fsp_df.id, class_fsp_df.name, class_fsp_df.bus, class_fsp_df.mva, resource_category], axis=1)
        fsp_info.index = labels

        _path2file = os.path.join(_out_root, _fsp_filename + '.xlsx')
        if os.path.exists(_path2file):
            mode_xlsx = 'a'

        io_file.save_excel(_data=fsp_info, _outroot=_out_root, _filename=_fsp_filename, _sheetname='FSPinfo_' + _class_fsp, _mode=mode_xlsx)

        io_file.save_excel(_data=fsp_frame(fsp_p_up_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='W_U_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_p_dwn_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='W_D_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_q_up_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='R_U_Cost_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_q_dwn_cost, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='R_D_Cost_' + _class_fsp, _mode='a')

        io_file.save_excel(_data=fsp_frame(fsp_w_init, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='Winit_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(fsp_r_init, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='Rinit_' + _class_fsp, _mode='a')

        io_file.save_excel(_data=fsp_frame(r_ub_dlim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='RUB_DLim_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(r_ub_ulim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='RUB_ULim_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(w_lb_ulim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='WLB_ULim_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=fsp_frame(w_ub_dlim, labels, _hours), _outroot=_out_root, _filename=_fsp_filename, _sheetname='WUB_DLim_' + _class_fsp, _mode='a')

        io_file.save_excel(_data=temperature_params, _outroot=_out_root, _filename=_fsp_filename, _sheetname='T_params_' + _class_fsp, _mode='a')
        io_file.save_excel(_data=hp_params, _outroot=_out_root, _filename=_fsp_filename, _sheetname='HP_params_' + _class_fsp, _mode='a')
    else:
        _fsp_filename = 0
    return _fsp_filename, fsp_bus_series(class_fsp_df, labels)


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
