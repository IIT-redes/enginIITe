# Validator codes

Every line printed by `scripts/validate_inputs.py` has a level, a code and a message. This page lists each code and its fix. Running the script is described in [Check inputs](../howto/check-your-inputs.md).

There are three levels.

- **ERROR** means the run would fail or give wrong results. The exit code of the script is 1.
- **WARNING** means a probable problem or a known limitation. Fix it unless you know why it is fine.
- **INFO** is a note, with nothing to fix.

Paths below are relative to `data_in/<net_folder>/`, and `net_folder` is the value in the configuration file.

## Configuration

| Code | Level | Meaning | How to fix |
|---|---|---|---|
| `config.not_a_mapping` | ERROR | The YAML file is empty or is not a set of keys and values. | Check that the file is valid YAML. |
| `config.missing_key` | ERROR | A key that the platform reads directly is absent, so the run would stop with a `KeyError`. The message lists the missing keys of that section, and [Configuration](configuration.md) marks every required key. The sections checked are the top level, `network` and `network.fsp`. | Add the key, with `null` or an empty value where it does not apply (for example `profile_models`). The script stops here because nothing else can be checked without it. |
| `config.bad_window` | ERROR | `simulation_window` is not `[start, end]` with integers and `0 <= start < end`. | Correct it. Profile checks are skipped until you do. |
| `config.network_format` | ERROR | `net_filename` does not end in `.xlsx`. | Only `.xlsx` networks are supported. |
| `config.unknown_model_tag` | ERROR | `ModelTAG` is not `CM`, `VC` or `CMVC`. | Use one of the three. |
| `config.unknown_product` | ERROR | An entry of `ProductTAG` is not `P`, `Q` or `PQ`. | Use only those. |
| `config.unknown_voltage_tag` | ERROR | An entry of `VLTAG` is not between `VL01` and `VL06`. | Use a defined voltage band. |
| `config.bad_fsp_tag` | ERROR | An entry of `FspTAG` does not look like `F01`, `F02`, ... | Use the two-digit form. |
| `config.product_without_fsp_file` | ERROR | A product in `ProductTAG` has no file under `fsp_input_filename`. | Add the file for that product. |
| `config.independent_snapshots_conflict` | ERROR | `simulation_window_as_timesteps` is `false`, which reads the window as independent snapshots, but `consecutive_hours` is not `1` or `intertemp_cons` is `true`. The platform refuses that combination. | Set `consecutive_hours` to `1` and `intertemp_cons` to `false`, or set `simulation_window_as_timesteps` to `true`. |
| `config.empty_simulation_tag` | INFO | `simulation_tag` is empty, so the run uses a tag taken from the name of the configuration file. | Set a tag if you want to choose it. |
| `config.empty_storage_tag` | WARNING | There are battery FSPs but `StorageTag` is empty, so their rating becomes zero and the model can fail. | Set a tag such as `SK01`. |

## Network

| Code | Level | Meaning | How to fix |
|---|---|---|---|
| `network.file_missing` | ERROR | The file named by `net_filename` is not in `network/`. | Check the folder and the file name. |
| `network.unreadable` | ERROR | The workbook cannot be read as a pandapower network. | Open it and check the sheets (`bus`, `line`, `load`, ...); export it again if needed. |
| `network.duplicated_branch_names` | ERROR | Lines and transformers share names. The sensitivity tables use the names as columns. | Give every line and transformer a unique name. |
| `network.no_slack` | ERROR | The network has no external grid. | Add one. |
| `network.missing_profile_columns` | ERROR | A table that has profiles lacks `denorm_profile`, `norm_profile` or `internal_profile`. All three are needed. | Add the three columns, empty where not used. |
| `network.storage_columns` | ERROR | The storage table lacks `soc_percent`, `min_e_mwh`, `max_e_mwh` or `sn_mva`, which battery FSPs need. | Add the missing columns. |
| `network.power_flow_failed` | ERROR | Appears only with `--power-flow`, when the power flow of the base network does not converge. | Check the network data (ratings, impedances, loads). |
| `network.empty_branch_names` | WARNING | Some lines or transformers have no name. | Name them. |
| `network.empty_element_names` | WARNING | Some loads, generators or batteries have no name. FSPs are matched to elements by name. | Name them. |
| `network.duplicated_element_names` | WARNING | A table repeats names. FSPs are matched by name and bus together. | Fine if the buses differ; otherwise rename. |
| `network.base_power_flow` | INFO | Appears only with `--power-flow`, when the base network converges. The message gives the voltage range and the maximum loading. These are the static values of the table, before applying the profiles. | Nothing to fix. |

## Profiles

| Code | Level | Meaning | How to fix |
|---|---|---|---|
| `profile.file_missing` | ERROR | A profile file named in the configuration is not in `profile/`. | Check the name. |
| `profile.unsupported_format` | ERROR | The profile is neither `.xlsx` nor `.csv`. | Convert it. |
| `profile.unreadable` | ERROR | The profile file cannot be read. | Open it and check that it is not corrupt. |
| `profile.sheet_name` | ERROR | In an `.xlsx` profile, the first sheet must have the same name as the file, without the extension. | Rename the sheet. |
| `profile.too_short` | ERROR | The file has fewer rows than the end of `simulation_window`. Rows are taken by position. | Add rows or shorten the window. |
| `profile.missing_values` | ERROR | Empty cells inside the simulation window. | Fill them. Cells outside the window are ignored. |
| `profile.not_numeric` | ERROR | Some columns hold text. | Check for headers or notes inside the data. |
| `profile.columns_not_integer` | ERROR | The columns of a denormalised profile must be element indices (integers). | Use the index of each element as column name. |
| `profile.denorm_missing_columns` | ERROR | A denormalised profile has no column for some of the elements that use it. | Add one column per element. |
| `profile.norm_category_missing` | ERROR | A normalised profile has no column named like the `norm_profile` of the elements. | Add the column, or correct the name in the network. |
| `profile.missing_file_key` | ERROR | The configuration lacks the `denorm`, `norm` or `internal` entry that some elements need under `network.profile.<category>.<product>`. | Add the entry. |
| `profile.ambiguous` | ERROR | An element defines more than one of `denorm_profile`, `norm_profile` and `internal_profile`. | Keep only one per element. |
| `profile.denorm_extra_columns` | WARNING | A denormalised profile has columns that do not match any element that uses it. | Remove them. |
| `profile.none_for_element` | WARNING | Some elements define no profile, so they stay constant. | Intended or not, check. |
| `profile.no_mapping` | WARNING | A category has elements but no entry under `network.profile`, so they stay constant. | Add the entry if they should vary. |
| `profile.missing_product` | WARNING | A category has no `p` or no `q` entry under `network.profile`. | Add the missing one. |
| `profile.category_skipped` | INFO | A category in the configuration is not in the network and is skipped. | Nothing to fix. |
| `profile.check_skipped` | INFO | Profiles were not checked because `simulation_window` is invalid. | Fix the window first. |

## Flexibility service providers (FSP)

| Code | Level | Meaning | How to fix |
|---|---|---|---|
| `fsp.file_missing` | ERROR | An FSP file is not in `fsp_files/`. | Check the name. |
| `fsp.unsupported_format` | ERROR | The FSP file is neither `.xlsx` nor `.csv`. | Convert it. For `.csv`, put the header on the second row. `fsp_sheetname` is ignored. |
| `fsp.sheet_missing` | ERROR | The sheet named by `fsp_sheetname` is not in the file. | Correct the sheet name or the configuration. |
| `fsp.unreadable` | ERROR | The FSP file cannot be read. | Open it and check that it is not corrupt. |
| `fsp.missing_columns` | ERROR | A required column is missing. The header must be on the **second** row of the sheet. | Add the column, or move the header to row 2. |
| `fsp.types_differ` | ERROR | The product files contain different sets of FSP types. | Keep the same types in every product file. |
| `fsp.empty_names` | ERROR | Some FSPs have no name. | Name them. |
| `fsp.duplicated_names` | ERROR | Two FSPs of the same type share a name. | Use unique names. |
| `fsp.unknown_type` | ERROR | The type is not a provider type of the platform. | Correct it. |
| `fsp.unmatched` | ERROR | The FSP does not match exactly one network element by name and bus, in the table that corresponds to its type (loads for A and D, generators for B, batteries for C). | Make the name and the bus equal to those of the element. |
| `fsp.negative_share` | ERROR | A column `Pup`, `Pdown`, `Qup` or `Qdown` has negative values. | Shares are not negative. |
| `fsp.names_differ` | WARNING | The FSP names differ between product files. | Keep the same FSPs in every file. |
| `fsp.negative_cost` | WARNING | A price column has negative values. | Check the prices. |
| `fsp.nonpositive_mva` | WARNING | Some FSPs have a rating of zero or less. | Set the rating. |
| `fsp.aggregator_not_wired` | WARNING | The FSP belongs to an aggregator, which is not connected end to end in the current code. | Leave `aggregator_name` empty for now. |

## Validator

| Code | Level | Meaning | How to fix |
|---|---|---|---|
| `validator.unexpected` | ERROR | A block of checks stopped on an unexpected error, which usually means a malformed input. | Read the message. If the input looks correct, report it as a bug. |
