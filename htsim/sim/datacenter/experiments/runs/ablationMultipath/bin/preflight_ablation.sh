#!/bin/bash
# Verify this machine can run the multipath ablation BEFORE committing days of compute.
#   usage: HTSIM_ROOT=/path/to/HTSIM/htsim WORKROOT=/big/disk/abl_work bash bin/preflight_ablation.sh
# Runs 4 short sims (~1 min total) unless SKIP_REPRO=1:
#   1. baseline reproduction: perm_random_128n_16MB, 1os, seed 13, IB K=1 and UET spray,
#      must match fidelityRuns/results/runs_all.csv EXACTLY (else the baselines can't be reused)
#   2. arm check: the same cell with -qps 2 (IB) and -load_balancing_algo ecmp (UET)
#      must finish ok and must actually change behaviour.
set -u
ABL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FID="$(cd "$ABL/../fidelityRuns" && pwd)"
HTSIM_ROOT="${HTSIM_ROOT:-$HOME/HTSIM/htsim}"; export HTSIM_ROOT
SIM="$HTSIM_ROOT/sim"; DC="$SIM/datacenter"
ROCE_BIN="${ROCE_BIN:-$DC/htsim_roce}"; UEC_BIN="${UEC_BIN:-$SIM/build/datacenter/htsim_uec}"
PARSE="${PARSE:-$SIM/build/parse_output}"
WORKROOT="${WORKROOT:-$ABL/work}"; export WORKROOT
fail=0
ok   () { printf "  \033[32mPASS\033[0m  %s\n" "$1"; }
bad  () { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; fail=1; }
warn () { printf "  WARN  %s\n" "$1"; }

echo "=== source carries the ablation code ==="
grep -q "MULTI-QP" "$DC/main_roce.cpp" 2>/dev/null && ok "main_roce.cpp has -qps (MULTI-QP)" || bad "main_roce.cpp lacks -qps -- git pull the 'ablations' branch"
[ "$(grep -c 'BUGFIX(#11)' "$SIM/roce.cpp" "$SIM/dcqcn.cpp" 2>/dev/null | awk -F: '{s+=$2}END{print s+0}')" -ge 2 ] \
  && ok "roce.cpp + dcqcn.cpp have BUGFIX(#11) (PFC-pause leak)" || bad "BUGFIX(#11) missing -- K>1 ring runs will run out of memory"
grep -q "ARM_ARGS" "$FID/bin/run_one_fidelity.sh" && ok "run_one_fidelity.sh has the ablation hooks" || bad "run_one_fidelity.sh lacks ARM/ARM_ARGS/OUTROOT -- git pull"

echo "=== binaries are built from that source ==="
for b in "$ROCE_BIN" "$UEC_BIN" "$PARSE"; do [ -x "$b" ] && ok "$(basename "$b")" || bad "missing/not executable: $b"; done
strings "$ROCE_BIN" 2>/dev/null | grep -q "Queue pairs per flow" && ok "htsim_roce understands -qps" || bad "htsim_roce predates -qps -- rebuild"
strings "$UEC_BIN" 2>/dev/null | grep -q "Load balancing algorithm set to" && ok "htsim_uec understands -load_balancing_algo" || bad "htsim_uec lacks -load_balancing_algo"
for pair in "$ROCE_BIN:$SIM/roce.cpp" "$ROCE_BIN:$SIM/dcqcn.cpp" "$ROCE_BIN:$DC/main_roce.cpp"; do
  b=${pair%%:*}; s=${pair#*:}
  [ "$b" -nt "$s" ] && ok "$(basename "$b") newer than $(basename "$s")" || bad "$(basename "$b") is OLDER than $(basename "$s") -- rebuild"
done

echo "=== topologies + matrices ==="
for n in 128 1024; do
  t="$FID/topos/fat_tree_${n}_1os.topo"
  [ -f "$t" ] && [ "$(grep -oE 'Downlink_speed_Gbps [0-9]+' "$t" | awk '{print $2}' | sort -u)" = 400 ] \
    && ok "fat_tree_${n}_1os.topo present, 400 G" || bad "fat_tree_${n}_1os.topo missing or not 400 G"
done
[ -f "$ABL/MANIFEST.csv" ] || bad "no MANIFEST.csv -- run: python3 bin/build_ablation_manifest.py"
miss=0; n=0
while IFS=, read -r _ _ _ _ m _; do
  [ "$m" = matrix ] && continue; n=$((n+1)); [ -f "$FID/$m" ] || miss=$((miss+1))
done < "$ABL/MANIFEST.csv"
[ "$miss" = 0 ] && ok "all matrices for $n manifest jobs present" || bad "$miss/$n jobs point at a missing matrix"
[ -f "$FID/results/runs_all.csv" ] && ok "baseline rows present (fidelityRuns/results/runs_all.csv)" || bad "fidelityRuns/results/runs_all.csv missing"

echo "=== resources ==="
ram=$(free -g | awk '/^Mem:/{print $7}'); echo "        RAM available: ${ram:-?} GB   cores: $(nproc)"
[ "${ram:-0}" -ge 80 ] && ok "RAM >= 80 GB (6 x 10 GB light, 2 x 40 GB heavy)" || warn "under 80 GB -- lower PARALLEL / HEAVY_PARALLEL / *_MEM_GB"
mkdir -p "$WORKROOT" 2>/dev/null || bad "cannot create WORKROOT $WORKROOT"
avail=$(df -BG --output=avail "$WORKROOT" 2>/dev/null | tail -1 | tr -dc 0-9)
fs=$(df --output=target "$WORKROOT" 2>/dev/null | tail -1)
echo "        WORKROOT $WORKROOT -> filesystem $fs, ${avail:-?} GB free"
[ "${avail:-0}" -ge 50 ] && ok "scratch disk has ${avail} GB free" || bad "scratch disk has only ${avail:-?} GB free (want >= 50) -- set WORKROOT to a big, MOUNTED disk"

if [ "${SKIP_REPRO:-0}" != 1 ] && [ "$fail" = 0 ]; then
  echo "=== baseline reproduction + arm check (4 short runs) ==="
  T="$WORKROOT/preflight_out"; rm -rf "$T"; mkdir -p "$T"
  M=../uet/perm_incast_128_1024/matrices/perm_random_128n_16MB.cm
  run () { OUTROOT="$T" ARM="$1" ARM_ARGS="$2" LOGTIME_US=20000 QSIZE=1000 MEM_CAP_GB=10 \
             bash "$FID/bin/run_one_fidelity.sh" "$3" "$M" "$4" 1os 13 1 | tail -1; }
  run ""     ""                           pf_ib   ib
  run ""     ""                           pf_uet  uet
  run "qp2"  "-qps 2"                     pf_ibk  ib
  run "ecmp" "-load_balancing_algo ecmp"  pf_uete uet
  python3 - "$T" "$FID/results/runs_all.csv" <<'EOF' || fail=1
import csv, glob, os, sys
T, base = sys.argv[1], sys.argv[2]
COLS = ["study","matrix","workload","size_MB","nodes","conns","stack","topo_kind","seed","rep","status","wall_s","peak_mb",
        "flows_fin","makespan_us","fct_min_us","fct_p50_us","fct_p99_us","fct_max_us","total_GB","New","Rtx","RTS","Bounced",
        "ACKs","NACKs","Pulls","sleek","spurious","pfc_pauses","pfc_pause_us","max_queue_bytes","slowdown_p50","slowdown_p99",
        "slowdown_max","fairness_jain","overflow"]
def row(study):
    p = glob.glob(os.path.join(T, study, "rows", "*.row"))
    return dict(zip(COLS, open(p[0]).read().strip().split(","))) if p else None
ref = {}
for r in csv.DictReader(open(base)):
    if os.path.basename(r["matrix"]) == "perm_random_128n_16MB.cm" and r["topo_kind"] == "1os" and r["seed"] == "13":
        ref[r["stack"]] = r
bad = 0
CHECK = {"ib": ["flows_fin","makespan_us","fct_p99_us","pfc_pauses","max_queue_bytes"],
         "uet": ["flows_fin","makespan_us","fct_p99_us","New","Rtx","NACKs"]}
for study, stack in (("pf_ib","ib"), ("pf_uet","uet")):
    got, want = row(study), ref.get(stack)
    if not got or not want:
        print(f"  \033[31mFAIL\033[0m  {stack}: missing run row or baseline row"); bad = 1; continue
    diff = [k for k in CHECK[stack] if float(got[k]) != float(want[k])]
    if diff:
        print(f"  \033[31mFAIL\033[0m  {stack} baseline NOT reproduced: " + ", ".join(f"{k} {got[k]} vs recorded {want[k]}" for k in diff)); bad = 1
    else:
        print(f"  \033[32mPASS\033[0m  {stack} baseline reproduced exactly (makespan {got['makespan_us']} us)")
for study, stack, label in (("pf_ibk","ib","-qps 2"), ("pf_uete","uet","ecmp")):
    got = row(study)
    if not got or got["status"] != "ok":
        print(f"  \033[31mFAIL\033[0m  {label}: run not ok ({got['status'] if got else 'no row'})"); bad = 1
    elif got["makespan_us"] == ref[stack]["makespan_us"]:
        print(f"  \033[31mFAIL\033[0m  {label}: identical to baseline -- the arm flag did not take effect"); bad = 1
    else:
        print(f"  \033[32mPASS\033[0m  {label} runs ok and changes behaviour (makespan {got['makespan_us']} vs {ref[stack]['makespan_us']} us)")
log =glob.glob(os.path.join(T, "pf_ibk", "logs", "*.log"))
if not (log and " qps 2" in open(log[0]).read()):
    print("  \033[31mFAIL\033[0m  -qps 2 log has no per-flow 'qps 2' finish lines"); bad = 1
sys.exit(bad)
EOF
  rm -rf "$T"
fi

echo
[ "$fail" = 0 ] && echo "PREFLIGHT PASSED -- safe to start: PHASE=pilot bash bin/start_ablation.sh" \
                || { echo "PREFLIGHT FAILED -- fix the items above before starting."; exit 1; }
