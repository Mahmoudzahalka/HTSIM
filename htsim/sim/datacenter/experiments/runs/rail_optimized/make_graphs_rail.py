#!/usr/bin/env python3
"""Figures for the rail-optimized sweep. Same Okabe-Ito style as the other decks."""
import csv, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = "/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs/rail_optimized"
OUT = os.path.join(D, "graphs"); os.makedirs(OUT, exist_ok=True)
rows = list(csv.DictReader(open(os.path.join(D, "results_rail.csv"))))
SIZES = [16, 64, 100]
WL = [("allreduce_rail_aware", "rail-aware all-reduce"),
      ("alltoall_moe_rail_aware", "rail-aware all-to-all (MoE)")]
IBC, UETC = "#0072B2", "#D55E00"

def g(wl, sz, st, tp, f="makespan_us"):
    for r in rows:
        if (r["workload"] == wl and r["size_MB"] == str(sz)
                and r["stack"] == st and r["topology"] == tp):
            return float(r[f])
    return np.nan

plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": .25,
    "grid.linewidth": .6, "axes.axisbelow": True, "axes.edgecolor": "#888",
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.dpi": 150})
def clean(ax):
    for s in ("top", "right"): ax.spines[s].set_visible(False)

# ---- fig 1: makespan, rail vs flat, grouped bars, one panel per workload ----
fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
for ax, (wl, title) in zip(axes, WL):
    x = np.arange(len(SIZES)); w = 0.2
    for i, (st, tp, c, hatch, lab) in enumerate([
            ("ib", "flat", IBC, "//", "IB — flat"), ("ib", "rail", IBC, "", "IB — rail"),
            ("uet", "flat", UETC, "//", "UET — flat"), ("uet", "rail", UETC, "", "UET — rail")]):
        ax.bar(x + (i - 1.5) * w, [g(wl, s, st, tp) / 1000 for s in SIZES], w,
               color=c, alpha=.55 if hatch else 1.0, hatch=hatch, edgecolor="white", label=lab)
    ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
    ax.set_title(title, fontsize=11); ax.set_ylabel("makespan (ms)"); clean(ax)
axes[0].legend(fontsize=8.5, frameon=False, ncol=2)
fig.suptitle("Rail-optimized vs shape-matched flat control (NVLink enabled in all runs)", fontsize=13, y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig1_rail_vs_flat.png", bbox_inches="tight"); plt.close(fig)

# ---- fig 2: rail benefit (%) + IB/UET ratio ----
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
x = np.arange(len(SIZES)); w = 0.35
for i, (st, c, lab) in enumerate([("ib", IBC, "IB"), ("uet", UETC, "UET")]):
    for j, (wl, title) in enumerate(WL):
        vals = [(g(wl, s, st, "rail") / g(wl, s, st, "flat") - 1) * 100 for s in SIZES]
        axes[0].bar(x + (i * 2 + j - 1.5) * w / 2, vals, w / 2, color=c,
                    alpha=1.0 if j == 0 else .55, edgecolor="white",
                    label=f"{lab} — {'AR' if j==0 else 'MoE'}")
axes[0].axhline(0, color="#444", lw=1)
axes[0].set_xticks(x); axes[0].set_xticklabels([f"{s} MB" for s in SIZES])
axes[0].set_ylabel("makespan change: rail vs flat (%)")
axes[0].set_title("Rails help IB on every run; UET is indifferent", fontsize=11)
axes[0].legend(fontsize=8, frameon=False, ncol=2); clean(axes[0])

for j, (wl, title) in enumerate(WL):
    axes[1].plot(x, [g(wl, s, "ib", "rail") / g(wl, s, "uet", "rail") for s in SIZES],
                 marker="o" if j == 0 else "s", lw=2, ms=8,
                 color="#111111" if j == 0 else "#009E73", label=title)
axes[1].axhline(1.0, color="#444", ls="--", lw=1)
axes[1].text(0.02, 1.05, "IB slower ↑", transform=axes[1].transAxes, fontsize=8, color="#666")
axes[1].text(0.02, 0.02, "IB faster ↓", transform=axes[1].transAxes, fontsize=8, color="#666")
axes[1].set_xticks(x); axes[1].set_xticklabels([f"{s} MB" for s in SIZES])
axes[1].set_ylabel("makespan ratio  IB / UET"); axes[1].set_ylim(0, 4.3)
axes[1].set_title("On MoE the stacks converge — IB wins at 100 MB", fontsize=11)
axes[1].legend(fontsize=9, frameon=False); clean(axes[1])
fig.tight_layout(); fig.savefig(f"{OUT}/fig2_rail_benefit_and_ratio.png", bbox_inches="tight"); plt.close(fig)

# ---- fig 3: each stack's congestion cost on the rail fabric ----
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
x = np.arange(len(SIZES)); w = 0.35
for j, (wl, title) in enumerate(WL):
    axes[0].bar(x + (j - .5) * w, [g(wl, s, "ib", "rail", "pfc_pause_us") / 1000 for s in SIZES],
                w, color=IBC, alpha=1.0 if j == 0 else .55, edgecolor="white", label=title)
    axes[1].bar(x + (j - .5) * w, [g(wl, s, "uet", "rail", "Rtx") / 1e6 for s in SIZES],
                w, color=UETC, alpha=1.0 if j == 0 else .55, edgecolor="white", label=title)
for ax, yl, t in [(axes[0], "PFC pause-time (ms)", "IB pays in back-pressure"),
                  (axes[1], "retransmitted packets (millions)", "UET pays in retransmissions")]:
    ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in SIZES])
    ax.set_ylabel(yl); ax.set_title(t, fontsize=11); ax.legend(fontsize=8.5, frameon=False); clean(ax)
fig.suptitle("Congestion cost on the rail fabric — two different currencies", fontsize=13, y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig3_rail_congestion_cost.png", bbox_inches="tight"); plt.close(fig)

print("wrote:")
for f in sorted(os.listdir(OUT)):
    if f.endswith(".png"): print("  ", os.path.join(OUT, f))
