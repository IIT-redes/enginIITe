"""Visualization package.

The Plotly template is registered as the
process default here, once, instead of being passed to every figure.

Passing the template name to ``update_layout`` makes Plotly construct
and deep-copy a fresh Template object for that figure.  Measured on this
machine that is 21.2 ms per figure against 0.9 ms when the template is the
registered default, and one run of this platform writes over seven hundred
figures.  Setting it in the package __init__ guarantees the default is in place
before any submodule builds its first figure, whichever entry point is used.
"""

try:
    import plotly.io as _pio

    _pio.templates.default = "plotly_white"
except Exception:  # pragma: no cover - plotly is optional for some entry points
    pass

try:
    from .showcase import generate_showcase
except Exception:  # pragma: no cover - optional visualization dependency
    generate_showcase = None
