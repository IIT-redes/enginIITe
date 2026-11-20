"""Technical-headroom bidding for flexibility service providers.

The platform has always sized a bid as an INCREMENT around the operating
point.  Both legacy strategies share that shape and differ only in the
reference that scales the fraction:

    initial_value   bound = P0 +/- rate * P0(h)      reference is the profile
    mva_value       bound = P0 +/- rate * Smax       reference is the rating

Neither is headroom.  A resource sized this way never reaches its technical
limit, and because the downward leg was never clamped it could be pushed
THROUGH zero -- a generator asked to consume, a load asked to inject.

The third strategy, ``headroom_value``, computes the physical room to move
first and then treats the bid fraction as the share of that room the provider
is willing to sell:

    up_available   = max(P_technical_max - P0, 0)
    down_available = max(P0 - P_technical_min, 0)
    bound_high     = P0 + up_rate   * up_available
    bound_low      = P0 - down_rate * down_available

so a rate of 1.0 offers the whole physical envelope, 0.5 offers half, and no
bound can ever leave the feasible region regardless of the rate.  This is what
lets a resource genuinely act up to its maximum capacity, and it is the model
behind an EV parking lot whose battery is implicit: the lot can be curtailed
toward its minimum draw and pushed up toward its connection rating.

The helpers here are deliberately numeric and convention-free.  Each resource
model maps its own market direction onto the numeric one:

    generator  numeric increase = upward flexibility
    load       numeric increase = DOWNWARD flexibility (more consumption)
    storage    numeric increase = upward flexibility (more injection)
"""

from __future__ import annotations

import logging
import math

STRATEGY_INITIAL = 'initial_value'
STRATEGY_MVA = 'mva_value'
STRATEGY_HEADROOM = 'headroom_value'

KNOWN_STRATEGIES = (STRATEGY_INITIAL, STRATEGY_MVA, STRATEGY_HEADROOM)


def _describe(name, hour):
    """A provider reference a human can act on, not an array index."""
    if hour is None:
        return str(name)
    return '%s at hour %s' % (name, hour)


def is_headroom(strategy):
    """True when a bid row asks for technical-headroom sizing."""
    return str(strategy).strip().lower() == STRATEGY_HEADROOM


def numeric(value, default=float('nan')):
    """Coerce a spreadsheet cell to float; blank and NaN both mean 'absent'."""
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out):
        return default
    return out


def first_finite(*values):
    """The first value that is a real number, else NaN."""
    for value in values:
        out = numeric(value)
        if not math.isnan(out):
            return out
    return float('nan')


def safe_sqrt_capability(s_rated, p, name='', hour=None, k_opt=1.0):
    """Reactive room on the apparent-power circle: sqrt(S^2 - P^2).

    Returns (q_abs_max, clipped).  A profile that already exceeds the declared
    rating is a data problem, not a solver problem, so it is reported by name
    and the circle collapses to zero rather than raising a domain error.
    """
    s = abs(numeric(s_rated, 0.0))
    p_abs = abs(numeric(p, 0.0))
    if s <= 0.0:
        return 0.0, False
    if p_abs > s:
        logging.warning(
            'Headroom: %s draws P = %.6f MW beyond its rating S = %.6f MVA; '
            'reactive capability collapsed to zero for this hour.',
            _describe(name, hour), p_abs, s)
        return 0.0, True
    return math.sqrt(s * s - p_abs * p_abs) * float(k_opt), False


def clip_with_warning(value, lower, upper, name='', hour=None, what='bound'):
    """Force a bound inside a technical window, saying so when it bites."""
    low = numeric(lower, -float('inf'))
    high = numeric(upper, float('inf'))
    if high < low:
        low, high = high, low
    out = numeric(value, 0.0)
    if out < low:
        logging.warning(
            'Headroom: %s %s = %.6f is below its technical minimum %.6f; clipped.',
            _describe(name, hour), what, out, low)
        return low, True
    if out > high:
        logging.warning(
            'Headroom: %s %s = %.6f exceeds its technical maximum %.6f; clipped.',
            _describe(name, hour), what, out, high)
        return high, True
    return out, False


# Two repairs of the LEGACY sizing
# (initial_value / mva_value), kept here so they can be tested on their own.
def floor_lower_bound(low, current, floor=0.0):
    """Legacy lower bid bound kept at or above the physical floor.

    The legacy downward leg is P0 - rate * reference.  Under mva_value (or a
    rate above one) it falls below the floor whenever rate * S > P0 - floor:
    below zero for a generator or a load, below -S for a battery.  The market's
    own variable bounds (W >= 0 for a generator, consumption >= 0 for a load,
    the S circle for a battery) already stop the DISPATCH there, so clearing
    results do not change.  The bid file, however, and every report read from
    it (offered flexibility, offer books, exploitation ratios) counted the
    impossible part as offered.  The floor never rises above the operating
    point, so P0 always stays inside the interval.
    """
    out = numeric(low, 0.0)
    return max(out, min(numeric(floor, 0.0), numeric(current, 0.0)))


def legacy_reactive_room(q_circle, q0):
    """Room the legacy reactive bid is a share of: q_circle - |Q0|, never negative.

    The legacy static-generator bounds were |Q0| +/- rate * (q_circle - |Q0|),
    centred on |Q0|.  For a unit already absorbing (Q0 < 0) that interval sits
    on the wrong side of zero and excludes Q0, so the market was forced to buy
    a reactive move.  Centring the same width on the signed Q0,
    Q0 +/- rate * legacy_reactive_room(q_circle, Q0), is identical for Q0 >= 0
    and always contains Q0.
    """
    return max(abs(numeric(q_circle, 0.0)) - abs(numeric(q0, 0.0)), 0.0)


def headroom_bounds(current, lower, upper, up_rate, down_rate):
    """Bid bounds as a share of the physical room to move.

    Purely numeric: `up` means a larger signed value, `down` a smaller one.
    Returns (low, high, down_available, up_available).  The operating point is
    itself clipped into the window first, so an infeasible starting profile
    yields a degenerate rather than an inverted interval.
    """
    low_lim = numeric(lower, -float('inf'))
    high_lim = numeric(upper, float('inf'))
    if high_lim < low_lim:
        low_lim, high_lim = high_lim, low_lim
    cur = min(max(numeric(current, 0.0), low_lim), high_lim)

    up_available = max(high_lim - cur, 0.0)
    down_available = max(cur - low_lim, 0.0)

    high = cur + max(numeric(up_rate, 0.0), 0.0) * up_available
    low = cur - max(numeric(down_rate, 0.0), 0.0) * down_available

    # Rates above one would otherwise walk straight out of the envelope.
    high = min(high, high_lim)
    low = max(low, low_lim)
    return low, high, down_available, up_available


class HeadroomDiagnostics:
    """Per-resource, per-hour record of how each bound was arrived at.

    Written beside the bids so a reviewer can see the technical limit, the room
    it left, and whether anything had to be clipped -- the questions that the
    bid bounds alone cannot answer.
    """

    FIELDS = (
        ('WMax', 'p_max'), ('WMin', 'p_min'),
        ('RMax', 'q_max'), ('RMin', 'q_min'),
        ('WUpAvail', 'p_up_avail'), ('WDownAvail', 'p_down_avail'),
        ('RUpAvail', 'q_up_avail'), ('RDownAvail', 'q_down_avail'),
        ('Clipped', 'clipped'),
    )

    def __init__(self, shape):
        # numpy is imported here so the sizing helpers above stay usable -- and
        # testable -- without the scientific stack.
        import numpy as np

        for _, attr in self.FIELDS:
            setattr(self, attr, np.zeros(shape=shape))
        self.active = False

    def record(self, i, h, p_min=0.0, p_max=0.0, q_min=0.0, q_max=0.0,
               p_down_avail=0.0, p_up_avail=0.0,
               q_down_avail=0.0, q_up_avail=0.0, clipped=False):
        self.active = True
        self.p_min[i, h] = p_min
        self.p_max[i, h] = p_max
        self.q_min[i, h] = q_min
        self.q_max[i, h] = q_max
        self.p_down_avail[i, h] = p_down_avail
        self.p_up_avail[i, h] = p_up_avail
        self.q_down_avail[i, h] = q_down_avail
        self.q_up_avail[i, h] = q_up_avail
        self.clipped[i, h] = 1.0 if clipped else 0.0

    def sheets(self, class_fsp):
        """Sheet name -> array, empty when no row used headroom sizing."""
        if not self.active:
            return {}
        return {'%s_%s' % (sheet, class_fsp): getattr(self, attr)
                for sheet, attr in self.FIELDS}
