# Limits and assumptions

This page lists what enginIITe leaves out on purpose and the approximations built into it. Read this page before comparing results with a real market.

## Not modelled

| Topic | What the platform does |
|---|---|
| Transmission operator | Only the distribution operator's local market exists. There is no transmission layer. |
| Coordination between markets | Providers are assumed to be free. A provider activated here could also be committed elsewhere, and that conflict is not modelled. |
| Prequalification | The capabilities in the provider tables are taken as true. Nothing checks that a provider can deliver what it bids. |
| Baselining | The profile you supply is the baseline. There is no method to establish what the provider would have done without the market. |
| Uncertainty | The problem is deterministic. Profiles are known, with no scenarios or robust formulation. |
| Price formation | The market minimises the cost of the bids. It does not compute marginal prices or locational prices. |

## Approximations

**The network is linearised.** The sensitivities are valid near the operating point at which they were measured. For small activations the error is small, and it grows with large ones. The tolerance margins in the configuration exist to absorb it. The check in stage 4 shows how much error is left, and a corrective market can remove part of it.

**Sensitivities belong to an hour.** They are measured at the operating point of one hour and used only for that hour. When profiles or the network change, they must be recomputed.

**Voltage is limited only where it is watched.** The optimisation constrains the voltage at the watched buses. A new problem at any other bus can only be seen in the check after the market. A corrective market adds the buses and branches that the check found outside the limits to what it watches. Setting `full_network` watches every bus from the start, at a higher computing cost.

**Blocks of hours are independent.** When the hours are split into blocks, the state of a battery or of the temperature of a building restarts at the beginning of each block. Choose a block length that covers the period over which these resources matter.

**Energy limits depend on a setting.** A battery has an energy limit only when intertemporal constraints are on. With them off it has power limits and nothing else.

**The check after the market corrects only as much as the configuration allows.** If the exact power flow shows a remaining problem, the platform runs at most `max_corrective_market_running` corrective markets, and none when the key is missing. A corrective market corrects the linearisation error, and it can only use the capacity that the providers have left, so a lack of capacity still leaves violations. See [Verification and the corrective market](verification-and-corrective-market.md).

## Unconnected parts

- The **aggregator** model, which would present several providers as one, exists in the code but is never run. Leave the aggregator column of the provider tables empty.
- A few configuration keys are read and have no effect, and some appear in examples and are never read. They are marked in [Configuration](../reference/configuration.md).

## Known defects

Some indicators give wrong values in specific situations, for example the average cost per direction for a battery, or the voltage hosting capacity. Treat those figures with care until they are fixed.
