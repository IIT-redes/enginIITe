# Glossary

The words that the platform and its documentation use, with one line each.

## Network and market

| Term | Meaning |
|---|---|
| Distribution system operator (DSO) | The company that runs the distribution network and procures flexibility to keep it secure. |
| Flexibility service provider (FSP) | A resource that offers to change its power when the DSO asks, which is a load, a generator or a battery. |
| Flexibility | A change of active power (MW) or reactive power (MVAr) of an FSP compared with what it would do without the market. |
| Upward flexibility | More power injected into the network. A generator produces more, a load consumes less and a battery discharges more. |
| Downward flexibility | Less power injected into the network. A generator produces less, a load consumes more and a battery charges more. |
| Market product | What is traded, which is `P` (active power), `Q` (reactive power) or `PQ` (both). |
| Bid depth | How much of its flexibility each FSP offers. The tags `F01`, `F02` and `F03` multiply the fractions of the FSP file by 1, 2 and 3. |
| Bid | The volume and the price at which an FSP offers flexibility in one direction. |
| Baseline | The power of each element before the market, taken from the profiles. |

## Study settings and results

| Term | Meaning |
|---|---|
| Operational limits | The allowed band of every bus voltage and the maximum loading of every line and transformer. |
| Violation | A bus voltage or a branch loading outside the operational limits. |
| Optimisation target | A limit slightly stricter than the operational limit, to which the market clears, so that the linearisation error does not leave residual violations. |
| Not served flexibility | The part of a flexibility need that no bid can cover. It is priced with `BetaCost`. |
| Sensitivities | Tables that give how much each FSP changes each bus voltage (`HVM`) and each branch flow (`HCM`). |
| Pilot bus | A bus whose voltage the market constrains. |
| Verification | A check of the market result with the exact AC power flow, to see that the network is really secure. |
| Corrective market | A new market clearing for the violations that remain after the verification. |
| Time step and scenario | A row of the profiles. It is an hour of one day (`h0`, `h1`, ...) or an independent scenario (`S1`, `S2`, ...). |
| Run and scenario | One run of `enginiite run` with one configuration file. It makes one scenario for every combination of product, voltage band and bid depth. |
| KPI | Key performance indicator, such as the share of violations solved, the cost of the flexibility or the increase of hosting capacity. |
| Hosting capacity | The extra power that the network can take before a limit is reached. |
| VOLL | Value of lost load, the price that `BetaCost` normally takes. |

## Tags

| Tag | Meaning |
|---|---|
| `ModelTAG` | What the market solves, which is `CM` (congestion), `VC` (voltage) or `CMVC` (both). |
| `ProductTAG` | The market products to run. |
| `VLTAG` | The voltage band, from `VL01` (0.95 to 1.05 p.u.) to `VL06` (0.98 to 1.02 p.u.). |
| `FspTAG` | The bid depths to run. |
| `StorageTag` | The size multiplier of the batteries. |
| `simulation_tag` | The short name of a run, which ends the name of every result folder. |

For the value of each tag, see the [configuration reference](configuration.md).
