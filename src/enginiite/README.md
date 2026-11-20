# `src/enginiite/`: the Python package

The code of the platform. Install it from the repository root with `pip install -e .` and import it as `enginiite`.

Layout

- `file_io.py`: every read and write on disk
- `auxiliary.py`: paths, parameters, FSP conversion and the registry of resource models
- `tolerance_policy.py`: voltage and current tolerance bands
- `network/`: time-series power flow, needs detection and sensitivities
- `market/`: clearing model, with one module per resource type in `market/models/`
- `kpis/`: evaluation of the results
- `visualization/`: optional figures, driven by the `visualization:` block of the configuration file
