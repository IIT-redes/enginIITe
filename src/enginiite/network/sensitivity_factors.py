import os
import gc
import math
import hashlib  # Input signature of a matrix
import warnings
from types import SimpleNamespace  # Cached result tables
import numpy as np
import pandas as pd
import pandapower as pp
from tqdm.auto import tqdm
from enginiite import file_io as io_file

gc.collect()
warnings.filterwarnings("ignore", category=FutureWarning)


def _should_recalculate_cache(_force, *_required_files, _signature=None):
    """Return True unless every required member of a sensitivity cache exists."""
    # P/Q sensitivity files are an atomic
    # cache pair; one surviving member never makes the cache complete.
    if not all(os.path.isfile(path) for path in _required_files):
        return True
    # _force means "never reuse a matrix
    # of an earlier run".  A matrix this run already wrote from identical inputs
    # (see _inputs_signature) is still valid, so it is not solved again for the
    # next F-level or product of the same run.
    if _force:
        return not (_signature is not None
                    and all(_WRITTEN_THIS_RUN.get(os.path.normcase(os.path.abspath(path))) == _signature
                            for path in _required_files))
    return False


# Files written by this process, mapped to
# the signature of the inputs they were computed from.
_WRITTEN_THIS_RUN = {}


def _mark_written(_signature, *_files):
    """Record that these matrix files were written in this run from _signature."""
    for path in _files:
        _WRITTEN_THIS_RUN[os.path.normcase(os.path.abspath(path))] = _signature


def _hash_part(_value):
    """Stable text for one input of a matrix (frames, series, arrays, scalars)."""
    if isinstance(_value, (pd.DataFrame, pd.Series)):
        return str(pd.util.hash_pandas_object(_value, index=True).values.tobytes())
    if isinstance(_value, np.ndarray):
        return repr(_value.tolist())
    if isinstance(_value, (list, tuple)):
        return '[' + ','.join(_hash_part(v) for v in _value) + ']'
    return repr(_value)


def _inputs_signature(*_parts):
    """Signature of every input a sensitivity matrix depends on.

    Two matrices with the same signature
    come from the same network, operating point, providers, monitored elements and
    perturbation, so they are identical.
    """
    digest = hashlib.sha1()
    for part in _parts:
        digest.update(_hash_part(part).encode('utf-8'))
        digest.update(b'|')
    return digest.hexdigest()


def _network_signature(_net):
    """Signature of the tables that define the network physics (not its results)."""
    tables = []
    for name in ('bus', 'line', 'trafo', 'trafo3w', 'switch', 'shunt', 'impedance', 'ward', 'ext_grid',
                 'load', 'sgen', 'gen', 'storage'):
        table = _net[name] if name in _net else None
        if table is None or table.empty:
            tables.append(name + ':empty')
            continue
        tables.append(table.drop(columns=[c for c in ('name', 'geo') if c in table.columns]).astype(str))
    return _inputs_signature(*tables)


def _hour_signature(_h, *_profiles):
    """Signature of the operating point of hour _h (loads, sgens, gens, storage)."""
    return _inputs_signature(_h, *[p[_h] if isinstance(p, pd.DataFrame) else p for p in _profiles])


def _ext_grid_vm_by_hour(_ts_res, _net):
    """
    Supply voltage of every external grid per hour.

    The time series logs the voltage of every bus; at an ext_grid bus it equals that hour's set-point (which may
    change per time step, see file_io.import_ext_grid_profile).  Returns a DataFrame (rows = ext_grid index,
    columns = hours) like the other transposed profiles, or 0 when the voltages were not logged, in which case
    the network-file set-point is kept.
    """
    if 'bus_vm_pu' not in _ts_res or _net.ext_grid.empty:
        return 0
    _vm = _ts_res['bus_vm_pu']
    _cols = {str(c): c for c in _vm.columns}
    _keys = [_cols.get(str(int(b))) for b in _net.ext_grid.bus]
    if any(k is None for k in _keys):
        return 0
    _out = _vm[_keys].copy()
    _out.columns = _net.ext_grid.index
    return _out.T


def _set_ext_grid_vm(_pp_net, _ext_vm, _h):
    """ apply hour _h of _ext_grid_vm_by_hour()."""
    if isinstance(_ext_vm, pd.DataFrame) and _h in _ext_vm.columns:
        _pp_net.ext_grid.vm_pu = list(_ext_vm[_h].reindex(_pp_net.ext_grid.index))


def _signed_voltage_sensitivity(_base_vm_pu, _perturbed_vm_pu, _delta):
    """Calculate signed voltage-magnitude sensitivity for a nonzero perturbation."""
    if abs(float(_delta)) <= 1e-15:
        raise ValueError('Voltage-sensitivity perturbation must be nonzero.')
    return (float(_perturbed_vm_pu) - float(_base_vm_pu)) / float(_delta)


def _unique_labels(_labels):
    seen = {}
    unique = []
    for label in _labels:
        if label not in seen:
            seen[label] = 0
            unique.append(label)
        else:
            seen[label] += 1
            unique.append(f"{label}__{seen[label]}")
    return unique


def _bus_values_and_labels(_bus_vector):
    """Split electrical bus locations from row labels used in sensitivity matrices."""
    if isinstance(_bus_vector, pd.Series):
        bus_values = _bus_vector.to_list()
        labels = _bus_vector.index.to_list()
    elif isinstance(_bus_vector, pd.DataFrame):
        if 'bus' not in _bus_vector.columns:
            raise ValueError("FSP bus dataframe must contain a 'bus' column.")
        bus_values = _bus_vector['bus'].to_list()
        labels = _bus_vector.index.to_list()
    else:
        bus_values = list(_bus_vector)
        labels = bus_values.copy()

    return bus_values, _unique_labels(labels)


def _check_element_names(_pp_network):
    """
    This function checks if the network passed defined the line names. In case it does not, add branch names.
    """
    _my_new_network = _copy_net_essential(_pp_network)
    for _idx_line, _name_line in tqdm(_my_new_network.line.name.items(), desc='Checking Name of Lines in the Network'):
        if _name_line is None:
            _my_new_network.line.name[_idx_line] = 'Line' + str(_idx_line)

    for _idx_trafo, _name_trafo in tqdm(_my_new_network.trafo.name.items(), desc='Checking Name of Trafo in the Network'):
        if _name_trafo is None:
            _my_new_network.trafo.name[_idx_trafo] = 'Trafo' + str(_idx_trafo)

    for _idx_trafo3w, _name_trafo3w in tqdm(_my_new_network.trafo3w.name.items(), desc='Checking Name of Trafo3W in the Network'):
        if _name_trafo3w is None:
            _my_new_network.trafo3w.name[_idx_trafo3w] = 'Trafo3w_' + str(_idx_trafo3w)

    return _my_new_network


def _copy_net_essential(_pp_network):
    """
    Copy essential elements of a pandapower network.

    :param _pp_network: Pandapower network

    :return _new_net: Copy of the essential elements of the pandapower network.
    """
    _new_net = pp.create_empty_network()
    _new_net.ext_grid = _pp_network.ext_grid.copy()
    _new_net.bus = _pp_network.bus.copy()
    _new_net.load = _pp_network.load.copy()
    _new_net.line = _pp_network.line.copy()
    if not _pp_network.sgen.empty:
        _new_net.sgen = _pp_network.sgen.copy()
    if not _pp_network.gen.empty:
        _new_net.gen = _pp_network.gen.copy()
    if not _pp_network.storage.empty:
        _new_net.storage = _pp_network.storage.copy()
    if not _pp_network.switch.empty:
        _new_net.switch = _pp_network.switch.copy()
    if not _pp_network.shunt.empty:
        _new_net.shunt = _pp_network.shunt.copy()
    if not _pp_network.trafo.empty:
        _new_net.trafo = _pp_network.trafo.copy()
    if not _pp_network.trafo3w.empty:
        _new_net.trafo3w = _pp_network.trafo3w.copy()
    if not _pp_network.impedance.empty:
        _new_net.impedance = _pp_network.impedance.copy()
    if not _pp_network.ward.empty:
        _new_net.ward = _pp_network.ward.copy()
    if not _pp_network.group.empty:
        _new_net.group = _pp_network.group.copy()
    return _new_net


def create_vsgen(_net, _bus, _p_q, _delta):
    """
    Custom function to create a virtual generator on a specific bus in the network
    with an active/reactive power equal to delta.

    :param _net: Pandapower network.

    :param _bus: Bus in which the virtual generator will be included.

    :param _p_q: Flag to identify if the generator will inject active or reactive power.

    :param _delta: Active/Reactive power of the virtual generator.
    """
    index = len(_net.sgen)
    try:
        nt = _net.sgen.type.iloc[index - 1]
    except IndexError:
        nt = 'wye'

    if _p_q == 'p':
        pp.create_sgen(_net, name='GVirt', index=index, bus=_bus, p_mw=_delta, q_mvar=0, type=nt, min_p_mw=0,
                       max_p_mw=_delta, min_q_mvar=0, max_q_mvar=0, controllable=True)
    elif _p_q == 'q':
        pp.create_sgen(_net, name='GVirt', index=index, bus=_bus, p_mw=0, q_mvar=_delta, type=nt, min_p_mw=0,
                       max_p_mw=0, min_q_mvar=0, max_q_mvar=_delta, controllable=True)
    else:
        raise UserWarning('Check p - q (p for active, q for reactive).')
    return True


# One pair of perturbed power flows per
# electrical bus.  The virtual +dP / +dQ injection of a provider depends only on
# the bus it is connected to, so every provider on one bus -- of any class -- and
# the pilot-bus self-sensitivity of that bus share the same two power flows.  Each
# perturbation starts from a fresh copy of the network, and only its result tables are kept.
def _perturbed_bus_results(_net, _buses, _dp, _dq, _cache=None):
    """Solve the +dP and +dQ perturbation of every distinct bus in _buses once.

    :param _net: Pandapower network at the operating point of the matrix.

    :param _buses: Buses to perturb (signed values allowed, as in the FSP vectors).

    :param _cache: Optional dict shared by every call made at this SAME operating
     point (one hour of one network); a bus solved before is not solved again.

    :return: dict (bus, dp, dq) -> (result tables after +dP, result tables after +dQ).
    """
    cache = {} if _cache is None else _cache
    for bus in _buses:
        key = (abs(bus), _dp, _dq)
        if key in cache:
            continue
        solved = []
        for p_q, delta in (('p', _dp), ('q', _dq)):
            _net_pert = _copy_net_essential(_net)
            create_vsgen(_net_pert, abs(bus), p_q, delta)
            pp.runpp(_net_pert)
            solved.append(SimpleNamespace(res_bus=_net_pert.res_bus, res_line=_net_pert.res_line,
                                          res_trafo=_net_pert.res_trafo, res_trafo3w=_net_pert.res_trafo3w))
        cache[key] = tuple(solved)
    return cache


# Optional CURRENT-based congestion
# sensitivity.  The market constrains s_init - cm_factor * H * dx <= Smax - tol,
# and both s_init (AC loading percent x rating) and the AC acceptance test
# (loading_percent, i.e. current against max_i_ka) are current-based.  The
# default dS/dP and dS/dQ, however, are built from sqrt(max|p|^2 + max|q|^2)
# with the larger end of P and of Q taken separately, which does not see the
# extra current that reactive absorption draws.  On SB72 (line 7, DER_WID_HIGH)
# it gave dS/dQ = -0.035 against -0.090 from the current, and the market, with
# reactive power priced at 5 % of active power, overloaded the line in every
# corrective round.  With _basis='current' the branch flow is the apparent
# power at its current: sqrt(3) * Vn * I for lines, loading x rating for
# transformers -- the quantity s_init and the AC test already use.
def _branch_current_mva(_net, _table, _idx, _res):
    """Apparent power of one branch at its current, in MVA (the market's s_init basis)."""
    if _table == 'line':
        vn = float(_net.bus.vn_kv.at[_net.line.from_bus.at[_idx]])
        return math.sqrt(3.0) * vn * float(_res.res_line.at[_idx, 'i_ka'])
    if _table == 'trafo':
        return float(_res.res_trafo.at[_idx, 'loading_percent']) / 100.0 * float(_net.trafo.sn_mva.at[_idx])
    return float(_res.res_trafo3w.at[_idx, 'loading_percent']) / 100.0 * float(_net.trafo3w.sn_hv_mva.at[_idx])


# _cache argument (bus perturbations shared at one operating point)
# and _basis ('apparent_power', the default and the original method, or 'current').
def sens_factors_cm(_net, _fsp_bus, _br_array, _trafo_array, _trafo3w_array, _dp, _dq, _only_ds=True, _cache=None,
                    _basis='apparent_power'):
    """
    Custom function for calculating the Sensitivity factors of the network for congestion management.

    :param _net: Pandapower network.

    :param _fsp_bus: List of bus included as flexibility service provider.

    :param _br_array: Numpy array of the congested branch in the network.

    :param _trafo_array: Numpy array of the congested trafo 2 windings in the network.

    :param _trafo3w_array: Numpy array of the congested trafo 3 windings in the network.

    :param _dp: Active power deviation.

    :param _dq: Reactive power deviation.

    :param _only_ds: Boolean value (True/False) to evaluate only dSdP and dSdQ matrix
     or evaluate PTDF and QTDF matrix as well.

    :param _cache: Optional perturbation cache shared by the calls made at the same
     operating point (see _perturbed_bus_results).
    """
    _ = gc.collect()

    # Starting power flow in initial conditions
    _net0 = _copy_net_essential(_net)
    pp.runpp(_net0)

    _tot_bus = _net.bus.index
    _tot_branch = _net.line.index
    _tot_trafo = _net.trafo.index
    _tot_trafo3w = _net.trafo3w.index

    fsp_buses, fsp_labels = _bus_values_and_labels(_fsp_bus)

    _ptdf = [list() for _ in range(len(fsp_buses))]
    _qtdf = [list() for _ in range(len(fsp_buses))]
    _dsdp = [list() for _ in range(len(fsp_buses))]
    _dsdq = [list() for _ in range(len(fsp_buses))]
    rawname = []
    colname = []

    if (not all(i in _tot_bus for i in map(abs, fsp_buses))
            or not all(i in _tot_branch for i in map(abs, _br_array))
            or not all(i in _tot_trafo for i in map(abs, _trafo_array))
            or not all(i in _tot_trafo3w for i in map(abs, _trafo3w_array))):
        print("WARNING: FSP Bus or Branch or trafo vectors contain errors")

    # ------------------------------- Obtaining PTDF, QTDF and Sensitivity Factor dS/dP -------------------------------
    # The +dP (_net1) and +dQ (_net2) power
    # flows are solved once per distinct bus and shared by every provider on it.
    _perturbed = _perturbed_bus_results(_net, fsp_buses, _dp, _dq, _cache)
    for _i in range(len(fsp_buses)):
        # Active power (_net1) and reactive power (_net2) perturbation results of this bus
        _net1, _net2 = _perturbed[(abs(fsp_buses[_i]), _dp, _dq)]
        # Save Bus Name
        colname.append(fsp_labels[_i])

        for _j in _br_array:
            p_zero = max(abs(_net0.res_line.loc[_j, 'p_from_mw']), abs(_net0.res_line.loc[_j, 'p_to_mw']))
            q_zero = max(abs(_net0.res_line.loc[_j, 'q_from_mvar']), abs(_net0.res_line.loc[_j, 'q_to_mvar']))
            p_plusone_1 = max(abs(_net1.res_line.loc[_j, 'p_from_mw']), abs(_net1.res_line.loc[_j, 'p_to_mw']))
            q_plusone_1 = max(abs(_net1.res_line.loc[_j, 'q_from_mvar']), abs(_net1.res_line.loc[_j, 'q_to_mvar']))
            p_plusone_2 = max(abs(_net2.res_line.loc[_j, 'p_from_mw']), abs(_net2.res_line.loc[_j, 'p_to_mw']))
            q_plusone_2 = max(abs(_net2.res_line.loc[_j, 'q_from_mvar']), abs(_net2.res_line.loc[_j, 'q_to_mvar']))

            if not _only_ds:
                _ptdf[_i].append((p_plusone_1 - p_zero) / _dp)
                _qtdf[_i].append((q_plusone_2 - q_zero) / _dq)

            smn_zero = math.sqrt(p_zero ** 2 + q_zero ** 2)
            smn_plusone_p = math.sqrt(p_plusone_1 ** 2 + q_plusone_1 ** 2)
            smn_plusone_q = math.sqrt(p_plusone_2 ** 2 + q_plusone_2 ** 2)
            if _basis == 'current':  # current-based flow
                smn_zero, smn_plusone_p, smn_plusone_q = (
                    _branch_current_mva(_net, 'line', _j, _r) for _r in (_net0, _net1, _net2))
            _dsdp[_i].append((smn_plusone_p - smn_zero) / _dp)
            _dsdq[_i].append((smn_plusone_q - smn_zero) / _dq)

            rawname.append(_net.line.loc[_j, 'name'])

        for _k in _trafo_array:
            pmn_zero = max(abs(_net0.res_trafo.loc[_k, 'p_hv_mw']), abs(_net0.res_trafo.loc[_k, 'p_lv_mw']))
            pmn_plusone_p = max(abs(_net1.res_trafo.loc[_k, 'p_hv_mw']), abs(_net1.res_trafo.loc[_k, 'p_lv_mw']))
            pmn_plusone_q = max(abs(_net2.res_trafo.loc[_k, 'p_hv_mw']), abs(_net2.res_trafo.loc[_k, 'p_lv_mw']))

            qmn_zero = max(abs(_net0.res_trafo.loc[_k, 'q_hv_mvar']), abs(_net0.res_trafo.loc[_k, 'q_lv_mvar']))
            qmn_plusone_p = max(abs(_net1.res_trafo.loc[_k, 'q_hv_mvar']), abs(_net1.res_trafo.loc[_k, 'q_lv_mvar']))
            qmn_plusone_q = max(abs(_net2.res_trafo.loc[_k, 'q_hv_mvar']), abs(_net2.res_trafo.loc[_k, 'q_lv_mvar']))

            if not _only_ds:
                _ptdf[_i].append((pmn_plusone_p - pmn_zero) / _dp)
                _qtdf[_i].append((qmn_plusone_q - qmn_zero) / _dq)

            smn_zero = math.sqrt(pmn_zero ** 2 + qmn_zero ** 2)
            smn_plusone_p = math.sqrt(pmn_plusone_p ** 2 + qmn_plusone_p ** 2)
            smn_plusone_q = math.sqrt(pmn_plusone_q ** 2 + qmn_plusone_q ** 2)
            if _basis == 'current':  # current-based flow
                smn_zero, smn_plusone_p, smn_plusone_q = (
                    _branch_current_mva(_net, 'trafo', _k, _r) for _r in (_net0, _net1, _net2))
            _dsdp[_i].append((smn_plusone_p - smn_zero) / _dp)
            _dsdq[_i].append((smn_plusone_q - smn_zero) / _dq)

            rawname.append(_net.trafo.loc[_k, 'name'])

        for _l in _trafo3w_array:
            pmn_zero = max(abs(_net0.res_trafo3w.loc[_l, 'p_hv_mw']),
                           abs(_net0.res_trafo3w.loc[_l, 'p_mv_mw'] + _net0.res_trafo3w.loc[_l, 'p_lv_mw']))
            pmn_plusone_p = max(abs(_net1.res_trafo3w.loc[_l, 'p_hv_mw']),
                                abs(_net1.res_trafo3w.loc[_l, 'p_mv_mw'] + _net1.res_trafo3w.loc[_l, 'p_lv_mw']))
            pmn_plusone_q = max(abs(_net2.res_trafo3w.loc[_l, 'p_hv_mw']),
                                abs(_net2.res_trafo3w.loc[_l, 'p_mv_mw'] + _net2.res_trafo3w.loc[_l, 'p_lv_mw']))

            qmn_zero = max(abs(_net0.res_trafo3w.loc[_l, 'q_hv_mvar']),
                           abs(_net0.res_trafo3w.loc[_l, 'q_mv_mvar'] + _net0.res_trafo3w.loc[_l, 'q_lv_mvar']))
            qmn_plusone_p = max(abs(_net1.res_trafo3w.loc[_l, 'q_hv_mvar']),
                                abs(_net1.res_trafo3w.loc[_l, 'q_mv_mvar'] + _net1.res_trafo3w.loc[_l, 'q_lv_mvar']))
            qmn_plusone_q = max(abs(_net2.res_trafo3w.loc[_l, 'q_hv_mvar']),
                                abs(_net2.res_trafo3w.loc[_l, 'q_mv_mvar'] + _net2.res_trafo3w.loc[_l, 'q_lv_mvar']))

            if not _only_ds:
                _ptdf[_i].append((pmn_plusone_p - pmn_zero) / _dp)
                _qtdf[_i].append((qmn_plusone_q - qmn_zero) / _dq)

            smn_zero = math.sqrt(pmn_zero ** 2 + qmn_zero ** 2)
            smn_plusone_p = math.sqrt(pmn_plusone_p ** 2 + qmn_plusone_p ** 2)
            smn_plusone_q = math.sqrt(pmn_plusone_q ** 2 + qmn_plusone_q ** 2)
            if _basis == 'current':  # current-based flow
                smn_zero, smn_plusone_p, smn_plusone_q = (
                    _branch_current_mva(_net, 'trafo3w', _l, _r) for _r in (_net0, _net1, _net2))
            _dsdp[_i].append((smn_plusone_p - smn_zero) / _dp)
            _dsdq[_i].append((smn_plusone_q - smn_zero) / _dq)

            rawname.append(_net.trafo3w.loc[_l, 'name'])
        # No forced garbage collection per
        # provider (it cost more than the power flows); one is done after the loop.

    # clean RAM after costly for-loop
    _ = gc.collect()

    _dsdp = pd.DataFrame(_dsdp, index=colname, columns=pd.unique(rawname))
    _dsdq = pd.DataFrame(_dsdq, index=colname, columns=pd.unique(rawname))

    if not _only_ds:
        _ptdf = pd.DataFrame(_ptdf, index=colname, columns=pd.unique(rawname))
        _qtdf = pd.DataFrame(_qtdf, index=colname, columns=pd.unique(rawname))

    return _ptdf, _qtdf, _dsdp, _dsdq


# _sens_basis ('apparent_power' or 'current', see _branch_current_mva).
def calc_sens_factors_cm(_net, _fsp_file, _fsp_bus, _ts_res, _cm_branch, _cm_trafo, _cm_trafo3w, _hours, _dp, _dq,
                         _path_matrix, _sim_tag, _sens_type, _sens_mode='VSGEN', _only_ds=True,
                         _force_hcm=False, _sens_basis='apparent_power'):
    """
    Evaluate the Congestion Management sensitivity factors (PTDF, QTDF & dSdP and dSdQ) for each congested hours.

    :param _net: Pandapower network.

    :param _fsp_file: Dictionary of file for each resource type.

    :param _fsp_bus: List of bus included as flexibility service provider.

    :param _ts_res: Dictionary of the timeseries simulation results.

    :param _cm_branch: List of the index of the congested lines in the network.

    :param _cm_trafo: List of the index of the congested trafo 2 windings in the network.

    :param _cm_trafo3w: List of the index of the congested trafo 3 windings in the network.

    :param _hours: List of hours with congestions.

    :param _path_matrix: Directory where to save sensitivity factor files.

    :param _sim_tag: Simulation tag.

    :param _sens_type: Product from which the matrix are evaluated ('P', 'Q' or 'PQ').

    :param _sens_mode: Sensitivity mode on which evalute the matrix.

    :param _version: Function Version to which evaluate the sensitivity factors.

    :param _dp: Active power deviation.

    :param _dq: Reactive power deviation.

    :param _only_ds: Boolean value (True/False) to evaluate only dSdP and dSdQ matrix
     or evaluate PTDF and QTDF matrix as well.
    """
    # Get profiles. Sgen, Gen and Storage are not compulsory resource category, so try to get the profile,
    # if not present just go through
    load_p = _ts_res['load_p_mw'].T
    load_q = _ts_res['load_q_mvar'].T
    try:
        sgen_p = _ts_res['sgen_p_mw'].T
        sgen_q = _ts_res['sgen_q_mvar'].T
    except KeyError:
        sgen_p = 0
        sgen_q = 0
    try:
        gen_p = _ts_res['gen_p_mw'].T
        gen_q = _ts_res['gen_q_mvar'].T
    except KeyError:
        gen_p = 0
        gen_q = 0
    try:
        storage_p = _ts_res['storage_p_mw'].T
        storage_q = _ts_res['storage_q_mvar'].T
    except KeyError:
        storage_p = 0
        storage_q = 0
    # Supply voltage of the external grid per hour.
    ext_vm = _ext_grid_vm_by_hour(_ts_res, _net)

    _my_net = _check_element_names(_net)
    _ptdf, _qtdf, _dsdp, _dsdq = 0, 0, 0, 0
    # Signature of the network physics, part
    # of every matrix signature (see _should_recalculate_cache).
    _net_sig = _network_signature(_my_net)

    _flag_calc = False
    _message = 'Building CM {h_type} sensitivity matrix'.format(h_type=_sens_type)
    for h in tqdm(_hours, desc=_message):
        t_th = str(h).zfill(2)
        # Every provider class of this hour is
        # evaluated at the same operating point, so they share one perturbation cache.
        _hour_cache = {}
        _op_sig = _hour_signature(h, load_p, load_q, sgen_p, sgen_q, gen_p, gen_q, storage_p, storage_q,
                                 ext_vm)  # + supply voltage

        for _fsp_type in _fsp_file.keys():
            if _fsp_file[_fsp_type] != 0:
                _list_tags_p = ['HCM' + 'dSdP', 'FSP' + _fsp_type, 'h' + t_th, _sim_tag]
                _list_tags_q = ['HCM' + 'dSdQ', 'FSP' + _fsp_type, 'h' + t_th, _sim_tag]
                _list_tags_ptdf = ['HCM' + 'PTDF', 'FSP' + _fsp_type, 'h' + t_th, _sim_tag]
                _list_tags_qtdf = ['HCM' + 'QTDF', 'FSP' + _fsp_type, 'h' + t_th, _sim_tag]
                filename_p = '_'.join(filter(None, _list_tags_p))
                filename_q = '_'.join(filter(None, _list_tags_q))
                filename_ptdf = '_'.join(filter(None, _list_tags_ptdf))
                filename_qtdf = '_'.join(filter(None, _list_tags_qtdf))
                file2sensp_cm = os.path.join(_path_matrix, filename_p + '.csv')
                file2sensq_cm = os.path.join(_path_matrix, filename_q + '.csv')
                # Everything this matrix depends on.
                _signature = _inputs_signature('CM', _fsp_type, _net_sig, _op_sig, _fsp_bus[_fsp_type],
                                               list(_cm_branch), list(_cm_trafo), list(_cm_trafo3w),
                                               _dp, _dq, _only_ds, _sens_basis)

                if _should_recalculate_cache(_force_hcm, file2sensp_cm, file2sensq_cm, _signature=_signature):
                #if True: # The above code is deactivated and this new line is inserted instead to calculate the matrix always
                    # Custom function to see it reduces the memory usage of the sensitivity factors calculation
                    pp.toolbox.drop_elements_simple(_my_net, 'controller', _my_net.controller.index)
                    pp.toolbox.clear_result_tables(_my_net)
                    _ = gc.collect()

                    # Update net according to each hour of study
                    _empty_ppnet = _copy_net_essential(_my_net)
                    _empty_ppnet.load.p_mw = list(load_p[h])
                    _empty_ppnet.load.q_mvar = list(load_q[h])
                    if not _empty_ppnet.sgen.empty:
                        _empty_ppnet.sgen.p_mw = list(sgen_p[h])
                        _empty_ppnet.sgen.q_mvar = list(sgen_q[h])
                    if not _empty_ppnet.gen.empty:
                        _empty_ppnet.gen.p_mw = list(gen_p[h])
                        _empty_ppnet.gen.q_mvar = list(gen_q[h])
                    if not _empty_ppnet.storage.empty:
                        _empty_ppnet.storage.p_mw = list(storage_p[h])
                        _empty_ppnet.storage.q_mvar = list(storage_q[h])
                    # Supply voltage of this hour.
                    _set_ext_grid_vm(_empty_ppnet, ext_vm, h)

                    # _cache shares the bus perturbations of this hour.
                    _ptdf, _qtdf, _dsdp, _dsdq = sens_factors_cm(_empty_ppnet, _fsp_bus[_fsp_type], _cm_branch, _cm_trafo,
                                                                 _cm_trafo3w, _dp, _dq, _only_ds, _cache=_hour_cache,
                                                                 _basis=_sens_basis)

                    if not _only_ds:
                        io_file.save_cvs(_data=_ptdf, _outroot=_path_matrix, _filename=filename_ptdf)
                        io_file.save_cvs(_data=_qtdf, _outroot=_path_matrix, _filename=filename_qtdf)

                    io_file.save_cvs(_data=_dsdp, _outroot=_path_matrix, _filename=filename_p)
                    io_file.save_cvs(_data=_dsdq, _outroot=_path_matrix, _filename=filename_q)
                    # Remember what this run wrote.
                    _mark_written(_signature, file2sensp_cm, file2sensq_cm)
                    _ = gc.collect()
    return True


def fasor2complex(_magnitude, _angle):
    """
    Evaluate the real and imaginary part of the fasor value.

    :param _magnitude:

    :param _angle:
    """
    angle_rad = math.radians(_angle)
    part_real = _magnitude * math.cos(angle_rad)
    part_imag = _magnitude * math.sin(angle_rad)
    return complex(part_real, part_imag)


# _cache argument (bus perturbations shared at one operating point).
def sens_factors_vc(_net, _fsp_bus, _pilot_bus, _dp, _dq, _path_matrix, _cache=None):
    """
    Custom function for calculating the Sensitivity factor of the network for voltage control.

    :param _net: Pandapower network.

    :param _fsp_bus: List of bus included as flexibility service provider.

    :param _pilot_bus: List of bus considered as pilot buses in the simulation.

    :param _dp: Active power deviation.

    :param _dq: Reactive power deviation.

    :param _path_matrix: Directory where to save sensitivity factor files.
    """
    _ = gc.collect()

    # Starting power flow in initial conditions
    _net0 = _copy_net_essential(_net)
    pp.runpp(_net0)

    total_bus_array = _net.bus.index

    fsp_buses, fsp_labels = _bus_values_and_labels(_fsp_bus)
    pilot_buses, pilot_labels = _bus_values_and_labels(_pilot_bus)

    _hvp = [list() for _ in range(len(fsp_buses))]
    _hvq = [list() for _ in range(len(fsp_buses))]
    colname = []

    if not all(i in total_bus_array for i in map(abs, fsp_buses)) \
            or not all(i in total_bus_array for i in map(abs, pilot_buses)):
        raise UserWarning('FSP Bus or Branch or trafo vectors contain errors')

    # The +dP (_net1) and +dQ (_net2) power
    # flows are solved once per distinct bus and shared by every provider on it.
    _perturbed = _perturbed_bus_results(_net, fsp_buses, _dp, _dq, _cache)
    for _i in range(len(fsp_buses)):
        # Active power (_net1) and reactive power (_net2) perturbation results of this bus
        _net1, _net2 = _perturbed[(abs(fsp_buses[_i]), _dp, _dq)]
        # Save Bus Name
        colname.append(fsp_labels[_i])

        for _j in pilot_buses:
            # Voltage sensitivities keep
            # the physical sign of the voltage-magnitude response.
            vmp_zero = _net0.res_bus.loc[_j, 'vm_pu']
            vmp_uno = _net1.res_bus.loc[_j, 'vm_pu']
            vmq_uno = _net2.res_bus.loc[_j, 'vm_pu']

            _hvp[_i].append(_signed_voltage_sensitivity(vmp_zero, vmp_uno, _dp))
            _hvq[_i].append(_signed_voltage_sensitivity(vmp_zero, vmq_uno, _dq))
        # No forced garbage collection per
        # provider (it cost more than the power flows); one is done after the loop.

    # clean RAM after costly for-loop
    _ = gc.collect()

    _hvp = pd.DataFrame(_hvp, index=colname, columns=pilot_labels).T
    _hvq = pd.DataFrame(_hvq, index=colname, columns=pilot_labels).T
    return _hvp, _hvq


def calc_sens_factors_vc(_net, _fsp_file, _fsp_bus, _ts_res, _pilot_bus, _hours, _dp, _dq, _path_matrix, _sim_tag,
                         _sens_type, _force_hvm, _save_inv_js):
    """
    Evaluate the Voltage Control sensitivity factors for each congested hours.

    :param _net: Pandapower network.

    :param _fsp_file: Dictionary of file for each resource type.

    :param _fsp_bus: List of bus included as flexibility service provider.

    :param _ts_res: Dictionary of the timeseries simulation results.

    :param _pilot_bus: List of the selected pilot buses.

    :param _hours: List of hours with congestions.

    :param _dp: Active Power Variation for each resource.

    :param _dq: Reactive Power Variation for each resource.

    :param _path_matrix: Directory where to save sensitivity factor files.

    :param _sim_tag: Simulation tag.

    :param _sens_type: Product from which the matrix are evaluated ('P', 'Q' or 'PQ').

    :param _force_hvm: Force evaluating hvm sensitivity matrix.

    :param _save_inv_js: Force saving the J22inv and J12inv to .csv.
    """

    # Get profiles. Sgen, Gen and Storage are not compulsory resource category, so try to get the profile,
    # if not present just go through
    load_p = _ts_res['load_p_mw'].T
    load_q = _ts_res['load_q_mvar'].T
    try:
        sgen_p = _ts_res['sgen_p_mw'].T
        sgen_q = _ts_res['sgen_q_mvar'].T
    except KeyError:
        sgen_p = 0
        sgen_q = 0
    try:
        gen_p = _ts_res['gen_p_mw'].T
        gen_q = _ts_res['gen_q_mvar'].T
    except KeyError:
        gen_p = 0
        gen_q = 0
    try:
        storage_p = _ts_res['storage_p_mw'].T
        storage_q = _ts_res['storage_q_mvar'].T
    except KeyError:
        storage_p = 0
        storage_q = 0
    # Supply voltage of the external grid per hour.
    ext_vm = _ext_grid_vm_by_hour(_ts_res, _net)

    # Signature of the network physics, part
    # of every matrix signature (see _should_recalculate_cache).
    _net_sig = _network_signature(_net)

    _message = 'Building VC {_h_type} sensitivity matrix'.format(_h_type=_sens_type)
    for h in tqdm(_hours, desc=_message):
        t_th = str(h).zfill(2)
        # Operating point of this hour, and the
        # signatures of the pilot self-pair and of each provider class's matrix.
        _op_sig = _hour_signature(h, load_p, load_q, sgen_p, sgen_q, gen_p, gen_q, storage_p, storage_q,
                                 ext_vm)  # + supply voltage
        _sig_self = _inputs_signature('VCii', _net_sig, _op_sig, list(_pilot_bus), _dp, _dq)

        _list_hvm_fsp_p = ['HVMPii', 'h' + t_th, _sim_tag]
        _list_hvm_fsp_q = ['HVMQii', 'h' + t_th, _sim_tag]
        filename_hvm_p = '_'.join(filter(None, _list_hvm_fsp_p))
        filename_hvm_q = '_'.join(filter(None, _list_hvm_fsp_q))
        file2hvm_p = os.path.join(_path_matrix, filename_hvm_p + '.csv')
        file2hvm_q = os.path.join(_path_matrix, filename_hvm_q + '.csv')

        pending_fsp_pairs = []
        for _fsp_type in _fsp_file.keys():
            if _fsp_file[_fsp_type] == 0:
                continue
            filename_p = '_'.join(filter(None, ['HVMP', 'FSP' + _fsp_type, 'h' + t_th, _sim_tag]))
            filename_q = '_'.join(filter(None, ['HVMQ', 'FSP' + _fsp_type, 'h' + t_th, _sim_tag]))
            file2sens_vc_p = os.path.join(_path_matrix, filename_p + '.csv')
            file2sens_vc_q = os.path.join(_path_matrix, filename_q + '.csv')
            # Everything this matrix depends on.
            _sig_type = _inputs_signature('VC', _fsp_type, _net_sig, _op_sig, _fsp_bus[_fsp_type],
                                          list(_pilot_bus), _dp, _dq)
            if _should_recalculate_cache(_force_hvm, file2sens_vc_p, file2sens_vc_q, _signature=_sig_type):
                pending_fsp_pairs.append((_fsp_type, filename_p, filename_q, _sig_type,
                                          file2sens_vc_p, file2sens_vc_q))

        diag_p_path = os.path.join(_path_matrix, 'myJ22INV_h' + t_th + '.csv')
        diag_q_path = os.path.join(_path_matrix, 'myJ12INV_h' + t_th + '.csv')
        need_self_pair = _should_recalculate_cache(_force_hvm, file2hvm_p, file2hvm_q, _signature=_sig_self)
        need_diagnostics = bool(_save_inv_js) and _should_recalculate_cache(
            _force_hvm, diag_p_path, diag_q_path, _signature=_sig_self
        )
        if not pending_fsp_pairs and not need_self_pair and not need_diagnostics:
            continue
        # The pilot self-pair and every provider
        # class of this hour share one perturbation cache (same operating point).
        _hour_cache = {}

        _empty_ppnet = _copy_net_essential(_net)
        _empty_ppnet.load.p_mw = list(load_p[h])
        _empty_ppnet.load.q_mvar = list(load_q[h])
        if not _empty_ppnet.sgen.empty:
            _empty_ppnet.sgen.p_mw = list(sgen_p[h])
            _empty_ppnet.sgen.q_mvar = list(sgen_q[h])
        if not _empty_ppnet.gen.empty:
            _empty_ppnet.gen.p_mw = list(gen_p[h])
            _empty_ppnet.gen.q_mvar = list(gen_q[h])
        if not _empty_ppnet.storage.empty:
            _empty_ppnet.storage.p_mw = list(storage_p[h])
            _empty_ppnet.storage.q_mvar = list(storage_q[h])
        # Supply voltage of this hour.
        _set_ext_grid_vm(_empty_ppnet, ext_vm, h)

        if need_self_pair or need_diagnostics:
            # _cache shares the bus perturbations of this hour.
            _hvp_diag, _hvq_diag = sens_factors_vc(
                _empty_ppnet, _pilot_bus, _pilot_bus, _dp, _dq, _path_matrix, _cache=_hour_cache
            )
            if need_self_pair:
                _hvm_pii = pd.DataFrame(np.diag(_hvp_diag.T), index=_pilot_bus, columns=[h])
                _hvm_qii = pd.DataFrame(np.diag(_hvq_diag.T), index=_pilot_bus, columns=[h])
                io_file.save_cvs(_data=_hvm_pii, _outroot=_path_matrix, _filename=filename_hvm_p)
                io_file.save_cvs(_data=_hvm_qii, _outroot=_path_matrix, _filename=filename_hvm_q)
                _mark_written(_sig_self, file2hvm_p, file2hvm_q)
            if need_diagnostics:
                # Save once per hour, outside the FSP loop, to avoid repeated
                # writes to synced folders and PermissionError races.
                io_file.save_cvs(_data=_hvp_diag, _outroot=_path_matrix, _filename='myJ22INV_h' + t_th)
                io_file.save_cvs(_data=_hvq_diag, _outroot=_path_matrix, _filename='myJ12INV_h' + t_th)
                _mark_written(_sig_self, diag_p_path, diag_q_path)

        for _fsp_type, filename_p, filename_q, _sig_type, file2sens_vc_p, file2sens_vc_q in pending_fsp_pairs:
            # _cache shares the bus perturbations of this hour.
            _hvmp, _hvmq = sens_factors_vc(
                _empty_ppnet, _fsp_bus[_fsp_type], _pilot_bus, _dp, _dq, _path_matrix, _cache=_hour_cache
            )
            io_file.save_cvs(_data=_hvmp.T, _outroot=_path_matrix, _filename=filename_p)
            io_file.save_cvs(_data=_hvmq.T, _outroot=_path_matrix, _filename=filename_q)
            _mark_written(_sig_type, file2sens_vc_p, file2sens_vc_q)
    return True
