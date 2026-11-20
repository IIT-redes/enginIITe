# Check inputs

A run can fail late because of a small mistake in the inputs, such as a profile with too few rows, an FSP name that matches no element or a wrongly named sheet. The validator finds these in seconds, without running the market or the solver.

Use it after creating or editing a case, and before the first run.

## Run the validator

From the root of the repository, give the configuration file and the workspace that contains its `data_in/`.

```bash
python scripts/validate_inputs.py examples/cigre/config/config_CIGRE.yaml --root examples/cigre
```

The script accepts these options.

| Option | Effect |
|---|---|
| `--root DIR` | Workspace, the folder that contains `data_in/`. The default is the current folder. |
| `--power-flow` | Also runs one power flow of the base network and reports the voltage range and the maximum loading. |
| `--strict` | Treats warnings as failures. For automated checks. |

The exit code is `0` when there are no errors, `1` when there is at least one error (or a warning with `--strict`), and `2` when the configuration file does not exist.

## Output

```
[ERROR  ] profile.too_short                    profile_load_p.xlsx has 10 rows but the simulation window ends at 24.
[INFO   ] config.empty_simulation_tag          simulation_tag is empty, so the run uses a tag taken from the name ...

Summary: 1 errors, 0 warnings, 1 notes.
```

Errors come first, then warnings, then notes. Each code is explained, with its fix, in [Validator codes](../reference/validator-codes.md).

The rules behind the checks are described in [Configuration](../reference/configuration.md) and [Input files](../reference/input-files.md).

## Checks

| Block | Examples |
|---|---|
| Configuration | Every required key, valid tags, a well-formed simulation window |
| Network | The workbook can be read, element names, the profile columns, an external grid |
| Profiles | File and sheet names, enough rows for the window, empty cells, one column per element |
| FSP tables | Header on the second row, required columns, the same types in every product file, each FSP matches exactly one network element |

## Common fixes

- For `profile.sheet_name`, rename the first sheet of the profile file so it equals the file name.
- For `fsp.missing_columns`, make the table start on the second row of its sheet.
- For `fsp.unmatched`, copy the element name and bus exactly from the network table.
- For `config.empty_storage_tag`, set a non-empty value.
- For `profile.norm_category_missing`, make the `norm_profile` column of the network name a column of the normalised profile file.

## Not checked

The validator does not check that the case has anything to solve. If the profiles and the voltage band produce no voltage or congestion problem in any hour, the run stops with a warning about "no congestions and over/under voltages detected". It does not judge whether the values are plausible (ratings, prices, units) and does not run the market. A clean result means the files fit the format the platform expects.
