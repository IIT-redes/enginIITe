# Four stages

enginIITe simulates a distribution system operator that buys flexibility from local providers to solve voltage and congestion problems at the lowest cost. Every run goes through the same four stages. Each stage feeds the next one, and the last one checks the results of the others. When that check finds violations, a corrective market can run before the indicators are final.

| Stage | Question it answers | Tool behind it |
|---|---|---|
| 1. Problem detection | Where and when does the network break its limits? | AC power flow |
| 2. Sensitivity analysis | What does a small change at each provider do to the network? | AC power flow, repeated |
| 3. Market optimization | Which providers should change their power, and by how much? | Mixed-integer optimisation |
| 4. Verification and KPIs | Did the chosen activations really solve the problems? | AC power flow, and indicators |
| Corrective market, only if needed | Can a second clearing remove the violations that remain? | Stages 2 and 3 again, then the check again |

## Inputs and results

| | What |
|---|---|
| Inputs | Network workbook, profiles of loads, generation and storage, provider tables, configuration file. See [Input files](../reference/input-files.md). |
| Results | Dispatch of each provider and hour, power flow after the market, indicator workbooks, interactive figures. See [Output files](../reference/output-files.md). |

## 1. Problem detection

The platform first runs an hourly AC power flow with the profiles of loads, generators and storage, and no market. This is the baseline. From the results it looks for two kinds of problem.

- **Voltage.** A bus has a problem when its voltage is outside the band of the chosen voltage level. A voltage exactly on the limit is compliant.
- **Congestion.** A line or transformer has a problem when its loading is above the detection limit, which is set a configurable margin below 100 %.

The margins are percentages of the limit, not offsets in per unit. The detection margin decides what counts as a problem. A second, stricter margin is the optimisation target, so that small errors in the later stages do not leave a residual violation. The details are in [Configuration](../reference/configuration.md).

The result of this stage is the list of hours to study, the buses that will be watched and, for each congested element, how much relief it needs.

## 2. Sensitivity analysis

The optimisation cannot run a power flow for every combination of activations, so it uses the response of the network to a change at each provider, measured in advance.

For each provider and each studied hour it adds a small virtual generator at the provider's bus, changes its active power by a small step, and runs the power flow again. It then divides the change in each watched voltage, or in each line and transformer loading, by the size of the step. The same is done for reactive power. These ratios are the **sensitivities**.

The method is finite differences. It builds no analytical Jacobian, so it works with any network the power flow can solve. It costs two extra power flows per provider and studied hour.

Sensitivity tables are saved and reused. A saved table is identified only by table kind, provider type, hour and simulation tag. After changing the network, the profiles or the providers under the same tag, set the recompute option in the configuration, otherwise the old tables are reused.

## 3. Market optimization

With the sensitivities, each network limit becomes a linear constraint on the changes in power of the providers. The platform then solves an optimisation problem for the studied hours.

- **Objective.** Minimise the sum of the bid price times the activation of every provider, plus a penalty on the part of each problem that could not be solved.
- **Constraints.** The limits of each resource, and the linearised network limits.
- **Slack variables.** One kind is added to the voltage constraints and another to the congestion constraints. They keep the problem feasible. Their penalty is the value of lost load, so an unsolved problem has an economic meaning.

Each provider type has its own model.

| Type | Resource | What its model adds |
|---|---|---|
| A | Flexible load | Reduce or increase consumption within limits, with a fixed power factor |
| B | Generator | Reduce or increase production, with a variable power factor |
| C | Battery | State of charge over time, charging and discharging modes |

Prices can differ for upward and downward changes and for active and reactive power. The product of a scenario, active, reactive or both, is set through the input tables of the providers, by allowing or forbidding each kind of change.

The hours are split into blocks of a configurable length, and each block is solved as a separate problem. Blocks keep each problem small. Nothing links one block to the next, so a battery starts every block from the state in its input table.

## 4. Verification and KPIs

The optimisation works with a linear model of the network, so its answer is only an approximation. The last stage applies the chosen activations to the profiles, runs the exact AC power flow again for the studied hours, and checks the result against the voltage and loading limits.

If the check finds violations and a corrective market is allowed, the platform runs it before the indicators are computed, as described below.

From the power flows before and after the market, the platform computes indicators.

- Voltage and congestion problems avoided.
- Hosting capacity before and after.
- Cost of the flexibility. Each activation is settled at the price of its own bid.
- Volume offered and volume cleared.

## Corrective market, only if needed

The corrective market is not a fixed stage. It runs only when the check of stage 4 finds violations and the configuration allows it. The number of corrective markets is set with `max_corrective_market_running`, and the examples of this repository set it to 1.

A corrective market repeats the work of stages 2 and 3.

1. It keeps the clearing of the snapshots that are already secure.
2. For the others, it measures the sensitivities again at the operating point that the dispatch left.
3. It clears again with the flexibility that the providers have left.
4. It applies the new dispatch and runs the check again.

The whole sequence is settled as one market. [Verification and the corrective market](verification-and-corrective-market.md) describes it.

When no corrective market is allowed, which is the default when `max_corrective_market_running` is missing, the check is reported and **not fed back** into the optimisation. A remaining problem then shows in the indicators. The remedies are a corrective market or a stricter optimisation target in the configuration.

## Code location

| Stage | Modules |
|---|---|
| 1 | `src/enginiite/network/run_network.py`, `src/enginiite/network/flex_eval.py` |
| 2 | `src/enginiite/network/sensitivity_factors.py` |
| 3 | `src/enginiite/market/run_flex_market.py` and the resource models in `src/enginiite/market/models/` |
| 4 | `src/enginiite/network/run_network.py`, `src/enginiite/network/ac_market_validation.py`, `src/enginiite/kpis/eval_kpis.py` |
| Corrective market | `src/enginiite/network/ac_market_validation.py` and `src/enginiite/workflow.py` |

The workflow (`src/enginiite/workflow.py`) calls them in this order. For what the platform leaves out, see [Limits and assumptions](limits-and-assumptions.md).
