#!/usr/bin/env python3
"""Plots from the consistent-200G v2 sweep (results_combined.csv). Outputs PNGs to plots/."""
import csv, re, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, 'results_combined.csv')
PD   = os.path.join(HERE, 'plots'); os.makedirs(PD, exist_ok=True)
FB   = ['1os', '4os', '8os']
COL  = {'1os':'#1f77b4', '4os':'#ff7f0e', '8os':'#d62728'}   # cool -> hot with oversub
LBL  = {'1os':'1:1 (full bisection)', '4os':'4:1', '8os':'8:1'}

def fnum(x):
    try: return float(x)
    except: return 0.0

rows = []
with open(SRC) as fh:
    for r in csv.DictReader(fh):
        for k in ('nodes','makespan_us','fct_p99_us','New','NACKs'):
            r[k] = fnum(r[k])
        r['nack_pct'] = 100*r['NACKs']/r['New'] if r['New'] else 0.0
        r['base'] = r['matrix'].split('/')[-1]
        rows.append(r)
ok = [r for r in rows if r['status']=='ok']

def szMB(b):
    m=re.search(r'_(\d+)M[Bs]',b); return int(m.group(1)) if m else None
def concC(b):
    m=re.search(r'_(\d+)c_',b); return int(m.group(1)) if m else None

def lineplot(fname, title, xlabel, ylabel, series, xlog=True, ylog=False):
    fig, ax = plt.subplots(figsize=(7.5,5))
    for fb in FB:
        xs, ys = series[fb]
        if not xs: continue
        ax.plot(xs, ys, 'o-', color=COL[fb], label=LBL[fb], lw=2, ms=6)
    if xlog: ax.set_xscale('log', base=2)
    if ylog: ax.set_yscale('log')
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.grid(True, which='both', ls=':', alpha=0.5)
    ax.legend(title='oversubscription')
    fig.tight_layout(); fig.savefig(os.path.join(PD,fname), dpi=120); plt.close(fig)
    print("wrote plots/"+fname)

# ---- perm_8192 vs flow size ----
def perm_series(metric):
    s={}
    for fb in FB:
        pts=sorted([(szMB(r['base']), r[metric]) for r in ok
                    if r['base'].startswith('perm_8192n_8192c_') and r['fabric']==fb and szMB(r['base'])],
                   key=lambda t:t[0])
        s[fb]=([p[0] for p in pts],[p[1] for p in pts])
    return s
sp=perm_series('makespan_us')
lineplot('perm8192_makespan_vs_size.png','Permutation @ 8192 — makespan vs flow size (200G)',
         'flow size (MB, log2)', 'makespan (ms)',
         {fb:(xs,[y/1000 for y in ys]) for fb,(xs,ys) in sp.items()}, xlog=True, ylog=True)
lineplot('perm8192_nack_vs_size.png','Permutation @ 8192 — loss (NACK%) vs flow size (200G)',
         'flow size (MB, log2)', 'NACK %', perm_series('nack_pct'), xlog=True, ylog=False)

# ---- incast_8192 (random, 0us jitter) vs concurrency, fixed 2MB ----
def incast_series(metric, sizeMB=2):
    s={}
    for fb in FB:
        pts=sorted([(concC(r['base']), r[metric]) for r in ok
                    if r['base'].startswith('gen_random_incast_8192n_') and '_0us_' in r['base']
                    and szMB(r['base'])==sizeMB and r['fabric']==fb and concC(r['base'])],
                   key=lambda t:t[0])
        s[fb]=([p[0] for p in pts],[p[1] for p in pts])
    return s
lineplot('incast8192_makespan_vs_fanin.png','Incast @ 8192 (2MB) — makespan vs fan-in (200G)',
         'incast degree (senders, log2)', 'makespan (µs)', incast_series('makespan_us'), xlog=True, ylog=True)
lineplot('incast8192_nack_vs_fanin.png','Incast @ 8192 (2MB) — loss (NACK%) vs fan-in (200G)',
         'incast degree (senders, log2)', 'NACK %', incast_series('nack_pct'), xlog=True, ylog=False)

# ---- makespan vs oversubscription (perm_8192, a few sizes) ----
fig, ax = plt.subplots(figsize=(7.5,5))
xo=[1,4,8]
for sz,c in [(16,'#2ca02c'),(64,'#9467bd'),(100,'#8c564b')]:
    ys=[]
    for fb in FB:
        m=[r['makespan_us']/1000 for r in ok if r['base']==f'perm_8192n_8192c_{sz}MB.cm' and r['fabric']==fb]
        ys.append(m[0] if m else None)
    ax.plot(xo, ys, 'o-', color=c, lw=2, ms=7, label=f'{sz} MB')
ax.set_title('Permutation @ 8192 — makespan vs oversubscription (200G)', fontsize=12, fontweight='bold')
ax.set_xlabel('oversubscription ratio (X:1)'); ax.set_ylabel('makespan (ms)')
ax.set_xticks(xo); ax.grid(True, ls=':', alpha=0.5); ax.legend(title='flow size')
fig.tight_layout(); fig.savefig(os.path.join(PD,'perm8192_makespan_vs_oversub.png'), dpi=120); plt.close(fig)
print("wrote plots/perm8192_makespan_vs_oversub.png")

# ---- TREE-SIZE scaling ----
def tree_plot(fname, title, ylabel, mapping, metric, ylog=False):
    """mapping: {nodes: base_filename}. One line per fabric across tree sizes."""
    fig, ax = plt.subplots(figsize=(7.5,5))
    ns=sorted(mapping)
    for fb in FB:
        ys=[]
        for n in ns:
            v=[r[metric] for r in ok if r['base']==mapping[n] and r['fabric']==fb]
            ys.append(v[0] if v else None)
        ax.plot(ns, ys, 'o-', color=COL[fb], label=LBL[fb], lw=2, ms=7)
    ax.set_xscale('log', base=2); ax.set_xticks(ns); ax.set_xticklabels([str(n) for n in ns])
    if ylog: ax.set_yscale('log')
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_xlabel('tree size (hosts)'); ax.set_ylabel(ylabel)
    ax.grid(True, which='both', ls=':', alpha=0.5); ax.legend(title='oversubscription')
    fig.tight_layout(); fig.savefig(os.path.join(PD,fname), dpi=120); plt.close(fig)
    print("wrote plots/"+fname)

# permutation 2MB: clean 3-point (128/1024/8192)
PERM={128:'perm_128n_128c_2MB.cm', 1024:'perm_1024n_1024c_0u_2000000b.cm', 8192:'perm_8192n_8192c_2MB.cm'}
tree_plot('perm2MB_makespan_vs_treesize.png','Permutation 2MB/flow — makespan vs tree size (200G)','makespan (µs)',PERM,'makespan_us',ylog=False)
tree_plot('perm2MB_nack_vs_treesize.png','Permutation 2MB/flow — loss (NACK%) vs tree size (200G)','NACK %',PERM,'nack_pct')

# ~128-way incast 2MB: 2-point (128 full=127c, 8192=128c). CAVEAT: victim placement differs.
INC={128:'incast_128.cm', 8192:'gen_random_incast_8192n_128c_0us_2Ms.cm'}
tree_plot('incast128way_makespan_vs_treesize.png','~128-way incast 2MB — makespan vs tree size (200G)\n[128n=127->1 full; 8192n=128->1 random victim]','makespan (µs)',INC,'makespan_us')
tree_plot('incast128way_nack_vs_treesize.png','~128-way incast 2MB — loss (NACK%) vs tree size (200G)\n[128n=127->1 full; 8192n=128->1 random victim]','NACK %',INC,'nack_pct')

print("DONE ->", PD)
