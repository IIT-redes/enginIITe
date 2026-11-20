# Verification and the corrective market

The market works with a linear model of the network, so its dispatch is only an approximation. This page explains how the platform checks the dispatch against the exact power flow, and how it can run the market again when the check finds a violation. It expands stage 4 of [Four stages](four-stages.md).

## Sequence

For every scenario, the platform runs the same loop.

```text
main market  ->  apply the dispatch  ->  exact AC power flow  ->  secure?
                                                                  |
                                                    yes: stop     |     no: corrective market
                                                                  |        (while one is left)
                                          apply the dispatch  <---+--------------+
```

1. **Main market.** The market of stage 3 clears the studied hours.
2. **Verification.** The dispatch is applied to the profiles, and the exact AC power flow is solved for the studied hours.
3. **Verdict.** The result is secure when no bus is outside the voltage band and no line or transformer is above the loading limit.
4. **Corrective market.** If the result is not secure and a corrective market is left, the market is cleared again, as described below, and the loop goes back to the verification.
5. **End.** The loop ends when the result is secure, or when the number of corrective markets set in the configuration has been used.

The number of corrective markets is `max_corrective_market_running`. Its value is `0` when the key is missing, and then the platform only verifies. It reports the violations and corrects nothing, which is how the platform behaved before the corrective market existed. The shipped examples set it to `1`. The key `ac_validate_post_market` switches the verification off, and with it every corrective market. Both keys are described in [Configuration](../reference/configuration.md#verification-and-corrective-market).

## What secure means

The verdict uses the detection limits of the configuration, which are the standard limits moved inwards by the margins `tol_v` and `tol_i`.

| Limit | Used by | In the shipped examples |
|---|---|---|
| Standard limits, the voltage band of `VLTAG` and 100 % loading | The KPIs, as the physical limits. They also report the other two beside them. | 0.95 to 1.05 p.u. and 100 % |
| Detection limits, the standard limits with `tol_v` and `tol_i` | Stage 1, and the verdict of the verification | The same as the standard limits, because the margins are zero |
| Optimisation target, the detection limits with `tol_v_opt` and `tol_i_opt` | The market, as the aim it constrains the dispatch to | 0.9595 to 1.0395 p.u. and 97 % |

The optimisation target is the aim of the market, and it is not the criterion of the verdict. A result can miss the target and still be secure. The tutorial [Run the CIGRE example](../tutorial/first-run.md) shows a transformer that ends at 97.15 % and is secure.

## What a corrective market is

A corrective market is a new clearing of the same hours, built to remove what the verification found, and it differs from the main market in five ways.

- **It keeps the first clearing.** The dispatch of the main market is accepted. The corrective market adds to it.
- **Its baseline is the accepted dispatch.** The baseline power of every provider moves to the operating point that the main market produced. The absolute technical limits of the providers, and the initial state of charge of the batteries, stay as they were. The variables of the corrective market therefore represent additional flexibility, within the capacity that the providers have left.
- **Its sensitivities are new.** They are measured again, with the same finite differences as in stage 2, at the operating point that the dispatch left. This removes most of the linearisation error of the first clearing. The tables of iteration `k` are written to `market_inputs/<ac_validation_sensitivity_subfolder>/<simulation_tag>/iteration_kk/` and are copied to the folder of the stage. They are deleted and rebuilt at each run, and the tables of the main market are never overwritten.
- **It watches what the dispatch broke.** The lines, transformers and buses that the exact power flow found outside the limits are added to the constraints, with their sensitivities, so the corrective market can act on a problem that the main market did not watch.
- **It is priced on its own increment.** The solver objective of a corrective market is the cost of its own correction plus the penalty of what it still cannot resolve. The cost of the sequence is settled separately, as explained below.

## How the sequence is settled

The main market and the corrective markets are not separate products. They are one local market, cleared in stages, so each provider is settled once, on its final net position.

For every provider, hour and product, the final activation is the activation of the main market plus the increments of the corrective markets. Activations use one sign for every provider type, positive for upward flexibility. Only the final position is paid, at the bid price of its final direction.

| Main market | Corrective market | Final position | Paid |
|---|---|---|---|
| +2.0 MW | -0.5 MW | +1.5 MW | 1.5 MW at the upward price |
| +2.0 MW | -3.0 MW | -1.0 MW | 1.0 MW at the downward price |
| +2.0 MW | -2.0 MW | 0 MW | nothing |

Two consequences follow.

- A corrective market that undoes part of the main market does not charge twice. The volume that one round bought and a later round reversed is reported as reversed activation, and it is not paid.
- The slack variables are not added up. The penalty counts what the market could not clear, and every round penalises the same physical residual of the same hour, so the penalty of the latest round is the one that counts.

The file `FinalNetSettlement.csv` has the position and the cost of every provider and hour. `FinalNetSettlementChecks.csv` holds consistency checks of the settlement, in which every count of rows and every error must be zero. The sheet `SequentialCostBasis` of the market results reconciles the solver objective with the settlement. See [Output files](../reference/output-files.md#verification-and-corrective-market-files).

## Independent snapshots and consecutive hours

The rows of `simulation_window` are either consecutive time steps of one scenario, or independent snapshots studied together only for comparison. The key `simulation_window_as_timesteps` tells which.

| | Consecutive time steps | Independent snapshots |
|---|---|---|
| Value of `simulation_window_as_timesteps` | `true`, the default | `false` |
| Labels | `h0`, `h1`, ... | `S1`, `S2`, ... |
| Verdict | One for the whole case | One for each snapshot |
| What a corrective market clears | Every hour | Only the snapshots that are not secure |
| Snapshots that were secure | Not applicable | Keep their clearing |

Independent snapshots need `consecutive_hours: 1` and `intertemp_cons: false`, since nothing links one snapshot to the next. The mode of a run is recorded as `joint` or `independent` in `ACMarketValidationBySnapshot.csv`, which has one row per snapshot and iteration, with a `decision`.

| Decision | Meaning |
|---|---|
| `kept_earlier_clearing` | The snapshot was not cleared in this iteration, because it was already secure. |
| `corrective_iteration_next` | It is not secure and a corrective market comes next. With consecutive hours, every hour gets this decision while the case is not secure. |
| `stop_secure` | It was cleared in this iteration and is secure. |
| `stop_corrective_limit` | It is not secure and no corrective market is left. |

## What a corrective market can and cannot do

A corrective market corrects the linearisation error. The violations that remain after it reflect a lack of capacity, because it can only use what the providers have left. In the CIGRE example, the scenario `F01` is not secure after the main market, with six bus-hours below 0.95 p.u. A corrective market runs and leaves the same six violations, because there is nothing more to activate. In the SB72 example the corrective market changes the result in some snapshots. In the scenario `F03`, nine of the twelve snapshots are secure after the main market and ten are after the corrective one. See [Run independent snapshots on the SB72 network](../tutorial/sb72-snapshots.md).

## Code location

| Step | Module |
|---|---|
| The loop and its decisions | `src/enginiite/workflow.py` |
| Verification, corrective inputs, settlement and the stage folders | `src/enginiite/network/ac_market_validation.py` |
