#!/usr/bin/env python3
"""Memory-budget scheduler for the ablation: same jobs, runner and rows as
sweep_ablation.sh, but each job gets its own ulimit cap and jobs are packed
under one shared budget instead of a fixed light/heavy split.

Why: after the pilot only IB a2a_concurrent needs a big cap (pilot qp8 peak
~10.8 GB at 16 MB); every other job peaks near 1 GB. One HEAVY_MEM_GB for all
heavy jobs would leave most cores idle.

  PHASE           pilot|main|all             (default main)
  MEM_BUDGET_GB   sum of caps of running jobs (default 84)
  MAX_JOBS        concurrent jobs             (default 10)
  BIG_MEM_GB      cap for IB a2a_concurrent   (default 26)
  BIG_MAX         IB a2a jobs at once while other jobs are still queued (default 2);
                  once the rest is done, as many as the budget allows
  SMALL_MEM_GB    cap for everything else     (default 4)
  RETRY_MEM_GB    a mem_capped job is requeued once with this cap (default 12;
                  big jobs: 40)

Resumable: run_one_fidelity.sh skips any job whose row is already ok.
Stop everything (timeout puts htsim in its own process group, so kill the session):
    pkill -TERM -s $(cat sweep_ablation.pgid)
"""
import csv, os, subprocess, sys, time

ABL = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FID = os.path.abspath(os.path.join(ABL, "..", "fidelityRuns"))
RUNNER = os.path.join(FID, "bin", "run_one_fidelity.sh")
PROG = os.path.join(ABL, "sweep_ablation.progress.log")

E = os.environ
PHASE = E.get("PHASE", "main")
BUDGET = int(E.get("MEM_BUDGET_GB", 84))
MAX_JOBS = int(E.get("MAX_JOBS", 10))
BIG_MEM = int(E.get("BIG_MEM_GB", 26))
BIG_MAX = int(E.get("BIG_MAX", 2))
SMALL_MEM = int(E.get("SMALL_MEM_GB", 4))
RETRY_MEM = int(E.get("RETRY_MEM_GB", 12))
BIG_RETRY_MEM = 40


def log(msg):
    with open(PROG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def row_status(job):
    base = os.path.basename(job["matrix"])[:-3]
    tag = f"{base}.{job['stack']}.{job['topo_kind']}.s{job['seed']}.{job['arm']}"
    p = os.path.join(ABL, job["study"], "rows", tag + ".row")
    try:
        return open(p).read().strip().split(",")[10]
    except (OSError, IndexError):
        return None


def main():
    if PHASE not in ("pilot", "main", "all"):
        sys.exit("PHASE must be pilot|main|all")
    E.setdefault("WORKROOT", os.path.join(ABL, "work"))
    E.setdefault("HTSIM_ROOT", os.path.join(os.path.expanduser("~"), "HTSIM", "htsim"))
    E["OUTROOT"] = ABL
    os.makedirs(E["WORKROOT"], exist_ok=True)

    jobs = [r for r in csv.DictReader(open(os.path.join(ABL, "MANIFEST.csv")))
            if PHASE == "all" or r["phase"] == PHASE]
    for j in jobs:
        j["big"] = j["stack"] == "ib" and j["workload"] == "a2a_concurrent"
        j["cap"] = BIG_MEM if j["big"] else SMALL_MEM
        j["retried"] = False
    # longest first: heavy before light, then bigger size, then more nodes
    key = lambda j: (j["heavy"] != "1", -int(j["size_MB"]), -int(j["nodes"]))
    big = sorted([j for j in jobs if j["big"]], key=key)
    small = sorted([j for j in jobs if not j["big"]], key=key)

    log(f"=== multipath ablation [{PHASE}, budget scheduler] {time.strftime('%F %T')} ===")
    log(f"    {len(big)} IB a2a jobs (cap {BIG_MEM}GB, <= {BIG_MAX} at once while others queue), "
        f"{len(small)} others (cap {SMALL_MEM}GB)")
    log(f"    budget {BUDGET}GB, <= {MAX_JOBS} jobs; workroot {E['WORKROOT']}; htsim {E['HTSIM_ROOT']}")

    running = {}   # Popen -> job
    out = open(PROG, "a")
    while big or small or running:
        used = sum(j["cap"] for j in running.values())
        nbig = sum(j["big"] for j in running.values())
        big_limit = BIG_MAX if small else MAX_JOBS
        launched = True
        while launched and len(running) < MAX_JOBS:
            launched = False
            for q in (big, small):
                if not q or (q is big and nbig >= big_limit):
                    continue
                j = q[0]
                if used + j["cap"] > BUDGET:
                    continue
                q.pop(0)
                env = dict(E, ARM=j["arm"], ARM_ARGS=j["arm_args"], LOGTIME_US=j["logtime_us"],
                           QSIZE=j["qsize"], MEM_CAP_GB=str(j["cap"]))
                p = subprocess.Popen(["bash", RUNNER, j["study"], j["matrix"], j["stack"], j["topo_kind"],
                                      j["seed"], j["rep"]], env=env, stdout=out, stderr=out,
                                     stdin=subprocess.DEVNULL)
                running[p] = j
                used += j["cap"]; nbig += j["big"]; launched = True
                break
        time.sleep(5)
        for p in [p for p in running if p.poll() is not None]:
            j = running.pop(p)
            if row_status(j) == "mem_capped" and not j["retried"]:
                j["retried"] = True
                j["cap"] = BIG_RETRY_MEM if j["big"] else RETRY_MEM
                log(f"[retry] {j['matrix']} {j['arm']} s{j['seed']} with cap {j['cap']}GB")
                (big if j["big"] else small).append(j)

    log(f"=== ablation [{PHASE}] finished {time.strftime('%F %T')} ===")
    out.flush()
    subprocess.run([sys.executable, os.path.join(ABL, "bin", "compare_ablation.py")], stdout=out, stderr=out)


if __name__ == "__main__":
    main()
