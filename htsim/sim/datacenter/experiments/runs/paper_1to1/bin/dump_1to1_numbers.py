import sys, os, statistics as st
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../fidelityRuns/bin")))
import fidelity_data as fd
cells = fd.load(); ix = fd.index(cells)
def g(wl,n,sz,stk): return ix.get(("flat",wl,n,sz,stk,"1os"))
def tr(r):
    d=float(r["New"])+float(r["Rtx"]); return 100*float(r["NACKs"])/d if d else 0
print("wl n sz | ib_ms uet_ms ratio p | uet_trim% ib_pause_s ib_maxq_MB | util? ")
for wl in fd.WL_ORDER:
  for n in (128,1024):
    for sz in fd.SIZES:
      a,b=g(wl,n,sz,"ib"),g(wl,n,sz,"uet")
      if not (a or b): continue
      s=f"{wl:15s} {n:5d} {sz:4d} |"
      if a: s+=f" ib={a.mean('makespan_us')/1e3:9.3f}"
      if b: s+=f" uet={b.mean('makespan_us')/1e3:9.3f}"
      if a and b: s+=f" r={a.mean('makespan_us')/b.mean('makespan_us'):5.2f} p={fd.welch_p(a.v('makespan_us'),b.v('makespan_us')):.1e}"
      if b: s+=f" | trim={st.mean([tr(r) for r in b.rows]):5.1f}% rtx={b.mean('Rtx')/1e6:.2f}M"
      if a: s+=f" pause={a.mean('pfc_pause_us')/1e6:8.2f}s maxq={a.mean('max_queue_bytes')/1e6:.3f}MB ovf={a.mean('overflow')}"
      if a and a.urows: s+=f" ibU1={st.mean(a.util('tier1_up_mean')):.2f} ibU2={st.mean(a.util('tier2_up_mean')):.2f}"
      if b and b.urows: s+=f" uetU1={st.mean(b.util('tier1_up_mean')):.2f} uetU2={st.mean(b.util('tier2_up_mean')):.2f}"
      s+=f" jain ib={a.mean('fairness_jain') if a else float('nan'):.2f} uet={b.mean('fairness_jain') if b else float('nan'):.2f}"
      print(s)
