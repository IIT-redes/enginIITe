# Install enginIITe

This page installs the platform in its own Python environment, adds a Gurobi licence and checks that everything works. It takes about ten minutes. At the end you have the `enginiite` command available and you are ready to run an example.

## Requirements

| Requirement | Details |
|---|---|
| Python | 3.9, 3.10 or 3.11. Newer versions have not been tested. |
| Gurobi licence | Needed to solve the market model. Free academic licences exist, see [Install a Gurobi licence](#install-a-gurobi-licence). |
| Git | To download the repository. You can also download it as a zip file. |
| Operating system | Verified on Windows 11. Linux and macOS should work with the commands below, but they have not been tested yet. |

The installation itself was checked on Python 3.9, 3.10 and 3.11, each in a clean environment. The reference results shipped with the examples were produced with Python 3.9, and the SB72 results were also reproduced with Python 3.11.

## Get the code

Download the repository and move into its folder. The examples live in it, so you need the whole repository and not only the package.

```bash
git clone <repository-url>
cd <repository-folder>
```

On Windows, clone into a short path such as `C:\enginiite`. The platform writes long file names and Windows limits a full path to 260 characters. See [Common problems](../howto/common-problems.md).

## Create an environment

Use one of the two options below. Both give the same package. Run the commands from the root of the repository, the folder that contains `pyproject.toml`.

### With conda

The file `environment.yml` pins the versions used for the reference results (Python 3.9, PandaPower 2.14.6, Gurobi 11.0.1).

```bash
conda env create -f environment.yml
conda activate enginiite
pip install .
```

### With venv on Windows

Open a terminal in the repository folder. Replace `3.11` by `3.9` or `3.10` if you prefer.

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install .
```

In PowerShell, activate with `.venv\Scripts\Activate.ps1`. If PowerShell refuses to run the script, allow scripts for your user once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### With venv on Linux and macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install .
```

### What pip installs

`pip install .` installs the package `enginiite`, the command `enginiite` and these dependencies, which are resolved to the newest versions the package allows.

| Package | Allowed versions | Used for |
|---|---|---|
| pandapower | 2.14 up to 3 | AC power flow |
| gurobipy | 11 up to 13 | Market optimisation |
| numpy | 1.26 up to 2 | Numerical arrays |
| pandas | 2.2 up to 3 | Tables |
| scipy, openpyxl, pyyaml, tqdm | recent | Numerics, Excel files, configuration, progress bars |
| matplotlib, plotly | recent | Figures |

If you plan to change the code, install it in editable mode with `pip install -e .`, so that your changes take effect without installing again.

## Install a Gurobi licence

Installing the package also installs `gurobipy`, but solving the market model needs a licence.

- The size-limited licence that comes with `gurobipy` solves models of up to 2,000 variables. The examples are larger than that. The CIGRE example, the smallest one, has 2,970 variables, so it cannot run with the limited licence.
- Students, teachers and researchers at academic institutions can request a free academic licence from the [Gurobi academic programme](https://www.gurobi.com/academia/academic-program-and-licenses/). Follow Gurobi's instructions to activate it. The licence is stored in a file called `gurobi.lic`, and academic licences have to be renewed every year.
- Commercial licences are available from Gurobi.

To activate an academic licence, open a terminal in the environment you created, with an internet connection, and run the `grbgetkey` command followed by the key that the Gurobi User Portal shows for your licence. The command asks where to save the licence file. Accept the suggested location, which is your home folder, or choose a folder that Gurobi can read later. If Gurobi cannot find the file, it prints `Restricted license` when it starts and falls back to the size-limited licence. The Gurobi Help Center explains how to [retrieve and set up a licence](https://support.gurobi.com/hc/en-us/articles/12872879801105-How-do-I-retrieve-and-set-up-a-Gurobi-license), and the [Gurobi documentation](https://docs.gurobi.com/) covers every licence type.

The platform works with Gurobi 11 and 12.

## Check the installation

Check that the command is available.

```bash
enginiite --help
```

It prints the usage of the command and the `run` subcommand.

Check that your licence solves a model larger than the limited licence allows.

```bash
python -c "import gurobipy as gp; m = gp.Model(); x = m.addVars(2001, ub=1); m.setObjective(x.sum(), gp.GRB.MAXIMIZE); m.optimize(); print('Licence OK, objective', m.ObjVal)"
```

With a full licence the last line is `Licence OK, objective 2001.0`. With the size-limited licence Gurobi stops with the message `Model too large for size-limited license`.

## Run the tests

The unit tests need no simulation and take about one minute. Run them from the root of the repository.

```bash
python -m unittest discover -s tests/unit
```

The last lines should read `OK`, followed by the number of expected failures. Those are known behaviours that the tests document on purpose.

## Update or remove

To update, download the new version of the repository and install it again.

```bash
git pull
pip install .
```

To remove the platform, uninstall the package or delete the environment.

```bash
pip uninstall enginiite
```

For a conda environment, `conda env remove -n enginiite` deletes it. For a venv, delete the `.venv` folder.

## Next step

Run the first example and read its results in [Run the CIGRE example](first-run.md).
