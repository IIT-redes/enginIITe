# Scripts

Helpers that are not part of the package. Run them from the root of the repository.

| Script | Purpose |
|---|---|
| `validate_inputs.py` | Checks the inputs of a case (configuration, network, profiles, FSP tables) without running any simulation. |

## `validate_inputs.py`

```bash
python scripts/validate_inputs.py config/my_case.yaml
python scripts/validate_inputs.py config/my_case.yaml --power-flow --strict
```

Exit code 0 when there are no errors, 1 when there is at least one, 2 when the configuration file is missing.

- Usage and output are described in [`docs/howto/check-your-inputs.md`](../docs/howto/check-your-inputs.md).
- Every finding and its fix are listed in [`docs/reference/validator-codes.md`](../docs/reference/validator-codes.md).

## Planned

- A script that generates the inputs of the example case.
- A script that regenerates the reference results used by the regression tests.
