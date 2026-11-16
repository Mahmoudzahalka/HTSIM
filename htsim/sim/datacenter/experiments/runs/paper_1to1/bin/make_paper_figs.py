#!/usr/bin/env python3
"""
paper_1to1 -- figures for the 1:1-only paper draft.

Every flat-fabric number here is taken from the 1:1 (full-bisection) fat-trees
only (topo_kind == "1os"); no other fabric is read.  Sources:
  * fidelityRuns/results/runs_all.csv + utilization_all.csv  (5 seeds, 400 G)
  * ablationMultipath/results/ablation_long.csv              (5 seeds, 16 MB)
The rail/NVLink figures (f08/f09/f10) are copied unchanged from fidelityRuns/graphs.

    python3 bin/make_paper_figs.py    -> figs/*.png  + figs/paper_numbers.json
"""
import csv, json, math, os, sys, statistics as st, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.abspath(os.path.dirname(__file__))
RUNS = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(RUNS, "fidelityRuns", "bin"))
import fidelity_data as fd  # noqa: E402

OUT = os.path.join(HERE, "..", "figs"); os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "savefig.dpi": 200,
                     "savefig.bbox": "tight"})
IBC, UETC = fd.IBC, fd.UETC
TOPO = "1os"                       # the ONLY flat fabric used in this paper
LBL = {"perm_random": "Permutation (random)", "perm_fullbis": "Permutation (bisection)",
       "incast_random": "Incast (random)", "incast_remote": "Incast (remote)",
       "outcast_incast": "Outcast-incast", "a2a_concurrent": "All-to-all",
       "allreduce_ring": "Ring all-reduce"}
SHORT = {"perm_random": "PermRand", "perm_fullbis": "PermBis", "incast_random": "IncRand",
         "incast_remote": "IncRem", "outcast_incast": "OutInc", "a2a_concurrent": "A2A",
         "allreduce_ring": "RingAR"}
NUMS = {}

cells = fd.load(); ix = fd.index(cells)
def get(wl, n, sz, stk): return ix.get(("flat", wl, n, sz, stk, TOPO))
def save(fig, name): fig.savefig(os.path.join(OUT, name)); plt.close(fig); print("  ", name)
def trim_rate(r):
    d = float(r["New"]) + float(r["Rtx"]); return 100 * float(r["NACKs"]) / d if d else 0.0

ROWS = [(wl, n) for wl in fd.WL_ORDER for n in (128, 1024)
        if get(wl, n, 16, "ib") or get(wl, n, 16, "uet")]

# -------------------------------------------------------------------------
# F1  RoCE/DCQCN / UET makespan ratio, 1:1 fat-tree
# -------------------------------------------------------------------------
M = np.full((len(ROWS), 3), np.nan); P = np.full_like(M, np.nan); ratios = []
for i, (wl, n) in enumerate(ROWS):
    for j, sz in enumerate(fd.SIZES):
        a, b = get(wl, n, sz, "ib"), get(wl, n, sz, "uet")
        if not (a and b): continue
        M[i, j] = a.mean("makespan_us") / b.mean("makespan_us")
        P[i, j] = fd.welch_p(a.v("makespan_us"), b.v("makespan_us"))
        ratios.append(dict(wl=wl, n=n, sz=sz, r=M[i, j], p=P[i, j]))
fig, ax = plt.subplots(figsize=(4.8, 5.0))
im = ax.imshow(np.log2(M), cmap="RdBu", vmin=-3.2, vmax=3.2, aspect="auto")
for i in range(M.shape[0]):
    for j in range(3):
        if np.isnan(M[i, j]):
            ax.text(j, i, "—", ha="center", va="center", color="#999"); continue
        ax.text(j, i, f"{M[i,j]:.2f}×" + ("" if P[i, j] < 0.05 else " n.s."), ha="center",
                va="center", fontsize=9, fontweight="bold",
                color="white" if abs(np.log2(M[i, j])) > 1.9 else "black")
ax.set_xticks(range(3)); ax.set_xticklabels([f"{s} MB" for s in fd.SIZES])
ax.set_yticks(range(len(ROWS))); ax.set_yticklabels([f"{SHORT[w]} · {n}" for w, n in ROWS], fontsize=9)
ax.grid(False); ax.tick_params(length=0)
cb = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)
cb.set_ticks([-3, -2, -1, 0, 1, 2, 3])
cb.set_ticklabels(["RoCE 8×", "4×", "2×", "equal", "2×", "4×", "UET 8×"], fontsize=8)
cb.set_label("which stack is faster", fontsize=8.5)
save(fig, "fig_flat_ratio.png")
NUMS["flat_ratio"] = dict(n=len(ratios), sig=sum(r["p"] < 0.05 for r in ratios),
                          uet_faster=sum(r["r"] > 1 for r in ratios),
                          by_wl={w: [round(min(r["r"] for r in ratios if r["wl"] == w), 2),
                                     round(st.median(r["r"] for r in ratios if r["wl"] == w), 2),
                                     round(max(r["r"] for r in ratios if r["wl"] == w), 2)]
                                 for w in fd.WL_ORDER})

# -------------------------------------------------------------------------
# F2  absolute makespan, 16 MB (the size every workload has on both stacks)
# -------------------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(9, 3.0), gridspec_kw=dict(width_ratios=[7, 5]))
for ax, n in zip(axes, (128, 1024)):
    wls = [w for w, nn in ROWS if nn == n]
    x = np.arange(len(wls)); w = 0.38
    for k, stk in enumerate(("ib", "uet")):
        ms, hs = [], []
        for wl in wls:
            c = get(wl, n, 16, stk); m, _, h = fd.tci([v / 1e3 for v in c.v("makespan_us")])
            ms.append(m); hs.append(h)
        ax.bar(x + (k - 0.5) * w, ms, w, yerr=hs, capsize=2, color=fd.STACK_C[stk],
               label="RoCE/DCQCN" if stk == "ib" else "UET", edgecolor="white")
    ax.set_yscale("log"); ax.set_xticks(x)
    ax.set_xticklabels([SHORT[w] for w in wls], fontsize=8.5)
    ax.set_title(f"{n} nodes, 16 MB flows", fontsize=10); ax.grid(axis="x", visible=False)
axes[0].set_ylabel("makespan (ms, log)"); axes[0].legend(frameon=False, fontsize=8.5)
save(fig, "fig_flat_makespan.png")

# -------------------------------------------------------------------------
# F3  what each stack pays: UET trim rate | RoCE PFC pause time
# -------------------------------------------------------------------------
# single-column layout: horizontal bars, one row per pattern·nodes, shared y
fig, axes = plt.subplots(1, 2, figsize=(5.2, 4.6), sharey=True)
SZC = {16: 1.0, 64: 0.65, 100: 0.38}
for ax, (stk, fn, lab, log) in zip(axes, [
        ("uet", trim_rate, "UET: packets trimmed\n(% of transmissions)", False),
        ("ib", lambda r: float(r["pfc_pause_us"]) / 1e6, "RoCE/DCQCN: PFC pause\n(port-seconds, log)", True)]):
    y = np.arange(len(ROWS)); h_ = 0.27
    for k, sz in enumerate(fd.SIZES):
        ms, hs = [], []
        for wl, n in ROWS:
            c = get(wl, n, sz, stk)
            if not c: ms.append(np.nan); hs.append(0); continue
            m, _, h = fd.tci([fn(r) for r in c.rows]); ms.append(max(m, 1e-3)); hs.append(h)
        ax.barh(y + (k - 1) * h_, ms, h_, xerr=hs, capsize=1.2, color=fd.STACK_C[stk],
                alpha=SZC[sz], label=f"{sz} MB", edgecolor="white", linewidth=0.3,
                error_kw=dict(lw=0.6))
    if log: ax.set_xscale("log")
    ax.set_yticks(y); ax.set_yticklabels([f"{SHORT[w]} · {n}" for w, n in ROWS], fontsize=8)
    ax.set_xlabel(lab, fontsize=8.5); ax.grid(axis="y", visible=False)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(frameon=False, fontsize=7, loc="lower right")
axes[0].set_xlim(0, 100); axes[0].invert_yaxis()   # shared y: invert once
save(fig, "fig_cost.png")
NUMS["trim"] = {f"{w}:{n}:{sz}": round(st.mean(trim_rate(r) for r in get(w, n, sz, "uet").rows), 2)
                for w, n in ROWS for sz in fd.SIZES if get(w, n, sz, "uet")}
NUMS["pause_s"] = {f"{w}:{n}:{sz}": round(get(w, n, sz, "ib").mean("pfc_pause_us") / 1e6, 3)
                   for w, n in ROWS for sz in fd.SIZES if get(w, n, sz, "ib")}
NUMS["ib_maxq_MB"] = [round(min(c.mean("max_queue_bytes") for c in ix.values() if c.stack == "ib" and c.topo == TOPO) / 1e6, 3),
                      round(max(c.mean("max_queue_bytes") for c in ix.values() if c.stack == "ib" and c.topo == TOPO) / 1e6, 3)]
NUMS["ib_overflow_max"] = max(max(c.v("overflow")) for c in ix.values() if c.stack == "ib" and c.topo == TOPO)

# -------------------------------------------------------------------------
# F4  per-tier link utilisation, 128 nodes, 16 MB
# -------------------------------------------------------------------------
TIERS = [("tier0_up", "host→ToR"), ("tier0_down", "ToR→host"), ("tier1_up", "ToR→Agg"),
         ("tier1_down", "Agg→ToR"), ("tier2_up", "Agg→Core"), ("tier2_down", "Core→Agg")]
W128 = [w for w, n in ROWS if n == 128]
fig, axes = plt.subplots(2, 1, figsize=(4.6, 5.4), sharex=True)
U = {}
for ax, stk in zip(axes, ("ib", "uet")):
    A = np.full((len(W128), len(TIERS)), np.nan)
    for i, wl in enumerate(W128):
        c = get(wl, 128, 16, stk)
        if c and c.urows:
            for j, (t, _) in enumerate(TIERS): A[i, j] = st.mean(c.util(f"{t}_mean"))
    U[stk] = A
    ax.imshow(A, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(A.shape[0]):
        for j in range(A.shape[1]):
            if not np.isnan(A[i, j]):
                ax.text(j, i, f"{A[i,j]:.2f}", ha="center", va="center", fontsize=8,
                        color="white" if A[i, j] > 0.55 else "black")
    ax.set_xticks(range(len(TIERS))); ax.set_xticklabels([t[1] for t in TIERS], rotation=30, ha="right", fontsize=8.5)
    ax.set_yticks(range(len(W128))); ax.set_yticklabels([SHORT[w] for w in W128], fontsize=9)
    ax.set_title("RoCE/DCQCN" if stk == "ib" else "UET", color=fd.STACK_C[stk], fontweight="bold", fontsize=10)
    ax.grid(False); ax.tick_params(length=0)
save(fig, "fig_util.png")
NUMS["util128_16"] = {stk: {wl: [round(v, 3) for v in U[stk][i]] for i, wl in enumerate(W128)} for stk in U}

# -------------------------------------------------------------------------
# Multipath ablation (16 MB, 1:1)
# -------------------------------------------------------------------------
L = [r for r in csv.DictReader(open(os.path.join(RUNS, "ablationMultipath", "results", "ablation_long.csv")))
     if r["status"] == "ok"]
AB = collections.defaultdict(list)
for r in L: AB[(r["workload"], int(r["nodes"]), r["stack"], r["arm"])].append(r)
def ms(wl, n, stk, arm): return [float(r["makespan_us"]) for r in sorted(AB[(wl, n, stk, arm)], key=lambda r: int(r["seed"]))]
ACELLS = [(wl, n) for wl, n in ROWS if AB.get((wl, n, "uet", "spray"))]
ARMS = [("ib", "qp1", "RoCE, 1 QP"), ("ib", "qp2", "RoCE, 2 QPs"), ("ib", "qp4", "RoCE, 4 QPs"),
        ("ib", "qp8", "RoCE, 8 QPs"), ("uet", "ecmp", "UET, single path"), ("uet", "spray", "UET, spraying")]
IBSH = {"qp1": "#9ecae1", "qp2": "#6baed6", "qp4": "#3182bd", "qp8": "#08519c"}

# F5  every arm normalised to UET-spray
fig, ax = plt.subplots(figsize=(10.5, 3.4))
x = np.arange(len(ACELLS)); w = 0.135
abl = {}
for k, (stk, arm, lab) in enumerate(ARMS):
    ys, es = [], []
    for wl, n in ACELLS:
        base = st.mean(ms(wl, n, "uet", "spray"))
        v = [m / base for m in ms(wl, n, stk, arm)]
        m, _, h = fd.tci(v); ys.append(m); es.append(h)
        abl[(wl, n, arm)] = m
    col = IBSH[arm] if stk == "ib" else (UETC if arm == "spray" else "#F2B48A")
    ax.bar(x + (k - 2.5) * w, ys, w, yerr=es, capsize=1.2, color=col, label=lab,
           edgecolor="white", linewidth=0.4, hatch="//" if arm == "ecmp" else "")
ax.axhline(1, color="k", lw=0.8)
ax.set_yscale("log")
from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator
tk = [0.9, 1, 1.5, 2, 3, 5, 8]
ax.yaxis.set_major_locator(FixedLocator(tk)); ax.yaxis.set_minor_locator(NullLocator())
ax.yaxis.set_major_formatter(FixedFormatter([f"{t:g}×" for t in tk]))
ax.set_ylabel("makespan ÷ UET (spraying)")
ax.set_xticks(x); ax.set_xticklabels([f"{SHORT[w]}\n{n}" for w, n in ACELLS], fontsize=8.5)
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, fontsize=8, ncol=6, loc="upper center", bbox_to_anchor=(0.5, 1.13))
save(fig, "fig_abl_arms.png")

# F6  decomposition of the RoCE-vs-UET gap: transport (both single-path) x spraying
fig, ax = plt.subplots(figsize=(5.0, 3.9))
dec = []
for wl, n in ACELLS:
    ib1 = st.mean(ms(wl, n, "ib", "qp1")); ue = st.mean(ms(wl, n, "uet", "ecmp")); us = st.mean(ms(wl, n, "uet", "spray"))
    dec.append(dict(wl=wl, n=n, total=ib1 / us, transport=ib1 / ue, spray=ue / us,
                    p_spray=fd.welch_p(ms(wl, n, "uet", "ecmp"), ms(wl, n, "uet", "spray")),
                    p_tr=fd.welch_p(ms(wl, n, "ib", "qp1"), ms(wl, n, "uet", "ecmp"))))
dec.sort(key=lambda d: -d["total"])
y = np.arange(len(dec))
tr = [math.log2(d["transport"]) for d in dec]; sp = [math.log2(d["spray"]) for d in dec]
ax.barh(y, tr, color="#7A7A7A", label="transport (both single-path)")
ax.barh(y, sp, left=[max(t, 0) if s >= 0 else 0 for t, s in zip(tr, sp)], color=UETC,
        label="per-packet spraying (UET)")
for i, d in enumerate(dec):
    ax.text(max(tr[i], 0) + max(sp[i], 0) + 0.08, i, f"{d['total']:.2f}×", va="center", fontsize=8)
ax.axvline(0, color="k", lw=0.8)
ax.set_yticks(y); ax.set_yticklabels([f"{SHORT[d['wl']]} · {d['n']}" for d in dec], fontsize=9)
ax.invert_yaxis()
tk = [-0.5, 0, 1, 2, 3]
ax.set_xticks(tk); ax.set_xticklabels(["0.7×", "1×", "2×", "4×", "8×"])
ax.set_xlabel("RoCE/DCQCN ÷ UET makespan (log scale)")
ax.grid(axis="y", visible=False); ax.set_xlim(-0.6, 3.6)
ax.legend(frameon=False, fontsize=8, loc="lower right")
save(fig, "fig_abl_decomp.png")
NUMS["abl_decomp"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()} for d in dec]

# F7  RoCE K-curve: speed-up over 1 QP vs number of QPs
fig, ax = plt.subplots(figsize=(5.0, 3.3))
for wl, n in ACELLS:
    base = st.mean(ms(wl, n, "ib", "qp1"))
    ys, es = [], []
    for arm in ("qp1", "qp2", "qp4", "qp8"):
        m, _, h = fd.tci([base / v for v in ms(wl, n, "ib", arm)]); ys.append(m); es.append(h)
    ax.errorbar([1, 2, 4, 8], ys, yerr=es, marker=fd.WL_M[wl], color=fd.WL_C[wl], lw=1.5, ms=5,
                capsize=2, ls="-" if n == 128 else "--", label=f"{SHORT[wl]} {n}")
ax.set_xscale("log", base=2); ax.set_xticks([1, 2, 4, 8]); ax.set_xticklabels(["1", "2", "4", "8"])
ax.set_xlabel("queue pairs per flow (K)"); ax.set_ylabel("RoCE/DCQCN speed-up over K = 1")
ax.axhline(1, color="k", lw=0.8)
ax.legend(frameon=False, fontsize=7.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.2))
save(fig, "fig_abl_kcurve.png")
NUMS["abl_arms"] = {f"{w}:{n}": {a: round(abl[(w, n, a)], 3) for _, a, _ in ARMS} for w, n in ACELLS}
NUMS["abl_ib_gain"] = {f"{w}:{n}": {a: round(st.mean(ms(w, n, 'ib', 'qp1')) / st.mean(ms(w, n, 'ib', a)), 3)
                                    for a in ("qp2", "qp4", "qp8")} for w, n in ACELLS}
NUMS["abl_pause"] = {f"{w}:{n}": {a: round(st.mean(float(r['pfc_pause_us']) for r in AB[(w, n, 'ib', a)]) / 1e6, 3)
                                  for a in ("qp1", "qp8")} for w, n in ACELLS}
NUMS["abl_p_qp8_vs_uecmp"] = {f"{w}:{n}": fd.welch_p(ms(w, n, "ib", "qp8"), ms(w, n, "uet", "ecmp")) for w, n in ACELLS}

# -------------------------------------------------------------------------
# Rail-optimized + NVLink cluster: rail topology ONLY (no flat control)
# -------------------------------------------------------------------------
RWL = [("allreduce_rail_aware", "Rail-aware all-reduce"), ("alltoall_moe_rail_aware", "Rail-aware MoE all-to-all")]
RG = [(n, sz) for n in (1024, 2048) for sz in fd.SIZES]
def rget(wl, n, sz, stk): return ix[("rail", wl, n, sz, stk, "rail")]

# R1  makespan, RoCE/DCQCN vs UET, ratio annotated
fig, axes = plt.subplots(2, 1, figsize=(5.0, 4.8))
NUMS["rail_only"] = {}
for ax, (wl, title) in zip(axes, RWL):
    x = np.arange(len(RG)); w = 0.38
    tops = []
    for k, stk in enumerate(("ib", "uet")):
        ms, hs = [], []
        for n, sz in RG:
            m, _, h = fd.tci([v / 1e3 for v in rget(wl, n, sz, stk).v("makespan_us")]); ms.append(m); hs.append(h)
        ax.bar(x + (k - 0.5) * w, ms, w, yerr=hs, capsize=2, color=fd.STACK_C[stk], edgecolor="white",
               label="RoCE/DCQCN" if stk == "ib" else "UET")
        tops.append([m + h for m, h in zip(ms, hs)])
    for i, (n, sz) in enumerate(RG):
        a, b = rget(wl, n, sz, "ib"), rget(wl, n, sz, "uet")
        r = a.mean("makespan_us") / b.mean("makespan_us"); p_ = fd.welch_p(a.v("makespan_us"), b.v("makespan_us"))
        NUMS["rail_only"][f"{wl}:{n}:{sz}"] = dict(ratio=round(r, 3), p=p_)
        ax.text(i, max(tops[0][i], tops[1][i]) * 1.04, f"{r:.2f}×" + ("" if p_ < 0.05 else "\nn.s."),
                ha="center", va="bottom", fontsize=7.5, fontweight="bold" if p_ < 0.05 else "normal")
    ax.set_xticks(x); ax.set_xticklabels([f"{n}\n{sz} MB" for n, sz in RG], fontsize=8)
    ax.set_ylabel("makespan (ms)", fontsize=9); ax.set_title(title, fontsize=9.5, loc="left")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15); ax.grid(axis="x", visible=False); ax.tick_params(axis="y", labelsize=8)
axes[0].legend(frameon=False, fontsize=8, loc="upper left")
fig.tight_layout(h_pad=0.6)
save(fig, "fig_rail_makespan.png")

# R2  congestion cost of MoE all-to-all on the rail cluster
fig, axes = plt.subplots(1, 2, figsize=(5.2, 2.5))
for ax, (stk, metric, sc, lab) in zip(axes, [("ib", "pfc_pause_us", 1e6, "RoCE/DCQCN: PFC pause\n(port-seconds)"),
                                            ("uet", "Rtx", 1e6, "UET: retransmitted\npackets (millions)")]):
    x = np.arange(len(fd.SIZES)); w = 0.38
    for k, (n, alpha, hatch) in enumerate([(1024, 0.95, ""), (2048, 0.55, "//")]):
        ms, hs = [], []
        for sz in fd.SIZES:
            m, _, h = fd.tci([v / sc for v in rget("alltoall_moe_rail_aware", n, sz, stk).v(metric)]); ms.append(m); hs.append(h)
        ax.bar(x + (k - 0.5) * w, ms, w, yerr=hs, capsize=2, color=fd.STACK_C[stk], alpha=alpha, hatch=hatch,
               edgecolor="white", label=f"{n} GPUs")
        for xi, m, h in zip(x + (k - 0.5) * w, ms, hs):
            ax.text(xi, m + h, f"{m:.1f}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks(x); ax.set_xticklabels([f"{s} MB" for s in fd.SIZES], fontsize=8)
    ax.set_ylabel(lab, fontsize=8.5); ax.tick_params(axis="y", labelsize=8)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12); ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")
fig.tight_layout(w_pad=1.0)
save(fig, "fig_rail_cost.png")

# -------------------------------------------------------------------------
# Rail + NVLink: rail placement vs flat placement, both stacks (print-size, full width)
# -------------------------------------------------------------------------
def fget(wl, n, sz, stk, topo): return ix[("rail", wl, n, sz, stk, topo)]
PR = {"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7.5,
      "ytick.labelsize": 7.5, "legend.fontsize": 7.5}
ARMS4 = [("ib", "flat", "//", 0.45, "RoCE/DCQCN, flat"), ("ib", "rail", "", 1.0, "RoCE/DCQCN, rail"),
         ("uet", "flat", "//", 0.45, "UET, flat"), ("uet", "rail", "", 1.0, "UET, rail")]
def grp_axis(ax):
    """two-level x axis for the 6 rail groups: size ticks, GPU-count headers, divider."""
    ax.set_xticks(range(len(RG))); ax.set_xticklabels([f"{sz} MB" for _, sz in RG])
    for cx, n in ((1, 1024), (4, 2048)):
        ax.text(cx, -0.17, f"{n} GPUs", transform=ax.get_xaxis_transform(), ha="center", va="top",
                fontsize=8, fontweight="bold")
    ax.axvline(2.5, color="#999", lw=0.7, ls=":")

with plt.rc_context(PR):
    # RF1  makespan bars: rail next to flat, both stacks
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))
    for ax, (wl, title) in zip(axes, RWL):
        x = np.arange(len(RG)); w = 0.2
        for k, (stk, topo, hatch, alpha, lab) in enumerate(ARMS4):
            ms, hs = [], []
            for n, sz in RG:
                m, _, h = fd.tci([v / 1e3 for v in fget(wl, n, sz, stk, topo).v("makespan_us")]); ms.append(m); hs.append(h)
            ax.bar(x + (k - 1.5) * w, ms, w, yerr=hs, capsize=1.5, color=fd.STACK_C[stk], alpha=alpha,
                   hatch=hatch, edgecolor="white", linewidth=0.4, label=lab, error_kw=dict(lw=0.7))
        grp_axis(ax)
        ax.set_title(title, loc="left"); ax.set_ylabel("makespan (ms)"); ax.grid(axis="x", visible=False)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.06))
    fig.tight_layout(w_pad=1.5)
    save(fig, "fig_rail_vs_flat.png")

    # RF2  what rail placement buys: % change rail vs flat, per seed + mean +/- CI
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=True)
    NUMS["rail_benefit"] = []
    for ax, (wl, title) in zip(axes, RWL):
        for k, stk in enumerate(("ib", "uet")):
            for g, (n, sz) in enumerate(RG):
                a, b = fget(wl, n, sz, stk, "rail"), fget(wl, n, sz, stk, "flat")
                ma, mb = a.mean("makespan_us"), b.mean("makespan_us")
                _, _, ha = a.ci("makespan_us"); _, _, hb = b.ci("makespan_us")
                ch = 100 * (ma / mb - 1); ci = math.hypot(ha / ma, hb / mb) * (ma / mb) * 100
                seeds = [100 * (x / y - 1) for x, y in zip(a.v("makespan_us"), b.v("makespan_us"))]
                p_ = fd.welch_p(a.v("makespan_us"), b.v("makespan_us"))
                NUMS["rail_benefit"].append(dict(wl=wl, stk=stk, n=n, sz=sz, ch=round(ch, 1), p=p_))
                xp = g + (k - 0.5) * 0.3
                ax.scatter([xp] * len(seeds), seeds, s=7, color=fd.STACK_C[stk], alpha=0.35, zorder=2, linewidths=0)
                ax.errorbar(xp, ch, yerr=ci, fmt="o", ms=4.5, capsize=2, color=fd.STACK_C[stk], lw=1,
                            mfc=fd.STACK_C[stk] if p_ < 0.05 else "white", zorder=3,
                            label=("RoCE/DCQCN" if stk == "ib" else "UET") if g == 0 else None)
        ax.axhline(0, color="k", lw=0.8)
        grp_axis(ax)
        ax.set_title(title, loc="left"); ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("makespan change, rail vs flat (%)")
    axes[0].legend(frameon=False, loc="lower right")
    fig.tight_layout(w_pad=1.2)
    save(fig, "fig_rail_benefit.png")

    # RF3  congestion cost of MoE all-to-all, rail vs flat, both scales
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6))
    for ax, (stk, metric, sc, lab) in zip(axes, [("ib", "pfc_pause_us", 1e6, "RoCE/DCQCN: PFC pause (port-s)"),
                                                ("uet", "Rtx", 1e6, "UET: retransmitted packets (M)")]):
        x = np.arange(len(RG)); w = 0.38
        for k, (topo, hatch, alpha) in enumerate([("flat", "//", 0.45), ("rail", "", 1.0)]):
            ms, hs = [], []
            for n, sz in RG:
                m, _, h = fd.tci([v / sc for v in fget("alltoall_moe_rail_aware", n, sz, stk, topo).v(metric)]); ms.append(m); hs.append(h)
            ax.bar(x + (k - 0.5) * w, ms, w, yerr=hs, capsize=1.5, color=fd.STACK_C[stk], alpha=alpha, hatch=hatch,
                   edgecolor="white", linewidth=0.4, label=topo, error_kw=dict(lw=0.7))
            if topo == "rail":
                for xi, m, h in zip(x + (k - 0.5) * w, ms, hs):
                    ax.text(xi, m + h, f"{m:.1f}", ha="center", va="bottom", fontsize=6.5)
        grp_axis(ax)
        ax.set_title(lab, loc="left", color=fd.STACK_C[stk]); ax.grid(axis="x", visible=False)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.08); ax.legend(frameon=False, loc="upper left")
    fig.tight_layout(w_pad=1.5)
    save(fig, "fig_rail_cost_flat.png")
# RF4  RoCE/DCQCN / UET ratio on the cluster, rail vs flat placement (print size, one column)
with plt.rc_context(PR):
    fig, ax = plt.subplots(figsize=(3.5, 3.3))
    rows = [(wl, n, sz) for wl, _ in RWL for n, sz in RG]
    for i, (wl, n, sz) in enumerate(rows):
        for topo, mk, mfc_rail in (("flat", "s", False), ("rail", "o", True)):
            a, b = fget(wl, n, sz, "ib", topo), fget(wl, n, sz, "uet", topo)
            r = a.mean("makespan_us") / b.mean("makespan_us")
            _, _, ha = a.ci("makespan_us"); _, _, hb = b.ci("makespan_us")
            e = r * math.hypot(ha / a.mean("makespan_us"), hb / b.mean("makespan_us"))
            col = fd.WL_C[wl]
            ax.errorbar(r, i + (0.17 if topo == "flat" else -0.17), xerr=e, fmt=mk, ms=4, capsize=1.5, lw=0.8,
                        color=col, mfc=col if mfc_rail else "white",
                        label=(f"{topo} placement" if (i == 0) else None))
    ax.axvline(1, color="k", lw=0.8)
    ax.set_xscale("log")
    from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator
    tk = [1, 1.5, 2, 3, 4, 5]
    ax.xaxis.set_major_locator(FixedLocator(tk)); ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FixedFormatter([f"{t:g}×" for t in tk]))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{'AR' if wl.startswith('allreduce') else 'MoE'} · {n} · {sz} MB" for wl, n, sz in rows])
    ax.invert_yaxis(); ax.axhline(5.5, color="#999", lw=0.7, ls=":")
    ax.set_xlabel("RoCE/DCQCN ÷ UET makespan (log)"); ax.grid(axis="y", visible=False)
    h, l = ax.get_legend_handles_labels()
    from matplotlib.lines import Line2D
    ax.legend([Line2D([], [], marker="o", color="#555", ls=""), Line2D([], [], marker="s", color="#555", mfc="white", ls="")],
              ["rail placement", "flat placement"], frameon=False, loc="lower right")
    fig.tight_layout()
    save(fig, "fig_rail_ratio.png")

NUMS["rail_ratio_flat"] = {f"{wl}:{n}:{sz}": round(fget(wl, n, sz, "ib", "flat").mean("makespan_us") /
                                                    fget(wl, n, sz, "uet", "flat").mean("makespan_us"), 3)
                           for wl, _ in RWL for n, sz in RG}
NUMS["rail_cost_flat_vs_rail"] = {f"{stk}:{n}:{sz}": [round(fget("alltoall_moe_rail_aware", n, sz, stk, t).mean(m) / 1e6, 2) for t in ("flat", "rail")]
                                  for stk, m in (("ib", "pfc_pause_us"), ("uet", "Rtx")) for n, sz in RG}

json.dump(NUMS, open(os.path.join(OUT, "paper_numbers.json"), "w"), indent=1, default=float)
print("  paper_numbers.json")
