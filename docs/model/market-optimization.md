# Market optimization model

This page writes down the optimisation problem that stage 3 solves, in the same form in which the code builds it. It is meant for readers who want to check the formulation, extend it or compare it with other market designs. For the overview see [Four stages](../how-it-works/four-stages.md).

The model is built once for each block of studied hours with Gurobi. It has three parts. A set of network constraints that use the sensitivities of stage 2, a set of resource constraints for each provider type, and an objective that adds the bid cost of the activations and a penalty for the problems that cannot be solved.

## Notation

| Symbol | Meaning |
|---|---|
| $t \in \mathcal{T}$ | Studied hours of the block. Blocks are cut by position, `consecutive_hours` hours at a time |
| $f \in \mathcal{F}_k$ | Providers of type $k$ ($k$ is A load, B generator, C battery) |
| $\ell \in \mathcal{L}$ | Monitored lines and transformers |
| $b \in \mathcal{B}$ | Pilot buses, the buses whose voltage is constrained |
| $\Delta W_{f,t}$, $\Delta R_{f,t}$ | Change of active and reactive power of provider $f$ with respect to its baseline |
| $\Delta W^{\uparrow}, \Delta W^{\downarrow}, \Delta R^{\uparrow}, \Delta R^{\downarrow}$ | Non-negative upward and downward parts of each change |
| $\alpha_{b,t}$, $\beta_{\ell,t}$ | Voltage and congestion slack variables |

Every provider variable is a change with respect to the baseline schedule, so a provider that is not activated has $\Delta W = \Delta R = 0$. The resulting power of the provider is the baseline plus the change.

## Decision variables

For each provider and hour the model has the changes $\Delta W$ and $\Delta R$, the resulting powers $W$ and $R$, and the split of each change into an upward and a downward part.

$$
\Delta W = \Delta W^{\uparrow} - \Delta W^{\downarrow}, \qquad
\Delta R = \Delta R^{\uparrow} - \Delta R^{\downarrow}, \qquad
\Delta W^{\uparrow}, \Delta W^{\downarrow}, \Delta R^{\uparrow}, \Delta R^{\downarrow} \ge 0
$$

Inside the market, powers use the generation convention, so a load is negative. The result workbook converts the variables of loads back to the load convention, where consumption is positive. Upward means that the provider consumes less or injects more.

For the network the model adds the voltage $V_{b,t}$ predicted after the market on every pilot bus, the voltage slack $\alpha_{b,t}$, its normalised version $\alpha'_{b,t}$ and the congestion slack $\beta_{\ell,t}$. The slacks are free in sign and are priced by their absolute value, which Gurobi receives as an absolute value constraint on a companion variable.

## Network constraints

Both families of constraints replace the AC power flow by a linear prediction built from the sensitivity tables of stage 2. How the tables are obtained is explained in [Four stages](../how-it-works/four-stages.md).

### Congestion management

Let $S^{0}_{\ell,t}$ be the apparent power of element $\ell$ before the market, $S^{\max}_{\ell}$ its rating and $\delta_{\ell}$ the margin kept below the rating, $\delta_{\ell} = S^{\max}_{\ell}\,(tol_i + tol_{i,opt})/100$. The sensitivity of the apparent power to each provider is $K^{W}_{f,\ell,t}$ for active power and $K^{R}_{f,\ell,t}$ for reactive power. The relief obtained from the activations is

$$
k_{\ell,t} = \sum_{k}\sum_{f \in \mathcal{F}_k} \left( K^{W}_{f,\ell,t}\,\Delta W_{f,t} + K^{R}_{f,\ell,t}\,\Delta R_{f,t} \right).
$$

The tables hold the change of apparent power per unit of provider power. They are multiplied by $-1$ when the market solves congestion (`cm_factor`), so that $k$ is positive when the activation reduces the loading. The first constraint keeps every monitored element below its optimisation target.

$$
S^{0}_{\ell,t} - k_{\ell,t} - \beta_{\ell,t} \le S^{\max}_{\ell} - \delta_{\ell}
\qquad \forall \ell, t \qquad \text{(C08a)}
$$

For elements that are congested in an hour that the market studies, a second constraint uses the need $N_{\ell,t}$, the excess of the loading over the detection limit expressed in MVA.

$$
N_{\ell,t} - k_{\ell,t} - \beta_{\ell,t} \le 0 \qquad \text{(C08b)}
$$

Since $\delta_{\ell} \ge 0$ and the need is measured from the detection limit, C08a is the stricter of the two and C08b is redundant in practice. When the hours are studied as independent scenarios, each scenario constrains only the elements it monitors.

### Voltage control

Let $V^{0}_{b,t}$ be the voltage of pilot bus $b$ before the market and $H^{W}_{f,b,t}$, $H^{R}_{f,b,t}$ the voltage sensitivities to the power of provider $f$. The voltage change produced by the activations is

$$
k^{V}_{b,t} = \sum_{k}\sum_{f \in \mathcal{F}_k} \left( H^{W}_{f,b,t}\,\Delta W_{f,t} + H^{R}_{f,b,t}\,\Delta R_{f,t} \right).
$$

The predicted voltage $V_{b,t}$ is tied to it with one of three equations, chosen by the state of the bus before the market, with $\underline V$ and $\overline V$ the detection limits.

$$
\begin{aligned}
V^{0}_{b,t} > \overline V &\;\Rightarrow\; V_{b,t} \ge V^{0}_{b,t} + \alpha_{b,t} + k^{V}_{b,t} \\
V^{0}_{b,t} < \underline V &\;\Rightarrow\; V_{b,t} \le V^{0}_{b,t} + \alpha_{b,t} + k^{V}_{b,t} \\
\text{otherwise} &\;\Rightarrow\; V_{b,t} = V^{0}_{b,t} + \alpha_{b,t} + k^{V}_{b,t}
\end{aligned}
\qquad \text{(C01)}
$$

The predicted voltage must stay inside the optimisation band, which is stricter than the detection band by the margin $tol_{v,opt}$.

$$
\underline V^{opt} \le V_{b,t} \le \overline V^{opt} \qquad \text{(C02)}
$$

An over-voltage bus is therefore bounded from below only through the band, and the inequality in C01 lets the model lower the voltage freely. The same holds the other way round for under-voltage buses. A bus inside the band keeps the equality, so both limits bind.

The slack is reported in per unit. For the objective it is converted to an equivalent power with the self sensitivity of the bus, $H^{W}_{b,b,t}$, which is the voltage response of the pilot bus to its own active power.

$$
\alpha'_{b,t} = \frac{\alpha_{b,t}}{H^{W}_{b,b,t}} \qquad \text{(C-alpha-primo)}
$$

When the self sensitivity is missing, not finite or smaller than $10^{-9}$ in magnitude, the model uses $\alpha'_{b,t} = \alpha_{b,t}$ and prints a warning.

## Objective

The model minimises the total cost of the activations plus the penalty for the problems that remain.

$$
\min \;
\underbrace{\sum_{t}\sum_{\ell} c^{\beta}\,|\beta_{\ell,t}|}_{\text{congestion, if CM}}
+ \underbrace{\sum_{t}\sum_{b} c^{\alpha}\,|\alpha'_{b,t}|}_{\text{voltage, if VC}}
+ \sum_{k}\sum_{f \in \mathcal{F}_k}\sum_{t}
\left( p^{W\uparrow}_{f,t}\,\Delta W^{\uparrow}_{f,t} + p^{W\downarrow}_{f,t}\,\Delta W^{\downarrow}_{f,t}
+ p^{R\uparrow}_{f,t}\,\Delta R^{\uparrow}_{f,t} + p^{R\downarrow}_{f,t}\,\Delta R^{\downarrow}_{f,t} \right)
$$

The four prices $p$ are the bid prices of each provider and are constant over the hours. Both penalties $c^{\alpha}$ and $c^{\beta}$ take the value of the configuration key `BetaCost`, the value of lost load in EUR per MWh. A provider therefore competes with the penalty, and an activation that costs more than leaving the problem unsolved is not chosen. The objective has no time step factor, because the time step is one hour.

The optimiser only minimises the sum of price times activation. The pay-as-bid rule appears when the results are settled in the indicators, where each activated unit is paid its own bid price.

For batteries the upward and downward activations are further split by direction of the baseline (injection and absorption), and each part has its own price column. The code pairs variables and price tables by position and stops with an error if the counts differ, so a misnamed price table cannot silently change the objective.

## Resource models

Every provider type adds its own variables and constraints in the same interface. The shared structure is the one of the load, described next. The other types add the elements that make them different.

### Type A, flexible load

With baseline $W^{0}$, $R^{0}$ (generation convention) the resulting powers are

$$
W_{f,t} = W^{0}_{f,t} + \Delta W_{f,t}, \qquad R_{f,t} = R^{0}_{f,t} + \Delta R_{f,t}.
$$

The resulting active power stays between the limits $W^{\min}_{f,t}$ and $W^{\max}_{f,t}$ written in the provider file, which come from the bid shares and the baseline. The reactive power follows a fixed power factor, equal to the one of the baseline, with $\rho_{f,t} = R^{0}_{f,t} / W^{0}_{f,t}$.

$$
\Delta R_{f,t} = \rho_{f,t}\,\Delta W_{f,t}, \qquad
\Delta R^{\uparrow}_{f,t} \le |\rho_{f,t}|\,\overline{\Delta W}^{\uparrow}_{f,t}, \qquad
\Delta R^{\downarrow}_{f,t} \le |\rho_{f,t}|\,\overline{\Delta W}^{\downarrow}_{f,t}
$$

where $\overline{\Delta W}^{\uparrow}$ and $\overline{\Delta W}^{\downarrow}$ are the upward and downward capacities of the file. With the capability curve switched on, which is always the case today, the apparent power is limited by the rating $S_f$ of the provider.

$$
W_{f,t}^{2} + R_{f,t}^{2} = q_{f,t}, \qquad 0 \le q_{f,t} \le S_f^{2}.
$$

This is a quadratic equality, so the problem is non-convex and the solver is always run with `NonConvex=2`. The reactive power of a load is not an independent flexibility in the current code. The fixed power factor constraint overrides any reactive share written in the provider table.

### Type B, generator

The structure is the one of the load, with two differences. The resulting power is non-negative and has no fixed power factor. A variable ratio $\theta_{f,t}$ links the powers through a bilinear constraint, and its magnitude is bounded by the power factor limits.

$$
R_{f,t} = \theta_{f,t}\,W_{f,t}, \qquad \tan\varphi^{\min} \le |\theta_{f,t}| \le \tan\varphi^{\max}.
$$

The power factor limits are fixed in the code, with $\cos\varphi \in [0.2, 1]$. The generator has no binary variables and no link between hours, so alone it gives a continuous non-convex problem.

### Type C, battery

The battery adds an injection and an absorption part of the power, selected by binary variables, and an energy balance.

$$
W_{f,t} = W^{inj}_{f,t}\,b^{1}_{f,t} + W^{ads}_{f,t}\,b^{2}_{f,t}, \qquad b^{1}_{f,t} + b^{2}_{f,t} = 1.
$$

$$
E_{f,t} = E_{f,t-1} + \left( -W^{ads}_{f,t}\,\eta^{ads}\,b^{2}_{f,t} - \frac{W^{inj}_{f,t}}{\eta^{inj}}\,b^{1}_{f,t} - |R_{f,t}|\,(1-\eta^{q}) \right)\Delta t,
\qquad E^{\min}_f \le E_{f,t} \le E^{\max}_f
$$

The first hour of a block starts from the initial energy of the provider table. The efficiencies are fixed at 0.99. The energy constraints exist only when `intertemp_cons` is true. Without it the battery has power limits and no energy limit. If a provider table makes the lower and upper power limits equal, the active (respectively reactive) activation is forced to zero, which is how the products P and Q act on batteries.

## Solver settings

| Setting | Value |
|---|---|
| `NonConvex` | 2, always |
| `MIPFocus` | 2 |
| `Method` | 5 |
| `MIPGap` | $10^{-5}$, and $10^{-6}$ when only voltage is controlled |

The status of the solution is checked after each block. An unbounded, infeasible or numerically unstable model stops the run with an error, and an infeasible one first prints its irreducible inconsistent subsystem.

## What the formulation implies

- The network is represented by one linear prediction around the operating point of the hour. Large activations move the real system away from it, and this is why stage 4 checks the result with an exact power flow.
- The slacks keep the model feasible. A problem that no provider can solve shows up as a non-zero slack and its penalty, not as an infeasible model.
- Blocks are solved one after another and nothing links them. A battery restarts from its initial state in every block.
- Voltage limits are enforced on pilot buses only. A violation at any other bus can be seen only after the market.
