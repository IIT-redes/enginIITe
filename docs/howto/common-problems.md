# Common problems

This page lists the problems that users meet most often, with their cause and the way out. If yours is not here, check the inputs first with the [input validator](check-your-inputs.md).

## Run fails with `FileNotFoundError` on Windows

**Cause.** Windows rejects any path longer than 259 characters unless long paths are enabled. A run writes figures whose file names repeat the name of the scenario, and the longest paths of the shipped examples are about 150 characters below the results folder, with short tags. Added to the path of your repository and of the results folder, they can pass the limit. Linux and macOS do not have this limit.

**What the platform does.** At the start of a run it estimates the longest path that the run will write. If that path is over the limit, it tries to create a file of that length on your system and, when the system refuses it, prints a warning that names the estimated length and the ways out. The check stays silent on systems that accept long paths.

**Ways out.** Use one or more of these.

- Keep the repository in a short path, for example `C:\enginiite` on Windows.
- Use a short `simulation_tag` in the configuration file. The tag is repeated three times in the longest path.
- Send the results to a short folder with `--output`.

  ```bash
  enginiite run examples/cigre/config/config_CIGRE.yaml --output C:\r
  ```

- Enable long paths in Windows, following Microsoft's documentation for the setting `LongPathsEnabled`. It needs administrator rights.

The sensitivity tables are written under `data_in/<case>/market_inputs/` of the workspace, whatever `--output` says, so the repository path still matters for them, although their names are short.

## Gurobi says `Model too large for size-limited license`

**Cause.** No full licence was found, so Gurobi fell back to the licence that comes with `gurobipy`, which solves models of up to 2,000 variables. The examples have thousands.

**Way out.** Install a licence as described in [Install enginIITe](../tutorial/installation.md#install-a-gurobi-licence). If you already have one, check where Gurobi looks for it. It reads the file named by the environment variable `GRB_LICENSE_FILE` and then the file `gurobi.lic` in your home folder.

## Gurobi says `Unable to open Gurobi license file`

**Cause.** The environment variable `GRB_LICENSE_FILE` points to a file that does not exist.

**Way out.** Correct the path or remove the variable.

## Licence has expired

Academic licences are valid for one year. Gurobi prints the expiry date every time it starts, in a line that begins with `Academic license`, and warns in the days before. Request a new licence from the Gurobi academic programme.

## Results do not change after I edit the inputs

**Cause.** The sensitivity tables are saved in `data_in/<case>/market_inputs/` and reused by later runs. A table is identified by its kind, the type of flexibility provider, the hour and the `simulation_tag`. It is not identified by the network, the profiles, the provider tables or the tolerances. If you change those and keep the same tag, a run can reuse tables computed for the old inputs.

**Way out.** Change the `simulation_tag`, delete the folder `market_inputs/` of the case, or set `force_HVM` and `force_HCM` to `True` in the configuration file so the tables are always recomputed.

## Run stops with an infeasible or unbounded model

The voltage and congestion slack variables absorb what the providers cannot resolve, so an infeasible model points to contradictory constraints in the inputs. When Gurobi reports `INFEASIBLE`, the platform prints the constraints that cannot be satisfied and stops with the message `The model cannot be solved because it is infeasible`. Read that list, which names the constraints involved, and check the provider tables with the [input validator](check-your-inputs.md).

## Messages during a run

These are the messages that users meet most often, with their meaning and what to do.

| Message | Meaning | What to do |
|---|---|---|
| `The configuration filename must include .yaml or .yml.` | The name of the configuration file is incomplete. | Write the full name, for example `config_my_grid.yaml`. |
| `The sheet of the file Excel must be equal to the name of the file.` | The first sheet of a profile workbook has another name. | Rename the sheet like the file, without the extension. |
| `Expected exactly one load element for FSP '...' at bus ...` | An FSP row matches no element, or more than one. | Correct `name` and `bus` in the FSP file so that they match one element of the network. |
| `Inconsistent 'type' values found across FSP Files` | The files of the products contain different FSP types. | Use the same FSPs in every product file. |
| `Number of FSP in sensitivity matrix ... does not match` | Saved sensitivities belong to older inputs. | Set `force_HVM` and `force_HCM` to `True`, or use a new `simulation_tag`. |
| `Load capacity saturated for some item` | An offer was trimmed to the limit of the element. | Nothing. It is information. |
| `NO CONGESTIONS and OVER/UNDER VOLTAGES DETECTED` | The chosen `ModelTAG` finds no violation in the window, so the market has nothing to do. The run ends. | Change the scenario so that it has violations, or choose another window or `ModelTAG`. |
| `Model too large for size-limited license` | No full Gurobi licence was found. | See [the section on the size limit](#gurobi-says-model-too-large-for-size-limited-license). |

## `pip install` refuses the package

If pip reports that the package requires a different Python version, your Python is outside the supported range, which is 3.9 to 3.11. Create the environment with a supported version.

## Different versions of the dependencies

`pip install .` resolves the newest versions that `pyproject.toml` allows, while `environment.yml` pins the versions of the reference results. Both give the same costs on the shipped examples, apart from numerical noise in variables that have several equivalent optimal values, such as the reactive power of a generator. If you need to reproduce a result to the last digit, use the conda environment.
