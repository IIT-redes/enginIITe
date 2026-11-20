# Sensitivity analysis model

This page describes how stage 2 measures the response of the network to a change at each provider, and how those measurements become the linear coefficients of the [market optimization model](market-optimization.md). For the overview see [Four stages](../how-it-works/four-stages.md).

## Why sensitivities

The market cannot run an AC power flow inside the optimisation. It replaces the network by its first order response around the operating point of each studied hour. If $y$ is a quantity of the network, such as the voltage of a bus or the loading of a line, and $x_f$ is the power of provider $f$, the market uses

$$
y(x + \Delta x) \approx y(x) + \sum_{f} \frac{\partial y}{\partial x_f}\,\Delta x_f .
$$

Stage 2 computes the coefficients $\partial y / \partial x_f$ numerically, hour by hour, by running the exact power flow with a small perturbation. The method is finite differences. It builds no analytical Jacobian, so it applies to any network that the power flow solver can handle.

## Operating point of an hour

For each studied hour the platform rebuilds the network at its baseline operating point. It copies the power of loads, static generators, generators and storage from the baseline time series, and the supply voltage of the external grid. When the case has no supply voltage profile, the set-point of the network file is kept. All coefficients of that hour are computed at this point.

## Perturbation

A provider is represented by its bus. For a bus $n$ the platform creates a virtual static generator and solves the power flow twice, with the same network each time.

| Perturbation | Virtual generator | Result tables |
|---|---|---|
| Active | $\Delta P$ injected at bus $n$ | $y^{P}_{n}$ |
| Reactive | $\Delta Q$ injected at bus $n$ | $y^{Q}_{n}$ |

The coefficients are the ratios between the change of each result and the size of the step.

$$
\frac{\partial y}{\partial P_n} \approx \frac{y^{P}_{n} - y^{0}}{\Delta P}, \qquad
\frac{\partial y}{\partial Q_n} \approx \frac{y^{Q}_{n} - y^{0}}{\Delta Q},
$$

where $y^{0}$ comes from a power flow without the virtual generator. The perturbation is an injection, in the generation sense, and the market applies the coefficients to the changes of power $\Delta W$ and $\Delta R$ of the providers in the same convention.

A perturbed pair depends only on the bus. Every provider connected to that bus, of any type, and the self sensitivity of the same bus as a pilot share the same two power flows within an hour. The cost of an hour is therefore one power flow at the operating point plus two for each distinct bus that carries a provider or is perturbed for a self sensitivity.

### Step size

The step must be small enough to stay in the linear region and large enough to be seen above the tolerance of the power flow. The platform derives it from the network file. It takes the smallest strictly positive active power among loads, generators, static generators and storage, and the smallest strictly positive reactive power among loads, static generators and storage, using the values stored in the network tables. If that value is written in scientific notation as $m \times 10^{-e}$ with $1 \le m < 10$, the step is

$$
\Delta = 10^{-(e+1)} .
$$

A smallest power of 0.0123 MW gives a step of 0.001 MW, and 0.5 MW gives 0.01 MW. If the smallest power is 1 or more, or the search fails for either side, both steps fall back to 0.1. The same $\Delta P$ and $\Delta Q$ serve voltage and congestion.

The keys `sensitivity_delta_p_mw` and `sensitivity_delta_q_mvar` override the derived values. They exist for robustness studies, where the step is varied without editing code.

## Voltage sensitivities

The watched buses of stage 1 are the pilot buses. For each provider bus $n$ and pilot bus $b$ the platform stores two coefficients, one for active and one for reactive power.

$$
H^{W}_{n,b} = \frac{V^{P}_{n,b} - V^{0}_{b}}{\Delta P}, \qquad
H^{R}_{n,b} = \frac{V^{Q}_{n,b} - V^{0}_{b}}{\Delta Q} .
$$

The sign is kept, so a coefficient is positive when injecting power raises the voltage and negative when it lowers it. The market multiplies these coefficients by the changes of power of the providers to predict the voltage after the market.

### Self sensitivity

A third table holds the response of each pilot bus to its own injection, $H^{W}_{b,b}$ and $H^{R}_{b,b}$, which is the diagonal of the same computation with the pilot buses playing the role of providers. The market uses $H^{W}_{b,b}$ to convert the voltage slack from per unit into an equivalent power. It is computed once per hour, because it does not depend on the provider types.

## Congestion sensitivities

For each monitored line or transformer the platform needs the response of its loading to the injection at each provider bus. The loading is a magnitude, so the coefficient is the change of an apparent power $S$.

$$
K^{W}_{n,\ell} = \frac{S^{P}_{n,\ell} - S^{0}_{\ell}}{\Delta P}, \qquad
K^{R}_{n,\ell} = \frac{S^{Q}_{n,\ell} - S^{0}_{\ell}}{\Delta Q} .
$$

The apparent power can be built in two ways, selected with `cm_sensitivity_basis`. The accurate one is the `current` basis, and the shipped examples use it.

### Current basis

With `current`, the branch quantity is the apparent power at nominal voltage and real current. It is the same quantity as the rating of the branch, which is also built with the nominal voltage (see [Problem detection model](problem-detection.md)). The initial loading $S^{0}_{\ell}$ of the market, its limit and the verification of stage 4 are all based on the current of the branch, so this basis differentiates the quantity that the rest of the platform compares.

$$
S_{line} = \sqrt{3}\,V_{n}\,I, \qquad S_{trafo} = \frac{\text{loading}}{100}\,S_{rated}.
$$

For a line, $V_{n}$ is the nominal voltage of its from bus and $I$ its current. For a transformer, the loading in percent is multiplied by its rated power, which for a three winding transformer is the rated power of the high voltage side.

### Apparent power at the branch ends

This is the default when `cm_sensitivity_basis` is missing, `apparent_power`. The active and reactive flows are taken at the larger of the two ends, each separately, and combined.

$$
S = \sqrt{P_{\max}^{2} + Q_{\max}^{2}}, \qquad
P_{\max} = \max\left(|P_{from}|, |P_{to}|\right), \quad
Q_{\max} = \max\left(|Q_{from}|, |Q_{to}|\right).
$$

For a two winding transformer the ends are the high and low voltage sides. For a three winding transformer the high voltage flow is compared with the sum of the medium and low voltage flows, $|P_{mv} + P_{lv}|$ and $|Q_{mv} + Q_{lv}|$.

This basis is built from power flows, so it depends on the actual voltage and not on the nominal voltage of the rating, and it takes the larger end of $P$ and of $Q$ separately. It can therefore miss the extra current that reactive absorption draws. A market that uses it can underestimate the effect of reactive power and leave a line overloaded after the dispatch. The default is kept as it is so that the results of earlier runs do not change.

### What the coefficient is

Both bases differentiate a magnitude, not a signed flow. Reducing the flow through an element does not always reduce $S$, and a coefficient can change sign between operating points. The market applies the coefficients with the sign convention described in [Market optimization model](market-optimization.md), where $k$ is positive when the activation relieves the element.

The code can also produce the coefficients of the active and reactive flows themselves, the power transfer distribution factors, but the workflow always asks for the apparent power coefficients only.

## Output tables

The tables are written as CSV files in the sensitivity folder of the case, one per kind, provider type and hour, with the `simulation_tag` at the end of the name.

| File | Rows | Columns | Content |
|---|---|---|---|
| `HCMdSdP_FSP<type>_h<HH>_<tag>.csv` | Providers | Monitored branches | $K^{W}$ |
| `HCMdSdQ_FSP<type>_h<HH>_<tag>.csv` | Providers | Monitored branches | $K^{R}$ |
| `HVMP_FSP<type>_h<HH>_<tag>.csv` | Providers | Pilot buses | $H^{W}$ |
| `HVMQ_FSP<type>_h<HH>_<tag>.csv` | Providers | Pilot buses | $H^{R}$ |
| `HVMPii_h<HH>_<tag>.csv`, `HVMQii_h<HH>_<tag>.csv` | Pilot buses | The hour | Self sensitivities |

Branch columns are labelled with the names of lines and transformers, so those names must be unique across all branch types.

## Reuse of tables

Computing the tables is the most expensive part of stage 2, so existing files are reused.

- A pair of tables, active and reactive, is the unit of reuse. If either file of a pair is missing, both are computed again.
- With `force_HVM` and `force_HCM` at `false`, every pair that exists on disk is reused as it is.
- With `true`, the tables are recomputed, with one exception. A table that this same run already wrote from identical inputs is not computed again, for example when the next product or provider capacity level of the same run needs the same hour. The inputs compared are the network physics, the operating point of the hour, the provider buses, the monitored branches or pilot buses, the steps and the basis.

The name of a file contains only the kind, the provider type, the hour and the `simulation_tag`. Nothing in it records the network, the profiles, the voltage band or the pilot buses. Reusing a file from an earlier run is therefore safe only when none of those changed. The market checks the size of a table before using it, but a table of the right size with different buses or branches would be accepted silently. After any change of the network, the profiles, the providers, the supply voltage or the basis, set `force_HVM` and `force_HCM` to `true`, or use a new `simulation_tag`.

## Cost and validity

| Kind of table | Perturbed power flows per studied hour |
|---|---|
| Voltage, providers and self sensitivity | $2 N_{pilot}$, because the pilot buses include every provider bus |
| Congestion, providers | $2 N_{bus}$ |

where $N_{bus}$ is the number of distinct provider buses and $N_{pilot}$ the number of pilot buses. Perturbations at the same bus are solved once per hour and kind. Each group of tables that is computed also needs one power flow at the unperturbed operating point.

The tables are valid around the operating point where they were measured. A large activation moves the network away from it, and the error of the linear prediction grows with the size of the activation. This is why the optimisation target keeps a margin below the limits, and why [verification](../how-it-works/verification-and-corrective-market.md) repeats the power flow after the market and, when the corrective market is enabled, measures new tables at the post-dispatch point.
