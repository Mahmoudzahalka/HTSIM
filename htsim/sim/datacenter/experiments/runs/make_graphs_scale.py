#!/usr/bin/env python3
"""128 vs 1024 node comparison graphs (point-to-point patterns only — the
collectives/a2a have no usable 1024 data). Encoding: flow size = color ramp,
node count = line style (128 solid/circle, 1024 dashed/square)."""
import csv, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import ScalarFormatter

RUNS="/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs"
OUT=os.path.join(RUNS,"uet","graphs"); os.makedirs(OUT,exist_ok=True)
SWEEPS=["uet/perm_incast_128_1024"]  # only sweep with both 128 & 1024

res=[]; util=[]
for s in SWEEPS:
    with open(os.path.join(RUNS,s,"results_combined.csv")) as f:
        for r in csv.DictReader(f): res.append(r)
    with open(os.path.join(RUNS,s,"utilization_combined.csv")) as f:
        for r in csv.DictReader(f): util.append(r)

PP=["perm_random","perm_fullbis","incast_random","incast_remote","outcast_incast"]
OS=[1,4,8]; SIZES=[16,64,100]
SIZE_COLOR={16:"#9ecae1",64:"#3182bd",100:"#08306b"}   # sequential blue ramp
NODE_STYLE={128:("-","o"),1024:("--","s")}

def getv(nodes,wl,size,os_,field,ok_only=True):
    for r in res:
        if (int(r["nodes"])==nodes and r["workload"]==wl and int(r["size_MB"])==size
                and int(r["os_ratio"])==os_):
            if ok_only and r["status"]!="ok": return None
            if not ok_only and int(r["flows_fin"])==0: return None
            try: return float(r[field])
            except: return None
    return None
def uov(nodes,wl,size,os_):
    for r in util:
        if (r["workload"]==wl and r.get("size_MB","")==str(size) and r.get("os_ratio","")==str(os_)
                and f"_{nodes}n_" in r["matrix"]):
            try: return float(r["overall_mean"])
            except: return None
    return None

plt.rcParams.update({"font.size":10,"axes.grid":True,"grid.alpha":0.25,"grid.linewidth":0.6,
    "axes.axisbelow":True,"axes.edgecolor":"#888","figure.facecolor":"white",
    "axes.facecolor":"white","savefig.dpi":150})

def legend_panel(ax):
    ax.axis("off")
    h=[Line2D([],[],color=SIZE_COLOR[s],lw=3,label=f"{s} MB") for s in SIZES]
    h+=[Line2D([],[],color="#444",lw=2,ls=NODE_STYLE[n][0],marker=NODE_STYLE[n][1],
               label=f"{n} nodes") for n in (128,1024)]
    ax.legend(handles=h,loc="center",frameon=False,fontsize=11,title="color = flow size\nstyle = node count")

def panel_grid(plot_one, ylabel, logy, ylim, title, fname):
    fig,axes=plt.subplots(2,3,figsize=(14,8)); axes=axes.ravel()
    for ax,wl in zip(axes,PP):
        for nodes in (128,1024):
            ls,mk=NODE_STYLE[nodes]
            for size in SIZES:
                y=[plot_one(nodes,wl,size,o) for o in OS]
                if all(v is None for v in y): continue
                xs=[i for i,v in enumerate(y) if v is not None]; ys=[v for v in y if v is not None]
                ax.plot(xs,ys,ls=ls,marker=mk,ms=6,lw=1.8,color=SIZE_COLOR[size])
        ax.set_title(wl,fontsize=11)
        ax.set_xticks(range(len(OS))); ax.set_xticklabels([f"{o}:1" for o in OS])
        ax.set_xlabel("OS ratio")
        if logy:
            ax.set_yscale("log"); ax.yaxis.set_major_formatter(ScalarFormatter())
            ax.yaxis.set_minor_formatter(plt.NullFormatter())
        if ylim: ax.set_ylim(*ylim)
        for sp in ("top","right"): ax.spines[sp].set_visible(False)
    axes[0].set_ylabel(ylabel); axes[3].set_ylabel(ylabel)
    legend_panel(axes[5])
    fig.suptitle(title,fontsize=13,y=1.0)
    fig.tight_layout(); fig.savefig(f"{OUT}/{fname}",bbox_inches="tight"); plt.close(fig)

# Fig 6: makespan 128 vs 1024 (ok only, log-y)
panel_grid(lambda n,w,s,o: getv(n,w,s,o,"makespan_ms",ok_only=True),
    "makespan (ms, log)", True, None,
    "Makespan: 128 vs 1024 nodes — point-to-point patterns",
    "fig6_makespan_128_vs_1024.png")

# Fig 7: trim rate 128 vs 1024 (include incomplete rows w/ flows>0; ratio still valid)
panel_grid(lambda n,w,s,o: getv(n,w,s,o,"nack_pct",ok_only=False),
    "trim rate NACKs/(New+Rtx) [%]", False, (-3,100),
    "Congestion (trim) rate: 128 vs 1024 nodes — point-to-point patterns\n(1024n incast_random 8os is incomplete but near-complete; ratio valid)",
    "fig7_nack_128_vs_1024.png")

# Fig 8: overall link utilization 128 vs 1024 (8 blanked 1024n-incast util cells appear as gaps)
panel_grid(lambda n,w,s,o: uov(n,w,s,o),
    "overall mean link utilization", False, (0,1.05),
    "Overall link utilization: 128 vs 1024 nodes — point-to-point patterns\n(some 1024n incast util cells blank — divisor bug, unrecoverable)",
    "fig8_util_128_vs_1024.png")

print("wrote fig6/7/8 to", OUT)
