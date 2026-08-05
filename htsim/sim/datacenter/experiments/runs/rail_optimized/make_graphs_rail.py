#!/usr/bin/env python3
"""Figures for the rail-optimized sweep. Same Okabe-Ito style as the other decks.

NOTE (updated once the 2048 grid completed): the previous version of g() matched
only on (workload, size, stack, topology) and returned the FIRST matching row.
That was fine while the CSV held 1024 GPUs only, but once 2048 rows were appended
it silently returned the 1024 row every time -- half the grid vanished from the
plots. g() now takes an explicit `n` (node count) and every figure carries both
scales. Titles are derived from the data rather than hardcoded, because the
2048 results contradict two of the old hardcoded claims.
"""
import csv, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = "/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs/rail_optimized"
OUT = os.path.join(D, "graphs"); os.makedirs(OUT, exist_ok=True)
rows = list(csv.DictReader(open(os.path.join(D, "results_rail.csv"))))
SIZES = [16, 64, 100]
SCALES = [1024, 2048]
WL = [("allreduce_rail_aware", "rail-aware all-reduce"),
      ("alltoall_moe_rail_aware", "rail-aware all-to-all (MoE)")]
IBC, UETC = "#0072B2", "#D55E00"

def g(wl, n, sz, st, tp, f="makespan_us"):
    for r in rows:
        if (r["workload"] == wl and r["nodes"] == str(n) and r["size_MB"] == str(sz)
                and r["stack"] == st and r["topology"] == tp):
            return float(r[f])
    return np.nan

plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": .25,
    "grid.linewidth": .6, "axes.axisbelow": True, "axes.edgecolor": "#888",
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.dpi": 150})
def clean(ax):
    for s in ("top", "right"): ax.spines[s].set_visible(False)

# ---- fig 1: makespan, rail vs flat -- rows = scale, cols = workload ----
fig, axes = plt.subplots(2, 2, figsize=(13, 8.6))
for row_i, n in enumerate(SCALES):
    for col_i, (wl, title) in enumerate(WL):
        ax = axes[row_i][col_i]
        x = np.arange(len(SIZES)); w = 0.2
        for i, (st, tp, c, hatch, lab) in enumerate([
                ("ib", "flat", IBC, "//", "IB — flat"), ("ib", "rail", IBC, "", "IB — rail"),
                ("uet", "flat", UETC, "//", "UET — flat"), ("uet", "rail", UETC, "", "UET — rail")]):
            ax.bar(x + (i - 1.5) * w, [g(wl, n, s, st, tp) / 1000 for s in SIZES], w,
                   color=c, alpha=.55 if hatch else 1.0, hatch=hatch, edgecolor="white", label=lab)
        ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
        ax.set_title(f"{title} — {n} GPUs", fontsize=11)
        ax.set_ylabel("makespan (ms)"); clean(ax)
axes[0][0].legend(fontsize=8.5, frameon=False, ncol=2)
fig.suptitle("Rail-optimized vs shape-matched flat control (NVLink enabled in all 48 runs)",
             fontsize=13, y=1.00)
fig.tight_layout(); fig.savefig(f"{OUT}/fig1_rail_vs_flat.png", bbox_inches="tight"); plt.close(fig)

# ---- fig 2: rail benefit (%), one panel per scale ----
fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
for ax, n in zip(axes, SCALES):
    x = np.arange(len(SIZES)); w = 0.35
    for i, (st, c, lab) in enumerate([("ib", IBC, "IB"), ("uet", UETC, "UET")]):
        for j, (wl, _t) in enumerate(WL):
            vals = [(g(wl, n, s, st, "rail") / g(wl, n, s, st, "flat") - 1) * 100 for s in SIZES]
            ax.bar(x + (i * 2 + j - 1.5) * w / 2, vals, w / 2, color=c,
                   alpha=1.0 if j == 0 else .55, edgecolor="white",
                   label=f"{lab} — {'AR' if j == 0 else 'MoE'}")
    ax.axhline(0, color="#444", lw=1)
    ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
    ax.set_title(f"{n} GPUs", fontsize=11); clean(ax)
axes[0].set_ylabel("makespan change: rail vs flat (%)")
axes[0].legend(fontsize=8, frameon=False, ncol=2)
fig.suptitle("Rails help IB on all 24 IB runs; UET gains only on MoE — and more so at scale",
             fontsize=13, y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig2_rail_benefit.png", bbox_inches="tight"); plt.close(fig)

# ---- fig 3: congestion cost on the rail fabric, both scales ----
fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
x = np.arange(len(SIZES)); w = 0.2
for j, (wl, title) in enumerate(WL):
    for k, n in enumerate(SCALES):
        idx = j * 2 + k
        axes[0].bar(x + (idx - 1.5) * w,
                    [g(wl, n, s, "ib", "rail", "pfc_pause_us") / 1000 for s in SIZES], w,
                    color=IBC, alpha=1.0 if j == 0 else .55,
                    hatch="" if k == 0 else "//", edgecolor="white",
                    label=f"{'AR' if j == 0 else 'MoE'} — {n}")
        axes[1].bar(x + (idx - 1.5) * w,
                    [g(wl, n, s, "uet", "rail", "Rtx") / 1e6 for s in SIZES], w,
                    color=UETC, alpha=1.0 if j == 0 else .55,
                    hatch="" if k == 0 else "//", edgecolor="white",
                    label=f"{'AR' if j == 0 else 'MoE'} — {n}")
for ax, yl, t in [(axes[0], "PFC pause-time (ms)", "IB pays in back-pressure"),
                  (axes[1], "retransmitted packets (millions)", "UET pays in retransmissions")]:
    ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
    ax.set_ylabel(yl); ax.set_title(t, fontsize=11)
    ax.legend(fontsize=8, frameon=False, ncol=2); clean(ax)
fig.suptitle("Congestion cost on the rail fabric — two different currencies", fontsize=13, y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig3_rail_congestion_cost.png", bbox_inches="tight"); plt.close(fig)

# ---- fig 4: IB/UET makespan ratio on the rail fabric, both scales ----
fig, ax = plt.subplots(figsize=(7.2, 4.8))
x = np.arange(len(SIZES))
for j, (wl, title) in enumerate(WL):
    for k, n in enumerate(SCALES):
        ax.plot(x, [g(wl, n, s, "ib", "rail") / g(wl, n, s, "uet", "rail") for s in SIZES],
                marker="o" if j == 0 else "s", lw=2, ms=8,
                ls="-" if k == 0 else "--",
                color="#111111" if j == 0 else "#009E73",
                label=f"{'all-reduce' if j == 0 else 'all-to-all (MoE)'} — {n}")
ax.axhline(1.0, color="#444", ls=":", lw=1.2)
ax.text(0.02, 1.03, "IB slower ↑", transform=ax.transAxes, fontsize=8, color="#666")
ax.text(0.02, 0.02, "IB faster ↓", transform=ax.transAxes, fontsize=8, color="#666")
ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
ax.set_ylabel("makespan ratio  IB / UET"); ax.set_ylim(0, 4.4)
ax.set_title("MoE closes the gap, but IB's 100 MB win\nat 1024 does not survive to 2048", fontsize=11)
# handlelength must exceed the marker width or the ms=8 marker covers the whole
# handle and every entry looks solid -- which hides the 1024/2048 dash coding.
# Park the legend in the empty mid band (y ~ 1.6-3.0) so it clears both the data
# and the "IB faster" annotation in the lower-left.
ax.legend(fontsize=8.5, frameon=False, loc="center left", handlelength=3.6,
          markerscale=0.85, labelspacing=0.7); clean(ax)
fig.tight_layout(); fig.savefig(f"{OUT}/fig4_ib_uet_ratio.png", bbox_inches="tight"); plt.close(fig)

print("wrote:")
for f in sorted(os.listdir(OUT)):
    if f.endswith(".png"): print("  ", os.path.join(OUT, f))
