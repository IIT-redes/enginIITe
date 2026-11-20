"""Check the inputs of a case against the contract of the platform, without running any simulation.

It reads the scenario configuration (YAML) and applies the same rules as the loaders to

* the configuration (required keys, tags, simulation window),
* the network table (readable, element names, profile columns),
* the profile files (file and sheet names, rows, columns, missing values),
* the tables of flexibility service providers (FSP), including columns, types and the match with network elements.

Run it from the folder that contains ``config/`` and ``data_in/``.

    python scripts/validate_inputs.py config/my_case.yaml
    python scripts/validate_inputs.py config/my_case.yaml --power-flow

The exit code is 1 when there is at least one error (or a warning with --strict), 0 otherwise.
"""
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

ERROR, WARNING, INFO = 'ERROR', 'WARNING', 'INFO'

PRODUCTS = ('P', 'Q', 'PQ')
MODEL_TAGS = ('CM', 'VC', 'CMVC')
VOLTAGE_TAGS = ('VL01', 'VL02', 'VL03', 'VL04', 'VL05', 'VL06')
PROFILE_COLUMNS = ('denorm_profile', 'norm_profile', 'internal_profile')

# FSP type -> pandapower table that holds the element
FSP_TYPE_TABLE = {'A': 'load', 'B': 'sgen', 'C': 'storage', 'D': 'load'}

REQUIRED_FSP_COLUMNS = (
    'id', 'bus', 'name', 'type', 'aggregator_name', 'mva', 'mw', 'mvar', 'bidding_strategy',
    'Pup', 'Pdown', 'Pup_cost', 'Pdown_cost', 'Qup', 'Qdown', 'Qup_cost', 'Qdown_cost',
)
REQUIRED_STORAGE_COLUMNS = ('soc_percent', 'min_e_mwh', 'max_e_mwh', 'sn_mva')

# Keys the platform reads with ``cfg[key]``, so a missing one stops the run with a KeyError.
REQUIRED_TOP_KEYS = (
    'simulation_tag', 'simulation_window', 'network', 'ModelTAG', 'ProductTAG', 'VLTAG', 'FspTAG', 'StorageTag',
    'scen_factor_load', 'scen_factor_sgen', 'scen_factor_gen', 'scen_factor_storage', 'BetaCost',
    'intertemp_cons', 'only_worst_hour', 'consecutive_hours', 'full_network', 'timeseries_force_1st_calculation',
    'only_pilot_busMV', 'vn_kv_mv', 'net_cstr_aggr', 'tol_v', 'tol_i', 'tol_v_opt', 'tol_i_opt',
    'debug_save_VPilotBus_FULLH',
)
REQUIRED_NETWORK_KEYS = ('net_folder', 'net_filename', 'profile', 'profile_models', 'ts_output_file_type', 'fsp', 'fsp_models')
REQUIRED_FSP_KEYS = ('fsp_input_filename', 'fsp_sheetname', 'fsp_additional_filename')


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str

    def __str__(self):
        return '[{:<7}] {:<34} {}'.format(self.level, self.code, self.message)


def _f(level, code, message):
    return Finding(level, code, message)


def load_config(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle)


# --------------------------------------------------------------------------- configuration
def check_config(cfg):
    findings = []
    if not isinstance(cfg, dict):
        return [_f(ERROR, 'config.not_a_mapping', 'The configuration file is empty or is not a mapping.')]

    missing = [k for k in REQUIRED_TOP_KEYS if k not in cfg]
    if missing:
        findings.append(_f(ERROR, 'config.missing_key', 'The configuration lacks the keys %s.' % ', '.join(missing)))

    net = cfg.get('network') if isinstance(cfg.get('network'), dict) else {}
    net_missing = [k for k in REQUIRED_NETWORK_KEYS if k not in net]
    if 'network' in cfg and net_missing:
        findings.append(_f(ERROR, 'config.missing_key', 'The "network" section lacks the keys %s.' % ', '.join(net_missing)))
    fsp = net.get('fsp') if isinstance(net.get('fsp'), dict) else {}
    fsp_missing = [k for k in REQUIRED_FSP_KEYS if k not in fsp]
    if 'fsp' in net and fsp_missing:
        findings.append(_f(ERROR, 'config.missing_key', 'The "network.fsp" section lacks the keys %s.' % ', '.join(fsp_missing)))

    window = cfg.get('simulation_window')
    if window is not None:
        ok = (isinstance(window, (list, tuple)) and len(window) == 2
              and all(isinstance(x, int) and not isinstance(x, bool) for x in window) and 0 <= window[0] < window[1])
        if not ok:
            findings.append(_f(ERROR, 'config.bad_window', 'simulation_window must be [start, end] with 0 <= start < end; got %r.' % (window,)))

    name = str(net.get('net_filename', ''))
    if name and not name.lower().endswith('.xlsx'):
        findings.append(_f(ERROR, 'config.network_format', 'Only .xlsx networks are supported; got "%s".' % name))

    if cfg.get('ModelTAG') is not None and cfg['ModelTAG'] not in MODEL_TAGS:
        findings.append(_f(ERROR, 'config.unknown_model_tag', 'ModelTAG "%s" is not one of %s.' % (cfg['ModelTAG'], ', '.join(MODEL_TAGS))))
    for prod in _as_list(cfg.get('ProductTAG')):
        if prod not in PRODUCTS:
            findings.append(_f(ERROR, 'config.unknown_product', 'ProductTAG "%s" is not one of %s.' % (prod, ', '.join(PRODUCTS))))
    for tag in _as_list(cfg.get('VLTAG')):
        if tag not in VOLTAGE_TAGS:
            findings.append(_f(ERROR, 'config.unknown_voltage_tag', 'VLTAG "%s" is not one of %s.' % (tag, ', '.join(VOLTAGE_TAGS))))
    for tag in _as_list(cfg.get('FspTAG')):
        if not re.fullmatch(r'F\d\d', str(tag)):
            findings.append(_f(ERROR, 'config.bad_fsp_tag', 'FspTAG "%s" must look like F01, F02, ...' % tag))

    if not str(cfg.get('simulation_tag', '') or '').strip():
        findings.append(_f(INFO, 'config.empty_simulation_tag',
                           'simulation_tag is empty, so the run uses a tag taken from the name of the configuration file.'))

    # Independent snapshots (simulation_window_as_timesteps False) are cleared one at a time and nothing may couple them.
    # The platform refuses any other combination, so report it before the run starts.
    window_as_timesteps = cfg.get('simulation_window_as_timesteps')
    if window_as_timesteps is not None and not window_as_timesteps             and 'consecutive_hours' in cfg and 'intertemp_cons' in cfg:
        try:
            hours = int(cfg['consecutive_hours'])
        except (TypeError, ValueError):
            hours = None
        if hours != 1 or bool(cfg['intertemp_cons']):
            findings.append(_f(ERROR, 'config.independent_snapshots_conflict',
                               'simulation_window_as_timesteps is false (independent snapshots), which needs consecutive_hours 1 '
                               'and intertemp_cons false; got consecutive_hours=%r and intertemp_cons=%r.'
                               % (cfg['consecutive_hours'], cfg['intertemp_cons'])))
    return findings


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _case_folder(cfg, root, sub):
    return Path(root) / 'data_in' / str(cfg['network']['net_folder']) / sub


# --------------------------------------------------------------------------- network
def check_network(cfg, root):
    """Return (network or None, findings)."""
    import pandapower as pp

    findings = []
    path = _case_folder(cfg, root, 'network') / str(cfg['network']['net_filename'])
    if not path.is_file():
        return None, [_f(ERROR, 'network.file_missing', 'Network file %s was not found.' % path)]
    try:
        net = pp.from_excel(str(path))
    except Exception as exc:  # pandapower raises many kinds of errors for a bad workbook
        return None, [_f(ERROR, 'network.unreadable', 'The network could not be read (%s).' % exc)]

    for table in ('load', 'sgen', 'storage'):
        df = getattr(net, table, None)
        if df is None or df.empty or 'name' not in df.columns:
            continue
        if df['name'].isna().any():
            findings.append(_f(WARNING, 'network.empty_element_names', 'Table "%s" has elements without a name.' % table))
        dup = df['name'][df['name'].duplicated() & df['name'].notna()].unique().tolist()
        if dup:
            findings.append(_f(WARNING, 'network.duplicated_element_names',
                               'Table "%s" repeats names %s; FSPs are matched by name and bus.' % (table, dup[:5])))

    names = []
    for table in ('line', 'trafo', 'trafo3w'):
        df = getattr(net, table, None)
        if df is not None and not df.empty and 'name' in df.columns:
            names.extend(df['name'].tolist())
    if any(pd.isna(n) for n in names):
        findings.append(_f(WARNING, 'network.empty_branch_names', 'Some lines or transformers have no name.'))
    named = [n for n in names if not pd.isna(n)]
    dup = sorted({n for n in named if named.count(n) > 1})
    if dup:
        findings.append(_f(ERROR, 'network.duplicated_branch_names',
                           'Lines and transformers share names %s; the sensitivity tables use names as columns.' % dup[:5]))

    if len(net.ext_grid) == 0:
        findings.append(_f(ERROR, 'network.no_slack', 'The network has no external grid.'))
    return net, findings


def check_power_flow(net):
    import pandapower as pp

    try:
        pp.runpp(net)
    except Exception as exc:
        return [_f(ERROR, 'network.power_flow_failed', 'The power flow of the base network does not converge (%s).' % exc)]
    vm = net.res_bus.vm_pu
    loading = max(net.res_line.loading_percent.max() if len(net.line) else 0,
                  net.res_trafo.loading_percent.max() if len(net.trafo) else 0)
    return [_f(INFO, 'network.base_power_flow',
               'The base power flow converges, with voltage from %.3f to %.3f pu and a maximum loading of %.1f %%.' % (vm.min(), vm.max(), loading))]


# --------------------------------------------------------------------------- profiles
def _read_profile_file(path, window):
    """Return (frame or None, findings). Mirrors read_file_profiles of the platform."""
    findings = []
    path = Path(path)
    if not path.is_file():
        return None, [_f(ERROR, 'profile.file_missing', 'Profile file %s was not found.' % path)]
    suffix = path.suffix.lower()
    try:
        if suffix == '.xlsx':
            with pd.ExcelFile(path) as book:  # closed on exit: an open handle blocks deleting the file on Windows
                sheet = book.sheet_names[0]
                frame = pd.read_excel(book, sheet_name=0, index_col=0)
            if sheet != path.stem:
                findings.append(_f(ERROR, 'profile.sheet_name',
                                   'In %s the first sheet is named "%s" but it must be named "%s", like the file.' % (path.name, sheet, path.stem)))
        elif suffix == '.csv':
            frame = pd.read_csv(path, index_col=0)
        else:
            return None, [_f(ERROR, 'profile.unsupported_format', 'Only .xlsx and .csv profiles are supported, so %s cannot be used.' % path.name)]
    except Exception as exc:
        return None, [_f(ERROR, 'profile.unreadable', '%s could not be read (%s).' % (path.name, exc))]

    t0, t1 = window
    if len(frame) < t1:
        findings.append(_f(ERROR, 'profile.too_short',
                           '%s has %d rows but the simulation window ends at %d.' % (path.name, len(frame), t1)))
        return frame, findings
    used = frame.iloc[t0:t1]
    if used.isna().any().any():
        findings.append(_f(ERROR, 'profile.missing_values', '%s has empty cells inside the simulation window.' % path.name))
    if not all(pd.api.types.is_numeric_dtype(dt) for dt in used.dtypes):
        findings.append(_f(ERROR, 'profile.not_numeric', '%s has non-numeric columns.' % path.name))
    return frame, findings


def check_profiles(cfg, net, root):
    findings = []
    window = cfg.get('simulation_window') or [0, 24]
    mapping = cfg['network'].get('profile') or {}
    folder = _case_folder(cfg, root, 'profile')

    for table in ('load', 'sgen', 'storage'):
        if table not in mapping and not getattr(net, table).empty:
            findings.append(_f(WARNING, 'profile.no_mapping',
                               'Category "%s" has elements but no entry under network.profile, so they stay constant.' % table))

    for category, products in mapping.items():
        df = getattr(net, category, None)
        if df is None or df.empty:
            findings.append(_f(INFO, 'profile.category_skipped', 'Category "%s" is not in the network and is skipped.' % category))
            continue
        absent = [c for c in PROFILE_COLUMNS if c not in df.columns]
        if absent:
            findings.append(_f(ERROR, 'network.missing_profile_columns',
                               'Table "%s" has no column(s) %s; every table with profiles needs all of %s.'
                               % (category, ', '.join(absent), ', '.join(PROFILE_COLUMNS))))
            continue

        has = {c: df[c].notnull() for c in PROFILE_COLUMNS}
        count = sum(has[c].astype(int) for c in PROFILE_COLUMNS)
        if (count > 1).any():
            findings.append(_f(ERROR, 'profile.ambiguous',
                               'In "%s", elements %s define more than one kind of profile.' % (category, df.index[count > 1].tolist()[:5])))
        if (count == 0).any():
            findings.append(_f(WARNING, 'profile.none_for_element',
                               'In "%s", elements %s define no profile, so they stay constant.' % (category, df.index[count == 0].tolist()[:5])))

        products = products or {}
        for needed in ('p', 'q'):
            if needed not in products:
                findings.append(_f(WARNING, 'profile.missing_product', 'Category "%s" has no "%s" entry under network.profile.' % (category, needed)))
        for product, spec in products.items():
            spec = spec or {}
            if has['denorm_profile'].any():
                findings += _check_denorm(folder, spec, df, has['denorm_profile'], category, product, window)
            if has['norm_profile'].any():
                findings += _check_norm(folder, spec, df, has['norm_profile'], category, product, window)
            if has['internal_profile'].any() and 'internal' not in spec:
                findings.append(_f(ERROR, 'profile.missing_file_key', 'network.profile.%s.%s needs an "internal" entry.' % (category, product)))
    return findings


def _check_denorm(folder, spec, df, mask, category, product, window):
    if 'denorm' not in spec:
        return [_f(ERROR, 'profile.missing_file_key',
                   'network.profile.%s.%s needs a "denorm" entry because some elements use denormalised profiles.' % (category, product))]
    frame, findings = _read_profile_file(folder / spec['denorm'], window)
    if frame is None:
        return findings
    try:
        columns = {int(c) for c in frame.columns}
    except (TypeError, ValueError):
        return findings + [_f(ERROR, 'profile.columns_not_integer',
                              'The columns of %s must be element indices (integers).' % spec['denorm'])]
    expected = set(df.index[mask].tolist())
    missing = sorted(expected - columns)
    if missing:
        findings.append(_f(ERROR, 'profile.denorm_missing_columns',
                           '%s has no column for %s elements %s.' % (spec['denorm'], category, missing[:8])))
    extra = sorted(columns - expected)
    if extra:
        findings.append(_f(WARNING, 'profile.denorm_extra_columns',
                           '%s has columns %s that do not correspond to denormalised %s elements.' % (spec['denorm'], extra[:8], category)))
    return findings


def _check_norm(folder, spec, df, mask, category, product, window):
    if 'norm' not in spec:
        return [_f(ERROR, 'profile.missing_file_key',
                   'network.profile.%s.%s needs a "norm" entry because some elements use normalised profiles.' % (category, product))]
    frame, findings = _read_profile_file(folder / spec['norm'], window)
    if frame is None:
        return findings
    # The platform looks each category up as a column with pandas, where the key 1.0 is the key 1. Compare the same
    # way, so that numeric categories stored as floats in the network table match integer column names.
    missing = sorted({str(c) for c in df.loc[mask, 'norm_profile'].unique() if c not in frame.columns})
    if missing:
        findings.append(_f(ERROR, 'profile.norm_category_missing',
                           '%s has no column for profile categories %s.' % (spec['norm'], missing)))
    return findings


# --------------------------------------------------------------------------- FSP tables
def check_fsp(cfg, net, root):
    findings = []
    fsp_cfg = cfg['network']['fsp']
    files = fsp_cfg['fsp_input_filename'] or {}
    sheet = fsp_cfg['fsp_sheetname']
    folder = _case_folder(cfg, root, 'fsp_files')

    for product in _as_list(cfg.get('ProductTAG')):
        if product not in files:
            findings.append(_f(ERROR, 'config.product_without_fsp_file', 'ProductTAG "%s" has no entry under fsp_input_filename.' % product))

    frames = {}
    for product, filename in files.items():
        path = folder / str(filename)
        if not path.is_file():
            findings.append(_f(ERROR, 'fsp.file_missing', 'FSP file %s was not found.' % path))
            continue
        suffix = path.suffix.lower()
        if suffix not in ('.xlsx', '.csv'):
            findings.append(_f(ERROR, 'fsp.unsupported_format', 'Only .xlsx and .csv FSP files are supported, so %s cannot be used.' % path.name))
            continue
        try:
            if suffix == '.csv':
                frame = pd.read_csv(path, header=1)  # the header is on the second row; there is no sheet to look for
            else:
                with pd.ExcelFile(path) as book:
                    if sheet not in book.sheet_names:
                        findings.append(_f(ERROR, 'fsp.sheet_missing', '%s has no sheet "%s" (it has %s).' % (path.name, sheet, book.sheet_names)))
                        continue
                    frame = pd.read_excel(book, sheet_name=sheet, header=1)  # the header is on the second row
        except Exception as exc:
            findings.append(_f(ERROR, 'fsp.unreadable', '%s could not be read (%s).' % (path.name, exc)))
            continue
        missing = [c for c in REQUIRED_FSP_COLUMNS if c not in frame.columns]
        if missing:
            findings.append(_f(ERROR, 'fsp.missing_columns',
                               '%s (product %s) lacks columns %s. The header must be on the second row.' % (path.name, product, missing)))
            continue
        frames[product] = frame

    if not frames:
        return findings

    type_sets = {p: set(f['type'].dropna().unique()) for p, f in frames.items()}
    if len({frozenset(s) for s in type_sets.values()}) > 1:
        findings.append(_f(ERROR, 'fsp.types_differ', 'The FSP types differ between product files (%s).' % {p: sorted(s) for p, s in type_sets.items()}))
    name_sets = {p: set(f['name'].astype(str)) for p, f in frames.items()}
    if len({frozenset(s) for s in name_sets.values()}) > 1:
        findings.append(_f(WARNING, 'fsp.names_differ', 'The FSP names differ between product files.'))

    for product, frame in frames.items():
        findings += _check_fsp_rows(frame, net, product)

    all_types = set().union(*type_sets.values())
    if 'C' in all_types:
        absent = [c for c in REQUIRED_STORAGE_COLUMNS if c not in net.storage.columns]
        if absent:
            findings.append(_f(ERROR, 'network.storage_columns', 'The storage table lacks %s, needed by the battery FSPs.' % absent))
        if not str(cfg.get('StorageTag', '') or '').strip():
            findings.append(_f(WARNING, 'config.empty_storage_tag',
                               'There are battery FSPs but StorageTag is empty, so their rating becomes 0 and the model can fail.'))
    return findings


def _check_fsp_rows(frame, net, product):
    findings = []
    label = 'product %s' % product

    empty = frame['name'].isna() | frame['name'].astype(str).str.strip().eq('')
    if empty.any():
        findings.append(_f(ERROR, 'fsp.empty_names', 'In %s, %d FSPs have no name.' % (label, int(empty.sum()))))

    for ftype, group in frame.groupby('type'):
        dup = group['name'][group['name'].duplicated()].astype(str).unique().tolist()
        if dup:
            findings.append(_f(ERROR, 'fsp.duplicated_names', 'In %s, type %s repeats the names %s.' % (label, ftype, dup[:5])))

    for _, row in frame.iterrows():
        ftype = row['type']
        table_name = FSP_TYPE_TABLE.get(ftype)
        if table_name is None:
            findings.append(_f(ERROR, 'fsp.unknown_type', 'In %s, FSP "%s" has type "%s" but the allowed types are %s.' % (label, row['name'], ftype, sorted(FSP_TYPE_TABLE))))
            continue
        table = getattr(net, table_name)
        by_name = table.index[table['name'].astype(str) == str(row['name'])]
        matches = by_name.intersection(table.index[table['bus'] == row['bus']])
        if len(matches) != 1:
            findings.append(_f(ERROR, 'fsp.unmatched',
                               'In %s, FSP "%s" (type %s, bus %s) matches %d elements of table "%s" by name and bus, and it must match exactly one.'
                               % (label, row['name'], ftype, row['bus'], len(matches), table_name)))
        if pd.notna(row.get('aggregator_name')):
            findings.append(_f(WARNING, 'fsp.aggregator_not_wired',
                               'In %s, FSP "%s" belongs to an aggregator, which is not connected end to end in the current code.' % (label, row['name'])))

    for col in ('Pup', 'Pdown', 'Qup', 'Qdown'):
        if (pd.to_numeric(frame[col], errors='coerce') < 0).any():
            findings.append(_f(ERROR, 'fsp.negative_share', 'In %s, column %s has negative shares.' % (label, col)))
    for col in ('Pup_cost', 'Pdown_cost', 'Qup_cost', 'Qdown_cost'):
        if (pd.to_numeric(frame[col], errors='coerce') < 0).any():
            findings.append(_f(WARNING, 'fsp.negative_cost', 'In %s, column %s has negative prices.' % (label, col)))
    if (pd.to_numeric(frame['mva'], errors='coerce') <= 0).any():
        findings.append(_f(WARNING, 'fsp.nonpositive_mva', 'In %s, some FSPs have a rating (mva) of zero or less.' % label))
    return findings


# --------------------------------------------------------------------------- orchestration
def validate_case(config_path, root='.', power_flow=False):
    cfg = load_config(config_path)
    findings = check_config(cfg)
    if any(f.code in ('config.not_a_mapping', 'config.missing_key') for f in findings):
        return findings  # nothing else can be checked without the basic keys

    net, net_findings = check_network(cfg, root)
    findings += net_findings
    if net is None:
        return findings
    if any(f.code == 'config.bad_window' for f in findings):
        findings.append(_f(INFO, 'profile.check_skipped', 'Profiles were not checked because simulation_window is invalid.'))
    else:
        findings += _guarded('profiles', check_profiles, cfg, net, root)
    findings += _guarded('FSP tables', check_fsp, cfg, net, root)
    if power_flow:
        findings += _guarded('power flow', check_power_flow, net)
    return findings


def _guarded(name, check, *args):
    """Run one block of checks; an unexpected failure becomes a finding instead of a traceback."""
    try:
        return check(*args)
    except Exception as exc:  # the validator must never crash on a malformed input
        return [_f(ERROR, 'validator.unexpected', 'The %s check stopped unexpectedly with %s (%s), so the inputs are probably malformed.'
                   % (name, type(exc).__name__, exc))]


def summarise(findings):
    return {lvl: sum(1 for f in findings if f.level == lvl) for lvl in (ERROR, WARNING, INFO)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check the inputs of a case without running any simulation.')
    parser.add_argument('config', help='path to the scenario YAML file')
    parser.add_argument('--root', default='.', help='folder that contains data_in/ (default: current folder)')
    parser.add_argument('--power-flow', action='store_true', help='also run one power flow of the base network')
    parser.add_argument('--strict', action='store_true', help='exit with an error code on warnings too')
    args = parser.parse_args(argv)

    if not Path(args.config).is_file():
        print('Configuration file %s was not found.' % args.config)
        return 2
    findings = validate_case(args.config, root=args.root, power_flow=args.power_flow)
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    for finding in sorted(findings, key=lambda f: order[f.level]):
        print(finding)
    counts = summarise(findings)
    print('\nSummary: %d errors, %d warnings, %d notes.' % (counts[ERROR], counts[WARNING], counts[INFO]))
    if counts[ERROR] or (args.strict and counts[WARNING]):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
