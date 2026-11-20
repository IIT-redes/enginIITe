"""Canonical technical-limit policy used by market, KPI, and visualizations."""

import warnings


VOLTAGE_SCENARIO_DELTAS = {
    "VL01": 0.00,
    "VL02": 0.02,
    "VL03": 0.05,
    "VL04": 0.04,
    "VL05": -0.02,
    "VL06": -0.03,
}


def _percent(value):
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def voltage_limits(vl_tag, tol_v=0.0, tol_v_opt=0.0):
    """Return standard, preventive, and optimization voltage bands in pu."""
    delta = VOLTAGE_SCENARIO_DELTAS.get(str(vl_tag), 0.0)
    standard_min = 0.95 - delta
    standard_max = 1.05 + delta
    tol_percent = _percent(tol_v)
    tol_opt_percent = _percent(tol_v_opt)
    tol = tol_percent / 100.0
    total_opt_tol = (tol_percent + tol_opt_percent) / 100.0
    detection_min = standard_min * (1.0 + tol)
    detection_max = standard_max * (1.0 - tol)
    optimization_min = standard_min * (1.0 + total_opt_tol)
    optimization_max = standard_max * (1.0 - total_opt_tol)
    # Detection uses tol_v alone, while
    # optimization uses the direct percentage sum tol_v + tol_v_opt.
    if optimization_min > optimization_max:
        raise ValueError(
            "Voltage optimization band is invalid for {tag}: minimum {vmin:.6f} pu "
            "exceeds maximum {vmax:.6f} pu. Reduce tol_v + tol_v_opt."
            .format(tag=vl_tag, vmin=optimization_min, vmax=optimization_max)
        )
    if optimization_max - optimization_min <= 0.005:
        warnings.warn(
            "Voltage optimization band for {tag} is extremely narrow: "
            "[{vmin:.6f}, {vmax:.6f}] pu."
            .format(tag=vl_tag, vmin=optimization_min, vmax=optimization_max),
            RuntimeWarning,
        )
    return {
        "standard_min_pu": standard_min,
        "standard_max_pu": standard_max,
        "detection_min_pu": detection_min,
        "detection_max_pu": detection_max,
        "optimization_min_pu": optimization_min,
        "optimization_max_pu": optimization_max,
        "tol_v_percent": tol_percent,
        "tol_v_opt_percent": tol_opt_percent,
        "optimization_tolerance_percent": tol_percent + tol_opt_percent,
    }


def current_limits(tol_i=0.0, tol_i_opt=0.0):
    """Return physical, preventive, and optimization loading limits in percent."""
    tol = _percent(tol_i)
    tol_opt = _percent(tol_i_opt)
    # tol_i and tol_i_opt are preventive
    # inward margins below 100%, not permissions to exceed the equipment rating.
    return {
        "standard_percent": 100.0,
        "detection_limit_percent": 100.0 - tol,
        "optimization_target_percent": 100.0 - tol - tol_opt,
        "tol_i_percent": tol,
        "tol_i_opt_percent": tol_opt,
    }


def build_tolerance_policy(cfg, voltage_tags=()):
    cfg = cfg or {}
    return {
        "current": current_limits(cfg.get("tol_i", 0.0), cfg.get("tol_i_opt", 0.0)),
        "voltage": {
            str(tag): voltage_limits(tag, cfg.get("tol_v", 0.0), cfg.get("tol_v_opt", 0.0))
            for tag in voltage_tags
        },
    }
