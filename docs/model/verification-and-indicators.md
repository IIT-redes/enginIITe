# Verification and indicators model

This page describes the technical side of stage 4. The first part is the verification of the market result with the exact power flow and the corrective market that follows when the result is not secure. The second part defines the indicators that summarise a run. For the narrative explanation, with worked examples, see [Verification and corrective market](../how-it-works/verification-and-corrective-market.md).

## Why verify

The market solves a linear approximation of the network. Its constraints hold exactly for the approximation, and only approximately for the real network. Stage 4 closes the loop by applying the dispatch to the network and solving the exact AC power flow again.

## Verification

### Applying the dispatch

For each provider and studied hour, the resulting power of the market, $W_{f,t}$ and $R_{f,t}$ in the native convention of the network element, replaces the baseline profile of that element. The time series is then solved again for the studied hours only, with the supply voltage of the hour.

### Security criterion

The post-market state is judged against the detection limits of stage 1, not against the optimisation target. A studied hour is secure when no monitored quantity is outside them.

$$
V_{b,t} \in \left[\underline V^{det}, \overline V^{det}\right] \quad \forall b, \qquad
L_{\ell,t} \le L^{det} \quad \forall \ell .
$$

The check covers every bus and every line and transformer of the network, not only the pilot buses and the elements that the market constrained. A violation at an element that the market did not see is therefore detected. The optimisation target is stricter than the detection limit by design, so a result that sits inside the target has margin left.

### Decision

The number of corrective rounds is bounded by `max_corrective_market_running`. A value of 0, also the default when the key is missing, makes verification report-only. The result is checked and the violations are recorded, but nothing is cleared again.

With a positive value, the platform repeats the following while violations remain and rounds are left.

1. Keep the dispatch accepted so far.
2. Rebase the providers at that dispatch.
3. Measure new sensitivities at the post-dispatch operating point.
4. Add the elements and buses that the exact power flow showed to be violated.
5. Clear a corrective market for the remaining problem.
6. Apply the new dispatch and verify again.

How the studied hours are treated depends on the scenario mode.

| Mode | Unit of the decision | Hours cleared in a corrective round |
|---|---|---|
| Consecutive time steps, `simulation_window_as_timesteps` true | The whole case | All studied hours, if any is insecure |
| Independent snapshots, `simulation_window_as_timesteps` false | Each hour | Only the hours that are still insecure. The others keep their last clearing |

Independent snapshots require `consecutive_hours` equal to 1 and `intertemp_cons` false. Each snapshot is then a market of its own, and clears the same alone as in a batch.

Each hour of each round receives one of these decisions, saved in the validation table by snapshot.

| Decision | Meaning |
|---|---|
| `corrective_iteration_next` | Insecure and rounds remain, so it is cleared again |
| `stop_secure` | Secure after this round |
| `stop_corrective_limit` | Insecure, but no round is left |
| `kept_earlier_clearing` | Not cleared in this round, because it was already secure |

## Corrective market

### Rebase of the providers

The corrective market does not start again from the original baseline. The first clearing is preserved, and every provider is re-expressed around the point that clearing reached. For a provider $f$ in hour $t$ the baseline powers of the corrective round become the accepted powers of the previous one.

$$
W^{0,(k+1)}_{f,t} = W^{(k)}_{f,t}, \qquad R^{0,(k+1)}_{f,t} = R^{(k)}_{f,t},
$$

where $k = 0$ is the main market. The sign is flipped for storage, because its workbook reports in the opposite convention from its input sheets. The absolute technical limits of the provider do not move, and neither does the initial state of charge of a battery. The corrective variables $\Delta W^{(k+1)}$ and $\Delta R^{(k+1)}$ are increments from the new baseline. Their feasible range is the capacity that remains between the accepted point and the absolute limits.

$$
W^{\min}_{f,t} \le W^{0,(k+1)}_{f,t} + \Delta W^{(k+1)}_{f,t} \le W^{\max}_{f,t}.
$$

The remaining capacity of every provider and hour is saved with the corrective inputs.

### New operating point

The network of the corrective round is the one with the accepted dispatch applied. Three things are rebuilt from the exact power flow of the previous round.

- The apparent power before the market, $S^{0}_{\ell,t}$, which is the loading of the AC result converted to MVA. The need $N_{\ell,t}$ is the excess over the detection limit, as in stage 1, so the physical threshold is not relaxed.
- The pre-market voltages of the pilot buses, $V^{0}_{b,t}$, which are the voltages of the AC result.
- The sensitivity tables, measured by finite differences at this operating point, as in [Sensitivity analysis model](sensitivity-analysis.md), but in a folder of their own and always recomputed. The cache of the main market is never overwritten.

The margin $\delta_\ell$ and the optimisation voltage band do not change between rounds.

### Growing the monitored set

An element or bus that the exact power flow shows to be violated is added to the monitored set, with its sensitivities, and stays in it in every later round. Elements that were already monitored remain protected. The restriction of pilot buses to a voltage level, `only_pilot_busMV`, applies to the initial set only. It does not hide a new violation at another level.

With independent snapshots the same growth is made for each snapshot separately. A snapshot adds what its own post-clearing result violates, so that no snapshot is held to the limits of another.

### Problem solved

The corrective market has the structure of the [market optimization model](market-optimization.md), with the rebased providers and the rebuilt coefficients. Its objective prices only its own increments, at the bid prices of the providers. The cost of a round is therefore the cost of its correction of the residual. The slack penalties are charged for the residual that remains in that round.

## Settlement of the sequence

A provider can be asked to go up in the main market and down in a corrective round. Paying each round separately would pay for both. The platform settles the whole sequence as a single market, on the final net position of each provider, hour and product.

Let $a^{(0)}$ be the activation of the main market and $a^{(1)}, \dots, a^{(K)}$ the increments of the corrective rounds, all signed with upward positive.

$$
a^{net} = a^{(0)} + \sum_{k=1}^{K} a^{(k)}, \qquad
\text{cost} =
\begin{cases}
a^{net}\, p^{\uparrow} & a^{net} > 0 \\
|a^{net}|\, p^{\downarrow} & a^{net} < 0 \\
0 & a^{net} = 0
\end{cases}
$$

The net position is paid at the price of its final direction. Some examples follow.

| Main | Corrective | Net | Paid |
|---|---|---|---|
| +2.0 MW | -0.5 MW | +1.5 MW | 1.5 MW at the upward price |
| +2.0 MW | -3.0 MW | -1.0 MW | 1.0 MW at the downward price |
| +2.0 MW | -2.0 MW | 0 | Nothing |

Next to the settlement, the platform keeps diagnostics of the sequence.

$$
\text{gross} = \sum_{k=0}^{K} |a^{(k)}|, \qquad
\text{reversed} = \frac{\text{gross} - |a^{net}|}{2}.
$$

The reversed activation is what one round bought and a later round undid. It measures how much of a corrective market is new procurement and how much is correction of the previous round. The settlement is written to a table row by row, with a table of consistency checks. The checks include that the final dispatch reproduces the original baseline point once the net activation is subtracted.

## Indicators

The indicators compare the baseline, before the market, with the result after it. They are evaluated once, after all scenarios. Voltage and congestion are judged against the standard limits, the band of the voltage tag and 100 % loading, and the tolerance bands are reported next to them as extra thresholds.

### Avoided congestion

A cell is an element and an hour. It is congested when its loading is above the threshold. Pre and post tables are aligned cell by cell, and the hours that the market did not simulate keep their pre-market state, so that they never appear as resolved. Each congested cell before the market is classified.

| Class | Before | After |
|---|---|---|
| Resolved | congested | not congested |
| Persistent | congested | congested |
| New | not congested | congested |

$$
\text{AvoidedCongestion} = \frac{n^{pre} - n^{post}}{n^{pre}} \times 100\,\%, \qquad
n^{pre} = n_{res} + n_{per}, \quad n^{post} = n_{per} + n_{new},
$$

with the value 0 when $n^{pre} = 0$. Lines, two winding transformers and three winding transformers are counted together, and each also has its own counts.

### Avoided voltage violations

A bus-hour violates when the voltage is below the lower limit, with a voltage of 0.1 per unit or less treated as not simulated, or above the upper limit. All buses and all hours of the tables are counted.

$$
\text{AvoidedViolations} = \frac{n^{pre} - n^{post}}{n^{pre}} \times 100\,\%.
$$

### Hosting capacity

The hosting capacity of a scenario is the smallest headroom among the components, in MVA, evaluated at the most loaded element of each kind.

$$
HC = \min\left(HC_{line},\, HC_{trafo},\, HC_{trafo3w}\right),
$$

$$
HC_{line} = \sqrt{3}\,\frac{L^{lim} - L_{\max}}{100}\,I^{\max}\,V ,
\qquad
HC_{trafo} = \frac{L^{lim} - L_{\max}}{100}\,S_n .
$$

The component of voltage is part of the definition, but it needs a table of the highest voltage that the platform does not fill. It is therefore infinite today, and the hosting capacity comes from lines and transformers. The increase is the difference between after and before.

$$
IHC = HC^{post} - HC^{pre}, \qquad pIHC = \frac{IHC}{|HC^{pre}|} \times 100\,\% .
$$

### Cost of flexibility

Every activation is paid at its own bid price, one price per direction and product.

$$
C^{W} = \sum_{f,t} \left( p^{W\uparrow}_{f}\,\Delta W^{\uparrow}_{f,t} + p^{W\downarrow}_{f}\,\Delta W^{\downarrow}_{f,t} \right),
$$

and the same for reactive power. The penalty of the problems that remain is added, with the slacks in the units of the objective and the value of lost load as price.

$$
\text{TotalCost} = C^{W} + C^{R} + c^{\alpha} \sum |\alpha'| + c^{\beta} \sum |\beta| .
$$

For a run without corrective rounds the total cost equals the objective value of the market, so the difference between them checks the run. When corrective rounds ran, the settlement table gives the cost of the whole sequence.

### Volume of flexibility

The offered volume is the sum, over the bound sheets of the provider files, of the distance between each limit and the baseline, in both directions. The cleared volume is the sum of the absolute activation. The share of the offered volume that was cleared is reported with them.

## Known limits of the indicators

Some indicators give values that need care in specific situations. The voltage indicators compare the studied hours after the market with all hours before it. The average cost per direction can be wrong for providers without reactive activation. The cleared volume counts one direction only. These cases are listed in [Limits and assumptions](../how-it-works/limits-and-assumptions.md).
