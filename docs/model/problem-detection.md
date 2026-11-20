# Problem detection model

This page describes how stage 1 decides where and when the network breaks its limits, which elements and hours the market will study, and what each limit and margin means. For the overview see [Four stages](../how-it-works/four-stages.md).

## Baseline power flow

The platform first runs an hourly AC power flow for the simulation window, with the baseline profiles of loads, static generators, generators and storage and without any market. Each profile is attached to its element as a controller of the power flow library, and the time series is solved hour by hour. A time step that does not converge stops the run. The results are written to disk and read back as tables with one row per hour, among them the bus voltages $V_{b,t}$ and the loading in percent of lines and transformers.

The baseline is the reference against which every later stage measures its effect.

## Limits and margins

Voltage and current each have three levels of limit, built from the voltage tag and the tolerances of the configuration. All tolerances are percentages of the limit, not offsets in per unit.

| Level | Role |
|---|---|
| Standard | The physical limit. The indicators of stage 4 judge the results against it. |
| Detection | Decides what counts as a problem. It is inside the standard limit by the margin $tol$. |
| Optimisation | The target of the market. It is inside the detection limit by the extra margin $tol_{opt}$. |

### Voltage

Each voltage tag defines a standard band $[\underline V, \overline V]$ in per unit.

| Tag | Standard band |
|---|---|
| VL01 | 0.95 to 1.05 |
| VL02 | 0.93 to 1.07 |
| VL03 | 0.90 to 1.10 |
| VL04 | 0.91 to 1.09 |
| VL05 | 0.97 to 1.03 |
| VL06 | 0.98 to 1.02 |

With $tol_v$ and $tol_{v,opt}$ expressed as fractions, the detection and optimisation bands are

$$
\underline V^{det} = \underline V\,(1 + tol_v), \qquad \overline V^{det} = \overline V\,(1 - tol_v),
$$

$$
\underline V^{opt} = \underline V\,(1 + tol_v + tol_{v,opt}), \qquad \overline V^{opt} = \overline V\,(1 - tol_v - tol_{v,opt}).
$$

For VL01 with $tol_v = 0$ and $tol_{v,opt} = 1\,\%$ the optimisation band is 0.9595 to 1.0395 per unit. The platform stops with an error if the optimisation band collapses, and warns if it is narrower than 0.005 per unit.

### Current

For lines and transformers the limits are expressed as loading in percent of the rating.

$$
L^{std} = 100\,\%, \qquad L^{det} = 100 - tol_i, \qquad L^{opt} = 100 - tol_i - tol_{i,opt}.
$$

The rating of an element is $S^{\max}_\ell = \sqrt{3}\,I^{\max}\,V_{n}$ for a line, with $V_{n}$ the nominal voltage of its from bus, the rated power $S_n$ for a two winding transformer and the rated power of the high voltage side for a three winding transformer.

## Voltage problems

A bus has a problem in an hour when its voltage is outside the detection band.

$$
V_{b,t} > \overline V^{det} \quad \text{or} \quad V_{b,t} < \underline V^{det}.
$$

The comparison is strict, so a voltage exactly on the limit is compliant, as it is in the indicators. All buses are checked, not only those that will later be watched. The result is a table of buses and hours that holds the voltage where a limit is violated and zero elsewhere, split into over-voltage and under-voltage, and the list of hours with at least one violation.

## Congestion problems

An element has a problem in an hour when its loading is above the detection limit, $L_{\ell,t} > L^{det}$. Its need is the excess over that limit, converted to MVA.

$$
N_{\ell,t} = \frac{\max\left(L_{\ell,t} - L^{det},\, 0\right)}{100}\,S^{\max}_\ell .
$$

Two more quantities are prepared for each element, and the market reads them as constants of its constraints.

$$
S^{0}_{\ell,t} = \frac{L_{\ell,t}}{100}\,S^{\max}_\ell, \qquad
\delta_\ell = \frac{tol_i + tol_{i,opt}}{100}\,S^{\max}_\ell .
$$

$S^{0}$ is the apparent power before the market, based on the current through the loading percent, and $\delta_\ell$ is the margin kept below the rating. They are the $S^{0}_{\ell,t}$ and $\delta_\ell$ of the [market optimization model](market-optimization.md). The margin is the same for every hour of an element.

### Which elements are monitored

An element is monitored when its loading exceeds the detection limit in at least one hour of the window. From then on it is constrained in every studied hour, not only in the hours where it was flagged. With `full_network` set to `true` every line and transformer is monitored.

## Hours to study

The market does not need every hour, and an hour without a problem would only add variables. The platform selects the hours with the rule below.

| `intertemp_cons` | Hours studied |
|---|---|
| `true` | The whole simulation window |
| `false` | Only the hours with a problem, according to `ModelTAG` |

When only the problem hours are used, `VC` takes the voltage hours, `CM` takes the congestion hours and `CMVC` takes their union. The list of hours is saved as `HoursToStudy`.

Some consequences follow from the rule.

- If no hour has a problem for the chosen `ModelTAG`, the platform ends the whole run with a warning. Later scenarios and the final indicators are not produced.
- The key `only_worst_hour` is read but has no effect, because its branch of the code is never reached. Keep it at `false`.
- With `intertemp_cons` false the studied hours need not be contiguous, and blocks are cut by position in the list of hours.

## Pilot buses

Voltage limits enter the market only at the pilot buses. The platform selects them as the union of two sets.

- The buses with a voltage problem, without the slack bus, the buses that are out of service and, when `only_pilot_busMV` is `true`, the buses whose nominal voltage differs from `vn_kv_mv`.
- Every bus that carries a provider.

With `full_network` every active bus except the slack is a pilot bus, plus the provider buses. The consequence is that a new violation at a bus outside this set cannot be seen by the market, and shows up only in the verification after the market.

## Outputs of the stage

| Result | Content |
|---|---|
| `VM_Problems_Stats_preMKT` | Counts of over and under voltage bus-hours, and the violations themselves |
| `VCHoursToStudy`, `CMHoursToStudy` | Hours with a voltage problem and with a congestion problem |
| `total_cm_PreMKT` | Need in MVA of every monitored element and hour |
| `HoursToStudy` | The hours that the next stages use |
| Pilot bus voltages | Voltage of the pilot buses in the studied hours |

After the market, the same checks run again on the exact power flow of stage 4. See [Verification and corrective market](../how-it-works/verification-and-corrective-market.md).
