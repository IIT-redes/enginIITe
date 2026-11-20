# CIGRE medium-voltage example

The CIGRE medium-voltage benchmark network with distributed energy resources, used to follow the four stages of the platform on a small case.

## What it contains

- A 20 kV network with two feeders and 15 buses, built from the standard CIGRE benchmark of pandapower.
- 33 flexibility service providers, 18 flexible loads (type A), 13 distributed generators (type B) and 2 batteries (type C).
- A 24-hour profile for every load, generator and battery, with the loads scaled by 1.2.
- Three scenarios, one product (`PQ`), one voltage band (`VL01`) and three provider capacity steps (`F01`, `F02`, `F03`).

The 24 rows of the window are consecutive hours of one day (`simulation_window_as_timesteps: True`, `consecutive_hours: 24`), solved together in one optimisation. The batteries run without intertemporal limits (`intertemp_cons: False`), so they have power limits only. With `intertemp_cons: True` they would also carry their charge from hour to hour, but that setting is not covered by the reference values of this example. The [SB72 example](../sb72/README.md) reads its window the other way, as independent snapshots.

## Run it

From the root of the repository.

```
enginiite run examples/cigre/config/config_CIGRE.yaml
```

It takes about 4 minutes and needs a Gurobi licence. Results are written to `examples/cigre/data_out/CIGRE_CMVC_SK01_L120/`.

## What to look at

- `KPI_results_CIGRE_CMVC_SK01_L120/CIGRE_CMVC_SK01_L120.xlsx`, sheet `Overall_Results`, with the objective, the activations and the cost of each scenario.
- One sub-folder per scenario, for instance `CIGRE_CMVC_PQ_VL01_F01_SK01_L120/`, with the market results and the sensitivity matrices.

## What a correct run gives

`expected/cigre.json` has the figures that the regression test checks. The objective of the first scenario is about 79,404 EUR, almost all of it the penalty on voltage violations that the offered flexibility cannot resolve. It falls as more flexibility is offered, to about 1,580 EUR in the second scenario and about 99 EUR in the third.

The tutorial [Run the CIGRE example](../../docs/tutorial/first-run.md) reads these results step by step, with the figures of the run. The output files are described in [output files](../../docs/reference/output-files.md).
