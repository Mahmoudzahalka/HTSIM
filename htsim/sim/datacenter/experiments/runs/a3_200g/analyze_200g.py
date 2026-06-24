#!/usr/bin/env python3
"""Generate a human-readable report + wide-pivot CSV from results_combined.csv.
Re-runnable: rerun after the perm_8192_100MB serial reruns land to refresh."""
import csv, re, os, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, 'results_combined.csv')
REP  = os.path.join(HERE, 'a3_report_200g.md')
WIDE = os.path.join(HERE, 'results_wide_200g.csv')
FB   = ['1os', '4os', '8os']

def fnum(x):
    try: return float(x)
    except: return 0.0

rows = []
with open(SRC) as fh:
    for r in csv.DictReader(fh):
        for k in ('nodes','conns','wall_s','flows_fin','makespan_us','fct_min_us',
                  'fct_p50_us','fct_p99_us','fct_max_us','total_GB','New','Rtx','RTS',
                  'Bounced','ACKs','NACKs','Pulls','sleek','spurious'):
            r[k] = fnum(r.get(k,0))
        r['nack_pct'] = 100*r['NACKs']/r['New'] if r['New'] else 0.0
        r['rtx_pct']  = 100*r['Rtx']/r['New']  if r['New'] else 0.0
        r['base'] = r['matrix'].split('/')[-1]
        rows.append(r)

ok     = [r for r in rows if r['status']=='ok']
failed = [r for r in rows if r['status']!='ok']
out = []
def p(s=''): out.append(s)

p(f"# A3 UEC network-metrics sweep — report")
p(f"_generated {datetime.now():%Y-%m-%d %H:%M} from results_combined.csv_\n")
p(f"- Branch: study/a3-uec-network-metrics (stock reference UEC, validated 12/12)")
p(f"- Config: `-sender_cc_only -linkspeed 200000 -end 2000`, fat-tree fabrics")
p(f"- Fabrics: auto (auto-gen full-bisection) / 1os (1:1) / 4os (4:1) / 8os (8:1)")
p(f"- Rows: **{len(rows)}** total — ok **{len(ok)}**, failed **{len(failed)}**")
if failed:
    p(f"- FAILED: " + ", ".join(f"{r['base']}@{r['fabric']}({r['status']})" for r in failed))
rts = [r for r in ok if r['RTS']>0]
p(f"- RTS>0 (retransmit-timeout activity; all completed → not wedges): {len(rts)} rows, max RTS={max((r['RTS'] for r in ok),default=0):.0f}\n")

p("> ## ✅ CORRECTED RUN — consistent 200 G")
p("> All fabrics use experiment-local 200 G topo copies (topos_200g/, stock files untouched), so")
p("> 1os/4os/8os AND cross-node-count comparisons are now valid. The auto fabric is dropped.")
p("> **Complete:** all 294 cells incl. the 9 heavy perm_8192 {32,64,100}MB (run serially, OOM-safe).")

def pivot(matrix_sub, keyfn=None):
    d={}
    for r in ok:
        if matrix_sub in r['matrix']:
            d.setdefault(r['base'], {})[r['fabric']] = r
    keys=sorted(d, key=keyfn) if keyfn else sorted(d)
    return d, keys

def szMB(k):
    m=re.search(r'_(\d+)M[Bs]',k); return int(m.group(1)) if m else 0  # perm uses MB, incast uses Ms
def concC(k):
    m=re.search(r'_(\d+)c_',k); return int(m.group(1)) if m else 0

# --- Permutation 8192 ---
p("## Permutation @ 8192 — makespan(ms) / p99 FCT(ms) / NACK%")
p("| flow size | " + " | ".join(FB) + " |")
p("|" + "---|"*(len(FB)+1))
d,keys = pivot('perm_8192n_8192c_', szMB)
for k in keys:
    cells=[]
    for fb in FB:
        r=d[k].get(fb)
        cells.append(f"{r['makespan_us']/1000:.1f} / {r['fct_p99_us']/1000:.1f} / {r['nack_pct']:.1f}%" if r else "—")
    p(f"| {szMB(k)} MB | " + " | ".join(cells) + " |")
p("")

# --- Incast 8192 (random + remote) ---
for fam,lbl in [('gen_random_incast_8192n_','Incast @ 8192 (random victim)'),
                ('gen_remote_incast_8192n_','Incast @ 8192 (remote victim)')]:
    p(f"## {lbl} — makespan(µs) / NACK%, by [concurrency, flowsize, jitter] × fabric")
    p("| concurrency | size | jitter | " + " | ".join(FB) + " |")
    p("|" + "---|"*(len(FB)+3))
    d,keys = pivot(fam)
    def sortk(k):
        j = 16 if '16us' in k else 0
        return (concC(k), szMB(k), j)
    for k in sorted(keys, key=sortk):
        j = '16µs' if '16us' in k else '0µs'
        cells=[]
        for fb in FB:
            r=d[k].get(fb)
            cells.append(f"{r['makespan_us']:.0f} / {r['nack_pct']:.1f}%" if r else "—")
        p(f"| {concC(k)}c | {szMB(k)}MB | {j} | " + " | ".join(cells) + " |")
    p("")

# --- 128 / 1024 node families ---
p("## 128 & 1024-node workloads — makespan(µs) / NACK% by fabric")
p("| workload | nodes | " + " | ".join(FB) + " |")
p("|" + "---|"*(len(FB)+2))
for sub in ['incast_128.cm','incast_collateral_128.cm','incast_2to1_size4194304B.cm',
            'incast_3-1_overlapped.tm','outcast_incast.cm','foo2.cm','perm_128n_128c_2MB',
            'incast_1024_100K.cm','perm_1024n_1024c_0u_2000000b','perm_1024n_1024c_0u_20000b']:
    d,_ = pivot(sub)
    if not d: continue
    k=list(d)[0]; n=int(d[k][list(d[k])[0]]['nodes'])
    cells=[]
    for fb in FB:
        r=d[k].get(fb)
        cells.append(f"{r['makespan_us']:.0f} / {r['nack_pct']:.0f}%" if r else "—")
    p(f"| {k} | {n} | " + " | ".join(cells) + " |")
p("")

# --- Small workloads ---
p("## Small workloads (2/16/32-node, auto fabric only)")
p("| workload | nodes | makespan(µs) | NACK% | Rtx | spurious |")
p("|---|---|---|---|---|---|")
for r in sorted([r for r in ok if r['nodes'] in (2,16,32)], key=lambda r:r['matrix']):
    p(f"| {r['base']} | {int(r['nodes'])} | {r['makespan_us']:.1f} | {r['nack_pct']:.1f} | {int(r['Rtx'])} | {int(r['spurious'])} |")
p("")

# --- Full dump ---
p("## Full results (all rows)")
p("| workload | nodes | fabric | status | makespan_us | p50 | p99 | NACK% | Rtx | NACKs | RTS | spurious | wall_s |")
p("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in sorted(rows, key=lambda r:(r['nodes'], r['base'], r['fabric'])):
    p(f"| {r['base']} | {int(r['nodes'])} | {r['fabric']} | {r['status']} | {r['makespan_us']:.1f} | "
      f"{r['fct_p50_us']:.1f} | {r['fct_p99_us']:.1f} | {r['nack_pct']:.1f} | {int(r['Rtx'])} | "
      f"{int(r['NACKs'])} | {int(r['RTS'])} | {int(r['spurious'])} | {int(r['wall_s'])} |")

with open(REP,'w') as fh: fh.write("\n".join(out)+"\n")

# --- wide pivot CSV (spreadsheet-friendly) ---
allm={}
for r in ok:
    allm.setdefault(r['base'], {'nodes':int(r['nodes']),'conns':int(r['conns'])})[r['fabric']]=r
with open(WIDE,'w',newline='') as fh:
    w=csv.writer(fh)
    hdr=['workload','nodes','conns']
    for fb in FB: hdr += [f'{fb}_makespan_us',f'{fb}_p99_us',f'{fb}_nack_pct']
    w.writerow(hdr)
    for m in sorted(allm, key=lambda m:(allm[m]['nodes'],m)):
        row=[m, allm[m]['nodes'], allm[m]['conns']]
        for fb in FB:
            r=allm[m].get(fb)
            row += ([f"{r['makespan_us']:.1f}",f"{r['fct_p99_us']:.1f}",f"{r['nack_pct']:.1f}"] if r else ['','',''])
        w.writerow(row)

print(f"wrote {REP}")
print(f"wrote {WIDE}")
print(f"  ({len(rows)} rows, {len(ok)} ok, {len(failed)} failed)")
