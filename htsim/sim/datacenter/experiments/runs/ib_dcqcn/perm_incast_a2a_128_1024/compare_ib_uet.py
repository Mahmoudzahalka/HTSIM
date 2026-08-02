import csv, os
from collections import defaultdict
BASE="/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs"
IB=f"{BASE}/ib_dcqcn/perm_incast_a2a_128_1024/results_ib.csv"
IBU=f"{BASE}/ib_dcqcn/perm_incast_a2a_128_1024/utilization_ib.csv"
UET=[f"{BASE}/uet/perm_incast_128_1024/results_combined.csv", f"{BASE}/uet/a2a_concurrent_128_1024/results_combined.csv"]
UETU=[f"{BASE}/uet/perm_incast_128_1024/utilization_combined.csv", f"{BASE}/uet/a2a_concurrent_128_1024/utilization_combined.csv"]

def key(p,f): return (os.path.basename(p).replace(".cm",""), f)
def load(files):
    d={}
    for fn in files:
        if not os.path.exists(fn): continue
        for r in csv.reader(open(fn)):
            if not r or r[0]=="matrix": continue
            d[key(r[0],r[3])]=r
    return d
def loadu(files):
    d={}
    for fn in files:
        if not os.path.exists(fn): continue
        for r in csv.reader(open(fn)):
            if not r or r[0]=="matrix": continue
            d[key(r[0],r[1])]=r
    return d
def sf(x):
    try: return float(x)
    except: return None
ib,uet=load([IB]),load(UET)
ibu,uetu=loadu([IBU]),loadu(UETU)
def pat(k):
    for p in ["perm_random","perm_fullbis","incast_remote","incast_random","outcast_incast","a2a"]:
        if k[0].startswith(p): return p
def nodes(k): return k[0].split("_")[-2]
def sizeMB(k):
    for s in (100,64,16):
        if f"{s}MB" in k[0]: return s
    return 0
def ideal_us(k): return sizeMB(k)*40.0
def avg(xs): xs=[x for x in xs if x is not None]; return sum(xs)/len(xs) if xs else float('nan')

print("="*76)
print("1. COMPLETION -- IB finished ALL 99. Where did UET fail on a matched run?")
for k in sorted(ib):
    if k in uet and uet[k][4]!="ok" and ib[k][4]=="ok":
        print(f"   UET {uet[k][4]:11} | IB ok  ->  {k[0]:26} {k[1]}")
# UET a2a-1024 timeouts (no IB counterpart since IB a2a-1024 infeasible)
print("   (a2a-1024: UET timed out; IB infeasible at 1M flows -> both fail)")

print("="*76); print("2. MAKESPAN ratio IB/UET (both ok).  <1.0 = IB faster")
agg=defaultdict(list)
for k in ib:
    if k in uet and ib[k][4]=="ok" and uet[k][4]=="ok":
        agg[(pat(k),nodes(k))].append(float(ib[k][7])/float(uet[k][7]))
print(f"   {'pattern':15}{'nodes':6}{'n':>3}{'IB/UET':>9}{'min':>7}{'max':>7}")
allr=[]
for (p,n),v in sorted(agg.items()):
    allr+=v; print(f"   {p:15}{n:6}{len(v):>3}{sum(v)/len(v):>9.2f}{min(v):>7.2f}{max(v):>7.2f}")
print(f"   OVERALL IB/UET mean={sum(allr)/len(allr):.2f}  IB-faster in {sum(1 for x in allr if x<1)}/{len(allr)} runs")

print("="*76); print("3. CONGESTION FINGERPRINT + slowdown/fairness/util  (mean over fabrics)")
print(f"   {'pattern':14}{'nd':5}| {'IBpause_s':>9}{'IB_Rtx':>7}{'IBsd99':>7}{'IBfair':>7}{'IButil':>7} | {'UET_Rtx':>12}{'UETsd99':>8}{'UETutil':>8}")
grp=defaultdict(list)
for k in ib:
    if k in uet: grp[(pat(k),nodes(k))].append(k)
for (p,n),ks in sorted(grp.items()):
    ib_ps=avg([sf(ib[k][23])/1e6 if ib[k][4]=="ok" else None for k in ks])
    ib_rtx=avg([sf(ib[k][14]) if ib[k][4]=="ok" else None for k in ks])  # New col? no -> Rtx is col15(idx14)
    ib_sd=avg([sf(ib[k][26]) if ib[k][4]=="ok" else None for k in ks])
    ib_f=avg([sf(ib[k][28]) if ib[k][4]=="ok" else None for k in ks])
    ibut=avg([sf(ibu[k][7]) if k in ibu else None for k in ks])
    # UET Rtx: flag overflow (negative or >1e9)
    rtxs=[sf(uet[k][15-1]) for k in ks if uet[k][4]=="ok"]
    rtxs=[r for r in rtxs if r is not None]
    ovf = any(r<0 or r>1e9 for r in rtxs)
    ue_rtx = "OVERFLOW" if ovf else (f"{avg(rtxs):.0f}" if rtxs else "-")
    ue_sd=avg([sf(uet[k][10])/ideal_us(k) if uet[k][4]=="ok" and ideal_us(k)>0 else None for k in ks])
    ueut=avg([sf(uetu[k][7]) if k in uetu and sf(uetu[k][7]) is not None else None for k in ks])
    print(f"   {p:14}{n:5}| {ib_ps:>9.1f}{ib_rtx:>7.0f}{ib_sd:>7.0f}{ib_f:>7.3f}{ibut:>7.3f} | {ue_rtx:>12}{ue_sd:>8.0f}{ueut:>8.3f}")
print("   (IB_Rtx=0 everywhere = lossless; UET pays in retransmits, overflowing 2^31 at 4os/8os)")
