#!/bin/bash
# =============================================================================
# fidelityRuns -- ONE seeded run, any stack, any topology, FULL metric superset.
#
# usage: run_one_fidelity.sh <study> <matrix> <stack> <topo_kind> <seed> <rep>
#
#   study      uet_perm_incast | uet_a2a_concurrent | uet_a2a_serial |
#              uet_allreduce_ring | ib_perm_incast_a2a | ib_allreduce_a2a_serial | rail
#   stack      ib | uet
#   topo_kind  1os|4os|8os   -> flat fat-tree (shared/topos_200g), NO NVLink
#              rail|flat     -> rail study topos + NVLink plane
#   seed       integer passed to -seed (seeds FatTreeSwitch hash salt + ECMP
#              path permutation -- this is what makes repeats differ at all)
#   rep        1..N, bookkeeping only
#
# Emits a 36-column .row: the 33-column rail superset + study,seed,rep.
#   common     : makespan, FCT min/p50/p99/max, total_GB
#   UET-native : New/Rtx/RTS/Bounced/ACKs/NACKs/Pulls/sleek/spurious (0 for IB)
#   IB-native  : pfc_pauses / pfc_pause_us / max_queue_bytes / overflow (0 for UET)
#   both       : slowdown p50/p99/max + Jain fairness
# plus a 45-column .urow (base,stack,topo,seed,rep + 42 utilization stats).
#
# -end UNITS ARE NOT THE SAME IN THE TWO STACKS (verified in source):
#   main_roce.cpp:383  setEndtime(timeFromUs(end_time))  -> -end is MICROseconds
#   main_uec.cpp:600   setEndtime(timeFromMs(end_time))  -> -end is MILLIseconds
# despite both printing "endtime(us)". Both values below are 600 simulated
# seconds; max makespan ever observed in this study is 9.53 s, so 60x headroom.
# =============================================================================
set -u

# ---- RELOCATABLE ----------------------------------------------------------
# Everything is derived from this script's own location plus HTSIM_ROOT, so the
# whole fidelityRuns/ directory can be copied to another machine and run there.
# Set HTSIM_ROOT to the checkout that CONTAINS sim/.
# ORIGINAL (kept for easy revert):
# DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
# SIM=/home/mahmoud_murad_allaah/HTSIM/htsim/sim
# FID="$DC/experiments/runs/fidelityRuns"
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HTSIM_ROOT="${HTSIM_ROOT:-/home/mahmoud_murad_allaah/HTSIM/htsim}"
SIM="${SIM:-$HTSIM_ROOT/sim}"
DC="${DC:-$SIM/datacenter}"
ROCE_BIN="${ROCE_BIN:-$DC/htsim_roce}"
UEC_BIN="${UEC_BIN:-$SIM/build/datacenter/htsim_uec}"
# ---- GENERATION: DGX H100 (400 G fabric + NVLink4 3600 G, ratio 9x) --------
# The study previously paired 200 G NICs (A100-era) with NVLink4 (H100-era) = 18x,
# a ratio no shipped system has. topos_h100/ is the 200 G set with ONLY
# Downlink_speed_Gbps rewritten to 400 -- shapes, radices and oversubscription are
# byte-identical, so all 279 cells and every matrix carry over unchanged.
# ORIGINAL (kept for easy revert):
# SHARED="$DC/experiments/runs/shared/topos_200g"
# RAILTOPO="$DC/experiments/runs/rail_optimized/topos"
SHARED="${SHARED:-$FID/topos}"
RAILTOPO="${RAILTOPO:-$FID/topos}"
# Host source rate. MUST equal the topology's Downlink_speed_Gbps or htsim exits
# (FatTreeTopologyCfg::set_linkspeeds).
FABRIC_MBPS="${FABRIC_MBPS:-400000}"
PARSE="${PARSE:-$SIM/build/parse_output}"
HELPERS="${HELPERS:-$FID/bin}"

study="$1"; matrix="$2"; stack="$3"; topo_kind="$4"; seed="$5"; rep="$6"

TIMEOUT="${TIMEOUT:-172800}"          # 48 h hard wall-clock cap per run
QSIZE="${QSIZE:-1000}"                # IB lossless buffer, packets
LOGTIME_US="${LOGTIME_US:-1000}"      # utilization sampling period
NVLINK_MBPS="${NVLINK_MBPS:-3600000}"   # NVLink4, unchanged from A100->H100 in our model
GPS="${GPS:-8}"
PATHS="${PATHS:-128}"
DCQCN_K="${DCQCN_K:-8}"
BPUS="${BPUS:-$((FABRIC_MBPS/8))}"   # link bytes/us for the slowdown ideal. DERIVED from
                                      # FABRIC_MBPS so it tracks the fabric: 400000 Mbps -> 50000 B/us.
                                      # Was hardcoded 25000 (200 Gbps), which understated slowdown 2x at 400 G.
POLL="${POLL:-0.5}"
# HARD PER-JOB MEMORY CAP. This box has 31 GB and a previous sweep exhausted
# RAM+swap and made it unreachable over SSH. ulimit -v makes an oversized run
# fail its allocation and abort in seconds instead of thrashing the machine;
# the run is then recorded as status=mem_capped and belongs on the big box.
# Set MEM_CAP_GB=0 to disable (do that only on the 90 GB machine).
MEM_CAP_GB="${MEM_CAP_GB:-13}"

# LIGHT-PHASE FLOOR, raised mid-sweep 2026-09-25 from 10 -> 20 GB.
# The driver bakes PHASE_MEM_GB into its environment at launch and cannot be
# changed in flight, but this script is re-executed per job, so flooring the
# value here takes effect on every subsequent run WITHOUT restarting the sweep.
# Why: the ib allreduce_ring 100MB 8os cells were measured at 8242-8834 MB, i.e.
# ~86% of the old 10 GB cap, and those runs are 30000-39000 s each -- tipping
# over would cost ~11 h per job, not seconds. 20 GB gives >2x headroom over the
# worst peak seen in 509 IB rows.
# CAVEAT: this breaks the runbook invariant PARALLEL x LIGHT_MEM_GB <= RAM
# (6 x 20 = 120 GB > 94 GB). It is safe only because ulimit -v caps ADDRESS
# SPACE, not reservation, and no IB row in the study has exceeded 8.8 GB, so
# realistic worst case is 6 x ~9 = 54 GB. bin/oom_guard.sh watches for the
# case where that assumption fails. Does not touch the heavy phase (75 > 20).
# FLOOR REMOVED 2026-09-28. It existed only to keep the uet_allreduce_ring 64/100MB
# cells off the 10 GB wall; those cells were dropped from the study, so the floor now
# just overrides whatever cap the caller asked for. MEM_CAP_GB is honoured as given.

# Manifest matrix paths are relative to the bundle so it can move between machines.
case "$matrix" in /*) ;; *) matrix="$FID/$matrix" ;; esac

# Fail fast and legibly on a missing matrix, BEFORE anything tries to read it.
[ -f "$matrix" ] || { echo "FATAL: matrix not found: $matrix" >&2; exit 2; }

for _b in "$ROCE_BIN" "$UEC_BIN" "$PARSE"; do
  [ -x "$_b" ] || { echo "FATAL: not executable: $_b  (set HTSIM_ROOT / ROCE_BIN / UEC_BIN / PARSE)" >&2; exit 4; }
done

n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
base=$(basename "$matrix" .cm)

# ---- 400 G QSIZE OVERRIDE (added 2026-09-26) -------------------------------
# qsize_for() in build_manifest.py gives the 2048-GPU MoE cells -q 8000, a value
# proven clean at 200 G (RUN_ON_BIGGER_BOX.md). At 400 G there is twice as much
# in flight and that same "proven clean" assumption ALREADY FAILED one scale
# down: the 1024-GPU MoE 100 MB cell overflowed at -q 1000 (ovf 2789-3738 flat,
# 73473-78061 rail) despite being clean at 200 G. The 2048 cells are the 60 most
# expensive jobs in the study, so they are not worth gambling on.
# The driver bakes QSIZE into its job list at launch, so overriding here is the
# only way to fix the RUNNING sweep without restarting it.
# Safe: -q does not change the answer, only whether the lossless buffer is
# honestly sized. Cost is ~2 GB more RAM, immaterial under the 75 GB heavy cap.
# ALL rail MoE cells on IB. Narrowing this was a mistake: 1024/100MB was fixed
# but 1024/16MB and 1024/64MB were left at q=1000 on the reasoning that they were
# "clean so far" -- they had simply not run yet, and all 20 then overflowed
# (ovf 65000-71000). Every MoE cell measured on IB at 400 G needs q>1000, so the
# rule is now the whole workload, not a per-size list. allreduce cells are
# genuinely clean at their documented q and stay untouched.
case "$base" in
  rail_alltoall_moe_*)
    if [ "$stack" = ib ] && [ "${QSIZE:-0}" -lt 16000 ]; then QSIZE=16000; fi ;;
esac

# ---- workload label (kept identical to the original harnesses) --------------
case "$base" in
  *allreduce_*gpu*)  workload=allreduce_rail_aware ;;
  *alltoall_moe*)    workload=alltoall_moe_rail_aware ;;
  *) workload=$(echo "$base" | sed -E 's/_[0-9]+n_[0-9]+MB$//') ;;
esac
case "$study" in
  uet_a2a_concurrent|ib_perm_incast_a2a) [ "$workload" = a2a ] && workload=a2a_concurrent ;;
  uet_a2a_serial|ib_allreduce_a2a_serial) [ "$workload" = a2a ] && workload=a2a_serial ;;
esac
size_MB=$(echo "$base" | grep -oE '[0-9]+MB' | tr -d 'MB'); size_MB=${size_MB:-0}

# ---- topology selection -----------------------------------------------------
NV=""
case "$topo_kind" in
  1os|4os|8os) TOPO="$SHARED/fat_tree_${n}_${topo_kind}.topo" ;;
  rail)  TOPO="$RAILTOPO/rail_${n}gpu_8rail.topo"
         NV="-nvlink_topo $RAILTOPO/nvlink_${n}gpu_8pergpu.topo -nvlink_linkspeed $NVLINK_MBPS -gpus_per_server $GPS" ;;
  flat)  TOPO="$RAILTOPO/flat_${n}gpu_sameshape.topo"
         NV="-nvlink_topo $RAILTOPO/nvlink_${n}gpu_8pergpu.topo -nvlink_linkspeed $NVLINK_MBPS -gpus_per_server $GPS" ;;
  *) echo "bad topo_kind: $topo_kind" >&2; exit 2 ;;
esac
[ -f "$TOPO" ] || { echo "missing topo $TOPO" >&2; exit 2; }

tag="${base}.${stack}.${topo_kind}.s${seed}"
log="$FID/$study/logs/${tag}.log"
row="$FID/$study/rows/${tag}.row"
urow="$FID/$study/util_rows/${tag}.urow"

# ---- resume guard: a completed run is never repeated ------------------------
if [ -s "$row" ] && awk -F, '$11=="ok"{ok=1}END{exit !ok}' "$row" 2>/dev/null; then
  echo "[skip $(date +%H:%M:%S)] $tag"; exit 0
fi

WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/fidelity_work}"
work="$WORKROOT/$tag"; rm -rf "$work"; mkdir -p "$work" || exit 3
raw="$work/htsim.stdout"; : > "$raw"
t0=$(date +%s)

if [ "$stack" = ib ]; then
  MSS=4000
  ( cd "$work" && { [ "$MEM_CAP_GB" -gt 0 ] && ulimit -v $((MEM_CAP_GB*1024*1024)); }
    exec timeout "$TIMEOUT" "$ROCE_BIN" \
      -tm "$matrix" -nodes "$n" -topo "$TOPO" $NV -seed "$seed" \
      -linkspeed "$FABRIC_MBPS" -strat ecmp_host -paths "$PATHS" \
      -queue_type lossless_input -pfc_thresholds 12 15 -q "$QSIZE" \
      -dcqcn "$DCQCN_K" -end 600000000 -logtime_us "$LOGTIME_US" \
      -log tor_downqueue -log tor_upqueue -o "$work/util.bin" ) > "$raw" 2>&1 &
else
  MSS=4150
  ( cd "$work" && { [ "$MEM_CAP_GB" -gt 0 ] && ulimit -v $((MEM_CAP_GB*1024*1024)); }
    exec timeout "$TIMEOUT" "$UEC_BIN" \
      -tm "$matrix" -sender_cc_only -nodes "$n" -topo "$TOPO" $NV -seed "$seed" \
      -linkspeed "$FABRIC_MBPS" -end 600000 -logtime_us "$LOGTIME_US" \
      -log tor_downqueue -log tor_upqueue -o "$work/util.bin" ) > "$raw" 2>&1 &
fi
pid=$!

# ---- watchdog: SIGTERM the instant all Connections flows have finished ------
# The mains install a SIGTERM handler that drains the event loop and finalises
# util.bin, so this is a clean stop, not a kill. peak RSS is sampled alongside.
peak_kb=0
( sig=0
  while kill -0 "$pid" 2>/dev/null; do
    f=$(grep -c "finished at" "$raw" 2>/dev/null || true); f=${f:-0}
    if [ "$sig" -eq 0 ] && [ "$f" -ge "$c" ] 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null && sig=1
    fi
    sleep "$POLL"
  done ) & wd=$!
( while kill -0 "$pid" 2>/dev/null; do
    for p in $(pgrep -P "$pid" 2>/dev/null) "$pid"; do
      k=$(awk '/VmHWM/{print $2}' /proc/$p/status 2>/dev/null); k=${k:-0}
      [ "$k" -gt "$peak_kb" ] 2>/dev/null && { peak_kb=$k; echo "$k" > "$work/peak_kb"; }
    done
    sleep 2
  done ) & rssw=$!

wait "$pid"; rc=$?
kill "$wd" "$rssw" 2>/dev/null; wait "$wd" "$rssw" 2>/dev/null
wall=$(( $(date +%s) - t0 ))
peak_mb=$(awk '{printf "%.0f",$1/1024}' "$work/peak_kb" 2>/dev/null); peak_mb=${peak_mb:-0}

# ---- compact the stdout into the per-run log --------------------------------
awk '/finished at/{print;next} /^New:/{print;next} /^PFC_PAUSES/{print;next}
     /Spurious/{sp++;next} /SPURIOUS_COUNT/{print;next}
     /LOSSLESS not working/{ov++;next}
     /Received SIGTERM/{print;next}
     /[Ee]rror|[Mm]ismatch|Aborted|core dumped|terminat/{print;next}
     END{print "SPURIOUS_COUNT " sp+0; print "OVERFLOW_COUNT " ov+0}' "$raw" > "$log"

# ---- FCT distribution (regex must accept scientific notation) ---------------
tmp=$(mktemp)
grep -oE "finished at [0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?" "$log" | awk '{printf "%.6f\n",$3}' | sort -n > "$tmp"
fin=$(wc -l < "$tmp")
if [ "$fin" -gt 0 ]; then
  read -r fmin p50 p99 fmax < <(awk 'NR==FNR{a[++m]=$1;next}END{
    i50=int(m*.5); i50=i50<1?1:i50; i99=int(m*.99); i99=i99<1?1:i99;
    printf "%.1f %.1f %.1f %.1f",a[1],a[i50],a[i99],a[m]}' "$tmp" "$tmp"); mk="$fmax"
else fmin=0;p50=0;p99=0;fmax=0;mk=0; fi
rm -f "$tmp"
bytes=$(awk '/->/{for(i=1;i<=NF;i++) if($i=="size"){s+=$(i+1)}}END{printf "%.3f",(s+0)/1e9}' "$matrix")

# ---- transport counters (UET-native; absent => 0 on IB) ---------------------
read -r nw rtx rts bnc ack nack pull slk < <(grep -E "^New:" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1);else if($i=="RTS:")cc=$(i+1);
  else if($i=="Bounced:")d=$(i+1);else if($i=="ACKs:")e=$(i+1);else if($i=="NACKs:")ff=$(i+1);
  else if($i=="Pulls:")g=$(i+1);else if($i=="sleek_pkts:")h=$(i+1)}
  printf "%s %s %s %s %s %s %s %s",a+0,b+0,cc+0,d+0,e+0,ff+0,g+0,h+0}')
sp=$(grep -oE "SPURIOUS_COUNT [0-9]+" "$log" | tail -1 | awk '{print $2}')

# ---- PFC counters (IB-native; absent => 0 on UET) ---------------------------
read -r pfcp pfcus maxq < <(grep -E "^PFC_PAUSES" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="PFC_PAUSES")a=$(i+1);else if($i=="PFC_PAUSE_US")b=$(i+1);
  else if($i=="MAX_QUEUE_BYTES")cc=$(i+1)} printf "%d %.1f %d",a+0,b+0,cc+0}')
ov=$(grep -oE "OVERFLOW_COUNT [0-9]+" "$log" | tail -1 | awk '{print $2}')

# ---- status -----------------------------------------------------------------
# -end TRUNCATION CANARY. The watchdog is what normally ends a run (it SIGTERMs
# the instant flows_fin == Connections, which the mains handle by draining the
# event loop cleanly). -end is only a fallback cap. If -end ever fired first the
# sim would stop with fin < c, which falls through to "incomplete" below -- it
# can NEVER be mislabelled "ok". This canary additionally warns if a makespan
# gets within 10% of the cap, long before truncation could bite.
cap_us=$([ "$stack" = ib ] && echo 600000000 || echo 600000000)   # both = 600 simulated seconds
near=$(awk -v m="$mk" -v c="$cap_us" 'BEGIN{print (c>0 && m>0.9*c)?1:0}')
[ "$near" = 1 ] && echo "[WARN] $tag makespan ${mk}us is within 10% of the ${cap_us}us -end cap" >&2

status=ok
[ "$rc" = 124 ] && status=timeout
[ "$rc" = 137 ] && status=oom_or_killed
# Allocation failure under the ulimit cap: not a result, a routing decision.
if grep -qiE 'bad_alloc|Cannot allocate memory|out of memory|std::bad_alloc' "$raw" 2>/dev/null; then
  status=mem_capped
  echo "[MEM] $tag exceeded ${MEM_CAP_GB}GB cap -> reassign to the big box" >&2
fi
# NB: must not clobber mem_capped. A memory-capped run ALWAYS has fin < c, so the
# unguarded version of this line overwrote every mem_capped with "incomplete" --
# which made status=mem_capped unreachable and bin/reassign_capped.py a no-op.
[ "$status" != mem_capped ] && [ "$fin" -lt "$c" ] && [ "$rc" != 124 ] && { [ "$fin" = 0 ] && status=failed || status=incomplete; }
# A lossless fabric that overflowed is MIS-CONFIGURED, not a result: htsim only
# warns and keeps the packet, so timings silently reflect a bigger buffer.
[ "$stack" = ib ] && [ "${ov:-0}" -gt 0 ] 2>/dev/null && status=lossless_overflow

sd50=0; sd99=0; sdmax=0; fair=0
[ "$fin" -gt 0 ] && read -r sd50 sd99 sdmax fair < <(python3 "$HELPERS/flow_metrics.py" "$log" "$MSS" "$BPUS" 2>/dev/null | tr ',' ' ')

printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
 "$study" "$matrix" "$workload" "$size_MB" "$n" "$c" "$stack" "$topo_kind" "$seed" "$rep" \
 "$status" "$wall" "$peak_mb" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
 "${nw:-0}" "${rtx:-0}" "${rts:-0}" "${bnc:-0}" "${ack:-0}" "${nack:-0}" "${pull:-0}" "${slk:-0}" "${sp:-0}" \
 "${pfcp:-0}" "${pfcus:-0}" "${maxq:-0}" "${sd50:-0}" "${sd99:-0}" "${sdmax:-0}" "${fair:-0}" "${ov:-0}" > "$row"

echo "[done $(date +%H:%M:%S)] $tag status=$status rc=$rc flows=$fin/$c mk=${mk}us rss=${peak_mb}MB ovf=${ov:-0} wall=${wall}s"

if [ -s "$work/util.bin" ] && [ -s "$work/idmap.txt" ] && [ "$status" != failed ] && [ "$status" != timeout ]; then
  u=$(python3 "$HELPERS/extract_util.py" "$PARSE" "$work/util.bin" "$work/idmap.txt" "$mk" 2>/dev/null || echo "")
  [ -n "$u" ] && printf "%s,%s,%s,%s,%s,%s\n" "$study" "$base" "$stack" "$topo_kind" "$seed" "$u" > "$urow"
fi
rm -rf "$work"
