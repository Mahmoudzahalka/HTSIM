#!/usr/bin/env python3
"""
fidelityRuns -- the full figure set for the DGX H100 (400 G fabric, NVLink4 3600 G)
five-seed sweep. Every point is a mean over 5 seeds; every error bar is a t-based
95% CI (n=5 -> t=2.776).

  python3 bin/make_figures.py        -> graphs/*.png  +  results/deck_numbers.json
"""
import json, math, os, statistics as st, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import fidelity_data as fd

OUT = os.path.join(fd.FID, "graphs"); os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "savefig.dpi": 150,
                     "savefig.bbox": "tight"})
cells = fd.load(); ix = fd.index(cells)
NUMS = {}

def save(fig, name):
    fig.savefig(os.path.join(OUT, name)); plt.close(fig); print("  ", name)

def get(fam, wl, n, sz, stk, topo): return ix.get((fam, wl, n, sz, stk, topo))

def per_run(c, fn): return [fn(r) for r in c.rows]
def trim_rate(r):
    d = float(r["New"]) + float(r["Rtx"]); return 100 * float(r["NACKs"]) / d if d else 0.0

FLAT_WLS = {"ib": ["perm_random", "perm_fullbis", "incast_random", "incast_remote",
                   "outcast_incast", "a2a_concurrent", "allreduce_ring"],
            "uet": ["perm_random", "perm_fullbis", "incast_random", "incast_remote",
                    "outcast_incast", "a2a_concurrent", "allreduce_ring"]}

# =========================================================================
# FLAT FABRIC
# =========================================================================
def os_panels(stack, nodes, metric_fn, ylabel, title, fname, log=True, scale=1.0, wls=None, ymin0=False):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), sharey=log)
    any_pt = False
    for ax, sz in zip(axes, fd.SIZES):
        for wl in (wls or FLAT_WLS[stack]):
            xs, ys, es = [], [], []
            for i, o in enumerate(fd.OS_ORDER):
                c = get("flat", wl, nodes, sz, stack, o)
                if not c: continue
                m, sd, h = fd.tci([v * scale for v in per_run(c, metric_fn)])
                xs.append(i); ys.append(m); es.append(h)
            if xs:
                any_pt = True
                ax.errorbar(xs, ys, yerr=es, marker=fd.WL_M[wl], color=fd.WL_C[wl], lw=2, ms=7,
                            capsize=4, label=fd.WL_LABEL[wl])
        ax.set_xticks(range(3)); ax.set_xticklabels([fd.OS_LABEL[o] for o in fd.OS_ORDER])
        ax.set_title(f"{sz} MB flows"); ax.set_xlabel("oversubscription")
        if log: ax.set_yscale("log")
        if ymin0: ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
    axes[0].set_ylabel(ylabel)
    h, l = axes[0].get_legend_handles_labels()
    for ax in axes[1:]:
        hh, ll = ax.get_legend_handles_labels()
        for a, b in zip(hh, ll):
            if b not in l: h.append(a); l.append(b)
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=len(l), frameon=False, fontsize=10)
    missing = collections.defaultdict(list)
    for wl in (wls or FLAT_WLS[stack]):
        if not any(get("flat", wl, nodes, sz, stack, o) for sz in fd.SIZES for o in fd.OS_ORDER): continue
        for o in fd.OS_ORDER:
            gone = [sz for sz in fd.SIZES if not get("flat", wl, nodes, sz, stack, o)]
            if gone: missing[wl].append((o, gone))
    if missing:
        parts = []
        for wl, lst in missing.items():
            gsets = {tuple(g) for _, g in lst}
            if len(lst) == 3 and len(gsets) == 1:
                gone = list(gsets)[0]
                szs = "all sizes" if len(gone) == 3 else "/".join(str(x) for x in gone) + " MB"
                parts.append(f"{fd.WL_LABEL[wl]} at {szs} (all ratios)")
            else:
                for o, gone in lst:
                    szs = "all sizes" if len(gone) == 3 else "/".join(str(x) for x in gone) + " MB"
                    parts.append(f"{fd.WL_LABEL[wl]} at {fd.OS_LABEL[o]} ({szs})")
        fig.text(0.5, -0.14, "Not in the sweep: " + "; ".join(parts), ha="center", fontsize=9.5, color="#555")
    fig.suptitle(title, y=1.02)
    if any_pt: save(fig, fname)
    else: plt.close(fig)

def makespan(r): return float(r["makespan_us"]) / 1000.0

print("flat fabric:")
for stack in ("ib", "uet"):
    for n in (128, 1024):
        os_panels(stack, n, makespan, "makespan (ms, log)",
                  f"{fd.STACK_L[stack]} — makespan vs oversubscription, {n} nodes — mean ± 95% CI, 5 seeds",
                  f"f01_{stack}_makespan_os_{n}.png")

os_panels("uet", 128, trim_rate, "packets trimmed  (% of all transmissions)",
          "UET — packet-trim rate  NACKs / (New + Rtx), 128 nodes — mean ± 95% CI",
          "f02_uet_trim_rate_os_128.png", log=False)
os_panels("uet", 1024, trim_rate, "packets trimmed  (% of all transmissions)",
          "UET — packet-trim rate  NACKs / (New + Rtx), 1024 nodes — mean ± 95% CI",
          "f02_uet_trim_rate_os_1024.png", log=False)
os_panels("ib", 128, lambda r: float(r["pfc_pause_us"]) / 1e6, "PFC pause time  (port-seconds, log)",
          "IB — PFC back-pressure: total pause time, 128 nodes — mean ± 95% CI",
          "f03_ib_pfc_pause_os_128.png")
os_panels("ib", 1024, lambda r: float(r["pfc_pause_us"]) / 1e6, "PFC pause time  (port-seconds, log)",
          "IB — PFC back-pressure: total pause time, 1024 nodes — mean ± 95% CI",
          "f03_ib_pfc_pause_os_1024.png")
os_panels("ib", 128, lambda r: float(r["max_queue_bytes"]) / 1e6, "peak queue occupancy (MB)",
          "IB — peak lossless buffer occupancy, 128 nodes — mean ± 95% CI  (PFC caps it: flat across every workload)",
          "f04_ib_peak_buffer_os_128.png", log=False, ymin0=True)

# ---- fairness + tail slowdown, now valid on BOTH stacks ----
fig, axes = plt.subplots(2, 2, figsize=(14, 8.5), sharex=True)
for col, stack in enumerate(("ib", "uet")):
    for row, (metric, lab, log) in enumerate([("fairness_jain", "Jain fairness (1 = perfectly fair)", False),
                                              ("slowdown_p99", "p99 slowdown  (FCT ÷ ideal, log)", True)]):
        ax = axes[row][col]
        for wl in ["perm_random", "perm_fullbis", "incast_random", "incast_remote", "outcast_incast", "a2a_concurrent"]:
            xs, ys, es = [], [], []
            for i, o in enumerate(fd.OS_ORDER):
                c = get("flat", wl, 128, 64, stack, o)
                if not c: continue
                m, sd, h = c.ci(metric); xs.append(i); ys.append(m); es.append(h)
            if xs: ax.errorbar(xs, ys, yerr=es, marker=fd.WL_M[wl], color=fd.WL_C[wl], lw=2, ms=7,
                               capsize=4, label=fd.WL_LABEL[wl])
        if log: ax.set_yscale("log")
        if row == 0: ax.set_title(fd.STACK_L[stack], color=fd.STACK_C[stack], fontweight="bold")
        if col == 0: ax.set_ylabel(lab)
        ax.set_xticks(range(3)); ax.set_xticklabels([fd.OS_LABEL[o] for o in fd.OS_ORDER])
        if row == 1: ax.set_xlabel("oversubscription")
h, l = axes[0][0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=len(l), frameon=False)
fig.suptitle("Fairness and tail slowdown, 128 nodes, 64 MB flows — mean ± 95% CI, 5 seeds", y=1.0)
save(fig, "f05_fairness_slowdown_both_stacks.png")

# ---- utilization heatmaps (mean over seeds) ----
TIERS = [("tier0_up", "T0 up\n(host→ToR)"), ("tier0_down", "T0 down\n(ToR→host)"),
         ("tier1_up", "T1 up\n(ToR→Agg)"), ("tier1_down", "T1 down\n(Agg→ToR)"),
         ("tier2_up", "T2 up\n(Agg→Core)"), ("tier2_down", "T2 down\n(Core→Agg)")]
for stack in ("ib", "uet"):
    wls = ["perm_random", "perm_fullbis", "incast_random", "incast_remote",
           "outcast_incast", "a2a_concurrent", "allreduce_ring"]
    fig, axes = plt.subplots(2, 4, figsize=(19, 9.5), constrained_layout=True)
    for k, (ax, wl) in enumerate(zip(axes.flat, wls)):
        M = np.full((len(TIERS), 3), np.nan)
        for j, o in enumerate(fd.OS_ORDER):
            c = get("flat", wl, 128, 100, stack, o)
            if not c or not c.urows: continue
            for i, (t, _) in enumerate(TIERS):
                M[i, j] = st.mean(c.util(f"{t}_mean"))
        ax.imshow(M, cmap="Blues", vmin=0, vmax=1, aspect="auto")
        for i in range(len(TIERS)):
            for j in range(3):
                if not np.isnan(M[i, j]):
                    ax.text(j, i, f"{M[i,j]:.2f}", ha="center", va="center", fontsize=9,
                            color="white" if M[i, j] > 0.55 else "black")
        ax.set_title(fd.WL_LABEL[wl]); ax.grid(False)
        ax.set_xticks(range(3)); ax.set_xticklabels([fd.OS_LABEL[o] for o in fd.OS_ORDER])
        ax.set_yticks(range(len(TIERS)))
        ax.set_yticklabels([t[1] for t in TIERS] if k % 4 == 0 else [], fontsize=8.5)
        if np.isnan(M).all():
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values(): sp.set_visible(False)
            ax.text(1, 2.5, "not run at 100 MB\n(exceeded the\nmemory budget)", ha="center",
                    va="center", fontsize=11, color="#666")
    axes.flat[-1].axis("off")
    sm = plt.cm.ScalarMappable(cmap="Blues", norm=plt.Normalize(0, 1))
    fig.colorbar(sm, ax=axes, shrink=0.6, label="mean link utilization", pad=0.01)
    fig.suptitle(f"{fd.STACK_L[stack]} — per-tier link utilization, 128 nodes, 100 MB flows (mean of 5 seeds)")
    save(fig, f"f06_{stack}_util_heatmap_128.png")

# ---- IB vs UET on the flat fabric: ratio with CI, per-seed dots ----
def ratio_rows(fam, wls, nodes_list):
    out = []
    for wl in wls:
        for n in nodes_list:
            for sz in fd.SIZES:
                for o in (fd.OS_ORDER if fam == "flat" else ["rail", "flat"]):
                    a, b = get(fam, wl, n, sz, "ib", o), get(fam, wl, n, sz, "uet", o)
                    if not (a and b): continue
                    ma, mb = a.mean("makespan_us"), b.mean("makespan_us")
                    r = ma / mb
                    _, _, ha = a.ci("makespan_us"); _, _, hb = b.ci("makespan_us")
                    rel = math.hypot(ha / ma, hb / mb)
                    seeds = [x / y for x, y in zip(a.v("makespan_us"), b.v("makespan_us"))]
                    out.append(dict(wl=wl, n=n, sz=sz, o=o, r=r, lo=r * (1 - rel), hi=r * (1 + rel),
                                    seeds=seeds, p=fd.welch_p(a.v("makespan_us"), b.v("makespan_us"))))
    return out

def forest(rows, title, fname, xlabel, ref=1.0, log=True, figsize=None):
    fig, ax = plt.subplots(figsize=figsize or (11, 0.26 * len(rows) + 1.6))
    for i, r in enumerate(rows):
        sig = r["p"] < 0.05
        col = fd.WL_C.get(r["wl"], "#444")
        ax.scatter(r["seeds"], [i] * len(r["seeds"]), s=9, color=col, alpha=0.35, zorder=2)
        ax.errorbar(r["r"], i, xerr=[[r["r"] - r["lo"]], [r["hi"] - r["r"]]], fmt="o",
                    color=col, mfc=col if sig else "white", ms=5.5, capsize=2.5, zorder=3)
    ax.axvline(ref, color="k", lw=1)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{fd.WL_LABEL[r['wl']]}  {r['n']}n {r['sz']}MB {fd.OS_LABEL.get(r['o'], r['o'])}"
                        for r in rows], fontsize=7.5)
    ax.invert_yaxis()
    if log:
        from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator
        ax.set_xscale("log")
        lo = min(min(r["seeds"] + [r["lo"]]) for r in rows); hi = max(max(r["seeds"] + [r["hi"]]) for r in rows)
        ticks = [t for t in (0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10) if lo * 0.9 <= t <= hi * 1.1]
        ax.xaxis.set_major_locator(FixedLocator(ticks)); ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FixedFormatter([f"{t:g}×" for t in ticks]))
    ax.set_xlabel(xlabel); ax.set_title(title, loc="left", fontsize=11)
    save(fig, fname)

print("cross-stack:")
fr = ratio_rows("flat", fd.WL_ORDER, (128, 1024))
from matplotlib.colors import TwoSlopeNorm, LogNorm
rows_hm = [(wl, n) for wl in fd.WL_ORDER for n in (128, 1024) if any(r["wl"] == wl and r["n"] == n for r in fr)]
cols_hm = [(sz, o) for sz in fd.SIZES for o in fd.OS_ORDER]
M = np.full((len(rows_hm), len(cols_hm)), np.nan); P = np.full_like(M, np.nan)
for r in fr:
    i = rows_hm.index((r["wl"], r["n"])); j = cols_hm.index((r["sz"], r["o"]))
    M[i, j] = r["r"]; P[i, j] = r["p"]
fig, ax = plt.subplots(figsize=(13, 7.2))
im = ax.imshow(np.log2(M), cmap="RdBu", vmin=-3.2, vmax=3.2, aspect="auto")
for i in range(M.shape[0]):
    for j in range(M.shape[1]):
        if np.isnan(M[i, j]):
            ax.text(j, i, "—", ha="center", va="center", color="#999"); continue
        txt = f"{M[i,j]:.2f}×" + ("" if P[i, j] < 0.05 else "\nn.s.")
        ax.text(j, i, txt, ha="center", va="center", fontsize=9,
                color="white" if abs(np.log2(M[i, j])) > 1.9 else "black",
                fontweight="bold" if P[i, j] < 0.05 else "normal")
ax.set_xticks(range(len(cols_hm))); ax.set_xticklabels([f"{sz} MB\n{fd.OS_LABEL[o]}" for sz, o in cols_hm])
ax.set_yticks(range(len(rows_hm))); ax.set_yticklabels([f"{fd.WL_LABEL[w]}  ·  {n}" for w, n in rows_hm])
for x in (2.5, 5.5): ax.axvline(x, color="white", lw=3)
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.01)
cb.set_ticks([-3, -2, -1, 0, 1, 2, 3]); cb.set_ticklabels(["IB 8× faster", "4×", "2×", "equal", "2×", "4×", "UET 8× faster"])
ax.set_title("IB ÷ UET makespan on the flat fat-tree (mean of 5 seeds).  Bold = significant (Welch p<0.05); "
             "n.s. = not.  — = not in the sweep.", loc="left", fontsize=10.5)
save(fig, "f07_ib_uet_ratio_flat.png")
NUMS["flat_ratio"] = dict(n=len(fr), sig=sum(r["p"] < 0.05 for r in fr),
                         uet_faster=sum(r["r"] > 1 for r in fr), ib_faster=sum(r["r"] < 1 for r in fr),
                         ib_faster_sig=sum(r["r"] < 1 and r["p"] < 0.05 for r in fr),
                         by_wl={wl: dict(median=st.median([r["r"] for r in fr if r["wl"] == wl]),
                                         lo=min(r["r"] for r in fr if r["wl"] == wl),
                                         hi=max(r["r"] for r in fr if r["wl"] == wl))
                                for wl in fd.WL_ORDER if any(r["wl"] == wl for r in fr)},
                         ib_wins=[(r["wl"], r["n"], r["sz"], r["o"], round(r["r"], 3), r["p"]) for r in fr if r["r"] < 1])

# =========================================================================
# RAIL-OPTIMIZED + NVLINK
# =========================================================================
print("rail:")
RWL = ["allreduce_rail_aware", "alltoall_moe_rail_aware"]
GROUPS = [(n, sz) for n in (1024, 2048) for sz in fd.SIZES]

fig, axes = plt.subplots(1, 2, figsize=(16, 5.4))
for ax, wl in zip(axes, RWL):
    x = np.arange(len(GROUPS)); w = 0.2
    for k, (stk, topo, hatch, alpha) in enumerate([("ib", "flat", "//", 0.5), ("ib", "rail", "", 0.95),
                                                    ("uet", "flat", "//", 0.5), ("uet", "rail", "", 0.95)]):
        ms, hs = [], []
        for n, sz in GROUPS:
            c = get("rail", wl, n, sz, stk, topo); m, sd, h = c.ci("makespan_us"); ms.append(m / 1e3); hs.append(h / 1e3)
        ax.bar(x + (k - 1.5) * w, ms, w, yerr=hs, capsize=2.5, color=fd.STACK_C[stk], alpha=alpha,
               hatch=hatch, edgecolor="white", label=f"{stk.upper()} {topo}")
    ax.set_xticks(x); ax.set_xticklabels([f"{n}\n{sz} MB" for n, sz in GROUPS])
    ax.set_title(fd.WL_LABEL[wl]); ax.set_ylabel("makespan (ms)"); ax.legend(fontsize=9, frameon=False)
fig.suptitle("Rail vs shape-matched flat control (both with NVLink) — mean ± 95% CI, 5 seeds")
save(fig, "f08_rail_vs_flat.png")

# ---- rail benefit: % change with CI and per-seed dots ----
fig, axes = plt.subplots(1, 2, figsize=(16, 5.6), sharey=True)
rail_rows = []
for ax, wl in zip(axes, RWL):
    for k, stk in enumerate(("ib", "uet")):
        for g, (n, sz) in enumerate(GROUPS):
            a, b = get("rail", wl, n, sz, stk, "rail"), get("rail", wl, n, sz, stk, "flat")
            ma, mb = a.mean("makespan_us"), b.mean("makespan_us")
            _, _, ha = a.ci("makespan_us"); _, _, hb = b.ci("makespan_us")
            ch = 100 * (ma / mb - 1); rel = math.hypot(ha / ma, hb / mb) * (ma / mb) * 100
            seeds = [100 * (x / y - 1) for x, y in zip(a.v("makespan_us"), b.v("makespan_us"))]
            p = fd.welch_p(a.v("makespan_us"), b.v("makespan_us"))
            flips = sum((s > 0) != (ch > 0) for s in seeds)
            rail_rows.append(dict(wl=wl, stk=stk, n=n, sz=sz, ch=ch, ci=rel, p=p, seeds=seeds, flips=flips))
            xpos = g + (k - 0.5) * 0.3
            ax.scatter([xpos] * len(seeds), seeds, s=12, color=fd.STACK_C[stk], alpha=0.35, zorder=2)
            ax.errorbar(xpos, ch, yerr=rel, fmt="o", color=fd.STACK_C[stk], ms=7, capsize=3,
                        mfc=fd.STACK_C[stk] if p < 0.05 else "white", zorder=3,
                        label=fd.STACK_L[stk] if g == 0 else None)
    ax.axhline(0, color="k", lw=1)
    ax.set_xticks(range(len(GROUPS))); ax.set_xticklabels([f"{n}\n{sz} MB" for n, sz in GROUPS])
    ax.set_title(fd.WL_LABEL[wl]); ax.legend(frameon=False, fontsize=9)
axes[0].set_ylabel("makespan change, rail vs flat (%)\nbelow 0 = rails faster")
fig.suptitle("How much do rails buy? — filled = significant (Welch p<0.05); faint dots = individual seeds", y=1.0)
save(fig, "f09_rail_benefit.png")
NUMS["rail"] = [dict(r, seeds=[round(s, 2) for s in r["seeds"]]) for r in rail_rows]

# ---- congestion cost on the rail fabric (MoE only; all-reduce is ~0 on both, reported in the title) ----
fig, axes = plt.subplots(1, 2, figsize=(15, 5.2))
ar_note = {}
for ax, (stk, metric, scale, lab) in zip(axes, [("ib", "pfc_pause_us", 1e6, "PFC pause time (port-seconds)"),
                                                ("uet", "Rtx", 1e6, "retransmitted packets (millions)")]):
    x = np.arange(len(fd.SIZES)); w = 0.36
    for k, (n, hatch, alpha) in enumerate([(1024, "", 0.95), (2048, "//", 0.6)]):
        ms, hs = [], []
        for sz in fd.SIZES:
            m, sd, h = fd.tci([v / scale for v in get("rail", "alltoall_moe_rail_aware", n, sz, stk, "rail").v(metric)])
            ms.append(m); hs.append(h)
        b = ax.bar(x + (k - 0.5) * w, ms, w, yerr=hs, capsize=3, color=fd.STACK_C[stk], hatch=hatch,
                   edgecolor="white", alpha=alpha, label=f"MoE all-to-all — {n} GPUs")
        for xi, m, h in zip(x + (k - 0.5) * w, ms, hs):
            ax.text(xi, m + h, f"{m:.1f}", ha="center", va="bottom", fontsize=9.5, fontweight="bold")
    ar = max(get("rail", "allreduce_rail_aware", n, sz, stk, "rail").mean(metric) / scale for n in (1024, 2048) for sz in fd.SIZES)
    ar_note[stk] = ar
    ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in fd.SIZES]); ax.set_ylabel(lab)
    ax.set_title(("IB pays in back-pressure" if stk == "ib" else "UET pays in retransmissions") +
                 f"\n(rail-aware all-reduce: at most {ar:.3g} on this scale, so not shown)",
                 color=fd.STACK_C[stk], fontsize=11)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
for ax in axes: ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
fig.suptitle("Congestion cost on the rail + NVLink cluster, rail topology — mean ± 95% CI, 5 seeds", y=1.07)
save(fig, "f10_rail_congestion_cost.png")
NUMS["rail_cost_ar_max"] = ar_note
NUMS["rail_cost_moe"] = {f"{stk}:{n}:{sz}": get("rail", "alltoall_moe_rail_aware", n, sz, stk, "rail").mean(m) / sc
                         for stk, m, sc in (("ib", "pfc_pause_us", 1e6), ("uet", "Rtx", 1e6))
                         for n in (1024, 2048) for sz in fd.SIZES}

rr = ratio_rows("rail", RWL, (1024, 2048))
forest(rr, "IB ÷ UET makespan on the rail + NVLink cluster — filled = significant (p<0.05)",
       "f11_rail_ib_uet_ratio.png", "IB makespan ÷ UET makespan  (log)", figsize=(15, 7.2))
NUMS["rail_ratio"] = [(r["wl"], r["n"], r["sz"], r["o"], round(r["r"], 3), r["p"]) for r in rr]

# =========================================================================
# WHAT FIVE SEEDS SHOW
# =========================================================================
print("seed analysis:")
flat_cells = [c for c in ix.values()]
# ---- CV of makespan per workload, per stack ----
ALLWL = fd.WL_ORDER + RWL
fig, ax = plt.subplots(figsize=(14, 5.4))
for k, stk in enumerate(("ib", "uet")):
    for i, wl in enumerate(ALLWL):
        cvs = [c.cv("makespan_us") for c in flat_cells if c.wl == wl and c.stack == stk]
        if not cvs: continue
        x = i + (k - 0.5) * 0.34
        ax.boxplot([cvs], positions=[x], widths=0.28, patch_artist=True, showfliers=False,
                   boxprops=dict(facecolor=fd.STACK_C[stk], alpha=0.25), medianprops=dict(color=fd.STACK_C[stk]))
        ax.scatter(np.random.default_rng(i).normal(x, 0.03, len(cvs)), cvs, s=14,
                   color=fd.STACK_C[stk], alpha=0.8, zorder=3, label=fd.STACK_L[stk] if i == 0 else None)
ax.set_xticks(range(len(ALLWL))); ax.set_xticklabels([fd.WL_LABEL[w].replace(" ", "\n", 1) for w in ALLWL], fontsize=9)
ax.set_ylabel("makespan CV across 5 seeds (%)")
ax.set_title("How much does the answer depend on the random seed?  Each dot is one configuration.", loc="left")
ax.legend(frameon=False)
save(fig, "f12_seed_cv_by_workload.png")
cvst = {stk: [c.cv("makespan_us") for c in flat_cells if c.stack == stk] for stk in ("ib", "uet")}
NUMS["cv"] = {stk: dict(median=st.median(v), max=max(v), n=len(v)) for stk, v in cvst.items()}
NUMS["cv_by_wl"] = {f"{stk}:{wl}": dict(median=st.median(v), max=max(v))
                    for stk in ("ib", "uet") for wl in ALLWL
                    for v in [[c.cv("makespan_us") for c in flat_cells if c.wl == wl and c.stack == stk]] if v}

# ---- single-seed spread: most seed-sensitive configurations ----
top = sorted([c for c in flat_cells if c.stack == "ib"], key=lambda c: -c.cv("makespan_us"))[:10] + \
      sorted([c for c in flat_cells if c.stack == "uet"], key=lambda c: -c.cv("makespan_us"))[:4]
fig, ax = plt.subplots(figsize=(12, 6.2))
for i, c in enumerate(top):
    v = c.v("makespan_us"); m = st.mean(v); dev = [100 * (x / m - 1) for x in v]
    ax.plot([min(dev), max(dev)], [i, i], color=fd.STACK_C[c.stack], lw=5, alpha=0.25, solid_capstyle="round")
    ax.scatter(dev, [i] * 5, color=fd.STACK_C[c.stack], s=40, zorder=3)
    ax.text(max(dev) + 0.8, i, f"{max(dev) - min(dev):.0f}% spread", va="center", fontsize=8.5, color="#444")
ax.axvline(0, color="k", lw=1)
ax.set_yticks(range(len(top)))
ax.set_yticklabels([f"{c.stack.upper()}  {fd.WL_LABEL[c.wl]}  {c.nodes}n {c.size}MB {fd.OS_LABEL.get(c.topo, c.topo)}" for c in top], fontsize=8.5)
ax.invert_yaxis(); ax.set_xlabel("each seed's makespan vs the 5-seed mean (%)")
ax.axhline(9.5, color="#999", lw=1, ls="--")
ax.set_title("The single-seed lottery — the 10 most seed-sensitive IB configurations, and the 4 most seed-sensitive UET ones.\n"
             "A single run could land anywhere on its bar.", loc="left", fontsize=11)
save(fig, "f13_single_seed_spread.png")
NUMS["top_spread"] = [(c.stack, c.wl, c.nodes, c.size, c.topo,
                       round(100 * (max(c.v('makespan_us')) - min(c.v('makespan_us'))) / c.mean('makespan_us'), 1),
                       round(c.cv('makespan_us'), 2)) for c in top]

# ---- seeds needed for a given precision ----
def n_needed(cv, e):
    """smallest n with t_{n-1} * cv / sqrt(n) <= e (both in %)."""
    from scipy import stats
    for n in range(2, 2001):
        if stats.t.ppf(0.975, n - 1) * cv / math.sqrt(n) <= e: return n
    return 2000
lab, vals2, vals5, cols = [], [], [], []
fig, axes = plt.subplots(1, 2, figsize=(16, 5.8), sharex=True, gridspec_kw=dict(wspace=0.5))
for ax, stk in zip(axes, ("ib", "uet")):
    L, V5, V2 = [], [], []
    for wl in ALLWL:
        cvs = [c.cv("makespan_us") for c in flat_cells if c.wl == wl and c.stack == stk]
        if not cvs: continue
        worst = max(cvs); L.append(fd.WL_LABEL[wl]); V5.append(n_needed(worst, 5)); V2.append(n_needed(worst, 2))
        lab.append(f"{stk.upper()} {fd.WL_LABEL[wl]}"); vals5.append(V5[-1]); vals2.append(V2[-1])
    y = np.arange(len(L))
    ax.barh(y - 0.2, V5, 0.4, color=fd.STACK_C[stk], alpha=0.95, label="±5% on makespan")
    ax.barh(y + 0.2, V2, 0.4, color=fd.STACK_C[stk], alpha=0.4, label="±2% on makespan")
    for yi, a, b in zip(y, V5, V2):
        ax.text(a * 1.08, yi - 0.2, str(a), va="center", fontsize=8.5)
        ax.text(b * 1.08, yi + 0.2, str(b), va="center", fontsize=8.5, color="#555")
    ax.axvline(5, color="k", ls="--", lw=1); ax.text(5.3, len(L) - 0.35, "we ran 5", fontsize=9)
    from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator
    ax.set_xscale("log"); ax.set_xlim(1, 600)
    tk = [1, 2, 5, 10, 20, 50, 100, 200, 500]
    ax.xaxis.set_major_locator(FixedLocator(tk)); ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FixedFormatter([str(t) for t in tk]))
    ax.set_yticks(y); ax.set_yticklabels(L); ax.invert_yaxis()
    ax.set_title(fd.STACK_L[stk], color=fd.STACK_C[stk], fontweight="bold"); ax.set_xlabel("seeds needed (log)")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
fig.suptitle("Seeds needed for a 95% CI of ±5% / ±2% on makespan — sized for the least stable configuration of each workload", y=1.01)
save(fig, "f14_seeds_needed.png")
NUMS["seeds_needed"] = {l.replace("\n", " "): dict(e5=a, e2=b) for l, a, b in zip(lab, vals5, vals2)}

# ---- which metrics are seed-stable ----
METRICS = [("makespan_us", "makespan"), ("fct_p50_us", "FCT p50"), ("fct_p99_us", "FCT p99"),
           ("slowdown_p99", "slowdown p99"), ("fairness_jain", "Jain fairness"),
           ("Rtx", "retransmits"), ("pfc_pause_us", "PFC pause time"), ("max_queue_bytes", "peak buffer")]
fig, axes = plt.subplots(1, 2, figsize=(19, 6.0), gridspec_kw=dict(wspace=0.55))
for ax, stk in zip(axes, ("ib", "uet")):
    ms = [m for m in METRICS if not (stk == "ib" and m[0] == "Rtx") and not (stk == "uet" and m[0] in ("pfc_pause_us", "max_queue_bytes"))]
    wls = [w for w in ALLWL if any(c.wl == w and c.stack == stk for c in flat_cells)]
    M = np.array([[st.median([c.cv(m) for c in flat_cells if c.wl == w and c.stack == stk]) for m, _ in ms] for w in wls])
    im = ax.imshow(M, cmap="OrRd", vmin=0, vmax=15, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M[i,j]:.1f}", ha="center", va="center", fontsize=8.5,
                    color="white" if M[i, j] > 9 else "black")
    ax.set_xticks(range(len(ms))); ax.set_xticklabels([l for _, l in ms], rotation=35, ha="right")
    ax.set_yticks(range(len(wls))); ax.set_yticklabels([fd.WL_LABEL[w] for w in wls], fontsize=9)
    ax.set_title(fd.STACK_L[stk], color=fd.STACK_C[stk], fontweight="bold"); ax.grid(False)
fig.colorbar(im, ax=axes, shrink=0.8, label="median CV across 5 seeds (%)", pad=0.02)
fig.suptitle("Which metrics can you trust from one run? — median seed-to-seed CV, by workload", y=1.02)
save(fig, "f15_metric_stability.png")
NUMS["metric_cv"] = {stk: {m: st.median([c.cv(m) for c in flat_cells if c.stack == stk]) for m, _ in METRICS}
                     for stk in ("ib", "uet")}

# ---- would one seed have given the wrong ANSWER? ----
def seedwise_flips(pairs):
    """pairs: (label, A cell, B cell). Fraction of the 5 seeds on which A-vs-B disagrees with the 5-seed mean."""
    out = []
    for lab, a, b in pairs:
        d = a.mean("makespan_us") - b.mean("makespan_us")
        per = [x - y for x, y in zip(a.v("makespan_us"), b.v("makespan_us"))]
        out.append((lab, sum((p > 0) != (d > 0) for p in per), fd.welch_p(a.v("makespan_us"), b.v("makespan_us"))))
    return out
rail_pairs = [(f"rail vs flat  {r['stk'].upper()} {fd.WL_LABEL[r['wl']]} {r['n']} {r['sz']}MB",
               get("rail", r["wl"], r["n"], r["sz"], r["stk"], "rail"), get("rail", r["wl"], r["n"], r["sz"], r["stk"], "flat"))
              for r in rail_rows]
stack_pairs = [(f"IB vs UET  {fd.WL_LABEL[r['wl']]} {r['n']}n {r['sz']}MB {fd.OS_LABEL.get(r['o'], r['o'])}",
                get("flat", r["wl"], r["n"], r["sz"], "ib", r["o"]), get("flat", r["wl"], r["n"], r["sz"], "uet", r["o"]))
               for r in fr] + \
              [(f"IB vs UET  {fd.WL_LABEL[r['wl']]} {r['n']} {r['sz']}MB {r['o']}",
                get("rail", r["wl"], r["n"], r["sz"], "ib", r["o"]), get("rail", r["wl"], r["n"], r["sz"], "uet", r["o"]))
               for r in rr]
fl_r, fl_s = seedwise_flips(rail_pairs), seedwise_flips(stack_pairs)
def single_seed_error(pairs, pct_change):
    """For every (config, seed): the effect one run would report minus the 5-seed effect."""
    errs = []
    for lab, a, b in pairs:
        va, vb = a.v("makespan_us"), b.v("makespan_us")
        mean_eff = pct_change(st.mean(va), st.mean(vb))
        errs += [pct_change(x, y) - mean_eff for x, y in zip(va, vb)]
    return errs
rail_err = single_seed_error(rail_pairs, lambda a, b: 100 * (a / b - 1))
stack_err = single_seed_error(stack_pairs, lambda a, b: 100 * math.log(a / b))
fig, axes = plt.subplots(1, 2, figsize=(15, 5))
for ax, errs, fl, name, unit in [
        (axes[0], rail_err, fl_r, "rail benefit (rail vs flat)", "percentage points"),
        (axes[1], stack_err, fl_s, "IB vs UET gap", "%, as a log-ratio")]:
    ax.hist(errs, bins=40, color="#666", alpha=0.85)
    wrong = sum(f for _, f, _ in fl); total = 5 * len(fl)
    q = sorted(abs(e) for e in errs)
    p90 = q[int(0.9 * len(q)) - 1]
    ax.axvline(0, color="k", lw=1)
    ax.set_xlabel(f"single-seed reading minus the 5-seed answer ({unit})"); ax.set_ylabel("single-seed readings")
    ax.set_title(f"{name}:  {len(fl)} comparisons × 5 seeds\n"
                 f"direction wrong in {wrong} of {total} readings  ·  90% of readings within ±{p90:.1f}",
                 loc="left", fontsize=10.5)
fig.suptitle("A single seed almost never gets the DIRECTION wrong — but it misreports the SIZE of the effect", y=1.03)
save(fig, "f16_single_seed_error.png")
NUMS["flips"] = dict(rail=[(l, f, p) for l, f, p in fl_r if f], stack=[(l, f, p) for l, f, p in fl_s if f],
                     rail_total=len(fl_r), stack_total=len(fl_s),
                     rail_err_p90=sorted(abs(e) for e in rail_err)[int(0.9 * len(rail_err)) - 1],
                     rail_err_max=max(abs(e) for e in rail_err),
                     stack_err_p90=sorted(abs(e) for e in stack_err)[int(0.9 * len(stack_err)) - 1],
                     stack_err_max=max(abs(e) for e in stack_err))

# ---- headline counts ----
NUMS["runs_ok"] = sum(c.n for c in cells.values()); NUMS["cells"] = len(cells)
json.dump(NUMS, open(os.path.join(fd.FID, "results", "deck_numbers.json"), "w"), indent=1, default=str)
print("wrote results/deck_numbers.json")
