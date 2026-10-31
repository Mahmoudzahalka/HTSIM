"""
fidelityRuns -- shared data layer for figures and the presentation.

Loads the 5-seed 400 G (DGX H100) sweep from results/runs_all.csv, keeps only
status==ok runs, and exposes per-cell statistics. Also joins the ORIGINAL
200 G single-seed study so "what changed" can be shown.

Excluded by design (see DEVIATIONS.md):
  * serial all-to-all -- dropped from the study as not representative of MoE
  * UET ring all-reduce at 64/100 MB -- memory-capped at 10 GB, not re-run
"""
import csv, math, os, statistics as st, collections
from scipy import stats

FID  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNS = os.path.abspath(os.path.join(FID, ".."))

OS_ORDER = ["1os", "4os", "8os"]
OS_LABEL = {"1os": "1:1", "4os": "4:1", "8os": "8:1"}
SIZES = [16, 64, 100]
IBC, UETC = "#0072B2", "#D55E00"
STACK_C = {"ib": IBC, "uet": UETC}
STACK_L = {"ib": "IB (RoCE + DCQCN)", "uet": "UET"}

WL_ORDER = ["perm_random", "perm_fullbis", "incast_random", "incast_remote",
            "outcast_incast", "a2a_concurrent", "allreduce_ring"]
WL_LABEL = {"perm_random": "perm_random", "perm_fullbis": "perm_fullbis",
            "incast_random": "incast_random", "incast_remote": "incast_remote",
            "outcast_incast": "outcast_incast", "a2a_concurrent": "a2a (concurrent)",
            "allreduce_ring": "ring all-reduce",
            "allreduce_rail_aware": "rail-aware all-reduce",
            "alltoall_moe_rail_aware": "rail-aware MoE all-to-all"}
WL_C = {"perm_random": "#0072B2", "perm_fullbis": "#56B4E9", "incast_random": "#D55E00",
        "incast_remote": "#E69F00", "outcast_incast": "#CC79A7", "a2a_concurrent": "#111111",
        "allreduce_ring": "#009E73", "allreduce_rail_aware": "#009E73",
        "alltoall_moe_rail_aware": "#882255"}
WL_M = {"perm_random": "o", "perm_fullbis": "s", "incast_random": "^", "incast_remote": "v",
        "outcast_incast": "D", "a2a_concurrent": "X", "allreduce_ring": "P"}

NUM = ["makespan_us", "fct_p50_us", "fct_p99_us", "fct_max_us", "New", "Rtx", "NACKs",
       "spurious", "pfc_pauses", "pfc_pause_us", "max_queue_bytes", "slowdown_p50",
       "slowdown_p99", "slowdown_max", "fairness_jain", "overflow", "wall_s", "peak_mb"]


def tci(vals, conf=0.95):
    """mean, sd, half-width of a t-based CI (n=5 -> t=2.776, not 1.96)."""
    n = len(vals); m = st.mean(vals)
    if n < 2: return m, 0.0, 0.0
    sd = st.stdev(vals)
    return m, sd, stats.t.ppf(0.5 + conf / 2, n - 1) * sd / math.sqrt(n)


def welch_p(a, b):
    if len(a) < 2 or len(b) < 2: return float("nan")
    if st.stdev(a) == 0 and st.stdev(b) == 0: return 0.0 if st.mean(a) != st.mean(b) else 1.0
    return stats.ttest_ind(a, b, equal_var=False).pvalue


class Cell:
    """One (study, workload, nodes, size, stack, topo) configuration and its seeds."""
    def __init__(self, key, rows):
        self.study, self.wl, self.nodes, self.size, self.stack, self.topo = key
        self.rows = sorted(rows, key=lambda r: int(r["seed"]))
        self.seeds = [int(r["seed"]) for r in self.rows]
        self.n = len(self.rows)

    def v(self, metric):
        return [float(r[metric]) for r in self.rows]

    def mean(self, m): return st.mean(self.v(m))
    def ci(self, m): return tci(self.v(m))
    def cv(self, m):
        vv = self.v(m); mu = st.mean(vv)
        return (st.stdev(vv) / mu * 100) if (mu and len(vv) > 1) else 0.0

    def util(self, stat):
        return [float(u[stat]) for u in self.urows]


def _study_family(study):
    """Flat-fabric arms of each stack share one logical namespace."""
    if study == "rail": return "rail"
    return "flat"


def load(include_utilization=True):
    rows = [r for r in csv.DictReader(open(os.path.join(FID, "results", "runs_all.csv")))
            if r["status"] == "ok" and r["workload"] != "a2a_serial"]
    g = collections.defaultdict(list)
    for r in rows:
        g[(r["study"], r["workload"], int(r["nodes"]), int(r["size_MB"]),
           r["stack"], r["topo_kind"])].append(r)
    cells = {k: Cell(k, v) for k, v in g.items()}

    if include_utilization:
        up = os.path.join(FID, "results", "utilization_all.csv")
        ug = collections.defaultdict(list)
        for u in csv.DictReader(open(up)):
            ug[(u["study"], u["matrix_base"], u["stack"], u["topo_kind"], u["seed"])] = u
        for c in cells.values():
            c.urows = []
            for r in c.rows:
                base = os.path.basename(r["matrix"]).replace(".cm", "")
                u = ug.get((c.study, base, c.stack, c.topo, r["seed"]))
                if u: c.urows.append(u)
    return cells


def index(cells):
    """(family, wl, nodes, size, stack, topo) -> Cell. Flat arms collapse into 'flat'."""
    out = {}
    for c in cells.values():
        out[(_study_family(c.study), c.wl, c.nodes, c.size, c.stack, c.topo)] = c
    return out


def load_old_200g():
    """The original single-seed 200 G study, keyed like index()."""
    src = [("uet/perm_incast_128_1024/results_combined.csv", "uet", "flat"),
           ("uet/a2a_concurrent_128_1024/results_combined.csv", "uet", "flat"),
           ("uet/allreduce_ring_128/results_combined.csv", "uet", "flat"),
           ("ib_dcqcn/perm_incast_a2a_128_1024/results_ib.csv", "ib", "flat"),
           ("ib_dcqcn/allreduce_a2a_serial_128/results_ib_parity.csv", "ib", "flat"),
           ("rail_optimized/results_rail.csv", None, "rail")]
    out = {}
    for rel, stack, fam in src:
        for x in csv.DictReader(open(os.path.join(RUNS, rel))):
            if x["status"] != "ok": continue
            path = x["matrix"]; base = os.path.basename(path).replace(".cm", "")
            if fam == "rail":
                wl = x["workload"]; stk = x["stack"]; topo = x["topology"]
                n = int(x["nodes"]); sz = int(x["size_MB"])
            else:
                import re
                m = re.match(r"(.+?)_(\d+)n_(\d+)MB", base)
                wl, n, sz = m.group(1), int(m.group(2)), int(m.group(3))
                if wl == "a2a":
                    if "a2a_conc" in path: wl = "a2a_concurrent"
                    else: continue                     # serial a2a: dropped from the study
                stk = stack; topo = x["fabric"]
            out[(fam, wl, n, sz, stk, topo)] = x
    return out
