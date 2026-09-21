#!/usr/bin/env python3
"""
fidelityRuns -- build MANIFEST.csv: one row per (cell x seed) job.

A "cell" is a (study, matrix, stack, topology) combination that completed with
status==ok in the original single-seed study.  Anything that timed out, went
incomplete, failed, or overflowed a lossless fabric is EXCLUDED -- repeating a
run we already know does not finish just burns the budget.

The PFC-only (no-DCQCN) arm is excluded entirely: in this study "IB" means
RoCE with PFC *and* DCQCN K=8.

Machine assignment is driven by measured peak RSS (bin/probe_memory.csv) plus a
safety factor, because this box has 31 GB and previously became unreachable
when a run exhausted RAM+swap.

usage: build_manifest.py [--seeds 13,101,202,303,404] [--local-budget-mb 9000]
"""
import argparse, csv, os, re, sys

RUNS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FID  = os.path.join(RUNS, "fidelityRuns")

# study -> (source results csv, stack, matrix dir, logtime rule)
# logtime replicates each original harness exactly so that seed 13 reproduces
# the published numbers; utilization stats depend on the sampling period.
SOURCES = [
    ("uet_perm_incast",          "uet/perm_incast_128_1024/results_combined.csv",        "uet", "uet/perm_incast_128_1024/matrices",     "fine"),
    ("uet_a2a_concurrent",       "uet/a2a_concurrent_128_1024/results_combined.csv",     "uet", "uet/a2a_concurrent_128_1024/matrices",  "fine"),
    ("uet_a2a_serial",           "uet/a2a_serial_128_1024/results_combined.csv",         "uet", "@SERIAL",                               "fine"),
    ("uet_allreduce_ring",       "uet/allreduce_ring_128/results_combined.csv",          "uet", "uet/allreduce_ring_128/matrices",       "fine"),
    ("ib_perm_incast_a2a",       "ib_dcqcn/perm_incast_a2a_128_1024/results_ib.csv",     "ib",  "@IBMAIN",                               "ib_coarse"),
    ("ib_allreduce_a2a_serial",  "ib_dcqcn/allreduce_a2a_serial_128/results_ib_parity.csv","ib", "@IBPARITY",                             "all_coarse"),
    ("rail",                     "rail_optimized/results_rail.csv",                      None,  "rail_optimized/matrices",               "coarse"),
]
SERIAL_MATRICES = "/media/mahmoud_murad_allaah/Data/a2a_128_1024/matrices"


def logtime_for(rule, base):
    if rule == "fine":        return 1000
    if rule == "coarse":      return 20000
    if rule == "all_coarse":  return 20000
    if rule == "ib_coarse":
        return 20000 if re.match(r'^(incast_|outcast_|a2a_)', base) else 1000
    raise ValueError(rule)


def qsize_for(stack, nodes, base):
    """IB lossless buffer. 2048-node MoE needed -q 8000 to keep overflow at 0;
    everything else was proven clean at 1000. UET is lossy -- -q unused."""
    if stack != "ib":
        return 0
    if nodes >= 2048:
        return 8000
    return 1000


def resolve_matrix(study, mdir, base):
    if mdir == "@SERIAL":
        return os.path.join(SERIAL_MATRICES, base + ".cm")
    if mdir == "@IBMAIN":
        # IB main sweep reused the UET matrices; a2a came from the CONCURRENT dir
        sub = "uet/a2a_concurrent_128_1024/matrices" if base.startswith("a2a_") \
              else "uet/perm_incast_128_1024/matrices"
        return os.path.join(RUNS, sub, base + ".cm")
    if mdir == "@IBPARITY":
        # parity arm: a2a came from the SERIAL dir (on /media), allreduce from the repo
        if base.startswith("a2a_"):
            return os.path.join(SERIAL_MATRICES, base + ".cm")
        return os.path.join(RUNS, "uet/allreduce_ring_128/matrices", base + ".cm")
    return os.path.join(RUNS, mdir, base + ".cm")


# ---------------------------------------------------------------------------
# MACHINE ASSIGNMENT
#
# A short RSS probe was tried and abandoned: htsim's peak arrives late (queues
# filling), so a 150 s probe on the 2048/100MB MoE cell reported 2.2 GB for a
# cell documented at ~32 GB. Guessing from a bad probe is worse than not
# probing, so assignment now rests on two things:
#
#   1. DOCUMENTED EVIDENCE. RUN_ON_BIGGER_BOX.md records that the 2048-GPU MoE
#      100 MB cell OOM-killed here at -q 8000 (~32 GB) and was run on the 94 GB
#      box. Those cells are pinned to bigbox up front.
#   2. A HARD PER-JOB CAP AT RUNTIME. run_one_fidelity.sh sets ulimit -v, so
#      anything misjudged as local dies in seconds with status=mem_capped
#      instead of taking the box down. bin/reassign_capped.py then moves it.
#
# Note the /csl/ paths in the UET CSVs do NOT mark big-box cells -- those whole
# sweeps were authored on that machine, so the path says nothing per-cell.
# ---------------------------------------------------------------------------
BIGBOX_PINNED = [
    # (workload, nodes, size_MB) -- every stack/topology combination of these
    ("alltoall_moe_rail_aware", 2048, 100),
]


def pinned_bigbox(workload, nodes, size_MB):
    return (workload, nodes, size_MB) in BIGBOX_PINNED


def estimate_mb(conns, size_MB, nodes, stack, qsize):
    """Rough model, used only for ORDERING and for the heavy/light split, never
    as the sole basis for a bigbox decision. ~20 KB/connection is the figure the
    flow-leak investigation measured for pre-allocated Src+Sink pairs; the -q
    term is the lossless buffer, which only IB carries."""
    per_conn = 0.020 * conns
    buffers  = (qsize * 4.0 / 1024.0) * max(nodes, 1) / 32.0 if stack == "ib" else 0.0
    inflight = conns * size_MB * 0.00002
    return 400 + per_conn + buffers + inflight


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="13,101,202,303,404")
    ap.add_argument("--local-budget-mb", type=float, default=9000,
                    help="per-job peak RSS this box will accept (leaves room to run 2 in parallel on 31 GB)")
    ap.add_argument("--out", default=os.path.join(FID, "MANIFEST.csv"))
    ap.add_argument("--stage", action="store_true",
                    help="copy every required matrix into fidelityRuns/matrices/<group>/ and write "
                         "RELATIVE paths, so the whole directory can be copied to another machine")
    ap.add_argument("--all-bigbox", action="store_true",
                    help="assign every job to the bigbox share (use when one machine runs the lot)")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]

    rows, skipped, missing = [], [], []
    for study, rel, fixed_stack, mdir, rule in SOURCES:
        path = os.path.join(RUNS, rel)
        if not os.path.exists(path):
            print(f"!! source missing: {rel}", file=sys.stderr); continue
        for x in csv.DictReader(open(path)):
            if x["status"] != "ok":
                skipped.append((study, os.path.basename(x["matrix"]), x["status"])); continue
            base   = os.path.basename(x["matrix"]).replace(".cm", "")
            stack  = fixed_stack or x["stack"]
            topo   = x.get("fabric") or x.get("topology")
            nodes  = int(x["nodes"]); conns = int(x["conns"])
            mpath  = resolve_matrix(study, mdir, base)
            if not os.path.exists(mpath):
                missing.append((study, base, mpath)); continue
            szm = re.search(r'(\d+)MB', base)
            wl = x.get("workload") or re.sub(r'_\d+n_\d+MB$', '', base)
            if wl == "a2a":
                wl = "a2a_serial" if "serial" in study else "a2a_concurrent"
            qs = qsize_for(stack, nodes, base)
            est = estimate_mb(conns, int(szm.group(1)) if szm else 0, nodes, stack, qs)
            if pinned_bigbox(wl, nodes, int(szm.group(1)) if szm else 0):
                machine, how = "bigbox", "documented-OOM"
            elif est > a.local_budget_mb:
                machine, how = "bigbox", "modelled"
            else:
                machine, how = "local", "modelled"
            for rep, sd in enumerate(seeds, start=1):
                rows.append(dict(
                    study=study, matrix=mpath, workload=wl,
                    size_MB=int(szm.group(1)) if szm else 0,
                    nodes=nodes, conns=conns, stack=stack, topo_kind=topo,
                    seed=sd, rep=rep,
                    logtime_us=logtime_for(rule, base),
                    qsize=qs,
                    est_peak_MB=round(est), est_how=how,
                    machine=machine,
                    orig_wall_s=int(float(x["wall_s"])),
                ))

    # ---- optional staging: matrices travel with the bundle ------------------
    # Grouped by SOURCE directory, not flattened: a2a_128n_*.cm exists in both the
    # concurrent and the serial set with identical names but different contents,
    # so a flat matrices/ directory would silently collide.
    if a.stage:
        import shutil
        GROUP = {"perm_incast_128_1024": "perm_incast",
                 "a2a_concurrent_128_1024": "a2a_concurrent",
                 "a2a_128_1024": "a2a_serial",
                 "allreduce_ring_128": "allreduce_ring",
                 "rail_optimized": "rail"}
        staged, nbytes = {}, 0
        for r in rows:
            src = r["matrix"]
            if not os.path.isabs(src):
                continue
            grp = next((v for k, v in GROUP.items() if k in src), "misc")
            dst_rel = os.path.join("matrices", grp, os.path.basename(src))
            dst = os.path.join(FID, dst_rel)
            if src not in staged:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
                    shutil.copy2(src, dst)
                    nbytes += os.path.getsize(src)
                staged[src] = dst_rel
            r["matrix"] = staged[src]
        print(f"staged {len(staged)} matrices ({nbytes/1e6:.0f} MB copied) into matrices/")

    if a.all_bigbox:
        for r in rows:
            r["machine"] = "bigbox"

    cols = ["study","matrix","workload","size_MB","nodes","conns","stack","topo_kind",
            "seed","rep","logtime_us","qsize","est_peak_MB","est_how","machine","orig_wall_s"]
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

    cells = {(r["study"], r["matrix"], r["stack"], r["topo_kind"]) for r in rows}
    loc = [r for r in rows if r["machine"] == "local"]
    big = [r for r in rows if r["machine"] == "bigbox"]
    print(f"MANIFEST: {len(rows)} jobs  ({len(cells)} cells x {len(seeds)} seeds)  -> {a.out}")
    print(f"  local  : {len(loc):5d} jobs, {sum(r['orig_wall_s'] for r in loc)/3600:8.1f} h serial")
    print(f"  bigbox : {len(big):5d} jobs, {sum(r['orig_wall_s'] for r in big)/3600:8.1f} h serial")
    if big:
        print("  bigbox cells:")
        seen = set()
        for r in sorted(big, key=lambda z: -z["est_peak_MB"]):
            k = (r["workload"], r["nodes"], r["size_MB"], r["stack"], r["topo_kind"])
            if k in seen: continue
            seen.add(k)
            print(f"    {r['est_peak_MB']:7d} MB [{r['est_how']:8s}] {r['stack']:3s} {r['workload']:24s} n={r['nodes']:<5d} {r['size_MB']:3d}MB {r['topo_kind']}")
    if skipped:
        print(f"  excluded (not ok in original): {len(skipped)}")
        for s in sorted(set(skipped))[:12]: print(f"    {s[2]:12s} {s[0]}/{s[1]}")
    if missing:
        print(f"  !! MATRIX MISSING for {len(missing)} cells:")
        for m in missing[:10]: print(f"    {m[0]}/{m[1]} -> {m[2]}")


if __name__ == "__main__":
    main()
