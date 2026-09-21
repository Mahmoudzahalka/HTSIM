#!/usr/bin/env python3
"""Move any cell that hit the local memory cap over to the bigbox share.

run_one_fidelity.sh records status=mem_capped when htsim's allocation failed
under ulimit -v. That is a routing signal, not a result: the cell simply needs
more RAM than this box can give it. This rewrites MANIFEST.csv so every seed of
that cell is marked bigbox, and clears the failed .row files so a later local
re-run does not trip over them.
"""
import csv, glob, os, sys

FID = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAN = os.path.join(FID, "MANIFEST.csv")

capped = set()
for p in glob.glob(os.path.join(FID, "*", "rows", "*.row")):
    for line in open(p):
        f = line.rstrip("\n").split(",")
        if len(f) > 10 and f[10] == "mem_capped":
            capped.add((f[0], f[2], int(f[4]), int(f[3]), f[6], f[7]))  # study,wl,nodes,size,stack,topo
            os.remove(p); break

if not capped:
    print("no mem_capped runs -- manifest unchanged"); sys.exit(0)

rows = list(csv.DictReader(open(MAN)))
n = 0
for r in rows:
    k = (r["study"], r["workload"], int(r["nodes"]), int(r["size_MB"]), r["stack"], r["topo_kind"])
    if k in capped and r["machine"] != "bigbox":
        r["machine"] = "bigbox"; r["est_how"] = "measured-cap"; n += 1
with open(MAN, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(f"reassigned {n} jobs ({len(capped)} cells) to bigbox:")
for c in sorted(capped): print("   ", c)
