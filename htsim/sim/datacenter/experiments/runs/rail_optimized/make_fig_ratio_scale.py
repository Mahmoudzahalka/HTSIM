#!/usr/bin/env python3
"""Standalone figure: IB/UET makespan ratio on the rail fabric, 1024 vs 2048 GPUs.

This is fig2's right-hand panel, rebuilt to fix two things:

  1. The dashed parity line at 1.0 was drawn WITHOUT a label, so the legend
     listed 2 entries for a plot containing 3 lines -- the dashed one was the
     unexplained one. It is labelled here.
  2. The original `g()` in make_graphs_rail.py does not filter on `nodes`, so it
     silently returned whichever row came first in the CSV (always 1024). Both
     scales are now selected explicitly and shown together.

Encoding: colour = workload, line style = scale (solid/filled = 1024,
dashed/open = 2048). No new hues, so the palette stays the deck's Okabe-Ito pair.

The 2048/100MB IB cells were `status=incomplete` in results_rail.csv (truncated
runs). The completed re-runs are read from the .row files and override the CSV,
so the 100MB points are real makespans rather than partial-run underestimates.
"""
import csv, glob, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = os.path.dirname(os.path.abspath(__file__))          # portable, unlike the old hardcoded path
OUT = os.path.join(D, "graphs"); os.makedirs(OUT, exist_ok=True)

HDR = open(os.path.join(D, "results_rail.csv")).readline().strip().split(",")
data = {}
def key(r): return (r["workload"], r["size_MB"], r["nodes"], r["stack"], r["topology"])
for r in csv.DictReader(open(os.path.join(D, "results_rail.csv"))):
    data[key(r)] = r
# completed re-runs win over any incomplete CSV row for the same cell
for f in sorted(glob.glob(os.path.join(D, "*", "rows", "*.row"))):
    r = dict(zip(HDR, open(f).read().strip().split(",")))
    if r.get("status") == "ok":
        data[key(r)] = r

SIZES = [16, 64, 100]
WL = [("allreduce_rail_aware", "rail-aware all-reduce", "#111111", "o"),
      ("alltoall_moe_rail_aware", "rail-aware all-to-all (MoE)", "#009E73", "s")]
SCALE = [(1024, "-", True), (2048, "--", False)]        # (nodes, linestyle, filled marker)

def ratio(wl, sz, n):
    try:
        ib = data[(wl, str(sz), str(n), "ib", "rail")]
        ue = data[(wl, str(sz), str(n), "uet", "rail")]
    except KeyError:
        return np.nan
    if ib["status"] != "ok" or ue["status"] != "ok":     # never plot a truncated run
        return np.nan
    return float(ib["makespan_us"]) / float(ue["makespan_us"])

plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": .25,
    "grid.linewidth": .6, "axes.axisbelow": True, "axes.edgecolor": "#888",
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.dpi": 200})

fig, ax = plt.subplots(figsize=(11.6, 5.0))
x = np.arange(len(SIZES))

# parity reference -- LABELLED, so the legend accounts for every line drawn
ax.axhline(1.0, color="#888888", ls=":", lw=1.6, label="parity — IB = UET", zorder=1)

for wl, lab, c, mk in WL:
    for n, ls, filled in SCALE:
        y = [ratio(wl, s, n) for s in SIZES]
        ax.plot(x, y, ls=ls, marker=mk, lw=2.0, ms=9, color=c, zorder=3,
                markerfacecolor=c if filled else "white",
                markeredgecolor=c, markeredgewidth=1.8,
                label=f"{lab} — {n} GPUs")

# selective direct labels: only the MoE 100 MB endpoints, which is the reversal
for n, dy, ha in [(1024, -0.20, "center"), (2048, 0.16, "center")]:
    v = ratio("alltoall_moe_rail_aware", 100, n)
    ax.annotate(f"{v:.2f}", (x[-1], v), textcoords="offset points",
                xytext=(0, dy * 100), ha=ha, fontsize=10, fontweight="bold", color="#009E73")

ax.text(0.015, 0.965, "IB slower ↑", transform=ax.transAxes, fontsize=9, color="#666", va="top")
ax.text(0.015, 0.035, "IB faster ↓", transform=ax.transAxes, fontsize=9, color="#666", va="bottom")

ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
ax.set_xlabel("per-GPU collective volume")
ax.set_ylabel("makespan ratio   IB / UET   (rail fabric)")
ax.set_ylim(0, 4.6); ax.set_xlim(-0.25, len(SIZES) - 0.75)
# no in-figure title: the slide header carries it, and repeating it wastes plot height
ax.legend(fontsize=10, frameon=False, loc="center left", ncol=1)
for s in ("top", "right"): ax.spines[s].set_visible(False)

fig.tight_layout()
p = os.path.join(OUT, "fig4_ratio_ib_uet_1024_vs_2048.png")
fig.savefig(p, bbox_inches="tight"); plt.close(fig)
print("wrote", p)
for wl, lab, _, _ in WL:
    for n, _, _ in SCALE:
        print(f"  {lab:<28} {n:>5} GPUs: " + "  ".join(f"{s}MB={ratio(wl,s,n):.2f}" for s in SIZES))
