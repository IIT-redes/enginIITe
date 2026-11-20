# Configuration

A case is described by one YAML file in the `config/` folder of a workspace. The file is chosen with `enginiite run <config.yaml>`. This page lists every key, its meaning and what happens when it is missing. Before a long run, check a file with the [input validator](../howto/check-your-inputs.md).

Keys marked **required** are read directly, so a missing key stops the run with a `KeyError` after the case has started loading. The validator reports every missing required key as `config.missing_key`. Keys marked **optional** have a default.

## Top level

| Key | Status | Values | Meaning |
|---|---|---|---|
| `simulation_tag` | required | text | Suffix added to the output folders and to the file names of the sensitivity tables. An empty or missing value is replaced by a tag taken from the name of the configuration file, without the prefix `config_`. |
| `simulation_window` | required | `[start, end]` | Hours to simulate, as positions in the profile files. `start` is included and `end` is excluded, so `[0, 24]` is one day. |
| `simulation_window_as_timesteps` | optional | `true` or `false` | Default `true`. `true` reads the rows of `simulation_window` as consecutive time steps of one scenario. `false` reads them as independent snapshots, each cleared as its own market. `false` needs `consecutive_hours: 1` and `intertemp_cons: false`. See [independent snapshots](../how-it-works/verification-and-corrective-market.md#independent-snapshots-and-consecutive-hours). |
| `ModelTAG` | required | `CMVC`, `CM`, `VC` | Market model. `CM` solves congestion, `VC` solves voltage problems and `CMVC` solves both. |
| `ProductTAG` | required | list of `P`, `Q`, `PQ` | Products traded. Each entry runs as a separate scenario. |
| `VLTAG` | required | list of `VL01` to `VL06` | Voltage band. Each entry runs as a separate scenario. See [Voltage bands](#voltage-bands). |
| `FspTAG` | required | list of `F01`, `F02`, ... | Bid coefficient. `F0k` multiplies the activation shares of the FSP table by `k`. Each entry runs as a separate scenario. |
| `StorageTag` | required | `''`, `SK01`, `SK02`, ... | Multiplier of the battery rating. `SKnn` multiplies by `nn`. An empty value gives a rating of zero, which makes battery FSPs unusable. |

The number of scenarios is the product of the lengths of `ProductTAG`, `VLTAG` and `FspTAG`. The market runs once per scenario.

## Scenario factors

All four are required and multiply the corresponding profiles before the simulation. Use `1` for no change.

| Key | Applies to |
|---|---|
| `scen_factor_load` | Loads. |
| `scen_factor_sgen` | Static generators. |
| `scen_factor_gen` | Generators. |
| `scen_factor_storage` | Batteries. |

The FSP ratings are scaled by the same factors.

## Network section

All keys live under `network`.

| Key | Status | Meaning |
|---|---|---|
| `net_folder` | required | Folder name under `data_in/`. Its sub-folders are `network/`, `profile/` and `fsp_files/`, which must exist. |
| `net_filename` | required | Network file inside `network/`. Only `.xlsx` is supported. |
| `profile` | required | Profile files, see [Profile section](#profile-section). |
| `profile_models` | required | Maps a resource name to a Python module that generates its baseline profile. Use `null` when every profile comes from a file. |
| `ext_grid_profile` | optional | Name of a file in `profile/` with the supply voltage of the external grid for every time step, as described in [Supply voltage profile](input-files.md#supply-voltage-profile). The default is `null`, and then the set-point stored in the network file is used at every time step. After changing it, rebuild the sensitivity tables with `force_HVM` and `force_HCM`. |
| `ts_output_file_type` | required | Format of the time-series results, `.csv` or `.xlsx`. |
| `fsp` | required | FSP files, see [FSP section](#fsp-section). |
| `fsp_models` | required | Maps an FSP type to a Python module, only to add types beyond the four built in. Use `null` otherwise. |

### Profile section

Under `network.profile` there is one entry per element category present in the network (`load`, `sgen`, `storage`, ...). Each has a `p` and a `q` entry, and each of those names the file to read.

```yaml
profile:
    load:
        p:
            norm: 'profile_load_p.xlsx'
        q:
            norm: 'profile_load_q.xlsx'
    sgen:
        p:
            denorm: 'profile_sgen_p.xlsx'
```

The key under `p` or `q` depends on how the elements are described in the network table.

| Key | Used for elements whose network row has | File content |
|---|---|---|
| `denorm` | `denorm_profile` | Absolute values in MW or MVAr, one column per element index. |
| `norm` | `norm_profile` | Per-unit curves, one column per curve name. |
| `internal` | `internal_profile` | A parameter file read by the module named in `profile_models`, which generates the profile. |

See [Input files](input-files.md) for the exact formats.

### FSP section

Under `network.fsp`.

| Key | Status | Meaning |
|---|---|---|
| `fsp_input_filename` | required | Maps each product (`P`, `Q`, `PQ`) to its FSP file in `fsp_files/`. Every product in `ProductTAG` needs an entry. |
| `fsp_sheetname` | required | Sheet that holds the FSP table. Ignored for `.csv` files. |
| `fsp_additional_filename` | required | Extra parameter file per FSP type. The types of this version do not use it, so give `null`. |

## Market behaviour

| Key | Status | Meaning |
|---|---|---|
| `BetaCost` | required | Penalty in EUR/MWh for the slack variables that keep the problem feasible. The same value is used for the voltage slack and for the congestion slack. It acts as the value of the flexibility that could not be supplied. |
| `intertemp_cons` | required | `true` adds the constraints that link consecutive hours, such as the battery state of charge. With `false` a battery has no energy limit and only per-hour power limits. |
| `consecutive_hours` | required | Number of studied hours solved together in one optimisation. Longer horizons are split into blocks and nothing links the blocks. |
| `only_worst_hour` | required | Has no effect today. Set it to `false`. |
| `full_network` | required | `true` constrains every bus and every line. `false` constrains only the pilot buses and the congested assets. |
| `only_pilot_busMV` | required | `true` limits the pilot buses to the medium-voltage level given by `vn_kv_mv`. |
| `vn_kv_mv` | required | Nominal voltage in kV of the medium-voltage level. |
| `net_cstr_aggr` | required | Read, but nothing uses it because the aggregator model is not connected. |

## Tolerances

All tolerances are percentages, so `1` means 1 %. They shrink the limits to leave a margin against the error of the linear model.

| Key | Status | Meaning |
|---|---|---|
| `tol_v` | required | Margin on the voltage band used to detect problems. |
| `tol_i` | required | Margin on the loading limit used to detect congestion. |
| `tol_v_opt` | required | Extra voltage margin applied only inside the optimisation, on top of `tol_v`. |
| `tol_i_opt` | required | Extra loading margin applied only inside the optimisation, on top of `tol_i`. |

For example, with `tol_i = 0` and `tol_i_opt = 5` a line is flagged as congested above 100 % loading, and the market aims at 95 %.

### Voltage bands

| Tag | Band in per unit |
|---|---|
| `VL01` | 0.95 to 1.05 |
| `VL02` | 0.93 to 1.07 |
| `VL03` | 0.90 to 1.10 |
| `VL04` | 0.91 to 1.09 |
| `VL05` | 0.97 to 1.03 |
| `VL06` | 0.98 to 1.02 |

## Verification and corrective market

After the main market, the platform checks the dispatch against the exact power flow and can clear again. See [Verification and the corrective market](../how-it-works/verification-and-corrective-market.md).

| Key | Status | Default | Meaning |
|---|---|---|---|
| `ac_validate_post_market` | optional | `true` | `true` applies the dispatch to the exact AC power flow and checks every bus and branch against the limits. `false` also switches every corrective market off. |
| `max_corrective_market_running` | optional | `0` | Maximum number of corrective markets after the main market, as a whole number. A corrective market runs only while the check still finds a violation. `0` means that the platform only verifies, reports the violations and corrects nothing. The shipped examples use `1`. Needs `ac_validate_post_market` to be `true`. |
| `ac_validation_sensitivity_subfolder` | optional | `ACOperatingPointSensitivity` | Name of the folder, inside `market_inputs/`, for the sensitivity tables of the corrective markets. The tables of iteration `k` go to `<folder>/<simulation_tag>/iteration_kk/`. They are deleted and rebuilt at each run. |
| `save_main_market_csv` | optional | `true` | The scenario folder shows the final market, after the last corrective one. `true` also keeps the main market there as CSV files, in `main_market_results/`, for comparison. It matters only when a corrective market runs. |

## Solver

The market is a mixed-integer problem solved by Gurobi. These keys tune each solve.

| Key | Status | Default | Meaning |
|---|---|---|---|
| `mip_focus` | optional | `2` | Search emphasis of Gurobi. `0` balanced, `1` finding feasible solutions, `2` proving optimality, `3` improving the best bound. |
| `mip_gap` | optional | `0.00001`, and `0.000001` for `VC` | Relative optimality gap at which each solve stops. `0.001` is 0.1 % and gives shorter solves. |
| `threads` | optional | `null` | Number of processor threads that Gurobi may use in each solve. `null` lets Gurobi decide, normally every core. Runs started in parallel share the processor, so their threads add up. |
| `time_limit` | optional | `null` | Wall-clock limit of one solve, in seconds, and not of the whole run. A solve that reaches it returns its best solution, and the console and `GReports/` say so. `null` means no limit. |
| `solver_log_to_console` | optional | `false` | `true` also prints the progress table of Gurobi on the console. The log file is always written. |

The number of solves follows `consecutive_hours`, `simulation_window_as_timesteps` and `max_corrective_market_running`. The main market has one solve per block of `consecutive_hours` time steps, and each corrective market adds one per block, or one per snapshot that is not secure.

## Calculation and debugging

| Key | Status | Default | Meaning |
|---|---|---|---|
| `timeseries_force_1st_calculation` | required | none | `true` always recalculates the baseline time series. Use `true` for normal runs. |
| `force_HVM` | optional | `false` | `true` recalculates the voltage sensitivity tables. |
| `force_HCM` | optional | `false` | `true` recalculates the congestion sensitivity tables. |
| `cm_sensitivity_basis` | optional | `apparent_power` | Branch quantity of the congestion sensitivities. `current` is the accurate basis, the apparent power at nominal voltage and real current, which is the quantity on which the rating, the loading and the verification are based. `apparent_power` uses the apparent power from the flows at the branch ends, and it stays the default so that earlier results do not change. Any other value stops the run with an error. Set `force_HCM` to `true` when changing it, so that no table of the other basis is reused. |
| `sensitivity_delta_p_mw`, `sensitivity_delta_q_mvar` | optional | derived from the network | Size of the active and reactive perturbation of the sensitivity power flows. By default it is derived from the smallest power in the network file, as described in [Sensitivity analysis model](../model/sensitivity-analysis.md#step-size). Set `force_HVM` and `force_HCM` to `true` when changing it. |
| `save_inverse_jacobian` | optional | `false` | Saves extra diagnostic tables. It does not change the market. |
| `debug_save_VPilotBus_FULLH` | required | none | `true` also saves an extra table with the voltage of the buses for every hour. |

The sensitivity tables are cached by kind, FSP type, hour and `simulation_tag` only. With `force_HVM` and `force_HCM` at `false`, two scenarios that share a `simulation_tag` can reuse tables that were built for different settings. Use `true` when scenarios differ in voltage band, product or profiles, or give each scenario set its own `simulation_tag`.

## Unused keys

These appear in some example files but nothing in the platform reads them, so changing them has no effect.

| Key | Note |
|---|---|
| `f_hz` | Frequency. Not read. |
| `par_pf_algo` | Power flow algorithm. Not read. |
| `debug_pf_res_to_excel` | Not read. |
| `only_worst_hour` | Read, but its branch is never reached. |
| `net_cstr_aggr` | Read, but only the aggregator would use it. |

## Visualization section

The optional `visualization` block sets how the topology pages look and which optional figures a run adds. If the block or a key is missing, the default below is used.

Every run writes the same figures, whatever the network. Each scenario folder gets `visualization/network_topology/`, `network_technical_analytics/` and `showcase/`, and the run folder gets `comparison/technical comparison/`. None of them has a switch. See [Output files](output-files.md#figures-of-a-scenario).

| Key | Default | Meaning |
|---|---|---|
| `interactive_pf_hour` | `0` | Time step shown in the pre-market and post-market pages when no studied time step is found. |
| `plot_fsp_resources` | `true` | Mark the FSP locations on the topology pages. |
| `topology_label_mode` | `compact` | FSP labels on the topology, `compact`, `full` or `none`. No effect while the topology pages are HTML only. |
| `show_bus_labels` | `true` | Write the bus numbers on the topology. No effect while the topology pages are HTML only. |
| `show_resource_table` | `false` | Add a table of FSP resources next to the topology. |
| `save_png`, `save_pdf` | `true` | Formats of the static topology. No effect while the topology pages are HTML only. |
| `save_svg` | `false` | Also save the static topology as SVG. No effect while the topology pages are HTML only. |
| `consistency_checks` | `false` | Network consistency audit and the KPI consistency check across scenarios, written to `comparison/network_consistency_audit/` and `ConsistencyCheck/`. |
| `kpi_plots` | `false` | KPI figures of the run. The KPI workbook is always written. |

The older keys `run_network_consistency_audit`, `run_kpi_consistency_check` and `run_kpi_plots`, and the master switch `enabled`, still work when the matching category is missing.
