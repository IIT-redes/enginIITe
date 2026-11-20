"""Write the compact reference values of one example from a finished run.

Usage, from the repository root:

    python tests/regression/make_reference.py <results_folder> <example> <reference_name>

The results folder is the one written under `data_out/` of the example (for instance
`examples/cigre/data_out/CIGRE_CMVC_SK01_L120`). The values come from the sheet
`Overall_Results` of its KPI workbook and are stored in
`examples/<example>/expected/<reference_name>.json`, keyed by scenario (`<product>_<voltage level>_<FSP step>`) so they do not depend on the
simulation tag used in the run.
"""
import glob
import json
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'examples')
SCENARIO_RE = re.compile(r'_(PQ|P|Q)_(VL\d+)_(F\d+)_SK\d+_')
VALUE_COLUMNS = {
    'ObjValue [Eur]': 'objective_eur',
    'ActivePowerCost [Eur]': 'active_power_cost_eur',
    'ReactivePowerCost [Eur]': 'reactive_power_cost_eur',
    'TotalCost [Eur]': 'total_cost_eur',
    'TotalActivePower [MW]': 'active_power_mw',
    'TotalReactivePower [MVAR]': 'reactive_power_mvar',
}


def scenario_key(label):
    """Return `<product>_<voltage level>_<FSP step>` from a scenario label."""
    found = SCENARIO_RE.search(label)
    if not found:
        raise ValueError(f'Cannot read a scenario from {label!r}')
    return '_'.join(found.groups())


def read_overall_results(results_folder):
    """Return {scenario key: {value name: float}} from the KPI workbook of a run."""
    pattern = os.path.join(results_folder, 'KPI_results_*', '*.xlsx')
    workbooks = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith('KPI_VolFlex')]
    if len(workbooks) != 1:
        raise FileNotFoundError(f'Expected one KPI workbook in {pattern}, found {len(workbooks)}')
    table = pd.read_excel(workbooks[0], sheet_name='Overall_Results', index_col=0)
    out = {}
    for label, row in table.iterrows():
        out[scenario_key(str(label))] = {name: float(row[col]) for col, name in VALUE_COLUMNS.items()}
    return out


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    values = read_overall_results(argv[1])
    reference_dir = os.path.join(EXAMPLES_DIR, argv[2], 'expected')
    os.makedirs(reference_dir, exist_ok=True)
    path = os.path.join(reference_dir, argv[3] + '.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(values, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(f'Wrote {len(values)} scenarios to {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
