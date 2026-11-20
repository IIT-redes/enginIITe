"""Early warning about paths that Windows may refuse.

Windows rejects a path longer than 259 characters unless long paths are enabled in the system. A run writes
hundreds of figures whose file names repeat the scenario name, so the results of a scenario can reach 250 characters
below the results folder. Without a warning, a run can fail minutes after it starts.

The estimate is checked against the real system, so nothing is reported on a system that accepts long paths.
"""
import os
import re
import shutil

WINDOWS_LIMIT = 259

# The longest file of a run, measured on finished runs of the shipped examples. It is a figure below the folder of a
# scenario, and its name contains the scenario name.
_LONGEST_FILES = (
    ('visualization', 'network_technical_analytics', 'voltage_congestion', 'VoltageViolationHeatmap_{scenario}.html'),
)


def longest_expected_path(scenario_dir):
    """Length of the longest path expected below the results folder of one scenario."""
    scenario = re.split(r'[\\/]', str(scenario_dir).rstrip('\\/'))[-1]
    return max(len(os.path.join(str(scenario_dir), *parts).format(scenario=scenario)) for parts in _LONGEST_FILES)


def probe_path(probe_dir, length):
    """A path of exactly ``length`` characters below ``probe_dir``, made of folders and a file with short names."""
    remaining = length - len(probe_dir)
    parts = []
    while remaining > 1:
        size = min(remaining - 1, 200)
        parts.append('p' * size)
        remaining -= size + 1
    if remaining == 1 and parts:
        parts[-1] += 'p'
    return os.path.join(probe_dir, *parts)


def os_accepts_path_length(base_dir, length):
    """Whether the system can create a file whose path has ``length`` characters below ``base_dir``.

    Only Windows has the limit, so every other system answers yes. The probe leaves nothing behind.
    """
    if os.name != 'nt':
        return True
    probe_dir = os.path.join(os.path.abspath(base_dir), '.path_probe')
    try:
        os.makedirs(probe_dir, exist_ok=True)
    except OSError:
        return True  # the folder cannot be written at all, so nothing can be said about the length
    try:
        path = probe_path(probe_dir, length)
        if path == probe_dir:
            return True
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w'):
                pass
            return True
        except OSError:
            return False
    finally:
        shutil.rmtree('\\\\?\\' + probe_dir, ignore_errors=True)


def check_output_paths(path_dict, accepts=None):
    """Return a warning if the longest expected path cannot be written on this system, otherwise ``None``.

    ``path_dict`` is the dictionary of ``auxiliary.set_paths``.
    """
    scenarios = [folder for products in path_dict['mrk_outputs']['res_market'].values()
                 for levels in products.values() for folder in levels.values()]
    if not scenarios:
        return None
    worst_folder = max(scenarios, key=longest_expected_path)
    worst = longest_expected_path(worst_folder)
    if worst <= WINDOWS_LIMIT:
        return None
    accepts = accepts or os_accepts_path_length
    if accepts(os.path.dirname(worst_folder), worst):
        return None
    return (f'Warning: this run will write paths of about {worst} characters, and this system refuses paths longer '
            f'than {WINDOWS_LIMIT}. Writing beyond that limit makes the run fail late. Shorten the simulation_tag, '
            f'start from a folder closer to the root of the drive, send the results to a shorter folder with '
            f'--output, or enable long paths in Windows.')
