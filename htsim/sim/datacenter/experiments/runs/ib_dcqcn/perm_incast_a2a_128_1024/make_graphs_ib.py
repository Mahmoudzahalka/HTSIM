#!/usr/bin/env python3
"""IB (RoCE + DCQCN, lossless PFC) result graphs — same style as the UET
make_graphs.py. Mirrors the UET figures where IB has the data (makespan,
utilization, 128-vs-1024 scaling), and adds IB-specific ones:
  - PFC pause-time vs OS   (IB's congestion signal; IB is lossless so NACKs=0)
  - Jain fairness vs OS     (unique: per-flow fairness)
  - slowdown p99 vs OS      (unique: per-flow FCT / ideal)
  - peak PFC buffer vs OS   (unique: lossless buffer high-water)
Pure stdlib csv + matplotlib. Okabe-Ito CVD-safe palette + distinct markers."""
import csv, os, re
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

D   = "/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs/ib_dcqcn/perm_incast_a2a_128_1024"
OUT = os.path.join(D, "..", "graphs"); os.makedirs(OUT, exist_ok=True)

WL_ORDER = ["perm_random","perm_fullbis","incast_random","incast_remote",
            "outcast_incast","a2a (concurrent)"]
STYLE = {"perm_random":("#0072B2","o"),"perm_fullbis":("#56B4E9","s"),
         "incast_random":("#D55E00","^"),"incast_remote":("#E69F00","v"),
         "outcast_incast":("#CC79A7","D"),"a2a (concurrent)":("#111111","X")}
OS=[1,4,8]; SIZES=[16,64,100]

def parse(matrix):
    b=os.path.basename(matrix).replace(".cm","")
    m=re.match(r'(.+)_(\d+)n_(\d+)MB', b)
    wl=m.group(1); return wl, int(m.group(2)), int(m.group(3))
def lab_of(wl): return "a2a (concurrent)" if wl=="a2a" else wl
def os_of(fabric): return int(fabric.replace("os",""))

# ---- load results ----
res=[]
for r in csv.DictReader(open(os.path.join(D,"results_ib.csv"))):
    wl,n,sz=parse(r["matrix"]); r["wl"]=wl; r["lab"]=lab_of(wl); r["nn"]=n; r["sz"]=sz; r["os"]=os_of(r["fabric"])
    res.append(r)
util=[]
for r in csv.DictReader(open(os.path.join(D,"utilization_ib.csv"))):
    wl,n,sz=parse(r["matrix"]); r["lab"]=lab_of(wl); r["nn"]=n; r["sz"]=sz; r["os"]=os_of(r["fabric"])
    util.append(r)

def get(nodes,lab,size,os_,col,f=float):
    for r in res:
        if r["nn"]==nodes and r["lab"]==lab and r["sz"]==size and r["os"]==os_ and r["status"]=="ok":
            try: return f(r[col])
            except: return None
    return None
def mk(nodes,lab,size,os_):   v=get(nodes,lab,size,os_,"makespan_us");   return v/1000 if v is not None else None
def pause_ms(nodes,lab,size,os_): v=get(nodes,lab,size,os_,"pfc_pause_us"); return v/1000 if v is not None else None
def fair(nodes,lab,size,os_): return get(nodes,lab,size,os_,"fairness_jain")
def slow(nodes,lab,size,os_): return get(nodes,lab,size,os_,"slowdown_p99")
def buf(nodes,lab,size,os_):  v=get(nodes,lab,size,os_,"max_queue_bytes"); return v/1024 if v is not None else None

plt.rcParams.update({"font.size":10,"axes.grid":True,"grid.alpha":0.25,"grid.linewidth":0.6,
    "axes.axisbelow":True,"axes.edgecolor":"#888","figure.facecolor":"white",
    "axes.facecolor":"white","savefig.dpi":150})
def styled(ax):
    ax.set_xticks(range(len(OS))); ax.set_xticklabels([f"{o}:1" for o in OS])
    ax.set_xlabel("oversubscription (OS ratio)")
    for sp in ("top","right"): ax.spines[sp].set_visible(False)
def avg(nodes,lab,fn):  # size-averaged over SIZES for each OS
    ys=[]
    for o in OS:
        v=[fn(nodes,lab,s,o) for s in SIZES]; v=[x for x in v if x is not None]
        ys.append(np.mean(v) if v else None)
    return ys

labs128 =[l for l in WL_ORDER if any(mk(128,l,s,o)  is not None for s in SIZES for o in OS)]
labs1024=[l for l in WL_ORDER if any(mk(1024,l,s,o) is not None for s in SIZES for o in OS)]

def panels_by_size(nodes,labs,fn,ylabel,title,fname,logy=True):
    fig,axes=plt.subplots(1,3,figsize=(13,4.4),sharey=True)
    for ax,size in zip(axes,SIZES):
        for l in labs:
            y=[fn(nodes,l,size,o) for o in OS]
            if all(v is None for v in y): continue
            c,m=STYLE[l]; ax.plot(range(len(OS)),y,marker=m,color=c,lw=2,ms=7,label=l)
        if logy: ax.set_yscale("log"); ax.yaxis.set_major_formatter(ScalarFormatter()); ax.yaxis.set_minor_formatter(plt.NullFormatter())
        styled(ax); ax.set_title(f"{size} MB flows",fontsize=11)
    axes[0].set_ylabel(ylabel)
    axes[-1].legend(fontsize=8,frameon=False,loc="upper left",bbox_to_anchor=(1.02,1.0))
    fig.suptitle(title,fontsize=13,y=1.02); fig.tight_layout()
    fig.savefig(f"{OUT}/{fname}",bbox_inches="tight"); plt.close(fig)

# ===== Fig 1 & 2: makespan vs OS (128, 1024) — mirrors UET fig1/fig5 =====
panels_by_size(128, labs128, mk, "makespan (ms, log)","IB DCQCN — makespan vs oversubscription, 128 nodes","fig1_makespan_vs_os_128.png")
panels_by_size(1024,labs1024,mk, "makespan (ms, log)","IB DCQCN — makespan vs oversubscription, 1024 nodes","fig2_makespan_vs_os_1024.png")

# ===== Fig 3: makespan 128 vs 1024 scaling (100MB) — mirrors UET fig6 =====
fig,axes=plt.subplots(1,2,figsize=(11,4.4),sharey=True)
for ax,nd in zip(axes,[128,1024]):
    labs=labs128 if nd==128 else labs1024
    for l in labs:
        y=[mk(nd,l,100,o) for o in OS]
        if all(v is None for v in y): continue
        c,m=STYLE[l]; ax.plot(range(len(OS)),y,marker=m,color=c,lw=2,ms=7,label=l)
    ax.set_yscale("log"); styled(ax); ax.set_title(f"{nd} nodes",fontsize=11)
    ax.yaxis.set_major_formatter(ScalarFormatter()); ax.yaxis.set_minor_formatter(plt.NullFormatter())
axes[0].set_ylabel("makespan (ms, log)"); axes[1].legend(fontsize=8,frameon=False,loc="upper left",bbox_to_anchor=(1.02,1.0))
fig.suptitle("IB DCQCN — makespan scaling 128 vs 1024 nodes (100 MB flows)",fontsize=13,y=1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig3_makespan_128_vs_1024.png",bbox_inches="tight"); plt.close(fig)

# ===== Fig 4: per-tier utilization heatmaps, 128 nodes, 100MB — mirrors UET fig3 =====
TIERS=["tier0_up","tier0_down","tier1_up","tier1_down","tier2_up","tier2_down"]
TIERLAB=["T0 up\n(host→ToR)","T0 down\n(ToR→host)","T1 up\n(ToR→Agg)","T1 down\n(Agg→ToR)","T2 up\n(Agg→Core)","T2 down\n(Core→Agg)"]
def uval(nodes,lab,size,os_,tier):
    for r in util:
        if r["lab"]==lab and r["sz"]==size and r["os"]==os_ and r["nn"]==nodes:
            try: return float(r[f"{tier}_mean"])
            except: return np.nan
    return np.nan
fig,axes=plt.subplots(2,3,figsize=(12,7.2))
for ax,l in zip(axes.ravel(),labs128):
    M=np.array([[uval(128,l,100,o,t) for o in OS] for t in TIERS])
    im=ax.imshow(M,cmap="Blues",vmin=0,vmax=1,aspect="auto")
    ax.set_xticks(range(len(OS))); ax.set_xticklabels([f"{o}:1" for o in OS],fontsize=8)
    ax.set_yticks(range(len(TIERS))); ax.set_yticklabels(TIERLAB,fontsize=6.5); ax.set_title(l,fontsize=9.5)
    for i in range(len(TIERS)):
        for j in range(len(OS)):
            v=M[i,j]
            if not np.isnan(v): ax.text(j,i,f"{v:.2f}",ha="center",va="center",fontsize=7,color="white" if v>0.55 else "#222")
for ax in axes.ravel()[len(labs128):]: ax.set_visible(False)
cb=fig.colorbar(im,ax=axes,fraction=0.02,pad=0.02); cb.set_label("mean link utilization")
fig.suptitle("IB DCQCN — per-tier link utilization, 128 nodes, 100 MB",fontsize=13)
fig.savefig(f"{OUT}/fig4_utilization_heatmaps_128.png",bbox_inches="tight"); plt.close(fig)

# ===== helper for size-averaged 2-panel (128 | 1024) line figs =====
def two_panel(fn,ylabel,title,fname,logy=False,ylim=None):
    fig,axes=plt.subplots(1,2,figsize=(11,4.4),sharey=True)
    for ax,nd in zip(axes,[128,1024]):
        labs=labs128 if nd==128 else labs1024
        for l in labs:
            ys=avg(nd,l,fn)
            if all(v is None for v in ys): continue
            c,m=STYLE[l]; ax.plot(range(len(OS)),ys,marker=m,color=c,lw=2,ms=7,label=l)
        if logy: ax.set_yscale("log")
        if ylim: ax.set_ylim(*ylim)
        styled(ax); ax.set_title(f"{nd} nodes",fontsize=11)
    axes[0].set_ylabel(ylabel); axes[1].legend(fontsize=8,frameon=False,loc="upper left",bbox_to_anchor=(1.02,1.0))
    fig.suptitle(title,fontsize=13,y=1.02); fig.tight_layout()
    fig.savefig(f"{OUT}/{fname}",bbox_inches="tight"); plt.close(fig)

# ===== Fig 5: PFC pause-time vs OS — IB congestion signal (analogue of UET NACK fig) =====
two_panel(pause_ms,"PFC pause-time (ms, log; summed over ports)","IB DCQCN — PFC backpressure vs oversubscription  (IB is lossless: NACKs=0, pays in pauses)","fig5_pfc_pause_vs_os.png",logy=True)
# ===== Fig 6: Jain fairness vs OS — IB-UNIQUE =====
two_panel(fair,"Jain fairness index","IB DCQCN — per-flow fairness (Jain) vs oversubscription  [IB-unique]","fig6_fairness_vs_os.png",ylim=(0,1.02))
# ===== Fig 7: slowdown p99 vs OS — IB-UNIQUE =====
two_panel(slow,"slowdown p99  (FCT / ideal, log)","IB DCQCN — tail slowdown (p99) vs oversubscription  [IB-unique]","fig7_slowdown_p99_vs_os.png",logy=True)
# ===== Fig 8: peak PFC buffer vs OS — IB-UNIQUE =====
two_panel(buf,"peak input-queue occupancy (KB)","IB DCQCN — peak PFC buffer high-water vs oversubscription  [IB-unique]","fig8_peak_buffer_vs_os.png")

print("wrote:")
for fn in sorted(os.listdir(OUT)):
    if fn.endswith(".png"): print("  ",os.path.join(OUT,fn))
