#!/usr/bin/env python3
"""Generate the UEC-sweep result graphs from the assembled combined CSVs.
Pure stdlib csv + matplotlib (no pandas). CVD-safe Okabe-Ito palette in fixed
order + distinct markers (secondary encoding); log-y where range demands."""
import csv, os, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

RUNS = "/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs"
OUT  = os.path.join(RUNS, "uet", "graphs"); os.makedirs(OUT, exist_ok=True)
SWEEPS = ["uet/perm_incast_128_1024","uet/a2a_serial_128_1024","uet/a2a_concurrent_128_1024","uet/allreduce_ring_128"]

def label(sweep, wl):
    # NB: `sweep` is the value stored in the CSV's `sweep` column (the original
    # sweep name), NOT the directory path in SWEEPS above -- the dirs were
    # reorganised under uet/ but the recorded data keeps the original names.
    if sweep == "a2a_128_1024": return "a2a (serial)"
    if sweep == "a2a_conc_128_1024": return "a2a (concurrent)"
    if wl == "allreduce_ring": return "ring AllReduce"
    return wl

# fixed categorical order + (color, marker) — Okabe-Ito, distinct markers = secondary encoding
WL_ORDER = ["perm_random","perm_fullbis","incast_random","incast_remote",
            "outcast_incast","a2a (serial)","a2a (concurrent)","ring AllReduce"]
STYLE = {"perm_random":("#0072B2","o"),"perm_fullbis":("#56B4E9","s"),
         "incast_random":("#D55E00","^"),"incast_remote":("#E69F00","v"),
         "outcast_incast":("#CC79A7","D"),"a2a (serial)":("#009E73","P"),
         "a2a (concurrent)":("#111111","X"),"ring AllReduce":("#A6761D","*")}
OS = [1,4,8]; SIZES = [16,64,100]

# ---- load ----
res = []  # list of dict rows
for s in SWEEPS:
    with open(os.path.join(RUNS,s,"results_combined.csv")) as f:
        for r in csv.DictReader(f):
            r["lab"] = label(r["sweep"], r["workload"]); res.append(r)
util = []
for s in SWEEPS:
    with open(os.path.join(RUNS,s,"utilization_combined.csv")) as f:
        for r in csv.DictReader(f):
            r["lab"] = label(r["sweep"], r["workload"]); util.append(r)

def mk(nodes, lab, size, os_):
    for r in res:
        if (int(r["nodes"])==nodes and r["lab"]==lab and int(r["size_MB"])==size
                and int(r["os_ratio"])==os_ and r["status"]=="ok"):
            return float(r["makespan_ms"])
    return None
def nk(nodes, lab, size, os_):
    for r in res:
        if (int(r["nodes"])==nodes and r["lab"]==lab and int(r["size_MB"])==size
                and int(r["os_ratio"])==os_ and r["status"]=="ok"):
            return float(r["nack_pct"])
    return None

plt.rcParams.update({"font.size":10,"axes.grid":True,"grid.alpha":0.25,
    "grid.linewidth":0.6,"axes.axisbelow":True,"axes.edgecolor":"#888",
    "figure.facecolor":"white","axes.facecolor":"white","savefig.dpi":150})

def styled(ax):
    ax.set_xticks(range(len(OS))); ax.set_xticklabels([f"{o}:1" for o in OS])
    ax.set_xlabel("oversubscription (OS ratio)")
    for sp in ("top","right"): ax.spines[sp].set_visible(False)

labs_128 = [l for l in WL_ORDER if any(mk(128,l,s,o) is not None for s in SIZES for o in OS)]

# ===== Fig 1: makespan vs OS, 128 nodes, 3 size panels (log-y) =====
fig, axes = plt.subplots(1,3,figsize=(13,4.4),sharey=True)
for ax,size in zip(axes,SIZES):
    for l in labs_128:
        y=[mk(128,l,size,o) for o in OS]
        if all(v is None for v in y): continue
        c,m=STYLE[l]
        ax.plot(range(len(OS)),y,marker=m,color=c,lw=2,ms=7,label=l)
    ax.set_yscale("log"); styled(ax); ax.set_title(f"{size} MB flows",fontsize=11)
    ax.yaxis.set_major_formatter(ScalarFormatter()); ax.yaxis.set_minor_formatter(plt.NullFormatter())
axes[0].set_ylabel("makespan (ms, log scale)")
axes[-1].legend(fontsize=8,frameon=False,loc="upper left",bbox_to_anchor=(1.02,1.0))
fig.suptitle("Makespan vs oversubscription — 128 nodes, by flow size",fontsize=13,y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig1_makespan_vs_os_128.png",bbox_inches="tight"); plt.close(fig)

# ===== Fig 2: NACK% vs OS, 128 nodes (size-averaged; sizes agree <0.1pt) =====
fig,ax=plt.subplots(figsize=(7.5,5))
for l in labs_128:
    ys=[]
    for o in OS:
        vals=[nk(128,l,s,o) for s in SIZES]; vals=[v for v in vals if v is not None]
        ys.append(np.mean(vals) if vals else None)
    if all(v is None for v in ys): continue
    c,m=STYLE[l]; ax.plot(range(len(OS)),ys,marker=m,color=c,lw=2,ms=8,label=l)
styled(ax); ax.set_ylabel("packet-trim rate  NACKs/(New+Rtx)  [%]"); ax.set_ylim(0,100)
ax.legend(fontsize=8.5,frameon=False,ncol=2,loc="upper left")
ax.set_title("Congestion (trim) rate vs oversubscription — 128 nodes\n(averaged over 16/64/100 MB; sizes agree to <0.1 pt)",fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/fig2_nack_vs_os_128.png",bbox_inches="tight"); plt.close(fig)

# ===== Fig 3: per-tier utilization heatmaps, 128 nodes, 100 MB =====
TIERS=["tier0_up","tier0_down","tier1_up","tier1_down","tier2_up","tier2_down"]
TIERLAB=["T0 up\n(host→ToR)","T0 down\n(ToR→host)","T1 up\n(ToR→Agg)",
         "T1 down\n(Agg→ToR)","T2 up\n(Agg→Core)","T2 down\n(Core→Agg)"]
def uval(nodes,lab,size,os_,tier):
    for r in util:
        if (int(r["nodes"] if "nodes" in r else 0) or True):
            pass
    for r in util:
        if (r["lab"]==lab and r.get("size_MB","")==str(size) and r.get("os_ratio","")==str(os_)):
            # node disambig: matrix path contains <N>n
            if f"_{nodes}n_" not in r["matrix"]: continue
            v=r.get(f"{tier}_mean","")
            try: return float(v)
            except: return np.nan
    return np.nan
fig,axes=plt.subplots(2,4,figsize=(15,7.2))
for ax,l in zip(axes.ravel(),labs_128):
    M=np.array([[uval(128,l,100,o,t) for o in OS] for t in TIERS])
    im=ax.imshow(M,cmap="Blues",vmin=0,vmax=1,aspect="auto")
    ax.set_xticks(range(len(OS))); ax.set_xticklabels([f"{o}:1" for o in OS],fontsize=8)
    ax.set_yticks(range(len(TIERS))); ax.set_yticklabels(TIERLAB,fontsize=6.5)
    ax.set_title(l,fontsize=9.5)
    for i in range(len(TIERS)):
        for j in range(len(OS)):
            v=M[i,j]
            if not np.isnan(v):
                ax.text(j,i,f"{v:.2f}",ha="center",va="center",fontsize=7,
                        color="white" if v>0.55 else "#222")
for ax in axes.ravel()[len(labs_128):]: ax.set_visible(False)
cb=fig.colorbar(im,ax=axes,fraction=0.02,pad=0.02); cb.set_label("mean link utilization")
fig.suptitle("Per-tier link utilization — 128 nodes, 100 MB flows (mean over sample window)",fontsize=13)
fig.savefig(f"{OUT}/fig3_utilization_heatmaps_128.png",bbox_inches="tight"); plt.close(fig)

# ===== Fig 4: serial vs concurrent A2A @128 =====
fig,axes=plt.subplots(1,4,figsize=(16,4.2))
for ax,size in zip(axes[:3],SIZES):
    for lab,ls,mk_ in [("a2a (serial)","--","P"),("a2a (concurrent)","-","X")]:
        y=[mk(128,lab,size,o) for o in OS]; c=STYLE[lab][0]
        ax.plot(range(len(OS)),y,ls=ls,marker=mk_,color=c,lw=2,ms=8,label=lab)
    styled(ax); ax.set_yscale("log"); ax.set_title(f"{size} MB",fontsize=11)
    ax.yaxis.set_major_formatter(ScalarFormatter()); ax.yaxis.set_minor_formatter(plt.NullFormatter())
axes[0].set_ylabel("makespan (ms, log)")
# 4th panel: NACK% (size-averaged)
ax=axes[3]
for lab,mk_ in [("a2a (serial)","P"),("a2a (concurrent)","X")]:
    ys=[np.mean([nk(128,lab,s,o) for s in SIZES]) for o in OS]; c=STYLE[lab][0]
    ax.plot(range(len(OS)),ys,marker=mk_,color=c,lw=2,ms=9,label=lab)
styled(ax); ax.set_ylabel("trim rate [%]"); ax.set_ylim(0,100); ax.set_title("NACK% (size-avg)",fontsize=11)
axes[0].legend(fontsize=9,frameon=False,loc="upper left")
fig.suptitle("Serial vs concurrent all-to-all — 128 nodes",fontsize=13,y=1.03)
fig.tight_layout(); fig.savefig(f"{OUT}/fig4_a2a_serial_vs_concurrent_128.png",bbox_inches="tight"); plt.close(fig)

# ===== Fig 5: makespan vs OS, 1024 nodes (completed point-to-point patterns) =====
labs_1024=[l for l in WL_ORDER if any(mk(1024,l,s,o) is not None for s in SIZES for o in OS)]
fig,axes=plt.subplots(1,3,figsize=(13,4.4),sharey=True)
for ax,size in zip(axes,SIZES):
    for l in labs_1024:
        y=[mk(1024,l,size,o) for o in OS]
        if all(v is None for v in y): continue
        c,m=STYLE[l]; ax.plot(range(len(OS)),y,marker=m,color=c,lw=2,ms=7,label=l)
    ax.set_yscale("log"); styled(ax); ax.set_title(f"{size} MB flows",fontsize=11)
    ax.yaxis.set_major_formatter(ScalarFormatter()); ax.yaxis.set_minor_formatter(plt.NullFormatter())
axes[0].set_ylabel("makespan (ms, log scale)")
axes[-1].legend(fontsize=8.5,frameon=False,loc="upper left",bbox_to_anchor=(1.02,1.0))
fig.suptitle("Makespan vs oversubscription — 1024 nodes (completed patterns; incast_random 8os incomplete)",fontsize=12,y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig5_makespan_vs_os_1024.png",bbox_inches="tight"); plt.close(fig)

print("wrote:")
for fn in sorted(os.listdir(OUT)):
    if fn.endswith(".png"): print("  ",os.path.join(OUT,fn))
