# SB72 example

A medium-voltage distribution network with a set of twelve operating snapshots and one set of flexibility service providers.

## What it contains

- One network, twelve snapshots and one profile set, described in [the input package notes](data_in/SB72/README_SB72_v3.md).
- The flexibility service providers, in `data_in/SB72/fsp_files/`. They are 74 loads (A), 73 generators (B) and 6 batteries (C).

The configuration `config_SB72.yaml` runs three scenarios, one product (`PQ`), one voltage band (`VL01`) and three provider capacity steps (`F01`, `F02`, `F03`). The twelve snapshots are independent cases, not consecutive hours, and the batteries run without intertemporal limits.

## Run it

From the root of the repository.

```
enginiite run examples/sb72/config/config_SB72.yaml
```

It takes about 20 minutes and needs a Gurobi licence. Results are written to `examples/sb72/data_out/SB72_CMVC_SK01_T1/`.

The simulation tag of the configuration is short on purpose, because the tag is repeated in many folder and file names and Windows limits a full path to 260 characters. On Windows, if the path of your repository is long, send the results to a short folder with `--output`, for instance `--output C:\r`.

## Data source and licence

The network and the profiles of this example come from a public benchmark data set, SimBench. [Pending: the exact licence of the data and the attribution it requires.]

## What a correct run gives

`expected/sb72.json` has the figures that the regression test checks. The settlement cost of the three scenarios, in EUR, is the following.

| F01 | F02 | F03 |
|---|---|---|
| 1,127 | 1,571 | 1,427 |

The settlement cost is the active plus the reactive power cost of the sheet `Overall_Results` in the KPI workbook.
