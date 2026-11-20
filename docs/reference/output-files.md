# Output files

A run writes its results under `data_out/` and the files it generates for the market under `data_in/<net_folder>/market_inputs/`. This page describes the folder naming and the main files. The inputs are described in [Input files](input-files.md) and the settings in [Configuration](configuration.md).

## Scenario names

Each combination of product, voltage band and bid coefficient is a scenario. Its name joins the non-empty parts below with underscores.

```
<net_folder>_<ModelTAG>_<product>_<VLTAG>_<FspTAG>_<StorageTag>_<simulation_tag>
```

For example, a network `grid`, model `CMVC`, product `P`, band `VL01`, coefficient `F01`, storage tag `SK01` and simulation tag `T1` gives `grid_CMVC_P_VL01_F01_SK01_T1`. An empty `simulation_tag` is replaced by a tag taken from the name of the configuration file.

The scenario name appears in the file names, so avoid underscores inside `net_folder` and `simulation_tag`, because the KPI step splits the name at the underscores.

## Folder layout

```
data_out/
└── <net_folder>_<ModelTAG>_<StorageTag>_<simulation_tag>/
    ├── res_ts_net/                   baseline time series, before any market
    ├── KPI_results_<...>/            the KPI workbooks
    └── <scenario name>/              one folder per scenario
        ├── FullTS_postMKT/           time series after the final market
        ├── ACCorrectionStages/       a copy of every market stage, from the verification
        ├── main_market_results/      the main market as CSV files
        ├── GReports/                 model files, when saving them is enabled
        └── visualization/            figures, when enabled
```

The scenario folder also holds the market results workbook, the `Support_<type>.xlsx` files and the files of the verification and the corrective market, described in [Verification and corrective market files](#verification-and-corrective-market-files). The folder shows the **final** market, which is the main market followed by the corrective markets that ran.

## Where to find what

Next to the scenario folders, the run folder holds `res_ts_net/` with the power flow before the market, `KPI_results_<...>/` with the KPI workbook and its figures, `comparison/technical comparison/` with the scenarios of the study side by side, and `ConsistencyCheck/` with checks across scenarios, which are written when `consistency_checks` is `true`.

Inside a scenario folder, use this table to find a result.

| I want to see | Look in |
|---|---|
| Which hours and buses have violations before the market | `market_inputs/HoursToStudy.csv`, `VM_Problems_Stats_preMKT.xlsx`, `total_cm_PreMKT.xlsx` |
| The bids prepared for the market | `market_inputs/FSPA_init<scenario>.xlsx`, and `FSPB_init...` and `FSPC_init...` for the other types |
| The market solution, with the activated flexibility of each FSP and hour | `model_results_<scenario>.xlsx` |
| Whether the network is secure after the market | `ACMarketValidation.csv`, `VM_Problems_Stats_postMKT.xlsx`, `total_cm_postMKT.xlsx` |
| Voltages and loadings after the market | `FullTS_postMKT/` |
| The main market and every corrective iteration | `main_market_results/` and `ACCorrectionStages/` |
| What each FSP delivered and what it is paid | `FinalNetSettlement.csv` |
| The log of the Gurobi solver | `GReports/` |
| The figures of the scenario | `visualization/` |

### Names of the sheets

The sheets of `model_results_<scenario>.xlsx` and of the bid workbooks use short codes. The names are built by joining the codes, so `DW_A_U` is the upward active power flexibility activated from each load.

| Code | Meaning |
|---|---|
| `W`, `R` | Active power (MW) and reactive power (MVAr) |
| `DW`, `DR` | Activated flexibility, which is the change of `W` or `R` |
| `alpha`, `beta` | Flexibility not served for voltage and for congestion |
| `_A`, `_B`, `_C` | FSP type, which is load, generator or battery |
| `_U`, `_D` | Upward and downward |
| `init` | Value before the market |
| `LB`, `UB` | Lower and upper bound of an offer |
| `Cost` | Bid price |

For example, `WLB_ULim_A` in a bid workbook is the lowest consumption that a load offers, which is the limit of its upward offer.

### Figures of a scenario

The folder `visualization/` holds interactive HTML pages that open in any web browser. Hover to read exact values, drag to zoom, double-click to reset and click a legend entry to hide a series.

| Folder | What it shows | Written when |
|---|---|---|
| `network_topology/` | The network with its FSPs, and the network before and after the market hour by hour | Always |
| `network_technical_analytics/` | Voltage and congestion maps, cleared flexibility, storage and not served flexibility, in the folders `voltage_congestion/`, `flexibility_activation/`, `storage_operation/` and `slack_diagnostics/` | Always |
| `showcase/` | State of charge of the batteries, congestion by asset and voltage by bus | Always |

The run folder also has `comparison/technical comparison/`, which sets the scenarios of the study side by side. It is written after every scenario and holds the whole comparison after the last one.

Start from `network_technical_analytics/voltage_congestion/`. It shows the voltage and the loading violations of each hour, before and after the market, so it tells at a glance whether the market removed them. Then look at `flexibility_activation/` to see what was activated.

## Time series

`res_ts_net/` and `FullTS_postMKT/` hold the result of the power flow for every hour in the format set by `ts_output_file_type`. They are organized in one sub-folder per element type (`res_bus`, `res_line`, `res_load`, ...), with one file per result variable such as `vm_pu` or `loading_percent`. Rows are hours and columns are elements.

The baseline covers the whole simulation window. The post-market series covers only the studied hours.

## Detection tables

Created before the market from the baseline time series, and saved in the folders of the scenario.

| File | Content |
|---|---|
| `VM_Problems_Stats_preMKT` | Buses by hours, with the voltage where it is outside the band and zero elsewhere. |
| `VM_Problems_Stats_postMKT` | The same after the market. |
| `total_cm_PreMKT` | Congestion needs per asset and hour. |
| `VCHoursToStudy`, `CMHoursToStudy` | Hours with a voltage or a congestion problem. |
| `HoursToStudy` | Hours that enter the market, which depends on `ModelTAG` and `intertemp_cons`. |

## Sensitivity tables

In `market_inputs/h24SensitivityMatrixes/`, shared by all scenarios with the same `simulation_tag`. One file per kind, FSP type and hour.

| Pattern | Content |
|---|---|
| `HVMP_FSP<type>_h<HH>_<tag>.csv` | Change of the voltage of each pilot bus per MW of active power of each FSP. |
| `HVMQ_FSP<type>_h<HH>_<tag>.csv` | The same for reactive power. |
| `HCMdSdP_FSP<type>_h<HH>_<tag>.csv` | Change of the apparent power of each line or transformer per MW of active power of each FSP. |
| `HCMdSdQ_FSP<type>_h<HH>_<tag>.csv` | The same for reactive power. |
| `HVMPii_h<HH>_<tag>.csv`, `HVMQii_h<HH>_<tag>.csv` | Response of each pilot bus to its own power. |

## Market inputs

In `market_inputs/<ModelTAG>/<product>/<VLTAG>/<FspTAG>/`, one workbook per FSP type named `FSP<type>_init<scenario>.xlsx`. Each sheet is a table of FSPs by hours, with the bid limits, the baseline power and the prices that the market uses. Sheet names start with `W` for active power and `R` for reactive power, for example `Winit_A` or `WUB_DLim_A`.

## Market results

`model_results_<scenario>.xlsx` in the scenario folder.

| Sheets | Content |
|---|---|
| One per variable of each FSP type | Resulting power (`W_<type>`, `R_<type>`), the change from the baseline (`DW_<type>`, `DR_<type>`) and the upward and downward parts, with one row per FSP and one column per studied hour. |
| `alpha_DVpu`, `alpha_primo`, `ABS_alpha_primo`, `VA` | Voltage slack, its power-equivalent, its absolute value and the predicted voltage, per pilot bus and hour. |
| `beta`, `ABS_beta` | Congestion slack per asset and hour. |
| `ObjValue` | Value of the objective function. |

Loads are reported with consumption positive, as in pandapower. A slack that is not zero means the market could not remove the problem completely with the flexibility offered.

If the studied hours are split into blocks, the sheets are concatenated and the objective values are added.

## Verification and corrective market files

Written in the scenario folder, from the check of the dispatch against the exact power flow. The sequence is explained in [Verification and the corrective market](../how-it-works/verification-and-corrective-market.md). A cell is one element in one hour, so an overload cell is a line or transformer in one hour, and a voltage violation cell is a bus in one hour.

### Verification

| File | Content |
|---|---|
| `ACMarketValidation.csv` | One row per verification. The row of iteration 0 checks the main market, and each later row checks a corrective market. |
| `ACMarketValidationBySnapshot.csv` | One row per snapshot or hour and iteration, with the verdict. |
| `ACValidationPolicy.json` | The settings under which the verification ran, as a record. |

The columns of `ACMarketValidation.csv` are the following.

| Column | Meaning |
|---|---|
| `iteration` | `0` for the main market, `1` for the first corrective market, and so on. |
| `market_stage` | `initial_market` or `corrective_remaining_capacity`. |
| `fsp_capacity_basis` | `original_available_capacity` for the main market, `remaining_after_first_dispatch` for a corrective one. |
| `sensitivity_policy`, `linearization_operating_point` | `reusable_initial` and `initial` for the main market, `fresh_post_dispatch` and `post_dispatch_ac` for a corrective one. |
| `sensitivity_cache_root` | Folder of the sensitivity tables that the market used. |
| `optimization_vmin_pu`, `optimization_vmax_pu`, `maximum_cm_margin_percent` | The optimisation target of the market, as a voltage band and as the largest loading margin in percent. |
| `post_max_loading_percent`, `post_overload_cell_count`, `post_max_overload_percentage_points` | Highest loading after the dispatch, number of overload cells, and the largest excess over the limit. |
| `post_min_voltage_pu`, `post_max_voltage_pu`, `post_voltage_violation_cell_count`, `post_max_voltage_violation_pu` | Lowest and highest voltage after the dispatch, number of voltage violation cells, and the largest violation in per unit. |

The columns of `ACMarketValidationBySnapshot.csv` are `market_tag`, `snapshot_mode` (`independent` or `joint`), `iteration`, `cleared_in_iteration`, `snapshot` (the position of the snapshot or hour), the same `post_...` figures for that snapshot, `secure` and `decision`. The decisions are listed in [Verification and the corrective market](../how-it-works/verification-and-corrective-market.md#independent-snapshots-and-consecutive-hours).

`ACValidationPolicy.json` has `policy_version`, `ac_validate_post_market`, `run_corrective_market`, `max_corrective_market_running`, `max_corrective_market_reruns`, `sequential_remaining_capacity`, `fresh_corrective_sensitivities`, `ac_validation_sensitivity_subfolder` and `snapshot_mode`.

### Market stages

| Path | Content |
|---|---|
| `ACCorrectionStages/stage_00_initial/` | A copy of the main market, so that no later stage overwrites it. |
| `ACCorrectionStages/stage_01_corrective/`, `stage_02_corrective/`, ... | The same for each corrective market. |
| `ACValidationCumulativeMarket_iteration_00.xlsx`, `_01.xlsx`, ... | The market results workbook after each iteration. The first is the main market, and each later one adds the corrective market of its iteration. The last one is the final market. |
| `main_market_results/` | The main market as CSV files, in `market/`, with its power flow, the order of the pilot buses and a `README.txt`. Written when `save_main_market_csv` is `true`. |

Each stage folder has the market results workbook of the stage, `ACCorrectionStageManifest.csv`, `PilotBusOrder.csv`, the detection tables `total_cm_PreMKT.xlsx` and `VM_Problems_Stats_preMKT.xlsx`, the power flow after the stage in `FullTS_postMKT/` and the sensitivity tables that the stage used in `sensitivity_matrices/`.

The sensitivity tables of the corrective markets are also written to `market_inputs/<ac_validation_sensitivity_subfolder>/<simulation_tag>/iteration_kk/`, and they are deleted and rebuilt at each run. The tables of the main market in `market_inputs/h24SensitivityMatrixes/` are never overwritten.

### Settlement

The main market and the corrective markets are settled as one market, on the final net position of each provider.

| File | Content |
|---|---|
| `FinalNetSettlement.csv` | One row per provider, hour and product, with its position and its cost. |
| `FinalNetSettlementChecks.csv` | One row of consistency checks of the settlement. |
| `SequentialActivationByStage.csv` | The activation that each stage adds, in total and in absolute value, by quantity and provider type. |
| `SequentialActivationChurn.csv` | By quantity and provider type, how much of the gross activation was reversed by a later stage, and the costs. |
| Sheet `SequentialCostBasis` | In the market results workbook, from the first corrective market on. It reconciles the solver objective with the settlement. |

The main columns of `FinalNetSettlement.csv` are the following. Activations use one sign for every provider type, positive for upward flexibility, and `reported_sign` maps them back to the sign of the market results workbook.

| Column | Meaning |
|---|---|
| `fsp_type`, `product`, `unit`, `provider`, `hour` | The provider type, the product (`P` or `Q`), its unit (MW or MVAr), the provider and the hour or snapshot. |
| `main_activation`, `corrective_01_increment`, `corrective_increment_total` | The activation of the main market, the increment of each corrective market and their sum. |
| `final_net_activation` | The final position, which is `main_activation` plus the increments. |
| `gross_activation`, `reversed_activation`, `settled_volume` | The sum of the activations of every round in absolute value, the part that a later round reversed, and the volume that is paid, which is the absolute value of the final position. |
| `price_up`, `price_down`, `settlement_price` | The two bid prices of the provider, and the one that applies to the final direction. |
| `main_market_cost_eur`, `corrective_incremental_cost_eur`, `final_net_settlement_cost_eur` | The cost of the main market on its own, the gross cost of the corrective increments, and the cost that is paid. |
| `dispatch_residual` | The difference between the final position and the dispatch that the network was given. It should be zero. |
| `final_direction` | `upward`, `downward` or `none`. |

In `FinalNetSettlementChecks.csv`, every count of rows (`double_counted_rows`, `baseline_paid_rows`, `wrong_direction_price_rows`, `unpriced_activation_rows` and the others) and every error (`net_identity_max_error`, `aggregation_error`) should be zero for a consistent settlement, and so should `dispatch_max_residual`.

## KPI workbooks

In `KPI_results_<...>/`, written once after all scenarios finish.

| File | Content |
|---|---|
| `<net_folder>_<ModelTAG>_<StorageTag>_<simulation_tag>.xlsx` | The main workbook, with one sheet per KPI family. |
| `KPI_VolFlex_<scenario>.xlsx` | Statistics of the flexibility volume. |

Sheets of the main workbook.

| Sheet | Content |
|---|---|
| `Overall_Results` | Summary table with one column per scenario. |
| `FlexALL` | All the KPI values behind the summary. |
| `AvoidCongestions_Results` | Congestion events before and after the market, and the share avoided. |
| `AvoidVoltageViol_Results` | The same for voltage violations. |
| `IHC_Results`, `pIHC_Results` | Increase of the hosting capacity, absolute and in percent. |
| `HC_Results_pre`, `HC_Results_post` | Hosting capacity before and after. |

The KPIs judge the network against the standard limits (the voltage band and 100 % loading) and report the tolerance bands next to them.

The cost KPIs settle each activated power at its own bid price. The total cost equals the objective value, so the difference between them checks a run.

## Limitations

- The voltage part of the hosting capacity is always infinite, so the hosting capacity reflects lines and transformers only.
- Voltage KPIs compare the studied hours after the market with all hours before it, so the avoided violations can be overstated when the studied hours are only a subset.
- The volume statistics count one direction per FSP type, so they can understate usage when both directions are used.
