# Frequently asked questions

Short answers to the questions that come up most, with a link to the page that explains each one in full. For error messages and fixes see [Common problems](common-problems.md).

## Scope

### What is enginIITe for?

It simulates how a distribution system operator buys flexibility from local providers to solve voltage and congestion problems at the lowest cost, and it checks the result against an exact power flow. See [Four stages](../how-it-works/four-stages.md).

### What does it not do?

It has no transmission layer, no bid forwarding between markets, no prequalification or baselining of providers and no uncertainty. See [Limits and assumptions](../how-it-works/limits-and-assumptions.md).

### Can I use it with my own network?

Yes. Create a workspace with the same layout as the examples and point `network.net_folder` of a configuration file at your case folder. Check the files before running with the [input validator](check-your-inputs.md). The format of every file is in [Input files](../reference/input-files.md).

## Installation and running

### Do I need Gurobi?

Yes. The market model uses features specific to Gurobi, such as absolute value constraints and non-convex quadratic constraints, and no other solver is supported. The licence that comes with `gurobipy` solves only small models, so the examples need a full or academic licence. See [Install enginIITe](../tutorial/installation.md).

### Which versions of Python and Gurobi are supported?

Python 3.9 to 3.11, and Gurobi 11 and 12. The conda environment pins the versions of the reference results, and `pip install .` takes the newest versions that `pyproject.toml` allows.

### How long does a run take?

The CIGRE example takes about four minutes on a laptop, and the SB72 example about twenty. The time grows with the number of scenarios, providers and studied hours, and with the corrective rounds. See [Configuration](../reference/configuration.md) for how the number of solves follows from the settings.

### Where do the results go?

To `data_out/` of the workspace, or to the folder given with `--output`. See [Output files](../reference/output-files.md).

## Modelling

### Why does the market use sensitivities and not a full AC optimal power flow?

An AC optimal power flow is non-convex and expensive. The sensitivities, measured with the exact power flow, turn the network limits into linear constraints and keep the market tractable and always feasible. The price is a linearisation error, which the margins and the verification address. See [Sensitivity analysis model](../model/sensitivity-analysis.md).

### Is the price paid the marginal price?

No. The optimisation minimises the sum of bid price times activation, and each activated unit is paid its own bid price, as pay-as-bid. See [Market optimization model](../model/market-optimization.md).

### What are the tags `ProductTAG`, `VLTAG` and `FspTAG`?

They define the scenarios. A product is the power that is traded, active, reactive or both, and is set by the provider tables you give for it. A voltage tag selects a voltage band, and a provider tag scales the activation shares of the provider table. Each combination runs as a market of its own. See [Configuration](../reference/configuration.md).

### What do the tolerances do?

The detection tolerance decides what counts as a problem. The optimisation tolerance is an extra margin that the market keeps inside the limit, so that the linearisation error does not leave a residual violation. Both are percentages of the limit. See [Problem detection model](../model/problem-detection.md).

### What is `BetaCost`?

It is the penalty on the slack variables that keep the market feasible, in EUR per MWh. It acts as the value of the flexibility that could not be supplied. The same value is used for voltage and congestion.

### Does the market clear all hours together?

It depends on the settings. With intertemporal constraints, the studied hours are solved in blocks of `consecutive_hours`, and nothing links one block to the next. With independent snapshots, each hour is a market of its own. See [Four stages](../how-it-works/four-stages.md) and [Verification and corrective market](../how-it-works/verification-and-corrective-market.md).

## Results

### Why is a problem still there after the market?

There are four usual reasons.

- The providers did not have enough capacity. The slack variables then take the rest, and their penalty shows in the cost.
- The linearisation error left a residual. A corrective market can reduce it, and it runs only if `max_corrective_market_running` is positive.
- The problem is at a bus or element that the market did not watch. Setting `full_network` watches everything from the start.
- The margins are too small for the size of the activation.

See [Verification and corrective market](../how-it-works/verification-and-corrective-market.md).

### Why does the total cost differ from the objective value?

For a run without corrective rounds they should agree, and a difference signals a problem. When corrective rounds run, each round has its own objective, and the cost of the sequence is the final net settlement, which pays each provider only for its final position. See [Verification and indicators model](../model/verification-and-indicators.md).

### Why do the results not change after I edit my inputs?

Saved sensitivity tables are reused, and their names do not record the network, the profiles or the providers. Change the `simulation_tag`, delete `market_inputs/` of the case, or set `force_HVM` and `force_HCM` to `true`. See [Common problems](common-problems.md).

### Can I trust every indicator?

Most of them, but a few give wrong values in specific situations, for example the voltage hosting capacity and the average cost per direction of a battery. They are listed in [Limits and assumptions](../how-it-works/limits-and-assumptions.md).

### Will I get exactly the reference results?

The examples ship the values of a correct run. Costs agree across the supported versions of the dependencies, apart from numerical noise in variables that have several equivalent optimal values, such as the reactive power of a generator. To reproduce a result to the last digit, use the conda environment.
