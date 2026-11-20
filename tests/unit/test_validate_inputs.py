"""Unit tests for the input validator (scripts/validate_inputs.py).

A tiny synthetic case (3 buses, 2 loads, 1 generator, 1 battery) is built once on disk; every test copies it,
breaks one thing and checks that the validator reports exactly that.

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import contextlib
import copy
import gc
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandapower as pp
import pandas as pd
import yaml
from pandapower import io_utils

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'validate_inputs.py'
_spec = importlib.util.spec_from_file_location('validate_inputs', SCRIPT)
assert _spec is not None and _spec.loader is not None, 'scripts/validate_inputs.py could not be loaded'
vi = importlib.util.module_from_spec(_spec)
sys.modules['validate_inputs'] = vi
_spec.loader.exec_module(vi)

FOLDER = 'tiny'
NET_FILE = 'tiny_network.xlsx'
HOURS = 24

CONFIG = {
    'simulation_tag': 'T1',
    'simulation_window': [0, 24],
    'network': {
        'net_folder': FOLDER,
        'net_filename': NET_FILE,
        'profile': {
            'load': {'p': {'norm': 'profile_load_p.xlsx'}, 'q': {'norm': 'profile_load_q.xlsx'}},
            'sgen': {'p': {'denorm': 'profile_sgen_p.xlsx'}, 'q': {'denorm': 'profile_sgen_q.xlsx'}},
            'storage': {'p': {'denorm': 'profile_storage_p.xlsx'}, 'q': {'denorm': 'profile_storage_q.xlsx'}},
        },
        'fsp': {
            'fsp_input_filename': {'P': 'fsp_P.xlsx', 'Q': 'fsp_Q.xlsx', 'PQ': 'fsp_PQ.xlsx'},
            'fsp_sheetname': 'fsp_data',
            'fsp_additional_filename': None,
        },
        'profile_models': None,
        'fsp_models': None,
        'ts_output_file_type': '.csv',
    },
    'ModelTAG': 'CMVC',
    'ProductTAG': ['P', 'PQ'],
    'VLTAG': ['VL01'],
    'FspTAG': ['F01'],
    'StorageTag': 'SK01',
    'scen_factor_load': 1,
    'scen_factor_sgen': 1,
    'scen_factor_gen': 1,
    'scen_factor_storage': 1,
    'BetaCost': 6000,
    'intertemp_cons': False,
    'only_worst_hour': False,
    'consecutive_hours': 24,
    'full_network': False,
    'timeseries_force_1st_calculation': True,
    'only_pilot_busMV': True,
    'vn_kv_mv': 20,
    'net_cstr_aggr': False,
    'tol_v': 0,
    'tol_i': 0,
    'tol_v_opt': 1,
    'tol_i_opt': 3,
    'debug_save_VPilotBus_FULLH': False,
}


def build_network():
    net = pp.create_empty_network()
    buses = pp.create_buses(net, 3, vn_kv=20.0)
    pp.create_ext_grid(net, buses[0])
    pp.create_line(net, buses[0], buses[1], 1.0, 'NA2XS2Y 1x95 RM/25 12/20 kV', name='line_a')
    pp.create_line(net, buses[1], buses[2], 1.0, 'NA2XS2Y 1x95 RM/25 12/20 kV', name='line_b')
    pp.create_load(net, buses[1], p_mw=1.0, q_mvar=0.2, sn_mva=1.2, name='Load 1')
    pp.create_load(net, buses[2], p_mw=0.8, q_mvar=0.1, sn_mva=1.0, name='Load 2')
    pp.create_sgen(net, buses[2], p_mw=0.5, sn_mva=0.5, name='PV 1')
    pp.create_storage(net, buses[1], p_mw=0.0, max_e_mwh=1.0, sn_mva=0.5, soc_percent=50.0, min_e_mwh=0.0, name='Battery 1')
    for table in ('load', 'sgen', 'storage'):
        df = getattr(net, table)
        df['element_name'] = table
        df['denorm_profile'] = np.nan
        df['norm_profile'] = np.nan
        df['internal_profile'] = np.nan
    net.load['norm_profile'] = 'res'
    net.sgen['denorm_profile'] = net.sgen.index.astype(float)
    net.storage['denorm_profile'] = net.storage.index.astype(float)
    return net


def fsp_frame():
    rows = [
        ('fsp0', 1, 'Load 1', 'A', 1.2, 1.0, 0.2),
        ('fsp1', 2, 'Load 2', 'A', 1.0, 0.8, 0.1),
        ('fsp2', 2, 'PV 1', 'B', 0.5, 0.5, 0.0),
        ('fsp3', 1, 'Battery 1', 'C', 0.5, 0.0, 0.0),
    ]
    df = pd.DataFrame(rows, columns=['id', 'bus', 'name', 'type', 'mva', 'mw', 'mvar'])
    df['aggregator_name'] = np.nan
    df['bidding_strategy'] = 'initial_value'
    for col, val in (('Pup', 0.05), ('Pdown', 0.05), ('Qup', 0.0), ('Qdown', 0.0),
                     ('Pup_cost', 40.0), ('Pdown_cost', 40.0), ('Qup_cost', 2.0), ('Qdown_cost', 2.0)):
        df[col] = val
    return df


def write_xlsx(path, frame, sheet, startrow=0, index=True):
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        frame.to_excel(writer, sheet_name=sheet, startrow=startrow, index=index)


def save_network(net, path):
    """Same layout as pandapower's to_excel, written with openpyxl (to_excel needs the extra package xlsxwriter)."""
    sheets = io_utils.to_dict_of_dfs(net, include_results=False, include_empty_tables=False)
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for name, table in sheets.items():
            table.to_excel(writer, sheet_name=name)


def build_case(root):
    case = Path(root) / 'data_in' / FOLDER
    for sub in ('network', 'profile', 'fsp_files'):
        (case / sub).mkdir(parents=True, exist_ok=True)
    save_network(build_network(), str(case / 'network' / NET_FILE))
    flat = np.linspace(0.5, 1.0, HOURS)
    profiles = {
        'profile_load_p': pd.DataFrame({'res': flat}),
        'profile_load_q': pd.DataFrame({'res': flat}),
        'profile_sgen_p': pd.DataFrame({0: flat * 0.5}),
        'profile_sgen_q': pd.DataFrame({0: np.zeros(HOURS)}),
        'profile_storage_p': pd.DataFrame({0: np.zeros(HOURS)}),
        'profile_storage_q': pd.DataFrame({0: np.zeros(HOURS)}),
    }
    for name, frame in profiles.items():
        write_xlsx(case / 'profile' / (name + '.xlsx'), frame, sheet=name)
    for product in ('P', 'Q', 'PQ'):
        write_xlsx(case / 'fsp_files' / ('fsp_%s.xlsx' % product), fsp_frame(), sheet='fsp_data', startrow=1, index=False)


class ValidatorCase(unittest.TestCase):
    """Base class that gives each test its own fresh copy of the tiny case."""

    @classmethod
    def setUpClass(cls):
        cls._template = tempfile.TemporaryDirectory()
        build_case(cls._template.name)

    @classmethod
    def tearDownClass(cls):
        cls._template.cleanup()

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.root = Path(self._work.name)
        self.reset()

    def reset(self):
        """Restore the untouched case (also usable several times inside one test)."""
        shutil.rmtree(self.root / 'data_in', ignore_errors=True)
        shutil.copytree(Path(self._template.name) / 'data_in', self.root / 'data_in')
        self.cfg = copy.deepcopy(CONFIG)
        self.case = self.root / 'data_in' / FOLDER

    # ---- helpers
    def validate(self, power_flow=False):
        path = self.root / 'config.yaml'
        path.write_text(yaml.safe_dump(self.cfg), encoding='utf-8')
        return vi.validate_case(str(path), root=str(self.root), power_flow=power_flow)

    def codes(self, findings, level=None):
        return {f.code for f in findings if level is None or f.level == level}

    def edit_network(self, change):
        path = self.case / 'network' / NET_FILE
        net = pp.from_excel(str(path))
        change(net)
        save_network(net, str(path))

    def edit_fsp(self, product, change):
        path = self.case / 'fsp_files' / ('fsp_%s.xlsx' % product)
        frame = pd.read_excel(path, sheet_name='fsp_data', header=1)
        frame = change(frame)
        write_xlsx(path, frame, sheet='fsp_data', startrow=1, index=False)

    def write_profile(self, stem, frame, sheet=None, ext='.xlsx'):
        path = self.case / 'profile' / (stem + ext)
        if ext == '.xlsx':
            write_xlsx(path, frame, sheet=sheet or stem)
        else:
            frame.to_csv(path)


class ValidCaseTests(ValidatorCase):
    def test_a_correct_case_has_no_errors_and_no_warnings(self):
        findings = self.validate()
        self.assertEqual([str(f) for f in findings if f.level != vi.INFO], [])

    def test_the_power_flow_option_adds_a_note_for_a_convergent_network(self):
        self.assertIn('network.base_power_flow', self.codes(self.validate(power_flow=True), vi.INFO))

    def test_a_network_that_does_not_converge_is_an_error(self):
        self.edit_network(lambda net: net.load.__setitem__('p_mw', 50000.0))
        self.assertIn('network.power_flow_failed', self.codes(self.validate(power_flow=True), vi.ERROR))


class ConfigTests(ValidatorCase):
    def test_a_missing_top_level_key_is_reported_and_stops_the_check(self):
        del self.cfg['ProductTAG']
        findings = self.validate()
        self.assertIn('config.missing_key', self.codes(findings, vi.ERROR))
        self.assertTrue(all(f.code.startswith('config.') for f in findings))

    def test_a_missing_nested_key_is_reported(self):
        del self.cfg['network']['fsp']['fsp_sheetname']
        self.assertIn('config.missing_key', self.codes(self.validate(), vi.ERROR))

    def test_a_bad_window_is_rejected(self):
        for window in ([5, 2], [0], 'all', [0.5, 3]):
            with self.subTest(window=window):
                self.cfg['simulation_window'] = window
                self.assertIn('config.bad_window', self.codes(self.validate(), vi.ERROR))

    def test_a_bad_window_skips_the_profile_check_instead_of_crashing(self):
        self.cfg['simulation_window'] = [0]
        findings = self.validate()
        self.assertIn('profile.check_skipped', self.codes(findings, vi.INFO))

    def test_an_unexpected_failure_becomes_a_finding(self):
        original = vi.check_fsp
        vi.check_fsp = lambda *args: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            findings = self.validate()
        finally:
            vi.check_fsp = original
        self.assertIn('validator.unexpected', self.codes(findings, vi.ERROR))

    def test_unknown_tags_are_rejected(self):
        self.cfg.update({'ModelTAG': 'XX', 'ProductTAG': ['P', 'Z'], 'VLTAG': ['VL09'], 'FspTAG': ['F1']})
        codes = self.codes(self.validate(), vi.ERROR)
        for expected in ('config.unknown_model_tag', 'config.unknown_product', 'config.unknown_voltage_tag', 'config.bad_fsp_tag'):
            self.assertIn(expected, codes)

    def test_only_xlsx_networks_are_accepted(self):
        self.cfg['network']['net_filename'] = 'network.csv'
        self.assertIn('config.network_format', self.codes(self.validate(), vi.ERROR))

    def test_an_empty_simulation_tag_is_only_a_note_because_the_run_derives_one(self):
        self.cfg['simulation_tag'] = ''
        findings = self.validate()
        self.assertIn('config.empty_simulation_tag', self.codes(findings, vi.INFO))
        self.assertNotIn('config.empty_simulation_tag', self.codes(findings, vi.WARNING))

    def test_independent_snapshots_with_one_hour_and_no_intertemporal_limits_are_accepted(self):
        self.cfg.update({'simulation_window_as_timesteps': False, 'consecutive_hours': 1, 'intertemp_cons': False})
        self.assertNotIn('config.independent_snapshots_conflict', self.codes(self.validate()))

    def test_independent_snapshots_with_blocks_of_several_hours_are_an_error(self):
        self.cfg.update({'simulation_window_as_timesteps': False, 'consecutive_hours': 24, 'intertemp_cons': False})
        self.assertIn('config.independent_snapshots_conflict', self.codes(self.validate(), vi.ERROR))

    def test_independent_snapshots_with_intertemporal_limits_are_an_error(self):
        self.cfg.update({'simulation_window_as_timesteps': False, 'consecutive_hours': 1, 'intertemp_cons': True})
        self.assertIn('config.independent_snapshots_conflict', self.codes(self.validate(), vi.ERROR))

    def test_consecutive_time_steps_may_use_blocks_and_intertemporal_limits(self):
        self.cfg.update({'consecutive_hours': 24, 'intertemp_cons': True})
        for value in (True, None):
            with self.subTest(simulation_window_as_timesteps=value):
                self.cfg['simulation_window_as_timesteps'] = value
                self.assertNotIn('config.independent_snapshots_conflict', self.codes(self.validate()))
        del self.cfg['simulation_window_as_timesteps']
        self.assertNotIn('config.independent_snapshots_conflict', self.codes(self.validate()))

    def test_the_validator_agrees_with_the_platform_on_every_combination(self):
        from enginiite.network.ac_market_validation import independent_snapshot_mode
        for window in (True, False, None):
            for hours in (1, 2, 24):
                for intertemp in (False, True):
                    self.reset()
                    self.cfg.update({'simulation_window_as_timesteps': window, 'consecutive_hours': hours, 'intertemp_cons': intertemp})
                    try:
                        independent_snapshot_mode(window, hours, intertemp)
                        platform_refuses = False
                    except ValueError:
                        platform_refuses = True
                    validator_refuses = 'config.independent_snapshots_conflict' in self.codes(self.validate(), vi.ERROR)
                    with self.subTest(window=window, hours=hours, intertemp=intertemp):
                        self.assertEqual(validator_refuses, platform_refuses)

    def test_battery_fsps_without_a_storage_tag_are_a_warning(self):
        self.cfg['StorageTag'] = ''
        self.assertIn('config.empty_storage_tag', self.codes(self.validate(), vi.WARNING))

    def test_a_product_without_an_fsp_file_is_an_error(self):
        del self.cfg['network']['fsp']['fsp_input_filename']['PQ']
        self.assertIn('config.product_without_fsp_file', self.codes(self.validate(), vi.ERROR))


class NetworkTests(ValidatorCase):
    def test_a_missing_network_file_is_an_error(self):
        (self.case / 'network' / NET_FILE).unlink()
        self.assertEqual(self.codes(self.validate(), vi.ERROR), {'network.file_missing'})

    def test_a_corrupt_network_file_is_an_error(self):
        (self.case / 'network' / NET_FILE).write_text('not a workbook', encoding='utf-8')
        self.assertEqual(self.codes(self.validate(), vi.ERROR), {'network.unreadable'})

    def test_lines_and_transformers_sharing_a_name_are_an_error(self):
        self.edit_network(lambda net: net.line.__setitem__('name', 'same'))
        self.assertIn('network.duplicated_branch_names', self.codes(self.validate(), vi.ERROR))

    def test_a_network_without_external_grid_is_an_error(self):
        self.edit_network(lambda net: net.ext_grid.drop(net.ext_grid.index, inplace=True))
        self.assertIn('network.no_slack', self.codes(self.validate(), vi.ERROR))

    def test_a_table_with_profiles_must_have_the_three_profile_columns(self):
        self.edit_network(lambda net: net.load.drop(columns=['norm_profile'], inplace=True))
        self.assertIn('network.missing_profile_columns', self.codes(self.validate(), vi.ERROR))

    def test_repeated_element_names_are_a_warning(self):
        self.edit_network(lambda net: net.load.__setitem__('name', 'Load 1'))
        self.assertIn('network.duplicated_element_names', self.codes(self.validate(), vi.WARNING))


class ProfileTests(ValidatorCase):
    def test_the_first_sheet_must_be_named_like_the_file(self):
        self.write_profile('profile_load_p', pd.DataFrame({'res': np.ones(HOURS)}), sheet='Sheet1')
        self.assertIn('profile.sheet_name', self.codes(self.validate(), vi.ERROR))

    def test_a_profile_shorter_than_the_window_is_an_error(self):
        self.write_profile('profile_load_p', pd.DataFrame({'res': np.ones(10)}))
        self.assertIn('profile.too_short', self.codes(self.validate(), vi.ERROR))

    def test_a_window_that_fits_inside_a_short_profile_is_accepted(self):
        self.write_profile('profile_load_p', pd.DataFrame({'res': np.ones(10)}))
        self.write_profile('profile_load_q', pd.DataFrame({'res': np.ones(10)}))
        for stem in ('profile_sgen_p', 'profile_sgen_q', 'profile_storage_p', 'profile_storage_q'):
            self.write_profile(stem, pd.DataFrame({0: np.ones(10)}))
        self.cfg['simulation_window'] = [0, 10]
        self.assertEqual(self.codes(self.validate(), vi.ERROR), set())

    def test_empty_cells_inside_the_window_are_an_error(self):
        values = np.ones(HOURS)
        values[3] = np.nan
        self.write_profile('profile_load_p', pd.DataFrame({'res': values}))
        self.assertIn('profile.missing_values', self.codes(self.validate(), vi.ERROR))

    def test_empty_cells_outside_the_window_are_ignored(self):
        values = np.ones(HOURS)
        values[20] = np.nan
        self.write_profile('profile_load_p', pd.DataFrame({'res': values}))
        self.cfg['simulation_window'] = [0, 12]
        self.assertNotIn('profile.missing_values', self.codes(self.validate()))

    def test_a_normalised_profile_needs_the_category_used_by_the_elements(self):
        self.write_profile('profile_load_p', pd.DataFrame({'other': np.ones(HOURS)}))
        self.assertIn('profile.norm_category_missing', self.codes(self.validate(), vi.ERROR))

    def test_numeric_profile_categories_match_integer_column_names(self):
        # The platform looks the column up with pandas, where the key 1.0 is the key 1, so a network table that stores
        # numeric categories as floats must be accepted when the profile file names its columns with integers.
        self.edit_network(lambda net: net.load.__setitem__('norm_profile', (np.arange(len(net.load)) % 2).astype(float)))
        for stem in ('profile_load_p', 'profile_load_q'):
            self.write_profile(stem, pd.DataFrame({0: np.ones(HOURS), 1: np.ones(HOURS)}))
        self.assertNotIn('profile.norm_category_missing', self.codes(self.validate()))

    def test_a_numeric_category_that_is_not_a_column_is_still_reported(self):
        self.edit_network(lambda net: net.load.__setitem__('norm_profile', (np.arange(len(net.load)) % 2).astype(float) + 5.0))
        for stem in ('profile_load_p', 'profile_load_q'):
            self.write_profile(stem, pd.DataFrame({0: np.ones(HOURS), 1: np.ones(HOURS)}))
        findings = self.validate()
        self.assertIn('profile.norm_category_missing', self.codes(findings, vi.ERROR))
        self.assertTrue(any('5.0' in f.message and '6.0' in f.message for f in findings if f.code == 'profile.norm_category_missing'))

    def test_a_denormalised_profile_needs_one_column_per_element(self):
        self.write_profile('profile_sgen_p', pd.DataFrame({5: np.ones(HOURS)}))
        findings = self.validate()
        self.assertIn('profile.denorm_missing_columns', self.codes(findings, vi.ERROR))
        self.assertIn('profile.denorm_extra_columns', self.codes(findings, vi.WARNING))

    def test_denormalised_columns_must_be_integers(self):
        self.write_profile('profile_sgen_p', pd.DataFrame({'abc': np.ones(HOURS)}))
        self.assertIn('profile.columns_not_integer', self.codes(self.validate(), vi.ERROR))

    def test_a_missing_profile_file_is_an_error(self):
        (self.case / 'profile' / 'profile_sgen_q.xlsx').unlink()
        self.assertIn('profile.file_missing', self.codes(self.validate(), vi.ERROR))

    def test_a_csv_profile_is_accepted(self):
        self.write_profile('profile_sgen_q', pd.DataFrame({0: np.zeros(HOURS)}), ext='.csv')
        (self.case / 'profile' / 'profile_sgen_q.xlsx').unlink()
        self.cfg['network']['profile']['sgen']['q'] = {'denorm': 'profile_sgen_q.csv'}
        self.assertEqual(self.codes(self.validate(), vi.ERROR), set())

    def test_an_unsupported_format_is_an_error(self):
        (self.case / 'profile' / 'profile_sgen_q.txt').write_text('0\n', encoding='utf-8')
        self.cfg['network']['profile']['sgen']['q'] = {'denorm': 'profile_sgen_q.txt'}
        self.assertIn('profile.unsupported_format', self.codes(self.validate(), vi.ERROR))

    def test_a_missing_file_key_in_the_configuration_is_an_error(self):
        self.cfg['network']['profile']['load']['p'] = {}
        self.assertIn('profile.missing_file_key', self.codes(self.validate(), vi.ERROR))

    def test_an_element_with_two_kinds_of_profile_is_ambiguous(self):
        self.edit_network(lambda net: net.load.__setitem__('denorm_profile', 0.0))
        self.assertIn('profile.ambiguous', self.codes(self.validate(), vi.ERROR))

    def test_an_element_without_profile_is_a_warning(self):
        self.edit_network(lambda net: net.load.__setitem__('norm_profile', np.nan))
        self.assertIn('profile.none_for_element', self.codes(self.validate(), vi.WARNING))

    def test_a_category_without_mapping_is_a_warning(self):
        del self.cfg['network']['profile']['storage']
        self.assertIn('profile.no_mapping', self.codes(self.validate(), vi.WARNING))

    def test_a_missing_reactive_entry_is_a_warning(self):
        del self.cfg['network']['profile']['load']['q']
        self.assertIn('profile.missing_product', self.codes(self.validate(), vi.WARNING))


class FspTests(ValidatorCase):
    def test_an_fsp_that_matches_no_element_is_an_error(self):
        self.edit_fsp('P', lambda df: df.assign(name=df['name'].replace({'Load 1': 'Ghost'})))
        self.assertIn('fsp.unmatched', self.codes(self.validate(), vi.ERROR))

    def test_an_fsp_at_the_wrong_bus_is_an_error(self):
        self.edit_fsp('P', lambda df: df.assign(bus=df['bus'].replace({1: 0})))
        self.assertIn('fsp.unmatched', self.codes(self.validate(), vi.ERROR))

    def test_duplicated_names_within_a_type_are_an_error(self):
        self.edit_fsp('P', lambda df: df.assign(name=df['name'].replace({'Load 2': 'Load 1'})))
        self.assertIn('fsp.duplicated_names', self.codes(self.validate(), vi.ERROR))

    def test_empty_fsp_names_are_an_error(self):
        self.edit_fsp('P', lambda df: df.assign(name=df['name'].replace({'Load 2': ' '})))
        self.assertIn('fsp.empty_names', self.codes(self.validate(), vi.ERROR))

    def test_the_types_must_be_the_same_in_every_product_file(self):
        self.edit_fsp('Q', lambda df: df[df['type'] != 'C'])
        self.cfg['ProductTAG'] = ['P', 'Q']
        self.assertIn('fsp.types_differ', self.codes(self.validate(), vi.ERROR))

    def test_different_names_between_products_are_a_warning(self):
        self.edit_fsp('Q', lambda df: df.assign(name=df['name'].replace({'PV 1': 'PV one'})))
        self.assertIn('fsp.names_differ', self.codes(self.validate(), vi.WARNING))

    def test_a_missing_column_is_an_error(self):
        self.edit_fsp('P', lambda df: df.drop(columns=['Pup_cost']))
        self.assertIn('fsp.missing_columns', self.codes(self.validate(), vi.ERROR))

    def test_a_header_on_the_first_row_is_an_error(self):
        path = self.case / 'fsp_files' / 'fsp_P.xlsx'
        write_xlsx(path, fsp_frame(), sheet='fsp_data', startrow=0, index=False)
        self.assertIn('fsp.missing_columns', self.codes(self.validate(), vi.ERROR))

    def test_a_missing_sheet_is_an_error(self):
        self.cfg['network']['fsp']['fsp_sheetname'] = 'other'
        self.assertIn('fsp.sheet_missing', self.codes(self.validate(), vi.ERROR))

    def test_a_missing_file_is_an_error(self):
        (self.case / 'fsp_files' / 'fsp_P.xlsx').unlink()
        self.assertIn('fsp.file_missing', self.codes(self.validate(), vi.ERROR))

    def test_an_unknown_type_is_an_error(self):
        self.edit_fsp('P', lambda df: df.assign(type=df['type'].replace({'B': 'Z'})))
        self.cfg['ProductTAG'] = ['P']
        self.assertIn('fsp.unknown_type', self.codes(self.validate(), vi.ERROR))

    def test_negative_shares_are_an_error_and_negative_prices_a_warning(self):
        self.edit_fsp('P', lambda df: df.assign(Pup=-0.1, Pdown_cost=-5.0))
        findings = self.validate()
        self.assertIn('fsp.negative_share', self.codes(findings, vi.ERROR))
        self.assertIn('fsp.negative_cost', self.codes(findings, vi.WARNING))

    def test_a_zero_rating_is_a_warning(self):
        self.edit_fsp('P', lambda df: df.assign(mva=0.0))
        self.assertIn('fsp.nonpositive_mva', self.codes(self.validate(), vi.WARNING))

    def test_an_aggregator_member_is_a_warning(self):
        self.edit_fsp('P', lambda df: df.assign(aggregator_name='agg1'))
        self.assertIn('fsp.aggregator_not_wired', self.codes(self.validate(), vi.WARNING))

    def test_battery_fsps_need_the_storage_columns(self):
        self.edit_network(lambda net: net.storage.drop(columns=['soc_percent'], inplace=True))
        self.assertIn('network.storage_columns', self.codes(self.validate(), vi.ERROR))


class CommandLineTests(ValidatorCase):
    def run_cli(self, *extra):
        path = self.root / 'config.yaml'
        path.write_text(yaml.safe_dump(self.cfg), encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vi.main([str(path), '--root', str(self.root), *extra])
        return code, out.getvalue()

    def test_a_correct_case_exits_with_zero(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn('0 errors', out)

    def test_an_error_exits_with_one(self):
        self.cfg['ModelTAG'] = 'XX'
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn('[ERROR', out)

    def test_warnings_only_fail_in_strict_mode(self):
        self.cfg['StorageTag'] = ''
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.run_cli('--strict')[0], 1)

    def test_a_missing_configuration_file_exits_with_two(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vi.main([str(self.root / 'nope.yaml')]), 2)

    def test_errors_are_listed_before_warnings(self):
        self.cfg['StorageTag'] = ''
        self.cfg['ModelTAG'] = 'XX'
        lines = [l for l in self.run_cli()[1].splitlines() if l.startswith('[')]
        self.assertTrue(lines[0].startswith('[ERROR'))
        self.assertTrue(lines[-1].startswith('[WARNING'))


@contextlib.contextmanager
def working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def run_real_loaders(root, cfg):
    """Run the platform's own loaders on a case.

    Return None if they all succeed, otherwise a short description of the failure. Only text is returned because an
    exception object keeps its traceback, which keeps the workbooks the loaders left open, and on Windows an open
    file cannot be deleted. The garbage collection afterwards releases them, since the loaders do not close them.
    """
    from enginiite import file_io as io_file
    from enginiite.market.models import fsp_utils
    failure = None
    try:
        with working_directory(root), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            net = io_file.import_network(cfg['network'])
            fsp_tables, _ = io_file.import_fsp_data(cfg['network'])
            io_file.import_profiles(net, cfg['network'], cfg['simulation_window'])
            for table in fsp_tables.values():
                for fsp_type, group in table.groupby('type'):
                    fsp_utils.fsp_labels(group, fsp_type)
                for _, row in table.iterrows():
                    element_table = vi.FSP_TYPE_TABLE.get(row['type'])
                    if element_table is not None:
                        fsp_utils.match_pp_element(getattr(net, element_table), row, element_table)
    except Exception as exc:  # any failure of the loaders counts
        failure = '%s: %s' % (type(exc).__name__, exc)
    gc.collect()
    return failure


def run_set_params(root, cfg):
    """Run the platform's own path and parameter setup on a case. Return None on success, otherwise the failure text."""
    import enginiite.auxiliary as aux
    failure = None
    try:
        with working_directory(root), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            paths = aux.set_paths(_main_root=os.getcwd(), _name_network=cfg['network']['net_folder'],
                                  _model_tag=cfg['ModelTAG'], _product_tags=cfg['ProductTAG'], _vl_tags=cfg['VLTAG'],
                                  _fsp_tags=cfg['FspTAG'], _ess_tag=cfg['StorageTag'], _sim_tag=cfg['simulation_tag'],
                                  _in_root='data_in', _out_root='data_out')
            aux.set_params(_cfg_file=cfg, _path_dict=paths, _vl_tags=cfg['VLTAG'], _fsp_tags=cfg['FspTAG'],
                           _ess_tag=cfg['StorageTag'])
    except Exception as exc:  # any failure counts
        failure = '%s: %s' % (type(exc).__name__, exc)
    gc.collect()
    return failure


class RequiredKeysTests(ValidatorCase):
    """The keys the validator requires must be exactly the keys the platform cannot run without."""

    # keys that set_params reads with cfg[key], so the real function can be used to check them
    READ_BY_SET_PARAMS = ('simulation_window', 'intertemp_cons', 'consecutive_hours', 'only_worst_hour', 'full_network',
                          'timeseries_force_1st_calculation', 'BetaCost', 'only_pilot_busMV', 'vn_kv_mv', 'net_cstr_aggr',
                          'tol_v', 'tol_i', 'tol_v_opt', 'tol_i_opt')
    NETWORK_KEYS_READ_BY_SET_PARAMS = ('ts_output_file_type', 'profile_models', 'fsp_models')

    def test_the_complete_configuration_has_no_missing_key(self):
        self.assertNotIn('config.missing_key', self.codes(self.validate()))

    def test_removing_any_top_level_key_is_reported(self):
        for key in vi.REQUIRED_TOP_KEYS:
            with self.subTest(key=key):
                self.reset()
                del self.cfg[key]
                findings = [f for f in self.validate() if f.code == 'config.missing_key']
                self.assertEqual(len(findings), 1)
                self.assertIn(key, findings[0].message)

    def test_removing_any_network_key_is_reported(self):
        for key in vi.REQUIRED_NETWORK_KEYS:
            with self.subTest(key=key):
                self.reset()
                del self.cfg['network'][key]
                self.assertIn('config.missing_key', self.codes(self.validate(), vi.ERROR))

    def test_removing_any_fsp_key_is_reported(self):
        for key in vi.REQUIRED_FSP_KEYS:
            with self.subTest(key=key):
                self.reset()
                del self.cfg['network']['fsp'][key]
                self.assertIn('config.missing_key', self.codes(self.validate(), vi.ERROR))

    def test_every_required_key_is_read_by_the_platform(self):
        root = Path(__file__).resolve().parents[2]
        files = [f for f in (root / 'src' / 'enginiite').rglob('*.py')
                 if 'visualization' not in f.parts and not f.stem.endswith('_old')]
        text = ''.join(f.read_text(encoding='utf-8', errors='replace') + chr(10) for f in files)
        keys = vi.REQUIRED_TOP_KEYS + vi.REQUIRED_NETWORK_KEYS + vi.REQUIRED_FSP_KEYS
        unused = [k for k in keys if not re.search(r"['\"]%s['\"]" % re.escape(k), text)]
        self.assertEqual(unused, [], 'required by the validator but never read by the platform')

    def test_the_real_setup_runs_with_the_complete_configuration(self):
        self.assertIsNone(run_set_params(self.root, self.cfg))

    def test_the_real_setup_fails_without_each_key_it_reads(self):
        for key in self.READ_BY_SET_PARAMS:
            with self.subTest(key=key):
                self.reset()
                del self.cfg[key]
                self.assertIn('KeyError', run_set_params(self.root, self.cfg) or '')
                self.assertIn('config.missing_key', self.codes(self.validate(), vi.ERROR))
        for key in self.NETWORK_KEYS_READ_BY_SET_PARAMS:
            with self.subTest(key=key):
                self.reset()
                del self.cfg['network'][key]
                self.assertIn('KeyError', run_set_params(self.root, self.cfg) or '')
                self.assertIn('config.missing_key', self.codes(self.validate(), vi.ERROR))


class ContractTests(ValidatorCase):
    """What the validator says must agree with what the platform's own loaders do with the same files.

    Three families:
    * LOADER_FAILS: the validator reports an error AND the real loaders fail on the same files.
    * LATER_STAGE: the validator reports an error that the loaders do not notice; the run would fail later
      (power flow, market). The validator is deliberately stricter here.
    * ACCEPTED: both accept the files.
    """

    LOADER_FAILS = [
        ('m_network_file_missing', 'network.file_missing'),
        ('m_network_corrupt', 'network.unreadable'),
        ('m_network_missing_profile_column', 'network.missing_profile_columns'),
        ('m_profile_file_missing', 'profile.file_missing'),
        ('m_profile_unsupported_format', 'profile.unsupported_format'),
        ('m_profile_sheet_name', 'profile.sheet_name'),
        ('m_profile_too_short', 'profile.too_short'),
        ('m_profile_norm_category_missing', 'profile.norm_category_missing'),
        ('m_profile_missing_file_key', 'profile.missing_file_key'),
        ('m_profile_columns_not_integer', 'profile.columns_not_integer'),
        ('m_fsp_file_missing', 'fsp.file_missing'),
        ('m_fsp_sheet_missing', 'fsp.sheet_missing'),
        ('m_fsp_header_on_first_row', 'fsp.missing_columns'),
        ('m_fsp_unsupported_format', 'fsp.unsupported_format'),
        ('m_fsp_types_differ', 'fsp.types_differ'),
        ('m_fsp_unmatched_name', 'fsp.unmatched'),
        ('m_fsp_unmatched_bus', 'fsp.unmatched'),
        ('m_fsp_duplicated_names', 'fsp.duplicated_names'),
        ('m_fsp_empty_names', 'fsp.empty_names'),
    ]
    LATER_STAGE = [
        ('m_profile_missing_values', 'profile.missing_values'),
        ('m_profile_not_numeric', 'profile.not_numeric'),
        ('m_profile_denorm_missing_columns', 'profile.denorm_missing_columns'),
        ('m_profile_ambiguous', 'profile.ambiguous'),
        ('m_network_no_slack', 'network.no_slack'),
        ('m_network_duplicated_branch_names', 'network.duplicated_branch_names'),
        ('m_fsp_negative_share', 'fsp.negative_share'),
        ('m_fsp_missing_cost_column', 'fsp.missing_columns'),
        ('m_fsp_unknown_type', 'fsp.unknown_type'),
        ('m_config_unknown_model_tag', 'config.unknown_model_tag'),
    ]
    ACCEPTED = ['m_valid', 'm_profile_csv', 'm_fsp_csv']

    # ---- mutations, each one breaks (or changes) a single thing
    def m_valid(self):
        pass

    def m_network_file_missing(self):
        (self.case / 'network' / NET_FILE).unlink()

    def m_network_corrupt(self):
        (self.case / 'network' / NET_FILE).write_text('not a workbook', encoding='utf-8')

    def m_network_missing_profile_column(self):
        self.edit_network(lambda net: net.load.drop(columns=['norm_profile'], inplace=True))

    def m_network_no_slack(self):
        self.edit_network(lambda net: net.ext_grid.drop(net.ext_grid.index, inplace=True))

    def m_network_duplicated_branch_names(self):
        self.edit_network(lambda net: net.line.__setitem__('name', 'same'))

    def m_profile_file_missing(self):
        (self.case / 'profile' / 'profile_sgen_q.xlsx').unlink()

    def m_profile_unsupported_format(self):
        (self.case / 'profile' / 'profile_sgen_q.txt').write_text('0\n', encoding='utf-8')
        self.cfg['network']['profile']['sgen']['q'] = {'denorm': 'profile_sgen_q.txt'}

    def m_profile_sheet_name(self):
        self.write_profile('profile_load_p', pd.DataFrame({'res': np.ones(HOURS)}), sheet='Sheet1')

    def m_profile_too_short(self):
        self.write_profile('profile_load_p', pd.DataFrame({'res': np.ones(10)}))

    def m_profile_norm_category_missing(self):
        self.write_profile('profile_load_p', pd.DataFrame({'other': np.ones(HOURS)}))

    def m_profile_missing_file_key(self):
        self.cfg['network']['profile']['load']['p'] = {}

    def m_profile_columns_not_integer(self):
        self.write_profile('profile_sgen_p', pd.DataFrame({'abc': np.ones(HOURS)}))

    def m_profile_missing_values(self):
        values = np.ones(HOURS)
        values[3] = np.nan
        self.write_profile('profile_load_p', pd.DataFrame({'res': values}))

    def m_profile_not_numeric(self):
        self.write_profile('profile_sgen_p', pd.DataFrame({0: ['x'] * HOURS}))

    def m_profile_denorm_missing_columns(self):
        self.write_profile('profile_sgen_p', pd.DataFrame({5: np.ones(HOURS)}))

    def m_profile_ambiguous(self):
        """The loads get a denormalised profile on top of their normalised one. The files and the configuration
        are completed so that this is the only thing wrong."""
        self.edit_network(lambda net: net.load.__setitem__('denorm_profile', 0.0))
        for product in ('p', 'q'):
            stem = 'profile_load_den_%s' % product
            self.write_profile(stem, pd.DataFrame({0: np.ones(HOURS), 1: np.ones(HOURS)}))
            self.cfg['network']['profile']['load'][product]['denorm'] = stem + '.xlsx'

    def m_profile_csv(self):
        self.write_profile('profile_sgen_q', pd.DataFrame({0: np.zeros(HOURS)}), ext='.csv')
        (self.case / 'profile' / 'profile_sgen_q.xlsx').unlink()
        self.cfg['network']['profile']['sgen']['q'] = {'denorm': 'profile_sgen_q.csv'}

    def m_fsp_file_missing(self):
        (self.case / 'fsp_files' / 'fsp_P.xlsx').unlink()

    def m_fsp_sheet_missing(self):
        self.cfg['network']['fsp']['fsp_sheetname'] = 'other'

    def m_fsp_header_on_first_row(self):
        write_xlsx(self.case / 'fsp_files' / 'fsp_P.xlsx', fsp_frame(), sheet='fsp_data', startrow=0, index=False)

    def m_fsp_unsupported_format(self):
        (self.case / 'fsp_files' / 'fsp_P.txt').write_text('FSP table\n', encoding='utf-8')
        self.cfg['network']['fsp']['fsp_input_filename']['P'] = 'fsp_P.txt'

    def m_fsp_types_differ(self):
        self.edit_fsp('Q', lambda df: df[df['type'] != 'C'])

    def m_fsp_unmatched_name(self):
        self.edit_fsp('P', lambda df: df.assign(name=df['name'].replace({'Load 1': 'Ghost'})))

    def m_fsp_unmatched_bus(self):
        self.edit_fsp('P', lambda df: df.assign(bus=df['bus'].replace({1: 0})))

    def m_fsp_duplicated_names(self):
        self.edit_fsp('P', lambda df: df.assign(name=df['name'].replace({'Load 2': 'Load 1'})))

    def m_fsp_empty_names(self):
        self.edit_fsp('P', lambda df: df.assign(name=df['name'].replace({'Load 2': ' '})))

    def m_fsp_negative_share(self):
        self.edit_fsp('P', lambda df: df.assign(Pup=-0.1))

    def m_fsp_missing_cost_column(self):
        self.edit_fsp('P', lambda df: df.drop(columns=['Pup_cost']))

    def m_fsp_unknown_type(self):
        for product in ('P', 'Q', 'PQ'):  # every file, so the type sets stay equal between products
            self.edit_fsp(product, lambda df: df.assign(type=df['type'].replace({'B': 'Z'})))

    def m_fsp_csv(self):
        path = self.case / 'fsp_files' / 'fsp_P.csv'
        path.write_text('FSP table\n' + fsp_frame().to_csv(index=False), encoding='utf-8')
        (self.case / 'fsp_files' / 'fsp_P.xlsx').unlink()
        self.cfg['network']['fsp']['fsp_input_filename']['P'] = 'fsp_P.csv'

    def m_config_unknown_model_tag(self):
        self.cfg['ModelTAG'] = 'XX'

    # ---- the three families
    def apply(self, mutation):
        self.reset()
        getattr(self, mutation)()

    def test_when_the_loaders_fail_the_validator_reports_an_error(self):
        for mutation, code in self.LOADER_FAILS:
            with self.subTest(mutation=mutation):
                self.apply(mutation)
                self.assertIn(code, self.codes(self.validate(), vi.ERROR))
                error = run_real_loaders(self.root, self.cfg)
                self.assertIsNotNone(error, 'the validator reports %s but the real loaders accepted the files' % code)

    def test_when_the_validator_reports_a_later_stage_error_the_loaders_do_not_notice(self):
        for mutation, code in self.LATER_STAGE:
            with self.subTest(mutation=mutation):
                self.apply(mutation)
                self.assertIn(code, self.codes(self.validate(), vi.ERROR))
                error = run_real_loaders(self.root, self.cfg)
                self.assertIsNone(error, 'the real loaders already fail (%r): move this case to LOADER_FAILS' % (error,))

    def test_files_accepted_by_the_loaders_are_accepted_by_the_validator(self):
        for mutation in self.ACCEPTED:
            with self.subTest(mutation=mutation):
                self.apply(mutation)
                error = run_real_loaders(self.root, self.cfg)
                self.assertIsNone(error, 'the real loaders reject this case: %r' % (error,))
                self.assertEqual(sorted(self.codes(self.validate(), vi.ERROR)), [])


class DocumentationTests(unittest.TestCase):
    """The page docs/reference/validator-codes.md must list exactly the codes the script can emit."""

    DOC = Path(__file__).resolve().parents[2] / 'docs' / 'reference' / 'validator-codes.md'

    @staticmethod
    def emitted_codes():
        import ast
        tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
        codes = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_f'
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
                codes.add(node.args[1].value)
        return codes

    def documented_codes(self):
        import re
        text = self.DOC.read_text(encoding='utf-8')
        return set(re.findall(r'^\| `([a-z]+\.[a-z_]+)` \|', text, flags=re.MULTILINE))

    def test_the_reference_page_exists(self):
        self.assertTrue(self.DOC.is_file())

    def test_every_code_the_script_can_emit_is_documented(self):
        self.assertEqual(sorted(self.emitted_codes() - self.documented_codes()), [])

    def test_no_documented_code_is_obsolete(self):
        self.assertEqual(sorted(self.documented_codes() - self.emitted_codes()), [])

    def test_the_levels_in_the_page_match_the_script(self):
        import re
        text = self.DOC.read_text(encoding='utf-8')
        documented = dict(re.findall(r'^\| `([a-z]+\.[a-z_]+)` \| (ERROR|WARNING|INFO) \|', text, flags=re.MULTILINE))
        import ast
        tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_f'
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[0], ast.Name)):
                with self.subTest(code=node.args[1].value):
                    self.assertEqual(documented.get(node.args[1].value), node.args[0].id)


if __name__ == '__main__':
    unittest.main()
