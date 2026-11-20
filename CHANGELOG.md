# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - YYYY-MM-DD

First public version of enginIITe, a local flexibility market simulation platform. A distribution system operator buys flexibility from local providers to solve voltage and congestion problems at the lowest cost. The power flow is solved with PandaPower and the market is cleared with Gurobi.

### Added

- The four stages of a run, problem detection, sensitivity analysis, market optimization and verification with indicators, and a corrective market that clears again the snapshots that the verification finds insecure.
- Market for voltage problems, congestion problems or both, with active power, reactive power or both as the product, a configurable voltage band and bid depth for each scenario, and a configurable size of the batteries.
- Provider models for flexible loads, generators and batteries, with prices that differ by direction and by active and reactive power.
- Sensitivity tables obtained by finite differences, with two bases for the congestion sensitivities.
- Indicators of the avoided voltage and congestion problems, the hosting capacity, the cost of the flexibility and the volumes offered and cleared, written as Excel workbooks.
- A fixed set of interactive figures for every network, written next to the results.
- The command `enginiite run <config.yaml>`, with `--workspace` and `--output`. A run warns at the start when the paths it will write are longer than Windows accepts.
- An input validator, `scripts/validate_inputs.py`, that checks the configuration, the network, the profiles and the provider tables of a case before a long run. Every finding has a code, listed in `docs/reference/validator-codes.md`.
- Two examples that run as they are, `examples/cigre/` and `examples/sb72/` with twelve independent snapshots, each with the reference values of its results.
- Documentation built with Sphinx, with tutorials, an explanation of how the platform works, the mathematical model of each stage, how-to guides and a reference of the configuration, the input files and the output files.
- Unit tests, tests that compare the platform with the validator on deliberately broken inputs, and regression tests that compare the results of the examples with their reference values.
- Installation with conda or venv, tested with Python 3.9, 3.10 and 3.11.

### Requirements

- Python 3.9 to 3.11.
- A Gurobi licence that solves models of the size of the examples. The licence that comes with `gurobipy` solves only small models. The results of the examples were obtained with Gurobi 11.0.1, and version 12.0.3 gives the same costs on the CIGRE example.

### Known issues

- The parameter `only_worst_hour` has no effect.
- The aggregator model is not connected end to end.
- The provider type `D`, a heat pump, is in the code but it is not documented and it is not supported in this version.
