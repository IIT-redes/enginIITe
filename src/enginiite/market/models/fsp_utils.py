import pandas as pd


def fsp_labels(_fsp_df, _class_fsp):
    """Return stable, unique FSP labels for market rows and sensitivity rows."""
    if 'name' not in _fsp_df.columns:
        raise ValueError(f"FSP type {_class_fsp} has no 'name' column to use as unique identifier.")

    raw_labels = _fsp_df['name']
    missing_labels = raw_labels.isna() | raw_labels.astype(str).str.strip().eq('')
    if missing_labels.any():
        raise ValueError(f"FSP type {_class_fsp} contains empty names. Each FSP needs a unique name.")

    labels = raw_labels.astype(str)
    duplicated = labels[labels.duplicated()].unique().tolist()
    if duplicated:
        raise ValueError(
            f"FSP type {_class_fsp} contains duplicated names {duplicated}. "
            "Use unique names so FSPs connected to the same bus are not overwritten."
        )
    return pd.Index(labels, name='fsp_name')


def fsp_bus_series(_fsp_df, _labels):
    """Keep FSP identity in the index and electrical bus location in the values."""
    return pd.Series(_fsp_df['bus'].to_numpy(), index=_labels, name='bus')


def fsp_frame(_data, _labels, _hours):
    return pd.DataFrame(_data, index=_labels, columns=_hours)


def match_pp_element(_net_table, _fsp_row, _element_name):
    """Resolve one pandapower element by actual table index, using name plus bus."""
    matches = _net_table.index[_net_table['name'].astype(str) == str(_fsp_row['name'])]
    if 'bus' in _net_table.columns and 'bus' in _fsp_row.index:
        bus_matches = _net_table.index[_net_table['bus'] == _fsp_row['bus']]
        matches = matches.intersection(bus_matches)

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {_element_name} element for FSP '{_fsp_row['name']}' "
            f"at bus {_fsp_row.get('bus', 'unknown')}, found {len(matches)}."
        )
    return matches[0]
