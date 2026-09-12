"""Shared chart styling for the analysis notebooks.

One place for the palette and matplotlib defaults so every notebook in the
project renders as one visual system.

Colour rules followed here
--------------------------
- Categorical hues are assigned in a fixed order and never cycled; past 8
  series, fold into "Other" rather than generating a new hue.
- Sequential (magnitude) encoding uses a single hue, light to dark.
- Diverging (polarity, e.g. growth above/below zero) uses blue vs red with a
  neutral grey midpoint.
- Text always wears ink tokens, never the series colour.

Usage::

    from src.viz import *
    apply_style()
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

# --- categorical slots (fixed order) --------------------------------------
SERIES = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = SERIES

# --- single-hue sequential ramp (light -> dark) ---------------------------
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#256abf", "#184f95", "#0d366b"]
BLUE_LIGHT = BLUE_RAMP[1]
SEQ_CMAP = LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP)

# --- diverging pair (growth up / down) ------------------------------------
POS, NEG, MID = "#2a78d6", "#e34948", "#f0efec"

# --- ink & surface --------------------------------------------------------
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#8a8983"
SURFACE = "#fcfcfb"
GRID = "#e3e2de"


def apply_style() -> None:
    """Apply the project's matplotlib defaults."""
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.prop_cycle": plt.cycler(color=SERIES),
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "font.size": 10,
        "figure.dpi": 110,
        "savefig.facecolor": SURFACE,
    })


def despine(ax, keep=("left", "bottom")) -> None:
    """Remove chart spines that carry no information."""
    for side in ("top", "right", "left", "bottom"):
        if side not in keep:
            ax.spines[side].set_visible(False)


def brl(value, _pos=None) -> str:
    """Format a number as Brazilian reais for axis ticks."""
    if abs(value) >= 1_000_000:
        return f"R${value/1_000_000:,.1f}M"
    if abs(value) >= 1_000:
        return f"R${value/1_000:,.0f}k"
    return f"R${value:,.0f}"


__all__ = [
    "SERIES", "BLUE", "ORANGE", "AQUA", "YELLOW", "MAGENTA", "GREEN", "VIOLET", "RED",
    "BLUE_RAMP", "BLUE_LIGHT", "SEQ_CMAP", "POS", "NEG", "MID",
    "INK", "INK_2", "INK_3", "SURFACE", "GRID",
    "apply_style", "despine", "brl",
]
