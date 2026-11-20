# Prepare your own study

This tutorial takes the CIGRE example as a template and shows how to replace each of its inputs with your own. It follows the six steps that every study needs. At the end you can describe a network, its flexibility providers and a market study, run it and find the results.

You need the platform installed and the CIGRE example run once. See [Install enginIITe](installation.md) and [Run the CIGRE example](first-run.md). You work with spreadsheets and one text file, and you do not edit the code.

| Step | What you prepare | Where it lives |
|---|---|---|
| 1 | The network | `data_in/<net_folder>/network/` |
| 2 | The profiles of loads, generators and batteries | `data_in/<net_folder>/profile/` |
| 3 | The flexibility service providers | `data_in/<net_folder>/fsp_files/` |
| 4 | The configuration file | `config/` |
| 5 | Run | `enginiite run` |
| 6 | Read the results | `data_out/` |

Steps 1 to 3 prepare the inputs once. After that, most studies change only the configuration file.

## Create the workspace

A workspace is a folder with a `config/` folder and a `data_in/` folder. The run starts inside it, reads every input from it and writes `data_out/` into it. The fastest way to start is to copy the CIGRE example and replace its files one by one.

```text
my_study/
├── config/
│   └── config_my_grid.yaml
└── data_in/
    └── my_grid/
        ├── network/
        │   └── my_grid.xlsx
        ├── profile/
        └── fsp_files/
```

Choose a short name without spaces for the network folder, such as `my_grid`. It is the value of `net_folder` in the configuration file and it starts the name of every result folder. Spell `network`, `profile` and `fsp_files` exactly like this.

Keep the workspace in a short path. Result paths are long, and Windows rejects paths over 259 characters. See [Common problems](../howto/common-problems.md).

## Step 1. Network

The network is an `.xlsx` file in the pandapower Excel format, with one sheet per element type. There are two ways to make it.

- **Start from the CIGRE file.** Copy `cigre_mv_der_all.xlsx`, then change, add or delete rows. Keep the column names. This is the easiest way for a first study.
- **Build it in Python.** Create the network with pandapower, check that the power flow converges and save it. This suits large networks, or networks that already exist in pandapower.

```python
import pandapower as pp
import pandapower.networks as pn

net = pn.create_cigre_network_mv(with_der='all')   # or your own network
pp.runpp(net)                                      # a network that does not converge cannot be studied
pp.to_excel(net, 'data_in/my_grid/network/my_grid.xlsx')
```

A network saved this way has the pandapower columns only. Add the four columns described below to the sheets `load`, `sgen` and `storage`.

### Sheets

| Sheet | What it holds | CIGRE example |
|---|---|---|
| `bus` | The nodes | 15 buses, one at 110 kV and 14 at 20 kV |
| `line` | Lines and cables | 15 lines |
| `trafo` | Transformers | 2 transformers of 25 MVA |
| `load` | Consumers | 18 loads |
| `sgen` | Static generators such as PV, wind and CHP | 13 generators |
| `storage` | Batteries | 2 batteries |
| `ext_grid` | The connection to the upstream grid | Bus 0 at 1.03 p.u. |

The other sheets are written by pandapower and kept as exported.

### Four columns

The sheets `load`, `sgen` and `storage` carry four extra columns that tell the platform how each element changes in time.

| Name | Bus | `p_mw` | `element_name` | `norm_profile` | `denorm_profile` | `internal_profile` |
|---|---|---|---|---|---|---|
| Load R1 | 1 | 14.994 | load | residential | | |
| PV 3 | 3 | 0.02 | generation | | 0 | |
| Battery 1 | 5 | 0 | storage | | 0 | |

- `element_name` is the kind of element, which is `load`, `generation` or `storage`.
- `norm_profile` is the name of a column of the normalised profile file. Its values multiply `p_mw` and `q_mvar`.
- `denorm_profile` is the number of a column of the denormalised profile file, which holds values in MW and MVAr. Use 0, 1, 2 and so on, one per element of the sheet.
- `internal_profile` is for elements whose profile a module computes. Leave it empty for a first study.

Fill exactly one of the three profile columns for each element and leave the other two empty.

### Checklist

- Every load, generator and battery has a name that is unique at its bus. The FSP file finds each element by name and bus.
- Every line and transformer name is unique across all branch types.
- Lines have `max_i_ka` and transformers have `sn_mva`. They set the 100 % loading used to detect congestion.
- The `vn_kv` of the medium-voltage buses equals `vn_kv_mv` in the configuration file, for example 20.
- The sheet `ext_grid` holds the supply voltage `vm_pu`. A file named by `ext_grid_profile` can give a value per time step instead.
- The file is in `data_in/<net_folder>/network/` and its name is the value of `net_filename`.

The [input files reference](../reference/input-files.md) lists every rule. The script described in [Check inputs](../howto/check-your-inputs.md) checks them for you.

## Step 2. Profiles

A profile gives one value per time step for every load, generator and battery. There are two kinds.

| | Normalised | Denormalised |
|---|---|---|
| Power at each step | A multiplier times `p_mw` | The value of the file, in MW |
| Columns of the file | One per curve name, such as `residential` | One per element, numbered from 0 |
| Good for | Many similar elements that share one curve | Elements that each have a measured or forecast series |

In the CIGRE example the loads use normalised profiles. Load R1 has `p_mw` 14.994 and the curve `residential`, which is 1.00 at hour 19, so it consumes 14.994 MW at that hour. The generators and batteries use denormalised profiles, in MW.

### Layout of a profile file

There is one file for active power (`p`) and one for reactive power (`q`) of each element type, so six files in total for loads, static generators and batteries. Both `.xlsx` and `.csv` are accepted.

| | residential | commercial |
|---|---|---|
| 0 | 0.42 | 0.30 |
| 1 | 0.38 | 0.28 |
| ... | ... | ... |
| 19 | 1.00 | 0.58 |

- Column A is the time step, from 0, with one row per step.
- For an `.xlsx` file, the sheet has the same name as the file without the extension.
- The rows are cut by position, so the file needs at least as many rows as the end of `simulation_window`, and cells inside the window cannot be empty.

### Profiles in the configuration file

The configuration file names the six files under `network.profile`. Write `norm` or `denorm` to match the network file.

```yaml
network:
    profile:
        load:
            p:
                norm: 'profile_df_load_p.xlsx'
            q:
                norm: 'profile_df_load_q.xlsx'
        sgen:
            p:
                denorm: 'profile_df_sgen_p.xlsx'
```

The scaling factors `scen_factor_load`, `scen_factor_sgen`, `scen_factor_gen` and `scen_factor_storage` multiply every profile of a type. A value of 1 leaves the profiles unchanged. A value of 1.2 for the loads means 20 % more load, so Load R1 consumes 1.2 times 14.994, which is 17.99 MW, at hour 19. This is how the CIGRE example creates its violations. With a factor of 1 the day has none.

## Step 3. Flexibility providers

Only the elements listed in an FSP file can offer flexibility. Each FSP is one row, and each row controls one element of the network.

| Type | Element | What it can do |
|---|---|---|
| A | A row of the `load` sheet | Consume less or more |
| B | A row of the `sgen` sheet | Produce less or more. PV and wind usually offer only curtailment. |
| C | A row of the `storage` sheet | Charge or discharge |

### Upward and downward

The direction is always seen from the network, as more or less power injected at the bus.

| | Upward | Downward |
|---|---|---|
| Generator | Produces more | Produces less |
| Load | Consumes less | Consumes more |
| Battery | Discharges more or charges less | Charges more or discharges less |

Upward flexibility raises the local voltage and lowers the power drawn from the substation, so it helps with under-voltages and with overloads caused by high demand. Downward flexibility lowers the local voltage and the power pushed back to the substation, so it helps with over-voltages and with overloads caused by high local generation.

### FSP file

The sheet named by `fsp_sheetname` has a free title in row 1, the column names in row 2 and one FSP per row from row 3.

| id | bus | name | type | mva | mw | mvar | bidding_strategy | Pup | Pdown | Pup_cost | Pdown_cost | Qup | Qdown | Qup_cost | Qdown_cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fspA_load_0 | 1 | Load R1 | A | 15.3 | 14.994 | 3.045 | initial_value | 0.05 | 0.05 | 45 | 45 | 0.05 | 0.05 | 2.25 | 2.25 |
| fspB_gen_0 | 3 | PV 3 | B | 0.02 | 0.02 | 0 | initial_value | 0 | 0.05 | 40 | 40 | 0.05 | 0.05 | 2 | 2 |

Read the first row as a sentence. Load R1 at bus 1 is an FSP of type A. In every hour it offers 5 % of its power upward and 5 % downward at 45 EUR/MWh, and 5 % of its reactive power in each direction at 2.25 EUR/MVArh.

The columns fall into four groups.

- **Who.** `id`, `bus`, `name` and `type`. The pair `name` and `bus` must match exactly one element of the network. Otherwise the run stops with `Expected exactly one load element for FSP ...`.
- **Size.** `mva`, `mw` and `mvar`.
- **How much.** `Pup`, `Pdown`, `Qup` and `Qdown` are the fractions offered, and `bidding_strategy` says what they are a fraction of.
- **Price.** `Pup_cost` and `Pdown_cost` in EUR/MWh, `Qup_cost` and `Qdown_cost` in EUR/MVArh.

Leave `aggregator_name` empty. The [input files reference](../reference/input-files.md#fsp-tables) describes every column.

### How much an FSP offers

The bidding strategy decides what the fractions multiply.

| Strategy | The fraction multiplies | Typical use |
|---|---|---|
| `initial_value` | The power of the element in that hour | Loads and generators that follow a profile |
| `mva_value` | The rating `mva` | Batteries, which may be idle in the profile |
| `headroom_value` | The room left between the operating point and the technical limit | Offers that use the physical margin of the element |

The scenario tag `F0k` multiplies the fractions by `k`, so `F02` doubles them. The table below is a worked example for Load R1 at hour 19 with `F02`, taken from a run of the CIGRE example.

| Quantity | Value |
|---|---|
| Power before the market | 17.99 MW |
| Fraction `Pup` times 2 | 10 % |
| Lowest consumption offered | 16.19 MW |
| Upward offer | 1.80 MW |
| Downward offer | 0 MW |

The downward offer is zero because the load already consumes the active power that its rating allows, so it cannot consume more. An offer never goes beyond the technical limits. When the platform trims one, it prints `Load capacity saturated for some item`, which is information and not an error.

The market activated the whole upward offer at that hour. It paid 1.80 MW times 45 EUR/MWh, which is 80.97 EUR, for the active power of Load R1.

### One file per product

The market product (`P`, `Q` or `PQ`) is expressed through the fractions. The CIGRE example has one file per product with the same FSPs.

| Product | File | `Pup`, `Pdown` | `Qup`, `Qdown` |
|---|---|---|---|
| P | `FSP_data_CIGRE_P.xlsx` | 0.05 | 0 |
| Q | `FSP_data_CIGRE_Q.xlsx` | 0 | 0.05 |
| PQ | `FSP_data_CIGRE_PQ.xlsx` | 0.05 | 0.05 |

All files must contain the same FSP types. Otherwise the run stops with `Inconsistent 'type' values found across FSP Files`. The configuration key `fsp_input_filename` names the file of each product.

Set `BetaCost`, the price of flexibility that no bid can cover, far above every bid price, so that buying from the FSPs is always preferred.

## Step 4. Configuration file

The configuration file holds every setting of a study. Copy `config_CIGRE.yaml` and rename it. Every key has a comment above it that says what it does, which values it takes and its default, so read the file once from top to bottom.

The file has ten sections, in the same order in every configuration.

| Section | What it sets |
|---|---|
| 1. Case identification and tags | The tag of the run, the market model, the products and the voltage bands |
| 2. Flexibility market and bids | The bid depths and the size of the batteries |
| 3. Network and input files | The folder and the names of every input file |
| 4. Simulation window and snapshots | Which time steps are simulated and how they relate to each other |
| 5. Operational limits and optimisation targets | The tolerances and the monitored buses |
| 6. Not served flexibility | The price of flexibility that no bid covers |
| 7. Sensitivity calculation | Whether the sensitivities are rebuilt |
| 8. Corrective iterations and validation | The check against the exact power flow |
| 9. Solver | The settings of Gurobi |
| 10. Outputs and visualization | Which figure families are drawn |

A run makes one scenario for every combination of `ProductTAG`, `VLTAG` and `FspTAG`. With one product, one voltage band and the three bid depths of the CIGRE example, that is three scenarios.

After you change the network, the profiles or the FSP files, keep `force_HVM` and `force_HCM` set to `True`, or use a new `simulation_tag`. Saved sensitivities of old inputs give wrong results or errors. See [Common problems](../howto/common-problems.md).

[Change the study](../howto/change-the-study.md) lists the keys to edit for the usual goals, and the [configuration reference](../reference/configuration.md) describes every key.

## Step 5. Run

From the folder that contains your workspace, give the path of the configuration file.

```bash
enginiite run my_study/config/config_my_grid.yaml
```

The command finds the workspace from the path, so it works from any folder. While it runs the console prints one block per scenario. The messages you meet most often are explained in [Common problems](../howto/common-problems.md#messages-during-a-run).

## Step 6. Read the results

Results go to `data_out/<net_folder>_<ModelTAG>_<StorageTag>_<simulation_tag>/` of the workspace. Start with the voltage and congestion maps and the KPI workbook.

- [Run the CIGRE example](first-run.md) reads the results of the example step by step.
- [Output files](../reference/output-files.md#where-to-find-what) says where to find each result.

A new run with the same `simulation_tag` overwrites the old folder. Use a new tag to keep both.

## Try it yourself

Change one key of the CIGRE configuration, run again and compare with the reference results. Work on a copy of the example, so the original stays as the reference.

1. **Remove the stress.** Set `scen_factor_load` to 1. The day has no violation, so there is nothing for the market to do. The platform prints `NO CONGESTIONS and OVER/UNDER VOLTAGES DETECTED` and ends the run.
2. **Compare the products.** Set `ProductTAG` to `['P', 'Q', 'PQ']` and see how much reactive power alone can do.
3. **Use a stricter band.** Set `VLTAG` to `['VL05']`, which is 0.97 to 1.03 p.u. A narrower band flags more violations.
4. **Treat hours as scenarios.** Set `simulation_window_as_timesteps` to `False`, `consecutive_hours` to 1 and keep `intertemp_cons` at `False`. Every hour becomes an independent scenario.
5. **Try bigger batteries.** Set `StorageTag` to `'SK02'`, which doubles the power of the batteries, and `intertemp_cons` to `True`, so that they carry their charge from hour to hour.
6. **Only congestion.** Set `ModelTAG` to `'CM'`. The market solves the overload of the transformer and ignores the voltages.

Give each variant its own `simulation_tag`, so that the results sit side by side.

## Checklist

1. The network is saved in the network folder, with unique names and the four columns filled, and its power flow converges.
2. The six profile files are in the profile folder, with one row per time step, and the sheet has the name of the file.
3. There is one FSP file per product, with the same FSP types, and every `name` and `bus` matches the network.
4. The configuration is a copy of the CIGRE one, and the names of the files match `data_in`.
5. The run shows the Gurobi licence line and ends with `Simulation finished.`
6. The voltage and congestion maps show whether the market removed the violations.
