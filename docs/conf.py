"""Sphinx configuration for the enginIITe documentation.

The pages are written in Markdown and read with MyST. The solver and the
power flow library are never imported while the documentation is built, so
the build needs neither a Gurobi licence nor the simulation environment.
"""

project = "enginIITe"
copyright = "enginIITe contributors"

extensions = [
    "myst_parser",
]

exclude_patterns = [
    "_build",
    "requirements.txt",
]

source_suffix = {
    ".md": "markdown",
}

myst_heading_anchors = 3

# Equations in the model pages are written with $...$ and $$...$$.
myst_enable_extensions = [
    "dollarmath",
    "amsmath",
]

html_theme = "furo"
html_title = "enginIITe"

# Needed once the API reference is generated from the docstrings. The package
# is not importable yet, so the list is prepared and the extension stays off.
autodoc_mock_imports = [
    "gurobipy",
    "pandapower",
]
