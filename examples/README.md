# Examples

Two ready-to-run cases, each in its own folder. Both are complete workspaces.

| Folder | Network | Configurations | Time on a laptop |
|---|---|---|---|
| [`cigre/`](cigre/README.md) | CIGRE medium-voltage benchmark, 15 buses, 33 flexibility providers | `config_CIGRE.yaml` | about 4 minutes |
| [`sb72/`](sb72/README.md) | Medium-voltage distribution network with twelve operating snapshots, 153 flexibility providers | `config_SB72.yaml` | about 20 minutes |

Every run needs a Gurobi licence.

## Two ways to study a window

The two examples read the rows of `simulation_window` in different ways. CIGRE reads them as the hours of one day, and SB72 reads them as independent snapshots.

| | CIGRE | SB72 |
|---|---|---|
| What the window holds | One day, 24 consecutive hours | Twelve independent snapshots |
| `simulation_window` | `[0, 24]` | `[0, 12]` |
| `simulation_window_as_timesteps` | `True` | `False` |
| `consecutive_hours` | `24` | `1` |
| `intertemp_cons` | `False` as shipped, `True` is also valid | `False` |

Use consecutive hours when the hours belong to one scenario and what happens in one hour matters for the next, as with the charge of a battery. All hours are then solved together in blocks of `consecutive_hours`. Use independent snapshots when every row is a case of its own, and nothing links one to the next. Each snapshot is then a market of its own, so `consecutive_hours` must be `1` and `intertemp_cons` must be `False`.

The three keys work together. See [independent snapshots and consecutive hours](../docs/how-it-works/verification-and-corrective-market.md#independent-snapshots-and-consecutive-hours) for what changes in the verification, and [Change the study](../docs/howto/change-the-study.md) to switch from one mode to the other.

## Workspace

A run reads its inputs from, and writes its results to, one folder called the workspace.

```
<workspace>/
├── config/          scenario files (.yaml)
├── data_in/
│   └── <case>/
│       ├── network/     network table (.xlsx, pandapower format)
│       ├── profile/     load, generation and storage profiles
│       └── fsp_files/   tables of flexibility service providers
├── expected/        reference values of the shipped examples (optional)
└── data_out/        created by the runs, not versioned
```

To use your own case, create a workspace with the same layout and point `network.net_folder` of a configuration file at your case folder inside `data_in/`.

## Running an example

From the root of the repository, with the package installed.

```
enginiite run examples/cigre/config/config_CIGRE.yaml
```

The workspace is found from the path of the configuration file. Results go to the `data_out/` folder of that example. The folder name carries the simulation tag of the configuration, so runs with different tags do not overwrite each other.

Keep the repository in a short path on Windows. The tag is repeated in many folder and file names, and Windows limits a full path to 260 characters.

## Checking a run

`expected/` holds the cost figures a correct run must reproduce, per scenario. After a run, the regression test compares them.

```
python -m unittest discover -s tests/regression
```

Tests whose results are missing are skipped.

## Planned

One case is not shipped yet and would cover what these examples do not exercise, a battery with intertemporal limits, which needs `intertemp_cons: True`.
