<!-- PROJECT LOGO -->
<br />
<div align="center">
    <img src="readme_file/logo-icai.png" alt="Logo" width="500" height="200">

<h3 align="center">enginIITe</h3>

  <p align="center">
    Analysis of the use of flexibility by Distribution System Operators (DSO) and their interaction with the new flexibility markets.
    <br />
    <br />
    <a href="docs/index.md">Documentation</a>
    ·
    <a href="examples/README.md">Examples</a>
    ·
    <a href="CONTRIBUTING.md">Contributing</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#what-it-does">What It Does</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li><a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#requirements">Requirements</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#gurobi-licence">Gurobi Licence</a></li>
        <li><a href="#check-the-installation">Check The Installation</a></li>
      </ul>
    </li>
    <li><a href="#quick-start">Quick Start</a></li>
    <li><a href="#examples">Examples</a></li>
    <li><a href="#documentation">Documentation</a></li>
    <li><a href="#mathematical-formulation">Mathematical Formulation</a></li>
    <li><a href="#theoretical-background">Theoretical Background</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#citing">Citing</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

The EUniversal project, funded by the European Union, has developed a universal approach on the use of flexibility by Distribution System Operators (DSO) and their interaction with the new flexibility markets, enabled through the development of the concept of the Universal Market Enabling Interface (UMEI) – a unique approach to foster interoperability across Europe.

The UMEI represents an innovative, agnostic, adaptable, modular and evolutionary approach that will be the basis for the development of new innovative services, market solutions and, above all, implementing the real mechanisms for active consumer, prosumer, and energy communities participation in the energy transition.


### What It Does

enginIITe simulates a local flexibility market. A Distribution System Operator (DSO) buys flexibility from distributed resources (flexible loads, generators and batteries) at minimum cost to solve voltage violations and line congestion. A run goes through four stages.

1. **Problem detection.** An hourly AC power flow without a market shows where the network violates its voltage or loading limits, and which hours to study.
2. **Sensitivity analysis.** Each flexibility provider is nudged with a small virtual generator and the power flow is solved again. The change in voltages and loadings gives the sensitivity matrices.
3. **Market optimization.** Gurobi chooses the activations of the providers at minimum cost, using the sensitivity matrices as linear network constraints.
4. **Verification and KPIs.** The dispatch is applied to the network, the exact AC power flow is solved again and the key performance indicators are computed.

The platform supports flexible loads, distributed generators, batteries with intertemporal limits, markets for active power, reactive power or both, and voltage constraints, congestion constraints or both. Scenarios are defined in a YAML configuration file, and a single run loops over products, voltage bands and provider capacity steps. See [How it works](docs/how-it-works/four-stages.md) for the detail.

<!-- Built With -->
### Built With
* [![Python][Python-shield]][Python-url]
* [![Gurobi][Gurobi-shield]][Gurobi-url]

<!-- <p align="right"><a href="#top">🔼 Back to top</a></p> -->

<p align="right"><a href="#top">🔼 Back to top</a></p>

<!-- GETTING STARTED -->
## Getting Started

### Requirements
* Python 3.9, 3.10 or 3.11
* A [Gurobi](https://www.gurobi.com/) licence, needed to solve the market model (free academic licences are available)
* Git

The installation was checked on Windows 11 with Python 3.9, 3.10 and 3.11. Linux and macOS have not been tested yet.

### Installation
Download the repository and run the commands below from its root folder. On Windows, use a short path such as `C:\enginiite`, because Windows limits full file paths to 260 characters.

```bash
git clone <repository-url>
cd <repository-folder>
```

Create an environment with conda or with venv.

**With conda**, which pins the versions of the reference results.
```bash
conda env create -f environment.yml
conda activate enginiite
pip install .
```

**With venv on Windows.**
```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install .
```

**With venv on Linux and macOS.**
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install .
```

Use `pip install -e .` instead if you plan to change the code. The step-by-step guide, with the options explained, is [Install enginIITe](docs/tutorial/installation.md).

### Gurobi Licence
The size-limited licence that comes with `gurobipy` solves models of up to 2,000 variables, and the examples are larger. Students and researchers at academic institutions can get a free licence from the [Gurobi academic programme](https://www.gurobi.com/academia/academic-program-and-licenses/). The platform works with Gurobi 11 and 12.

### Check The Installation
```bash
enginiite --help
python -c "import gurobipy as gp; m = gp.Model(); x = m.addVars(2001, ub=1); m.setObjective(x.sum(), gp.GRB.MAXIMIZE); m.optimize(); print('Licence OK, objective', m.ObjVal)"
```
With a full licence the last line is `Licence OK, objective 2001.0`.

<p align="right"><a href="#top">🔼 Back to top</a></p>

<!-- QUICK START -->
## Quick Start

Run the CIGRE medium-voltage example from the root of the repository. It takes about 4 minutes.

```bash
enginiite run examples/cigre/config/config_CIGRE.yaml
```

A run reads its inputs from, and writes its results to, one folder called the workspace, with `config/`, `data_in/<network>/` and `data_out/`. The workspace is found from the path of the configuration file, or given with `--workspace`. The option `--output <folder>` sends the results to another folder.

The results are written to `examples/cigre/data_out/CIGRE_CMVC_SK01_L120/`. The workbook `KPI_results_CIGRE_CMVC_SK01_L120/CIGRE_CMVC_SK01_L120.xlsx` summarises each scenario, and the folder `examples/cigre/expected/` has the figures that a correct run must reproduce. To compare them, run `python -m unittest discover -s tests/regression`.

Before a long run on your own case, check the inputs with `python scripts/validate_inputs.py <config.yaml> --root <workspace>`. It takes seconds and needs no solver.

<p align="right"><a href="#top">🔼 Back to top</a></p>

<!-- EXAMPLES -->
## Examples

| Example | Network | Time on a laptop |
|---|---|---|
| [`examples/cigre/`](examples/cigre/README.md) | CIGRE medium-voltage benchmark, 15 buses, 33 flexibility providers | about 4 minutes |
| [`examples/sb72/`](examples/sb72/README.md) | Medium-voltage distribution network with twelve operating snapshots, 153 flexibility providers | about 20 minutes |

Each example is a complete workspace with its configuration, its input data and the reference values of a correct run. See [`examples/README.md`](examples/README.md) for the layout of a workspace and how to use your own case.

<!-- DOCUMENTATION -->
## Documentation

The documentation is in [`docs/`](docs/index.md).

* [Install enginIITe](docs/tutorial/installation.md) and [run the CIGRE example](docs/tutorial/first-run.md) and [the SB72 snapshots](docs/tutorial/sb72-snapshots.md), with a reading of their results
* [How it works](docs/how-it-works/four-stages.md) and its [limits and assumptions](docs/how-it-works/limits-and-assumptions.md)
* The [model](docs/model/market-optimization.md), stage by stage, with its equations
* [Check your inputs](docs/howto/check-your-inputs.md) and [common problems](docs/howto/common-problems.md)
* Reference for the [configuration file](docs/reference/configuration.md), the [input files](docs/reference/input-files.md), the [output files](docs/reference/output-files.md) and the [validator codes](docs/reference/validator-codes.md)

<p align="right"><a href="#top">🔼 Back to top</a></p>

<!-- Mathematical Problems -->
## Mathematical Formulation

The market of stage 3 minimises the bid cost of the activations plus a penalty on the problems that cannot be solved. With $\Delta W$ and $\Delta R$ the changes of active and reactive power of each provider $f$ in each studied hour $t$, split into upward and downward parts, and $\alpha$ and $\beta$ the slack variables of voltage and congestion, the objective is

```math
\min \sum_{t}\sum_{f}\left( p^{W\uparrow}_{f,t}\,\Delta W^{\uparrow}_{f,t} + p^{W\downarrow}_{f,t}\,\Delta W^{\downarrow}_{f,t} + p^{R\uparrow}_{f,t}\,\Delta R^{\uparrow}_{f,t} + p^{R\downarrow}_{f,t}\,\Delta R^{\downarrow}_{f,t} \right) + \sum_{t}\sum_{b} c^{\alpha}\,|\alpha'_{b,t}| + \sum_{t}\sum_{\ell} c^{\beta}\,|\beta_{\ell,t}|
```

The constraints are of three kinds.

* **Voltage.** The voltage of each pilot bus is predicted from the baseline voltage and the sensitivities to the providers, and must stay inside the optimisation band.
* **Congestion.** The loading of each monitored line and transformer is predicted in the same way, and must stay below its rating minus a margin.
* **Resources.** Each provider type has its own limits, power factor and energy models.

The full formulation, with every constraint and the conventions of the code, is in the model pages of the documentation.

* [Problem detection model](docs/model/problem-detection.md), which defines the limits, the problems and the hours to study
* [Sensitivity analysis model](docs/model/sensitivity-analysis.md), which defines the coefficients of the constraints
* [Market optimization model](docs/model/market-optimization.md), which defines the variables, constraints and objective
* [Verification and indicators model](docs/model/verification-and-indicators.md), which defines the check with the exact power flow, the corrective market and the indicators

<p align="right"><a href="#top">🔼 Back to top</a></p>

<!-- THEORETICAL BACKGROUND -->
## Theoretical Background

The design of the platform follows the Theoretical Market Framework developed at Comillas, which describes any electricity market design through five pillars: market architecture, sub-market coordination, market optimisation, market operation and network representation.

* Troncia, M., Chaves Ávila, J. P., Damas Silva, B., Gerard, H., Willeghems, G. (2023). Market-Based TSO-DSO Coordination: A Comprehensive Theoretical Market Framework and Lessons from Real-World Implementations. *Energies*, 16(19), 6939. [doi:10.3390/en16196939](https://doi.org/10.3390/en16196939)

<!-- CONTRIBUTING -->
## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and use the issue templates to report a bug or propose a change.

## License

The licence of this repository is stated in [LICENSE](LICENSE). Gurobi is a commercial product with its own licence, and the data of the SB72 example comes from a third party, as its [README](examples/sb72/README.md) says.

## Citing

If you use enginIITe in your work, cite it as described in [CITATION.cff](CITATION.cff). The people who developed it are listed in [AUTHORS](AUTHORS).

<p align="right"><a href="#top">🔼 Back to top</a></p>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
<!-- To create your personalise shield go to: https://shields.io/ -->
[Python-shield]: https://img.shields.io/badge/Python-py-green
[Python-url]: https://www.python.org/
[Gurobi-shield]: https://img.shields.io/badge/Gurobi-py-red
[Gurobi-url]: https://www.gurobi.com/
