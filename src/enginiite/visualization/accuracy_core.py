"""Data behind the linear-model accuracy comparison: what the market predicted against what the AC power flow gave.

The comparison figures read it through build_scenario_accuracy_data.
"""
import os
import re
import ast
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from enginiite import tolerance_policy

try:
    import yaml
except ImportError:  # pragma: no cover - YAML reading falls back to simple parsing
    yaml = None

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
except ImportError:  # pragma: no cover - plotting is optional for table generation
    go = None
    px = None
    make_subplots = None


FSP_TYPES = ("A", "B", "C", "D")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _norm_label(value):
    if pd.isna(value):
        return ""
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _numeric_df(df):
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    out = df.copy()
    out.index = [_norm_label(i) for i in out.index]
    out.columns = [_norm_label(c) for c in out.columns]
    return out.apply(pd.to_numeric, errors="coerce")


def _read_csv(path):
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    try:
        return _numeric_df(pd.read_csv(path, index_col=0))
    except Exception:
        return pd.DataFrame()


def _find_first(folder, pattern):
    matches = sorted(Path(folder).glob(pattern))
    return str(matches[0]) if matches else None


def _project_root(start=None):
    cur = Path(start or os.getcwd()).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / "config").is_dir() and (parent / "data_in").is_dir():
            return str(parent)
    return os.getcwd()


def _active_main_config(project_root):
    main_path = Path(project_root) / "main.py"
    if not main_path.exists():
        return None
    active = None
    pattern = re.compile(r"^\s*file_cfg_name\s*=\s*(['\"])(?P<name>.+?\.ya?ml)\1")
    for line in main_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = pattern.search(line)
        if match:
            active = match.group("name")
    if active:
        candidate = Path(project_root) / "config" / active
        if candidate.exists():
            return str(candidate)
    return None


def _network_name_from_root(path):
    name = Path(str(path)).stem
    if name.endswith(".zip"):
        name = Path(name).stem
    return name.split("_")[0] if name else None


def _resolve_config_path(scenario_roots, config_path=None):
    if config_path and os.path.exists(config_path):
        return os.path.abspath(config_path)

    roots = [Path(str(r)).resolve() for r in _as_list(scenario_roots)]
    project = _project_root(roots[0] if roots else None)
    candidates = []
    for root in roots:
        for cur in [root, *root.parents]:
            candidates.extend(cur.glob("config*.yaml"))
            candidates.extend(cur.glob("config*.yml"))
            if str(cur) == project:
                break

    active = _active_main_config(project)
    if active:
        candidates.append(Path(active))

    networks = {n for n in (_network_name_from_root(r) for r in roots) if n}
    config_dir = Path(project) / "config"
    for network in networks:
        candidates.extend(config_dir.glob(f"config_{network}*.yaml"))
        candidates.extend(config_dir.glob(f"config_{network}*.yml"))

    seen = []
    for c in candidates:
        c = c.resolve()
        if c.exists() and c not in seen:
            seen.append(c)
    if active and Path(active).resolve() in seen:
        return str(Path(active).resolve())
    return str(seen[0]) if len(seen) == 1 else None


def _read_simple_yaml_scalars(path):
    values = {}
    if not path or not os.path.exists(path):
        return values
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*(?:#.*)?$")
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw in {"", "null", "None", "~"}:
            values[key] = None
            continue
        try:
            values[key] = ast.literal_eval(raw)
        except Exception:
            try:
                values[key] = float(raw)
            except Exception:
                values[key] = raw.strip("'\"")
    return values


def _read_yaml_config(path):
    if not path or not os.path.exists(path):
        return {}
    if yaml is not None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return _read_simple_yaml_scalars(path)


def _loading_limits_from_config(config_path=None, line_loading_limit=None, trafo_loading_limit=None):
    cfg = _read_yaml_config(config_path)
    current = tolerance_policy.current_limits(
        cfg.get("tol_i", 0) if isinstance(cfg, dict) else 0,
        cfg.get("tol_i_opt", 0) if isinstance(cfg, dict) else 0,
    )
    detected_limit = current["detection_limit_percent"]
    # Tolerance settings are metadata for
    # accuracy and never a substitute for an asset's physical MVA rating.
    return {
        "line": float(line_loading_limit) if line_loading_limit is not None else detected_limit,
        "trafo": float(trafo_loading_limit) if trafo_loading_limit is not None else detected_limit,
        "trafo3w": float(trafo_loading_limit) if trafo_loading_limit is not None else detected_limit,
        "config_path": os.path.abspath(config_path) if config_path else None,
        "tol_i": current["tol_i_percent"],
        "tol_i_opt": current["tol_i_opt_percent"],
        "optimization_target": current["optimization_target_percent"],
    }


def _market_result_path(scenario_root):
    return _find_first(scenario_root, "model_results_*.xlsx")


def _market_tag(scenario_root):
    model = _market_result_path(scenario_root)
    if model:
        return Path(model).stem.replace("model_results_", "", 1)
    return Path(scenario_root).name


def _sim_tag_from_market_tag(market_tag):
    parts = str(market_tag).split("_")
    return parts[-1] if parts else ""


def _stage_roots(scenario_root):
    stages = Path(str(scenario_root)) / "ACCorrectionStages"
    if not stages.is_dir():
        return []
    return [
        str(path) for path in sorted(stages.iterdir())
        if path.is_dir() and _market_result_path(str(path))
    ]


def _read_market_sheets(model_path):
    sheets = {}
    if not model_path or not os.path.exists(model_path):
        return sheets
    try:
        xls = pd.ExcelFile(model_path)
    except Exception:
        return sheets
    for name in [
        "VA", "alpha_DVpu", "DW_A", "DR_A", "DW_B", "DR_B",
        "DW_C", "DR_C", "DW_D", "DR_D", "beta", "ABS_beta",
    ]:
        if name in xls.sheet_names:
            sheets[name] = _numeric_df(pd.read_excel(xls, sheet_name=name, index_col=0))
    return sheets


def _parent_scenario_root(scenario_root):
    """Return the scenario root that owns a stage folder, or None."""
    # Stage folders live in
    # <scenario_root>/ACCorrectionStages/<stage_name>/, so the scenario root that
    # holds the pilot-bus files is two levels up.
    root = Path(str(scenario_root)).resolve()
    if root.parent.name != "ACCorrectionStages":
        return None
    candidate = root.parent.parent
    return str(candidate) if candidate.is_dir() else None


def _pilot_ids_from_folder(folder):
    """Read the pilot-bus order of one folder, newest convention first."""
    if not folder:
        return [], ""
    # PilotBusOrder.csv is written per AC-correction stage, so it stays correct
    # even when a corrective iteration expands the represented pilot-bus set.
    path = os.path.join(str(folder), "PilotBusOrder.csv")
    if os.path.exists(path):
        try:
            frame = pd.read_csv(path)
        except Exception:
            frame = pd.DataFrame()
        if not frame.empty:
            column = "bus" if "bus" in frame.columns else frame.columns[0]
            values = [_norm_label(v) for v in frame[column] if pd.notna(v)]
            if values:
                return values, path
    path = os.path.join(str(folder), "pilot_bus_vm_post.csv")
    if os.path.exists(path):
        try:
            frame = pd.read_csv(path, index_col=0, nrows=1)
        except Exception:
            frame = pd.DataFrame()
        if not frame.empty:
            return [_norm_label(c) for c in frame.columns], path
    for fname in ("VPilotBus_HTS.csv", "VPilotBus24h.csv"):
        path = os.path.join(str(folder), fname)
        if os.path.exists(path):
            try:
                values = pd.read_csv(path, index_col=0).index.to_numpy()
            except Exception:
                continue
            values = [_norm_label(v) for v in values if pd.notna(v)]
            if values:
                return values, path
    return [], ""


def _read_pilot_bus_ids(scenario_root, va_rows=None):
    """Return the real bus id of every VA row, in VA row order.

    The market writes VA and alpha_DVpu with a positional row index, so the row
    order has to be mapped back onto real bus numbers before the linear
    prediction can be compared with the AC bus voltages.

    The previous version fell back to the
    positional VA index whenever no pilot-bus file was found, and returned those
    positions as if they were bus numbers.  An AC-correction stage folder holds
    no pilot-bus file, so every stage silently compared pilot row 0 against bus
    0, row 1 against bus 1 and so on.  Because the positions happen to be valid
    bus labels, nothing failed - the voltage error was simply reported against
    the wrong buses and looked far larger than the real linearization error.
    The fallback is therefore resolved against the owning scenario root, and the
    row count must match, otherwise no bus identity is claimed at all.
    """
    expected = None if va_rows is None else len(list(va_rows))
    for folder in (scenario_root, _parent_scenario_root(scenario_root)):
        values, source = _pilot_ids_from_folder(folder)
        if values and (expected is None or len(values) == expected):
            return values
    return []


def _post_bus_vm(scenario_root):
    return _read_csv(os.path.join(scenario_root, "FullTS_postMKT", "res_bus", "vm_pu.csv"))


def _physical_linear_voltage_matrix(scenario_root, market_sheets, sensitivity_root=None, pre_ts_root=None):
    """Linear voltage prediction of one market stage at its pilot buses.

    V_lin = V_base + sum_i (HVMP_i * dP_i + HVMQ_i * dQ_i), the expression of
    the market's voltage constraint (run_flex_market.py, C#01_V*): V_base is
    the AC voltage at the stage's linearisation point (pre-market AC for the
    main market, the AC state after the previous stage for a corrective round),
    HVMP/HVMQ are the matrices that cleared this stage and dP/dQ the stage
    increments of the exported DW/DR, converted to the positive-injection sign
    of the matrices (_equivalent_injection_delta, as for congestion).  Checked
    on SB72: it reproduces VA - alpha_DVpu to machine precision at every pilot
    bus whose constraint is an equality.  Returns an empty frame when any
    input is missing.

    The market variable VA is NOT the
    linear prediction at a pilot bus that violates a limit before the market.
    There the constraint is an inequality (VA >= V_base + alpha + k for an
    over-voltage, <= for an under-voltage) and VA only has to stay inside the
    optimisation band, so the solver may return any value between the linear
    prediction and the band edge (in SB72 F03 nine pilot buses sit at
    exactly 1.0395 pu while their linear prediction is 1.026-1.039 pu).
    "VA - alpha" therefore overstated the linearisation error at exactly the
    buses that matter, by up to 0.014 pu against a true error below 0.001 pu.
    """
    va = market_sheets.get("VA", pd.DataFrame())
    if va.empty or not scenario_root or not os.path.isdir(str(scenario_root)):
        return pd.DataFrame()
    pilot_ids = _read_pilot_bus_ids(scenario_root, va.index)
    if not pilot_ids or len(pilot_ids) != len(va.index):
        return pd.DataFrame()
    base_root = _stage_baseline_ts_root(scenario_root, pre_ts_root)
    base = _read_csv(os.path.join(str(base_root), "res_bus", "vm_pu.csv")) if base_root else pd.DataFrame()
    sens_root = _sensitivity_root(scenario_root, sensitivity_root)
    if base.empty or not sens_root:
        return pd.DataFrame()
    hours = [_norm_label(h) for h in va.columns]
    # an hour without a market of the previous stage has no AC result there;
    # it stays NaN and drops out of the comparison
    if not any(h in base.index for h in hours) or any(b not in base.columns for b in pilot_ids):
        return pd.DataFrame()
    linear = base.reindex(index=hours, columns=pilot_ids).T.astype(float).copy()
    sim_tag = _sim_tag_from_market_tag(_market_tag(scenario_root))
    stage_market = _subtract_previous_cumulative_market(scenario_root, market_sheets)
    matrices_seen = 0
    for hpos, hour in enumerate(hours):
        for fsp_type in FSP_TYPES:
            for kind, prefix in (("HVMP", "DW_"), ("HVMQ", "DR_")):
                sheet = stage_market.get(prefix + fsp_type)
                mat = _read_hcm_matrix(sens_root, kind, fsp_type, hour, sim_tag)
                if mat.empty or sheet is None or sheet.empty:
                    continue
                matrices_seen += 1
                cols = [b for b in pilot_ids if b in mat.columns]
                for row_pos, fsp_label in enumerate(mat.index):
                    value = _action_value(sheet, fsp_label, hour, row_position=row_pos, hour_position=hpos)
                    value = _equivalent_injection_delta(fsp_type, value)
                    if not np.isfinite(value) or abs(value) <= 1e-15:
                        continue
                    linear.loc[cols, hour] += mat.loc[fsp_label, cols].to_numpy(dtype=float) * value
    if matrices_seen == 0:
        return pd.DataFrame()
    return _numeric_df(linear)


def _stage_dispatched_hours(scenario_root, market_sheets, tol=1e-9):
    """Hours in which this market stage changed any activation (DW_* / DR_* increment).

    In an hour without any activation of
    the stage, the linear prediction equals its baseline and so does the AC
    result, so the 'error' is exactly zero by construction; such cells verify
    nothing about the linear model and are flagged instead of averaged in.
    """
    stage_market = _subtract_previous_cumulative_market(scenario_root, market_sheets)
    hours = set()
    for name, frame in stage_market.items():
        if not name.startswith(("DW_", "DR_")) or frame is None or frame.empty:
            continue
        active = (frame.abs() > tol).any(axis=0)
        hours.update(_norm_label(h) for h, flag in active.items() if flag)
    return hours


def _linear_voltage_matrix(scenario_root, market_sheets, sensitivity_root=None, pre_ts_root=None):
    va = market_sheets.get("VA", pd.DataFrame())
    if va.empty:
        return pd.DataFrame()
    # The physical linear prediction
    # (baseline + sensitivities x stage increments) is used whenever its inputs
    # exist; VA - alpha_DVpu is kept only as the fallback, because VA is a
    # bounded decision variable, not the prediction, at buses violated before
    # the market (see _physical_linear_voltage_matrix).
    physical = _physical_linear_voltage_matrix(scenario_root, market_sheets, sensitivity_root, pre_ts_root)
    if not physical.empty:
        return physical
    alpha = market_sheets.get("alpha_DVpu", pd.DataFrame(0.0, index=va.index, columns=va.columns))
    alpha = alpha.reindex(index=va.index, columns=va.columns).fillna(0.0)
    linear = va - alpha

    # A missing scenario_root keeps the positional index so the pure formula
    # VA - alpha_DVpu stays testable without any scenario folder on disk.
    if not scenario_root or not os.path.isdir(str(scenario_root)):
        return _numeric_df(linear)

    pilot_ids = _read_pilot_bus_ids(scenario_root, va.index)
    if not pilot_ids or len(pilot_ids) != len(linear.index):
        # Without a resolved pilot-bus
        # order the VA rows cannot be paired with AC bus columns.  Returning the
        # positional index here would compare pilot row n against bus n and
        # report a meaningless voltage error, so report no voltage data instead.
        return pd.DataFrame()
    linear = linear.copy()
    linear.index = pilot_ids
    return _numeric_df(linear)


def _voltage_comparison(scenario_root, market_sheets, sensitivity_root=None, pre_ts_root=None):
    # The sensitivity and baseline roots
    # are passed on, so the physical linear prediction can be formed.
    linear = _linear_voltage_matrix(scenario_root, market_sheets, sensitivity_root, pre_ts_root)
    ac_all = _post_bus_vm(scenario_root)
    if linear.empty or ac_all.empty:
        return pd.DataFrame(), linear, pd.DataFrame()

    rows = [r for r in linear.index if r in ac_all.columns]
    cols = [c for c in linear.columns if c in ac_all.index]
    if not rows or not cols:
        return pd.DataFrame(), linear, pd.DataFrame()

    ac = ac_all.loc[cols, rows].T
    linear = linear.loc[rows, cols]
    err = ac - linear
    long = _matrix_long(
        ac=ac,
        linear=linear,
        error=err,
        kind="voltage",
        unit="pu",
        percent_base=pd.DataFrame(1.0, index=err.index, columns=err.columns),
    )
    return long, linear, ac


def _matrix_long(ac, linear, error, kind, unit, percent_base):
    rows = []
    for idx in error.index:
        for hour in error.columns:
            e = error.loc[idx, hour]
            if pd.isna(e):
                continue
            base = percent_base.loc[idx, hour] if isinstance(percent_base, pd.DataFrame) else percent_base
            pct = np.nan if not np.isfinite(base) or abs(base) <= 1e-15 else abs(e) / abs(base) * 100
            rows.append({
                "kind": kind,
                "element": idx,
                "hour": hour,
                "linear": linear.loc[idx, hour],
                "ac": ac.loc[idx, hour],
                "error": e,
                "abs_error": abs(e),
                "percent_error": pct,
                "unit": unit,
            })
    return pd.DataFrame(rows)


def _pre_timeseries_root(scenario_root, pre_ts_root=None):
    if pre_ts_root:
        return pre_ts_root
    parent = os.path.dirname(os.path.abspath(scenario_root))
    candidate = os.path.join(parent, "res_ts_net")
    if os.path.isdir(candidate):
        return candidate
    return os.path.join(scenario_root, "res_ts_net")


def _read_loading_by_kind(ts_root, kind):
    sub = {
        "line": "res_line",
        "trafo": "res_trafo",
        "trafo3w": "res_trafo3w",
    }[kind]
    return _read_csv(os.path.join(ts_root, sub, "loading_percent.csv"))


def _asset_kind(asset):
    label = str(asset)
    low = label.lower()
    if "trafo3" in low or "3w" in low:
        return "trafo3w"
    if "trafo" in low:
        return "trafo"
    return "line"


def _asset_column_candidates(asset, aliases_by_asset=None):
    label = str(asset)
    candidates = [label]
    if aliases_by_asset:
        candidates.extend(str(value) for value in aliases_by_asset.get(label, []))
    match = re.search(r"(-?\d+)$", label.strip())
    if match:
        candidates.append(match.group(1))
    if label.upper().startswith("L") and label[1:].isdigit():
        candidates.append(label[1:])
    return list(dict.fromkeys(candidates))


def _loading_matrix_for_assets(ts_root, assets, aliases_by_asset=None):
    cache = {}
    out = pd.DataFrame(index=[str(a) for a in assets])
    for asset in assets:
        kind = _asset_kind(asset)
        if kind not in cache:
            cache[kind] = _read_loading_by_kind(ts_root, kind)
        src = cache[kind]
        if src.empty:
            continue
        col = next((c for c in _asset_column_candidates(asset, aliases_by_asset) if c in src.columns), None)
        if col is None:
            continue
        out.loc[str(asset), src.index] = src[col].to_numpy()
    return _numeric_df(out)


def _canonicalize_axis(labels, alias_to_asset=None):
    if not alias_to_asset:
        return [_norm_label(label) for label in labels]
    return [alias_to_asset.get(_norm_label(label), _norm_label(label)) for label in labels]


def _canonicalize_asset_frame(df, alias_to_asset=None, axis="index", reducer="max"):
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if axis == "columns":
        out.columns = _canonicalize_axis(out.columns, alias_to_asset)
        if out.columns.duplicated().any():
            out = out.T.groupby(level=0).max().T if reducer == "max" else out.T.groupby(level=0).sum().T
    else:
        out.index = _canonicalize_axis(out.index, alias_to_asset)
        if out.index.duplicated().any():
            out = out.groupby(level=0).max() if reducer == "max" else out.groupby(level=0).sum()
    return _numeric_df(out)


def _read_cm_need(scenario_root, filename, alias_to_asset=None):
    path = os.path.join(scenario_root, filename)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_excel(path, sheet_name="Congestion needs", index_col=0)
    except Exception:
        return pd.DataFrame()
    mat = _numeric_df(df).T
    mat = _canonicalize_asset_frame(mat, alias_to_asset=alias_to_asset, axis="index", reducer="max")
    mat = mat.loc[(mat.abs().sum(axis=1) > 0)]
    return mat


def _configured_network_workbook(config_path):
    cfg = _read_yaml_config(config_path)
    network = cfg.get("network", {}) if isinstance(cfg, dict) else {}
    if not isinstance(network, dict) or not network.get("net_filename"):
        return None
    filename = Path(str(network["net_filename"]))
    if filename.is_absolute():
        return str(filename) if filename.is_file() else None
    project = Path(config_path).resolve().parent.parent if config_path else Path(_project_root())
    candidates = [
        project / "data_in" / str(network.get("net_folder", "")) / "network" / filename,
        project / "data_in" / "network" / filename,
        project / filename,
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def _network_asset_metadata(config_path):
    workbook = _configured_network_workbook(config_path)
    if not workbook:
        return pd.DataFrame()
    try:
        bus = pd.read_excel(workbook, sheet_name="bus", index_col=0)
    except Exception:
        bus = pd.DataFrame()
    rows = []
    for table_name, rating_column in (("line", None), ("trafo", "sn_mva"), ("trafo3w", "sn_hv_mva")):
        try:
            table = pd.read_excel(workbook, sheet_name=table_name, index_col=0)
        except Exception:
            continue
        for idx, row in table.iterrows():
            try:
                label = _norm_label(row.get("name", idx))
                if table_name == "line":
                    if bus.empty:
                        continue
                    value = np.sqrt(3.0) * float(row["max_i_ka"]) * float(bus.loc[row["from_bus"], "vn_kv"])
                else:
                    value = float(row[rating_column])
                if not label or not np.isfinite(value) or value <= 0:
                    continue
                aliases = [
                    label,
                    _norm_label(idx),
                    f"{table_name}:{_norm_label(idx)}",
                    f"{table_name}_{_norm_label(idx)}",
                    f"{table_name}-{_norm_label(idx)}",
                ]
                rows.append({
                    "asset": label,
                    "kind": table_name,
                    "element_index": _norm_label(idx),
                    "smax_mva": value,
                    "aliases": aliases,
                })
            except Exception:
                continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates("asset")


def _network_asset_alias_maps(config_path):
    metadata = _network_asset_metadata(config_path)
    alias_to_asset = {}
    aliases_by_asset = {}
    if metadata.empty:
        return alias_to_asset, aliases_by_asset
    for _, row in metadata.iterrows():
        asset = _norm_label(row["asset"])
        aliases = [_norm_label(value) for value in row.get("aliases", [])]
        aliases_by_asset[asset] = list(dict.fromkeys([asset] + aliases))
        for alias in aliases_by_asset[asset]:
            alias_to_asset.setdefault(alias, asset)
    return alias_to_asset, aliases_by_asset


def _network_asset_smax(config_path):
    """Read the exact market capacity definition from the network workbook."""
    metadata = _network_asset_metadata(config_path)
    if metadata.empty:
        return pd.Series(dtype=float, name="smax_mva")
    # Congestion error normalization uses
    # physical network ratings and never reverse-engineers Smax from tol_i needs.
    return pd.Series(
        metadata.set_index("asset")["smax_mva"].astype(float),
        dtype=float,
        name="smax_mva",
    )


def _sensitivity_root(scenario_root, sensitivity_root=None):
    candidates = []
    # corrective-market stage folders
    # carry their own sensitivity provenance, so accuracy plots use the same
    # HVM/HCM cache that cleared that exact stage instead of falling back to
    # the initial operating-point matrices.
    stage_manifest = os.path.join(
        os.path.abspath(scenario_root), "ACCorrectionStageManifest.csv"
    )
    if os.path.exists(stage_manifest):
        try:
            stage = pd.read_csv(stage_manifest)
            # The matrices archived beside
            # the stage are permanent; the cache folder is rebuilt by the next
            # run of the same case, so the archive is preferred.
            if (
                "sensitivity_archive_root" in stage
                and not stage["sensitivity_archive_root"].dropna().empty
            ):
                candidates.append(str(stage["sensitivity_archive_root"].dropna().iloc[0]))
            if (
                "sensitivity_cache_root" in stage
                and not stage["sensitivity_cache_root"].dropna().empty
            ):
                candidates.append(str(stage["sensitivity_cache_root"].dropna().iloc[0]))
        except Exception:
            pass
    if sensitivity_root:
        candidates.append(sensitivity_root)
    cur = os.path.abspath(scenario_root)
    for _ in range(8):
        candidates.extend([
            os.path.join(cur, "h24SensitivityMatrixes"),
            os.path.join(cur, "market_inputs", "h24SensitivityMatrixes"),
            os.path.join(cur, "data_in", "market_inputs", "h24SensitivityMatrixes"),
        ])
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


def _read_hcm_matrix(root, kind, fsp_type, hour, sim_tag):
    if not root:
        return pd.DataFrame()
    hh = str(int(float(hour))).zfill(2) if str(hour).replace(".", "", 1).isdigit() else str(hour).zfill(2)
    exact = os.path.join(root, f"{kind}_FSP{fsp_type}_h{hh}_{sim_tag}.csv")
    if os.path.exists(exact):
        return _read_csv(exact)
    matches = sorted(Path(root).glob(f"{kind}_FSP{fsp_type}_h{hh}_*.csv"))
    return _read_csv(str(matches[0])) if matches else pd.DataFrame()


def _stage_manifest_row(scenario_root):
    manifest = os.path.join(os.path.abspath(str(scenario_root)), "ACCorrectionStageManifest.csv")
    if not os.path.isfile(manifest):
        return {}
    try:
        df = pd.read_csv(manifest)
    except Exception:
        return {}
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def _stage_iteration(scenario_root):
    row = _stage_manifest_row(scenario_root)
    if not row:
        return None
    try:
        return int(row.get("iteration", 0))
    except Exception:
        return None


def _previous_stage_root(scenario_root):
    iteration = _stage_iteration(scenario_root)
    if iteration is None or iteration <= 0:
        return None
    root = Path(str(scenario_root)).resolve()
    previous_name = "stage_00_initial" if iteration == 1 else f"stage_{iteration - 1:02d}_corrective"
    candidate = root.parent / previous_name
    return str(candidate) if candidate.is_dir() else None


def _stage_baseline_ts_root(scenario_root, pre_ts_root=None):
    previous = _previous_stage_root(scenario_root)
    if previous:
        candidate = os.path.join(previous, "FullTS_postMKT")
        if os.path.isdir(candidate):
            return candidate
    return _pre_timeseries_root(scenario_root, pre_ts_root)


def _subtract_previous_cumulative_market(scenario_root, market_sheets):
    """Return stage-increment market sheets from cumulative stage workbooks."""
    # Corrective accuracy uses
    # Δx_k = C_k − C_{k−1}.  A stage workbook may be cumulative after merging,
    # so using it directly with corrective HCM would overstate the sensitivity
    # effect and mix operating points.
    out = {name: frame.copy() for name, frame in market_sheets.items()}
    previous = _previous_stage_root(scenario_root)
    if not previous:
        return out
    previous_market = _read_market_sheets(_market_result_path(previous))
    for fsp_type in FSP_TYPES:
        for prefix in ("DW_", "DR_"):
            sheet_name = prefix + fsp_type
            if sheet_name not in out or out[sheet_name].empty:
                continue
            prior = previous_market.get(sheet_name, pd.DataFrame())
            if prior.empty:
                continue
            prior = prior.reindex(index=out[sheet_name].index, columns=out[sheet_name].columns).fillna(0.0)
            out[sheet_name] = out[sheet_name].astype(float) - prior.astype(float)
    return out


def _label_lookup(labels, target):
    target = _norm_label(target)
    if target in labels:
        return target
    normalized = {_norm_label(label): label for label in labels}
    return normalized.get(target)


def _action_value(sheet, fsp_label, hour, row_position=None, hour_position=None):
    if sheet is None or sheet.empty:
        return 0.0
    h = _label_lookup(sheet.columns, hour)
    if h is None and hour_position is not None and hour_position < sheet.shape[1]:
        h = sheet.columns[hour_position]
    if h is None:
        return 0.0

    row_label = _label_lookup(sheet.index, fsp_label)
    if row_label is not None:
        return float(sheet.loc[row_label, h])

    # Last-resort support for legacy files whose FSP rows were saved without
    # identifiers. Named HCM rows and named activation rows are matched by .loc.
    if row_position is not None and row_position < sheet.shape[0]:
        return float(sheet.iloc[row_position, sheet.columns.get_loc(h)])
    return 0.0


def _equivalent_injection_delta(fsp_type, exported_delta):
    """Convert exported market activation to the HCM positive-injection sign."""
    try:
        value = float(exported_delta)
    except Exception:
        return 0.0
    return -value if str(fsp_type) in {"A", "C", "D"} else value


def _linear_congestion_matrix(scenario_root, market_sheets, sensitivity_root, asset_smax, pre_ts_root=None,
                              alias_to_asset=None, aliases_by_asset=None):
    diagnostics = []
    pre_need = _read_cm_need(scenario_root, "total_cm_PreMKT.xlsx", alias_to_asset=alias_to_asset)
    if pre_need.empty:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "error",
            "reason": "missing_congestion_need_workbook_or_no_monitored_assets",
            "detail": os.path.join(str(scenario_root), "total_cm_PreMKT.xlsx"),
        })
        # Six values, matching the successful return below: this function
        # grew an outside_validity flag matrix and a pre_abs matrix, but the
        # two no-data exits still returned the original four, so every
        # bundle without a congestion-need workbook raised "not enough
        # values to unpack (expected 6, got 4)" and silently dropped three
        # accuracy figures instead of reporting the missing input.
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                pd.Series(dtype=float), pd.DataFrame(diagnostics))

    baseline_root = _stage_baseline_ts_root(scenario_root, pre_ts_root)
    pre_pct = _loading_matrix_for_assets(baseline_root, pre_need.index, aliases_by_asset=aliases_by_asset)
    supplied = pd.Series(asset_smax, dtype=float, name="smax_mva")
    supplied.index = [_norm_label(i) for i in supplied.index]
    supplied.index = _canonicalize_axis(supplied.index, alias_to_asset)
    supplied = supplied.groupby(level=0).max()
    smax = supplied.reindex(pre_need.index).dropna()
    smax = smax[(smax > 0) & np.isfinite(smax)]
    missing = [asset for asset in pre_need.index if asset not in smax.index]
    if missing:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "warning",
            "reason": "missing_network_rating_smax_mva",
            "detail": ", ".join(map(str, missing)),
        })
        warnings.warn("Congestion accuracy omitted assets with no network rating: " + ", ".join(missing), RuntimeWarning)
    assets = [a for a in pre_need.index if a in smax.index]
    if not assets:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "error",
            "reason": "no_common_assets_between_congestion_need_and_network_ratings",
            "detail": f"need_assets={len(pre_need.index)}, rated_assets={len(smax.index)}",
        })
        # Six values: see the note on the exit above. smax is already known
        # here, so it keeps its real value in position five.
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                smax, pd.DataFrame(diagnostics))

    hours = [h for h in market_sheets.get("VA", pd.DataFrame(columns=pre_need.columns)).columns]
    if not hours:
        for key in ("DW_A", "DW_B", "DW_C", "DR_A", "DR_B", "DR_C"):
            if key in market_sheets and not market_sheets[key].empty:
                hours = list(market_sheets[key].columns)
                break
    hours = [_norm_label(h) for h in hours] or list(pre_need.columns)

    pre_abs = pre_pct.reindex(index=assets, columns=hours).mul(smax.reindex(assets), axis=0) / 100.0
    missing_loading = [
        asset for asset in assets
        if asset not in pre_pct.index or pre_pct.reindex(index=[asset], columns=hours).isna().all().all()
    ]
    if missing_loading:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "warning",
            "reason": "missing_baseline_ac_loading_for_asset",
            "detail": ", ".join(map(str, missing_loading)),
        })
    linear = pre_abs.copy().fillna(0.0)
    sens_root = _sensitivity_root(scenario_root, sensitivity_root)
    if not sens_root:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "error",
            "reason": "missing_hcm_sensitivity_root",
            "detail": "No h24SensitivityMatrixes folder found near the scenario or in configuration defaults.",
        })
    sim_tag = _sim_tag_from_market_tag(_market_tag(scenario_root))
    stage_market = _subtract_previous_cumulative_market(scenario_root, market_sheets)
    hcm_files_seen = 0
    active_cells_seen = 0

    for hpos, hour in enumerate(hours):
        for fsp_type in FSP_TYPES:
            dw = stage_market.get("DW_" + fsp_type)
            dr = stage_market.get("DR_" + fsp_type)
            mp = _canonicalize_asset_frame(
                _read_hcm_matrix(sens_root, "HCMdSdP", fsp_type, hour, sim_tag),
                alias_to_asset=alias_to_asset,
                axis="columns",
                reducer="max",
            )
            mq = _canonicalize_asset_frame(
                _read_hcm_matrix(sens_root, "HCMdSdQ", fsp_type, hour, sim_tag),
                alias_to_asset=alias_to_asset,
                axis="columns",
                reducer="max",
            )
            for mat, sheet in ((mp, dw), (mq, dr)):
                if mat.empty or sheet is None or sheet.empty:
                    continue
                hcm_files_seen += 1
                for row_pos, fsp_label in enumerate(mat.index):
                    value = _action_value(sheet, fsp_label, hour, row_position=row_pos, hour_position=hpos)
                    value = _equivalent_injection_delta(fsp_type, value)
                    if not np.isfinite(value) or abs(value) <= 1e-15:
                        continue
                    active_cells_seen += 1
                    for asset in assets:
                        if asset in mat.columns:
                            linear.loc[asset, hour] += mat.loc[fsp_label, asset] * value
    if hcm_files_seen == 0:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "error",
            "reason": "no_hcm_files_matched_requested_hours_and_fsp_types",
            "detail": f"sensitivity_root={sens_root}, sim_tag={sim_tag}, hours={','.join(map(str, hours[:8]))}",
        })
    if active_cells_seen == 0:
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "warning",
            "reason": "no_nonzero_incremental_activation_aligned_with_hcm_rows",
            "detail": "Check FSP row names/order, product sheets DW_*/DR_*, and corrective cumulative-to-incremental alignment.",
        })
    # dS/dP linearises the branch-flow
    # MAGNITUDE in MVA around the pre-market point (with cm_sensitivity_basis
    # 'current' this is sqrt(3)*Vn*I for lines and loading x Sn for transformers,
    # with 'apparent_power' it is sqrt(P^2+Q^2); the matrices read here are those
    # the market used, so the figure follows the configured basis).  When the
    # accepted activation reverses the flow, that linearisation is extrapolated
    # straight through zero and returns a negative flow, which is physically
    # impossible and inflated the reported error.  The physical estimate is
    # therefore clipped at zero, the raw signed extrapolation is kept for
    # transparency, and those cells are marked as outside the linear model's
    # validity instead of being reported as ordinary accuracy.
    linear_signed = linear.copy()
    linear_physical = linear.clip(lower=0.0)
    outside_validity = linear_signed < -1e-9
    if bool(outside_validity.to_numpy().any()):
        diagnostics.append({
            "stage": Path(str(scenario_root)).name,
            "severity": "warning",
            "reason": "linear_model_extrapolated_through_zero_flow",
            "detail": (
                f"{int(outside_validity.to_numpy().sum())} of {linear_signed.size} "
                "asset-window cells: the predicted flow change exceeds the pre-market "
                "flow (the activation reverses the flow), so the magnitude linearisation "
                "is outside its validity; these cells are left out of the accuracy averages."
            ),
        })
    return linear_physical, linear_signed, outside_validity, pre_abs, smax, pd.DataFrame(diagnostics)


def _post_congestion_matrix(scenario_root, assets, smax, aliases_by_asset=None):
    post_root = os.path.join(scenario_root, "FullTS_postMKT")
    post_pct = _loading_matrix_for_assets(post_root, assets, aliases_by_asset=aliases_by_asset)
    common = [a for a in assets if a in post_pct.index and a in smax.index]
    if not common:
        return pd.DataFrame()
    return post_pct.loc[common, :].mul(smax.reindex(common), axis=0) / 100.0


def _congestion_comparison(scenario_root, market_sheets, sensitivity_root=None, asset_smax=None, pre_ts_root=None,
                           alias_to_asset=None, aliases_by_asset=None):
    asset_smax = pd.Series(dtype=float) if asset_smax is None else asset_smax
    linear, linear_signed, outside_validity, _, smax, diagnostics = _linear_congestion_matrix(
        scenario_root=scenario_root,
        market_sheets=market_sheets,
        sensitivity_root=sensitivity_root,
        asset_smax=asset_smax,
        pre_ts_root=pre_ts_root,
        alias_to_asset=alias_to_asset,
        aliases_by_asset=aliases_by_asset,
    )
    if linear.empty:
        return pd.DataFrame(), linear, pd.DataFrame(), smax, diagnostics
    ac = _post_congestion_matrix(scenario_root, linear.index, smax, aliases_by_asset=aliases_by_asset)
    if ac.empty:
        extra = pd.DataFrame([{
            "stage": Path(str(scenario_root)).name,
            "severity": "error",
            "reason": "missing_post_market_ac_loading_for_monitored_assets",
            "detail": os.path.join(str(scenario_root), "FullTS_postMKT"),
        }])
        diagnostics = pd.concat([diagnostics, extra], ignore_index=True) if not diagnostics.empty else extra
        return pd.DataFrame(), linear, ac, smax, diagnostics
    cols = [c for c in linear.columns if c in ac.columns]
    rows = [r for r in linear.index if r in ac.index]
    linear = linear.loc[rows, cols]
    ac = ac.loc[rows, cols]
    err = ac - linear
    base = pd.DataFrame(index=rows, columns=cols)
    for r in rows:
        base.loc[r, :] = smax.loc[r]
    base = base.apply(pd.to_numeric, errors="coerce")
    long = _matrix_long(ac=ac, linear=linear, error=err, kind="congestion", unit="MVA", percent_base=base)
    # Carry the raw extrapolation and the validity flag, so a cell where the
    # magnitude linearisation broke down is never mistaken for ordinary error.
    if not long.empty:
        signed = linear_signed.reindex(index=rows, columns=cols)
        flags = outside_validity.reindex(index=rows, columns=cols).fillna(False)
        long["linear_signed"] = [
            float(signed.loc[r, c]) for r, c in zip(long["element"], long["hour"])
        ]
        long["outside_linear_validity"] = [
            bool(flags.loc[r, c]) for r, c in zip(long["element"], long["hour"])
        ]
        # The AC loading of each cell, so the
        # summary can report the error on cells near the limit (NEAR_LIMIT_PERCENT).
        long["ac_loading_percent"] = (
            100.0 * long["ac"].to_numpy(dtype=float) / smax.reindex(long["element"]).to_numpy(dtype=float)
        )
    return long, linear, ac, smax, diagnostics


def build_scenario_accuracy_data(scenario_root, sensitivity_root=None, pre_ts_root=None,
                                 config_path=None, loading_limits=None, asset_smax=None):
    """Build one canonical VA-alpha and physical-MVA accuracy dataset."""
    scenario_root = os.path.abspath(str(scenario_root))
    analysis_root = scenario_root
    # The top-level scenario workbook is
    # cumulative when corrective markets run.  For accuracy, use the latest
    # archived stage instead of mixing the original AC baseline, initial
    # sensitivities, and cumulative activation.
    if not _stage_manifest_row(scenario_root):
        stages = _stage_roots(scenario_root)
        if stages:
            analysis_root = os.path.abspath(stages[-1])
    market_path = _market_result_path(analysis_root)
    market = _read_market_sheets(market_path)
    resolved_config = _resolve_config_path([scenario_root], config_path)
    if loading_limits is None:
        loading_limits = _loading_limits_from_config(resolved_config)
    if asset_smax is None:
        asset_smax = _network_asset_smax(resolved_config)
    alias_to_asset, aliases_by_asset = _network_asset_alias_maps(resolved_config)
    # Every accuracy figure consumes this
    # shared definition, with voltage_linear = VA - alpha_DVpu.
    voltage_long, voltage_linear, voltage_ac = _voltage_comparison(
        analysis_root, market, sensitivity_root=sensitivity_root, pre_ts_root=pre_ts_root)
    congestion_long, congestion_linear, congestion_ac, congestion_smax, congestion_diagnostics = _congestion_comparison(
        analysis_root, market, sensitivity_root=sensitivity_root,
        asset_smax=asset_smax, pre_ts_root=pre_ts_root,
        alias_to_asset=alias_to_asset,
        aliases_by_asset=aliases_by_asset,
    )
    # Mark the hours in which this stage
    # activated anything; elsewhere linear = baseline = AC and the zero error
    # verifies nothing (figures leave those cells blank).
    dispatched = _stage_dispatched_hours(analysis_root, market)
    for frame in (voltage_long, congestion_long):
        if not frame.empty:
            frame["dispatched"] = [_norm_label(h) in dispatched for h in frame["hour"]]
    source_audit = _accuracy_source_audit(
        analysis_root, market_path, voltage_linear, voltage_ac,
        congestion_linear, congestion_ac, congestion_diagnostics,
    )
    return {
        "scenario_root": scenario_root,
        "analysis_root": analysis_root,
        # Which market stage was analysed
        # (0 = main market, k = corrective round k; None without stage folders).
        "stage_iteration": _stage_iteration(analysis_root),
        "dispatched_hours": sorted(dispatched, key=lambda h: (len(h), h)),
        "market_path": market_path,
        "loading_limits": loading_limits,
        "voltage_long": voltage_long,
        "voltage_linear": voltage_linear,
        "voltage_ac": voltage_ac,
        "congestion_long": congestion_long,
        "congestion_linear": congestion_linear,
        "congestion_ac": congestion_ac,
        "congestion_smax": congestion_smax,
        "congestion_diagnostics": congestion_diagnostics,
        "source_audit": source_audit,
    }


def _matrix_identity_status(linear, ac):
    if linear is None or ac is None or linear.empty or ac.empty:
        return {"common_cells": 0, "max_abs_ac_minus_linear": np.nan, "nearly_identical": False}
    rows = [row for row in linear.index if row in ac.index]
    cols = [col for col in linear.columns if col in ac.columns]
    if not rows or not cols:
        return {"common_cells": 0, "max_abs_ac_minus_linear": np.nan, "nearly_identical": False}
    diff = (ac.loc[rows, cols] - linear.loc[rows, cols]).abs()
    max_abs = float(diff.max().max()) if not diff.empty else np.nan
    return {
        "common_cells": int(diff.size),
        "max_abs_ac_minus_linear": max_abs,
        "nearly_identical": bool(np.isfinite(max_abs) and max_abs <= 1e-12),
    }


def _accuracy_source_audit(scenario_root, market_path, voltage_linear, voltage_ac,
                           congestion_linear, congestion_ac, congestion_diagnostics):
    stage = _stage_manifest_row(scenario_root)
    voltage_status = _matrix_identity_status(voltage_linear, voltage_ac)
    congestion_status = _matrix_identity_status(congestion_linear, congestion_ac)
    # Record which file supplied the
    # pilot-bus order.  A mislabelled order silently inflates the reported
    # voltage error, so its provenance belongs in the audit table.
    _pilot_ids, pilot_source = _pilot_ids_from_folder(scenario_root)
    if not _pilot_ids:
        _pilot_ids, pilot_source = _pilot_ids_from_folder(
            _parent_scenario_root(scenario_root))
    rows = [
        {
            "kind": "voltage",
            "stage_name": stage.get("stage_name", Path(str(scenario_root)).name),
            "iteration": stage.get("iteration", ""),
            "linear_source": "model workbook sheets VA and alpha_DVpu; formula VA - alpha_DVpu",
            "ac_source": os.path.join(str(scenario_root), "FullTS_postMKT", "res_bus", "vm_pu.csv"),
            "market_workbook": market_path or "",
            "pilot_bus_order_source": pilot_source or "UNRESOLVED - voltage accuracy skipped",
            "pilot_bus_count": len(_pilot_ids),
            **voltage_status,
        },
        {
            "kind": "congestion",
            "stage_name": stage.get("stage_name", Path(str(scenario_root)).name),
            "iteration": stage.get("iteration", ""),
            "linear_source": "baseline AC loading plus HCMdSdP/HCMdSdQ times incremental DW/DR",
            "ac_source": os.path.join(str(scenario_root), "FullTS_postMKT", "res_line|res_trafo|res_trafo3w", "loading_percent.csv"),
            "market_workbook": market_path or "",
            **congestion_status,
        },
    ]
    if congestion_diagnostics is not None and not congestion_diagnostics.empty:
        rows.append({
            "kind": "congestion_diagnostic",
            "stage_name": stage.get("stage_name", Path(str(scenario_root)).name),
            "iteration": stage.get("iteration", ""),
            "linear_source": "",
            "ac_source": "",
            "market_workbook": market_path or "",
            "common_cells": 0,
            "max_abs_ac_minus_linear": np.nan,
            "nearly_identical": False,
            "diagnostic_count": int(len(congestion_diagnostics)),
        })
    return pd.DataFrame(rows)
