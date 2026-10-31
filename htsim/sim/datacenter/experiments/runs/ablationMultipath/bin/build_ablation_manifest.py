#!/usr/bin/env python3
"""Build ablationMultipath/MANIFEST.csv from fidelityRuns/MANIFEST.csv.

Every ablation job is a copy of a fidelity job (same matrix, topology, seed,
logtime, qsize) with one arm's flags added, so each ablation row has an exact
baseline row in fidelityRuns/results/runs_all.csv.

  arms   ib  -> qp2, qp4, qp8   (-qps K: flow split over K QPs, each QP keeps
                                 DCQCN + PFC + go-back-N)
         uet -> ecmp            (-load_balancing_algo ecmp: one path per flow)
  scope  topo_kind == 1os only, fabric fat tree only (no rail/flat/NVLink)

usage: build_ablation_manifest.py [--seeds 13,101,202,303,404] [--include-uet-ring-large]

  seeds  default = the 5 fidelity seeds; the pilot phase is seed 13 only
"""
import argparse, csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ABL = os.path.dirname(HERE)
FID = os.path.join(os.path.dirname(ABL), "fidelityRuns")

# Fidelity manifest paths point at fidelityRuns/matrices/<group>/, which is not in
# git. The same files are tracked under uet/*/matrices/ (verified: the current
# binaries reproduce the recorded fidelity rows from them exactly). Paths are
# relative to fidelityRuns/, which is how run_one_fidelity.sh resolves them.
MATRIX_DIR = {
    "perm_incast":    "../uet/perm_incast_128_1024/matrices",
    "allreduce_ring": "../uet/perm_incast_128_1024/matrices",
    "a2a_concurrent": "../uet/a2a_concurrent_128_1024/matrices",
}
ARMS = {
    "ib":  [("qp2", "-qps 2"), ("qp4", "-qps 4"), ("qp8", "-qps 8")],
    "uet": [("ecmp", "-load_balancing_algo ecmp")],
}
HEAVY_WORKLOADS = {"allreduce_ring", "a2a_concurrent"}   # hours-long, GB-scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="13,101,202,303,404")
    ap.add_argument("--include-uet-ring-large", action="store_true",
                    help="keep UET allreduce_ring 64/100 MB (dropped from the fidelity "
                         "study, so they have NO spray baseline)")
    a = ap.parse_args()
    seeds = {s.strip() for s in a.seeds.split(",") if s.strip()}

    out_rows, missing = [], []
    with open(os.path.join(FID, "MANIFEST.csv")) as f:
        for r in csv.DictReader(f):
            if r["topo_kind"] != "1os" or r["seed"] not in seeds or r["stack"] not in ARMS:
                continue
            if (r["stack"] == "uet" and r["workload"] == "allreduce_ring"
                    and r["size_MB"] in ("64", "100") and not a.include_uet_ring_large):
                continue
            group = r["matrix"].split("/")[1]
            matrix = f"{MATRIX_DIR[group]}/{os.path.basename(r['matrix'])}"
            if not os.path.isfile(os.path.normpath(os.path.join(FID, matrix))):
                missing.append(matrix)
            phase = "pilot" if (r["nodes"] == "128" and r["size_MB"] == "16" and r["seed"] == "13") else "main"
            heavy = "1" if r["workload"] in HEAVY_WORKLOADS else "0"
            for arm, args in ARMS[r["stack"]]:
                out_rows.append({
                    "phase": phase, "arm": arm, "arm_args": args,
                    "study": f"abl_{r['stack']}_{arm}", "matrix": matrix,
                    "workload": r["workload"], "size_MB": r["size_MB"], "nodes": r["nodes"],
                    "conns": r["conns"], "stack": r["stack"], "topo_kind": "1os",
                    "seed": r["seed"], "rep": r["rep"], "logtime_us": r["logtime_us"],
                    "qsize": r["qsize"], "heavy": heavy, "baseline_study": r["study"],
                })
    if missing:
        sys.exit("FATAL: matrices not found (relative to fidelityRuns/):\n  " + "\n  ".join(sorted(set(missing))))

    # pilot first, then light before heavy, then small before large
    out_rows.sort(key=lambda r: (r["phase"] != "pilot", r["heavy"], int(r["nodes"]), int(r["size_MB"]),
                                 r["workload"], r["stack"], r["arm"], int(r["seed"])))
    cols = list(out_rows[0].keys())
    with open(os.path.join(ABL, "MANIFEST.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(out_rows)

    from collections import Counter
    print(f"wrote {len(out_rows)} jobs to {os.path.join(ABL, 'MANIFEST.csv')}  (seeds {','.join(sorted(seeds, key=int))})")
    for k, v in sorted(Counter((r["phase"], r["study"]) for r in out_rows).items()):
        print(f"  {k[0]:5s} {k[1]:14s} {v}")


if __name__ == "__main__":
    main()
