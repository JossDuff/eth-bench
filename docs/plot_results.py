"""Render the README results table as two bar charts.

    uv run --with matplotlib python docs/plot_results.py

Writes docs/results-all.png (every run) and docs/results-open-weight.png (the
open-weight models with and without assists).
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

TITLE = "Ethereum knowledge evaluation"
SUBTITLE = "245 questions, Sept 17th 2026"

# (label, score, family, step)   step 0 = darkest within the family
ALL = [
    ("GPT-6\nAstra", 0.961, "openai", 0),
    ("GPT-5.6\nSol", 0.951, "openai", 1),
    ("Claude\nOpus 5", 0.930, "anthropic", 0),
    ("Claude\nFable 5.1", 0.926, "anthropic", 1),
    ("GPT-5.6\nTerra", 0.891, "openai", 2),
    ("Claude\nSonnet 5", 0.875, "anthropic", 2),
    ("Qwen3.8-27b\n+ wikipethia", 0.794, "qwen", 0),
    ("Gemma 4 26B\n+ wikipethia", 0.719, "gemma", 0),
    ("Qwen3.8-27b\n+ eth-mcp", 0.655, "qwen", 1),
    ("Gemma 4 26B\n+ eth-mcp", 0.558, "gemma", 1),
    ("Qwen3.8-27b", 0.525, "qwen", 2),
    ("Gemma 4 26B", 0.479, "gemma", 2),
]
OPEN_WEIGHT = [r for r in ALL if r[2] in ("qwen", "gemma")]
# The full chart shows one assisted run per open-weight model, the strongest.
FULL = [r for r in ALL if "eth-mcp" not in r[0]]

# Validated with the dataviz palette checker: lightness band, chroma, CVD and
# normal-vision separation for adjacent bars all pass.
FAMILIES = {
    "openai": ("OpenAI", ["#0f6e47", "#33ab78", "#57c28e"]),
    "anthropic": ("Anthropic", ["#9c3a10", "#d9622e", "#f08c50"]),
    "qwen": ("Qwen (Alibaba, open weight)", ["#1f5aa8", "#2a78d6", "#5b9be6"]),
    "gemma": ("Gemma (Google, open weight)", ["#a37600", "#c48f00", "#e0a800"]),
}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e2"


def rounded_bar(ax, x, height, width, color):
    """A bar with a 4px-ish rounded top and a square base, like the mark spec."""
    r = 0.012  # rounding radius in data units (y axis is 0..1)
    ax.add_patch(
        FancyBboxPatch(
            (x - width / 2, 0), width, height,
            boxstyle=f"round,pad=0,rounding_size={r}",
            linewidth=0, facecolor=color, mutation_aspect=1, clip_on=False,
        )
    )
    # square off the base: cover the bottom rounding with a flat rectangle
    ax.add_patch(plt.Rectangle((x - width / 2, 0), width, min(r * 2, height), linewidth=0, facecolor=color))


def draw(rows, out, width_in):
    plt.rcParams.update({
        "font.family": ["Inter", "Noto Sans", "DejaVu Sans"],
        "axes.edgecolor": GRID, "axes.labelcolor": INK2,
        "xtick.color": INK, "ytick.color": INK2,
    })
    fig, ax = plt.subplots(figsize=(width_in, 6.2), dpi=200)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)

    xs = range(len(rows)); bar_w = 0.62
    for i, (label, score, fam, step) in zip(xs, rows):
        color = FAMILIES[fam][1][step]
        rounded_bar(ax, i, score, bar_w, color)
        ax.text(i, score + 0.012, f"{score:.3f}", ha="center", va="bottom", fontsize=10.5, color=INK, fontweight="semibold")

    ax.set_xlim(-0.6, len(rows) - 0.4); ax.set_ylim(0, 1.0)
    ax.set_xticks(list(xs)); ax.set_xticklabels([r[0] for r in rows], fontsize=9.5, color=INK)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0]); ax.set_yticklabels(["0", "0.2", "0.4", "0.6", "0.8", "1.0"], fontsize=9.5)
    ax.set_ylabel("Score (mean of section scores)", fontsize=10, color=INK2, labelpad=8)
    ax.yaxis.grid(True, color=GRID, linewidth=1); ax.set_axisbelow(True)
    for side in ("top", "right", "left"): ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID); ax.tick_params(axis="both", length=0)

    fig.text(0.02, 0.965, TITLE, fontsize=17, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.02, 0.915, SUBTITLE, fontsize=11, color=INK2, ha="left", va="top")

    present = [f for f in FAMILIES if any(r[2] == f for r in rows)]
    handles = [Patch(facecolor=FAMILIES[f][1][1], label=FAMILIES[f][0], linewidth=0) for f in present]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9.5, labelcolor=INK2, handlelength=1.2, handleheight=1.0, borderaxespad=0.2)

    fig.subplots_adjust(left=0.075, right=0.985, top=0.84, bottom=0.17)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    here = Path(__file__).parent
    draw(FULL, here / "results-all.png", 12)
    draw(OPEN_WEIGHT, here / "results-open-weight.png", 9)
