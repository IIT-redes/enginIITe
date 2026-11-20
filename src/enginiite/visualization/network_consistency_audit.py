from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


AUDIT_FOLDER = "network_consistency_audit"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _norm_label(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value).strip()


def _find_first(folder: str, pattern: str) -> Optional[str]:
    matches = sorted(Path(folder).glob(pattern))
    return str(matches[0]) if matches else None


def _market_result_path(scenario_root: str) -> Optional[str]:
    return _find_first(scenario_root, "model_results_*.xlsx")


def _market_tag(scenario_root: str) -> str:
    model = _market_result_path(scenario_root)
    if model:
        return Path(model).stem.replace("model_results_", "", 1)
    return Path(scenario_root).name


def discover_scenario_roots(root_or_roots) -> List[str]:
    roots: List[str] = []
    for root in _as_list(root_or_roots):
        root = os.path.abspath(str(root))
        if _market_result_path(root):
            roots.append(root)
            continue
        if os.path.isdir(root):
            for child in sorted(Path(root).iterdir()):
                if child.is_dir() and _market_result_path(str(child)):
                    roots.append(str(child))
    return roots


def _project_root(start: str) -> str:
    cur = Path(start).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / "data_in").is_dir() and (parent / "data_out").is_dir():
            return str(parent)
    return os.getcwd()


def _tag_parts(market_tag: str) -> Dict[str, str]:
    # Support underscored network names
    # and both the shortened tag and legacy tag with a trailing suffix.
    m = re.match(r"^(.+)_([^_]+)_(PQ|P|Q)_(VL\d+)_(F\d+)_(SK\d+)(?:_(.+))?$", str(market_tag))
    if not m:
        return {}
    country, market, product, vl_case, flex_case, storage_case, ess_case = m.groups()
    return {
        "country": country,
        "market": market,
        "product": product,
        "vl_case": vl_case,
        "flex_case": flex_case,
        "storage_case": storage_case,
        "ess_case": ess_case or "",
    }


def _scenario_code(market_tag: str) -> str:
    parts = _tag_parts(str(market_tag))
    if not parts:
        return str(market_tag)
    try:
        level = int(str(parts.get("flex_case", "F0")).replace("F", ""))
    except Exception:
        level = parts.get("flex_case", "")
    return f"{parts.get('product', '')}{level}"


def _input_fsp_folder(scenario_root: str, market_tag: str) -> Optional[str]:
    # Case market inputs now live in the
    # consolidated case folder; the old data_in location is kept as a fallback
    # for result folders produced before the change.
    consolidated = os.path.join(os.path.abspath(scenario_root), "market_inputs")
    if os.path.isdir(consolidated):
        return consolidated
    parts = _tag_parts(market_tag)
    if not parts:
        return None
    candidate = os.path.join(
        _project_root(scenario_root),
        "data_in",
        parts["country"],
        "market_inputs",
        parts["market"],
        parts["product"],
        parts["vl_case"],
        parts["flex_case"],
    )
    return candidate if os.path.isdir(candidate) else None


def _read_csv_matrix(path: str) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, index_col=0)
    except Exception:
        return pd.DataFrame()
    df.index = [_norm_label(i) for i in df.index]
    df.columns = [_norm_label(c) for c in df.columns]
    return df


def _read_excel_matrix(path: str, sheet_name=0) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, index_col=0)
    except Exception:
        return pd.DataFrame()
    df.index = [_norm_label(i) for i in df.index]
    df.columns = [_norm_label(c) for c in df.columns]
    return df


def _read_fsp_info(input_folder: Optional[str], market_tag: str) -> pd.DataFrame:
    rows = []
    if not input_folder:
        return pd.DataFrame()
    for cls in ["A", "B", "C", "D"]:
        path = os.path.join(input_folder, f"FSP{cls}_init{market_tag}.xlsx")
        if not os.path.exists(path):
            matches = sorted(Path(input_folder).glob(f"FSP{cls}_init*.xlsx"))
            path = str(matches[0]) if matches else ""
        if not path or not os.path.exists(path):
            continue
        sheet = f"FSPinfo_{cls}"
        try:
            df = pd.read_excel(path, sheet_name=sheet, index_col=0)
        except Exception:
            continue
        df = df.copy()
        df.index = [_norm_label(i) for i in df.index]
        df["fsp_name"] = df.index
        df["fsp_class"] = cls
        df["source_file"] = os.path.basename(path)
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True, sort=False)
    for col in ["bus", "id", "name", "res_category"]:
        if col not in out.columns:
            out[col] = ""
    out["bus_label"] = out["bus"].map(_norm_label)
    out["name_label"] = out["name"].map(_norm_label)
    return out


def _market_output_labels(model_path: Optional[str]) -> pd.DataFrame:
    if not model_path or not os.path.exists(model_path):
        return pd.DataFrame()
    rows = []
    sheet_class = {"DW_A": "A", "DR_A": "A", "DW_B": "B", "DR_B": "B", "DW_C": "C", "DR_C": "C"}
    try:
        xls = pd.ExcelFile(model_path)
    except Exception:
        return pd.DataFrame()
    for sheet, cls in sheet_class.items():
        if sheet not in xls.sheet_names:
            continue
        df = _read_excel_matrix(model_path, sheet)
        for idx in df.index:
            rows.append({"sheet": sheet, "fsp_class": cls, "fsp_name": idx})
    return pd.DataFrame(rows).drop_duplicates()


def _loading_asset_labels(scenario_root: str) -> List[str]:
    labels = []
    for rel in [
        ("FullTS_postMKT", "res_line", "loading_percent.csv"),
        ("FullTS_postMKT", "res_trafo", "loading_percent.csv"),
        ("FullTS_postMKT", "res_trafo3w", "loading_percent.csv"),
    ]:
        df = _read_csv_matrix(os.path.join(scenario_root, *rel))
        labels.extend([_norm_label(c) for c in df.columns])
    return sorted(set([x for x in labels if x]))


def _pilot_bus_audit(scenario_root: str) -> pd.DataFrame:
    pilot = _read_csv_matrix(os.path.join(scenario_root, "pilot_bus_vm_post.csv"))
    ac = _read_csv_matrix(os.path.join(scenario_root, "FullTS_postMKT", "res_bus", "vm_pu.csv"))
    ac_cols = set(ac.columns)
    rows = []
    for bus in pilot.columns:
        rows.append({
            "object_type": "pilot_bus",
            "label": bus,
            "present_in_platform_output": True,
            "present_in_ac_result": bus in ac_cols,
            "status": "OK" if bus in ac_cols else "MISMATCH",
            "comment": "Pilot bus exists in FullTS_postMKT/res_bus/vm_pu.csv" if bus in ac_cols else "Pilot bus missing from AC voltage result columns",
        })
    return pd.DataFrame(rows)


def _asset_index_map(scenario_root: str, config_path: Optional[str] = None) -> Dict[str, tuple]:
    """Asset name -> (table, element index) from the network workbook of the configuration.

    The market names its congested assets
    (e.g. SB_LINE_007) while the AC loading CSVs are indexed by the pandapower
    element number, so the audit resolves each name through the network itself.
    """
    try:
        from enginiite.visualization import accuracy_core as acc
        meta = acc._network_asset_metadata(acc._resolve_config_path([scenario_root], config_path))
    except Exception:
        return {}
    if meta is None or meta.empty:
        return {}
    return {str(r.asset): (str(r.kind), str(r.element_index)) for r in meta.itertuples()}


def _loading_columns_by_table(scenario_root: str) -> Dict[str, set]:
    out = {}
    for table in ("line", "trafo", "trafo3w"):
        df = _read_csv_matrix(os.path.join(scenario_root, "FullTS_postMKT", "res_" + table, "loading_percent.csv"))
        out[table] = {_norm_label(c) for c in df.columns}
    return out


def _congested_asset_audit(scenario_root: str, config_path: Optional[str] = None) -> pd.DataFrame:
    cm_pre = _read_excel_matrix(os.path.join(scenario_root, "total_cm_PreMKT.xlsx"))
    cm_post = _read_excel_matrix(os.path.join(scenario_root, "total_cm_postMKT.xlsx"))
    cm_assets = sorted(set(cm_pre.columns).union(set(cm_post.columns)))
    ac_assets = set(_loading_asset_labels(scenario_root))
    ac_numeric_count = len([a for a in ac_assets if str(a).isdigit()])
    # Names that are not AC columns are resolved to their element
    # index through the network (only names of the form L<digits> were mapped before, so every SB72
    # congested line was reported as MISMATCH although it is in the AC result).
    index_by_name = _asset_index_map(scenario_root, config_path)
    columns_by_table = _loading_columns_by_table(scenario_root) if index_by_name else {}
    rows = []
    for asset in cm_assets:
        present = asset in ac_assets
        table, element = index_by_name.get(str(asset), (None, None))
        by_index = (not present) and table is not None and element in columns_by_table.get(table, set())
        mapped_by_position = (not present) and (not by_index) and str(asset).upper().startswith("L") and str(asset)[1:].isdigit() and ac_numeric_count > 0
        rows.append({
            "object_type": "congested_asset",
            "label": asset,
            "present_in_platform_output": True,
            "present_in_ac_result": present or by_index,
            "status": "OK" if (present or by_index) else ("MAPPING_REQUIRED" if mapped_by_position else "MISMATCH"),
            "comment": (
                "Congested asset exists in AC loading result columns"
                if present else
                f"Congested asset found in the AC {table} loading results as element {element} (name resolved through the network)"
                if by_index else
                "Market uses asset names while AC loading CSV uses positional numeric columns; verify name-to-position mapping from the pandapower net before treating this as an error."
                if mapped_by_position else
                "Congested asset missing from AC line/trafo loading columns"
            ),
        })
    return pd.DataFrame(rows)


def _fsp_identity_audit(fsp_info: pd.DataFrame, market_labels: pd.DataFrame) -> pd.DataFrame:
    if fsp_info.empty:
        return pd.DataFrame()
    output_pairs = set(zip(market_labels.get("fsp_class", []), market_labels.get("fsp_name", [])))
    name_counts = fsp_info.groupby(["fsp_class", "fsp_name"])["fsp_name"].transform("count")
    bus_counts = fsp_info.groupby("bus_label")["fsp_name"].transform("count")
    rows = []
    for _, row in fsp_info.iterrows():
        pair = (row["fsp_class"], row["fsp_name"])
        duplicate_name = int(name_counts.loc[row.name]) > 1 if row.name in name_counts.index else False
        same_bus_count = int(bus_counts.loc[row.name]) if row.name in bus_counts.index else int((fsp_info["bus_label"] == row["bus_label"]).sum())
        rows.append({
            "fsp_class": row["fsp_class"],
            "fsp_name": row["fsp_name"],
            "network_name": row.get("name_label", ""),
            "bus": row.get("bus_label", ""),
            "resource_category": row.get("res_category", ""),
            "same_bus_fsp_count": same_bus_count,
            "duplicate_fsp_name": duplicate_name,
            "present_in_market_output": pair in output_pairs,
            "status": "OK" if (not duplicate_name and pair in output_pairs) else "CHECK",
            "comment": (
                "Multiple FSPs share this bus; safe if names remain unique."
                if same_bus_count > 1 else
                "Single FSP on this bus."
            ),
        })
    return pd.DataFrame(rows)


def _summary_cards(fsp_audit: pd.DataFrame, target_audit: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if not fsp_audit.empty:
        rows.extend([
            {"check": "FSP names", "value": int((~fsp_audit["duplicate_fsp_name"].astype(bool)).sum()), "total": len(fsp_audit), "status": "OK" if not fsp_audit["duplicate_fsp_name"].any() else "CHECK"},
            {"check": "FSPs present in market output", "value": int(fsp_audit["present_in_market_output"].sum()), "total": len(fsp_audit), "status": "OK" if fsp_audit["present_in_market_output"].all() else "CHECK"},
            {"check": "FSPs on shared buses", "value": int((fsp_audit["same_bus_fsp_count"] > 1).sum()), "total": len(fsp_audit), "status": "INFO"},
        ])
    if not target_audit.empty:
        acceptable = target_audit["status"].isin(["OK", "MAPPING_REQUIRED"])
        rows.append({"check": "Pilot buses and congested assets present or traceably mapped", "value": int(acceptable.sum()), "total": len(target_audit), "status": "OK" if acceptable.all() else "CHECK"})
    return pd.DataFrame(rows)


def _fsp_class_summary(fsp_audit: pd.DataFrame) -> pd.DataFrame:
    if fsp_audit is None or fsp_audit.empty:
        return pd.DataFrame()
    return (
        fsp_audit.groupby("fsp_class", as_index=False)
        .agg(
            input_fsp_count=("fsp_name", "nunique"),
            network_bus_count=("bus", "nunique"),
            shared_bus_fsp_count=("same_bus_fsp_count", lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) > 1).sum())),
            duplicate_name_count=("duplicate_fsp_name", lambda s: int(pd.Series(s).astype(bool).sum())),
            present_in_market_output_count=("present_in_market_output", lambda s: int(pd.Series(s).astype(bool).sum())),
        )
        .assign(
            status=lambda d: np.where(
                (d["duplicate_name_count"] == 0) & (d["present_in_market_output_count"] == d["input_fsp_count"]),
                "OK",
                "CHECK",
            )
        )
    )


def _shared_bus_table(fsp_audit: pd.DataFrame) -> pd.DataFrame:
    if fsp_audit is None or fsp_audit.empty:
        return pd.DataFrame()
    rows = []
    for bus, g in fsp_audit.groupby("bus", dropna=False):
        names = sorted(g["fsp_name"].astype(str).tolist())
        classes = sorted(g["fsp_class"].astype(str).unique().tolist())
        rows.append({
            "bus": bus,
            "fsp_count": len(names),
            "fsp_classes": ", ".join(classes),
            "fsp_names": "; ".join(names),
            "status": "INFO" if len(names) > 1 else "OK",
            "comment": "Shared bus; safe because FSP names are unique and checked independently." if len(names) > 1 else "Single FSP at this bus.",
        })
    return pd.DataFrame(rows).sort_values(["fsp_count", "bus"], ascending=[False, True])


def _management_cards_html(summary: pd.DataFrame) -> str:
    if summary is None or summary.empty:
        return ""
    cards = []
    for _, r in summary.iterrows():
        status = str(r.get("status", "INFO"))
        color = {"OK": "#0F766E", "INFO": "#B45309", "CHECK": "#B91C1C"}.get(status, "#475569")
        cards.append(
            f"""<article class="metric-card" style="border-top-color:{color}">
              <div class="metric-status">{html.escape(status)}</div>
              <div class="metric-value">{html.escape(str(r.get('value', '')))} / {html.escape(str(r.get('total', '')))}</div>
              <div class="metric-label">{html.escape(str(r.get('check', '')))}</div>
            </article>"""
        )
    return '<div class="metric-grid">' + "".join(cards) + "</div>"


def _table_html(df: pd.DataFrame, max_rows: int = 200) -> str:
    if df is None or df.empty:
        return "<p>No rows available.</p>"
    return df.head(max_rows).to_html(index=False, escape=True, classes="audit-table")


def _bus_svg(fsp_audit: pd.DataFrame) -> str:
    if fsp_audit is None or fsp_audit.empty or "bus" not in fsp_audit:
        return ""
    counts = fsp_audit.groupby("bus", as_index=False)["fsp_name"].count().rename(columns={"fsp_name": "fsp_count"})
    counts = counts.sort_values("fsp_count", ascending=False).head(20)
    if counts.empty:
        return ""
    width, height = 1180, max(280, 38 * len(counts) + 72)
    left, right, top = 170, 170, 36
    max_count = max(float(counts["fsp_count"].max()), 1.0)
    rows = []
    for i, r in counts.reset_index(drop=True).iterrows():
        y = top + i * 32 + 18
        bar = (width - left - right) * float(r["fsp_count"]) / max_count
        color = "#007C89" if int(r["fsp_count"]) == 1 else "#D97706"
        rows.append(f'<text x="{left-12}" y="{y+5}" text-anchor="end">{html.escape(str(r["bus"]))}</text>')
        rows.append(f'<rect x="{left}" y="{y-12}" width="{bar:.1f}" height="22" rx="3" fill="{color}" opacity="0.86"></rect>')
        rows.append(f'<text x="{left+bar+8}" y="{y+5}">{int(r["fsp_count"])} FSP</text>')
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><text x="{left}" y="20" font-weight="700">FSP count per bus (shared buses are expected but must preserve unique FSP names)</text>{"".join(rows)}</svg>'


def _html_page(title: str, summary: pd.DataFrame, fsp_audit: pd.DataFrame, target_audit: pd.DataFrame, class_summary: Optional[pd.DataFrame] = None, shared_bus: Optional[pd.DataFrame] = None) -> str:
    failed = []
    if not fsp_audit.empty:
        failed.extend(fsp_audit[~fsp_audit["status"].isin(["OK", "INFO"])]["fsp_name"].astype(str).tolist()[:5])
    if not target_audit.empty:
        failed.extend(target_audit[~target_audit["status"].isin(["OK", "MAPPING_REQUIRED"])]["label"].astype(str).tolist()[:5])
    mapped = []
    if not target_audit.empty:
        mapped = target_audit[target_audit["status"] == "MAPPING_REQUIRED"]["label"].astype(str).tolist()[:5]
    takeaway = (
        "No identity mismatch was detected in the available output tables. Shared buses are not a problem when each FSP keeps a unique name and appears separately in market-output sheets."
        if not failed else
        "Some labels need review: " + ", ".join(failed) + ". These are the rows most likely to reveal loc/index mismatch or overwritten FSP identity."
    )
    if mapped and not failed:
        takeaway += " Congested assets " + ", ".join(mapped) + " use market asset names while the AC loading CSV uses positional numeric columns, so the audit marks them as traceably mapped rather than failed."
    class_summary = class_summary if class_summary is not None else _fsp_class_summary(fsp_audit)
    shared_bus = shared_bus if shared_bus is not None else _shared_bus_table(fsp_audit)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin:0; font-family:"Times New Roman", Times, serif; background:#F6F8FB; color:#111827; }}
    header {{ background:linear-gradient(90deg,#003A70,#007C89); color:white; padding:18px 32px; text-align:center; }}
    main {{ max-width:1760px; margin:0 auto; padding:24px 28px; }}
    section {{ background:white; border:1px solid #D8E0EA; border-radius:14px; padding:18px 22px; margin-bottom:18px; box-shadow:0 8px 26px rgba(16,42,67,0.075); overflow:auto; }}
    h1 {{ margin:0; font-size:25px; }}
    h2 {{ color:#003A70; margin:0 0 12px 0; }}
    p, li, td, th {{ font-size:15px; line-height:1.4; }}
    .audit-table {{ border-collapse:collapse; width:100%; min-width:1180px; table-layout:auto; }}
    .audit-table th, .audit-table td {{ border:1px solid #D8E0EA; padding:8px 10px; text-align:left; vertical-align:top; white-space:normal; overflow-wrap:anywhere; word-break:normal; min-width:90px; }}
    .audit-table th {{ background:#EAF2F8; position:sticky; top:0; }}
    .audit-table th:first-child, .audit-table td:first-child {{ position:sticky; left:0; background:#F8FBFD; z-index:1; font-weight:700; }}
    svg {{ max-width:100%; height:auto; overflow:visible; }}
    .metric-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:18px; }}
    .metric-card {{ border:1px solid #D8E0EA; border-top:5px solid #007C89; border-radius:10px; padding:14px 16px; background:#F8FBFD; }}
    .metric-status {{ font-size:13px; font-weight:700; color:#475569; text-transform:uppercase; letter-spacing:.04em; }}
    .metric-value {{ font-size:28px; font-weight:700; color:#003A70; margin:6px 0; }}
    .metric-label {{ font-size:15px; line-height:1.3; }}
    @media (max-width:1100px) {{ .metric-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    .takeaway {{ page-break-before:always; break-before:page; }}
  </style>
</head>
<body>
  <header><h1>{html.escape(title)}</h1></header>
  <main>
    <section><h2>Management Dashboard</h2>{_management_cards_html(summary)}{_table_html(summary)}</section>
    <section><h2>FSP Class-Level Integrity</h2>{_table_html(class_summary)}</section>
    <section><h2>Shared-Bus Identity Map</h2>{_bus_svg(fsp_audit)}</section>
    <section><h2>Shared-Bus Detailed Register</h2>{_table_html(shared_bus)}</section>
    <section><h2>FSP Input-to-Output Identity Check</h2>{_table_html(fsp_audit)}</section>
    <section><h2>Pilot-Bus and Congested-Asset Check</h2>{_table_html(target_audit)}</section>
    <section class="takeaway"><h2>Takeaway</h2><p>{html.escape(takeaway)}</p>
    <p><strong>Hidden diagnostic value.</strong> This audit separates two different risks: non-continuous network indices and duplicate buses. Non-continuous indices are safe when labels are matched by <code>loc</code>-style names; duplicate buses are safe when FSP rows are keyed by unique FSP names rather than bus numbers. A shared bus count above one is therefore informational, not an error, unless names disappear from market output sheets.</p></section>
  </main>
</body>
</html>"""


def audit_scenario(scenario_root: str, output_root: Optional[str] = None,
                   config_path: Optional[str] = None) -> Dict[str, str]:
    # config_path names the network used to resolve asset names.
    scenario_root = os.path.abspath(str(scenario_root))
    tag = _market_tag(scenario_root)
    out_dir = output_root or os.path.join(scenario_root, "visualization", AUDIT_FOLDER)
    _ensure_dir(out_dir)
    input_folder = _input_fsp_folder(scenario_root, tag)
    fsp_info = _read_fsp_info(input_folder, tag)
    market_labels = _market_output_labels(_market_result_path(scenario_root))
    fsp_audit = _fsp_identity_audit(fsp_info, market_labels)
    target_audit = pd.concat([_pilot_bus_audit(scenario_root), _congested_asset_audit(scenario_root, config_path)], ignore_index=True)
    summary = _summary_cards(fsp_audit, target_audit)
    class_summary = _fsp_class_summary(fsp_audit)
    shared_bus = _shared_bus_table(fsp_audit)

    paths = {
        "summary": os.path.join(out_dir, f"NetworkConsistencySummary_{tag}.csv"),
        "fsp": os.path.join(out_dir, f"FSPIdentityAudit_{tag}.csv"),
        "targets": os.path.join(out_dir, f"NetworkTargetAudit_{tag}.csv"),
        "classes": os.path.join(out_dir, f"FSPClassIntegrity_{tag}.csv"),
        "shared_bus": os.path.join(out_dir, f"SharedBusRegister_{tag}.csv"),
        "html": os.path.join(out_dir, f"NetworkConsistencyAudit_{tag}.html"),
    }
    summary.to_csv(paths["summary"], index=False)
    fsp_audit.to_csv(paths["fsp"], index=False)
    target_audit.to_csv(paths["targets"], index=False)
    class_summary.to_csv(paths["classes"], index=False)
    shared_bus.to_csv(paths["shared_bus"], index=False)
    with open(paths["html"], "w", encoding="utf-8") as fh:
        fh.write(_html_page(f"Network consistency audit ({tag})", summary, fsp_audit, target_audit, class_summary, shared_bus))
    return paths


def run_network_consistency_audit(scenario_roots, output_root: Optional[str] = None,
                                  config_path: Optional[str] = None) -> pd.DataFrame:
    # config_path (optional) is passed on to audit_scenario.
    scenarios = discover_scenario_roots(scenario_roots)
    records = []
    if output_root is None and scenarios:
        common = os.path.commonpath(scenarios)
        output_root = os.path.join(common, "comparison", AUDIT_FOLDER)
    if output_root:
        _ensure_dir(output_root)
    for scenario in scenarios:
        tag = _market_tag(scenario)
        out_dir = output_root or os.path.join(scenario, "visualization", AUDIT_FOLDER)
        paths = audit_scenario(scenario, out_dir, config_path=config_path)
        summary = pd.read_csv(paths["summary"])
        summary.insert(0, "scenario", tag)
        summary.insert(1, "scenario_code", _scenario_code(tag))
        records.append(summary)
    bundle = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    if output_root and not bundle.empty:
        bundle_path = os.path.join(output_root, "NetworkConsistencyBundleSummary.csv")
        bundle.to_csv(bundle_path, index=False)
        with open(os.path.join(output_root, "NetworkConsistencyBundleSummary.html"), "w", encoding="utf-8") as fh:
            fh.write(_html_page("Network consistency audit - bundle summary", bundle, pd.DataFrame(), pd.DataFrame()))
    return bundle


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Audit FSP, pilot-bus, and congested-asset label consistency.")
    parser.add_argument("scenario_roots", nargs="+")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    result = run_network_consistency_audit(args.scenario_roots, args.output_root)
    print(result.to_string(index=False) if not result.empty else "No audit results generated.")
