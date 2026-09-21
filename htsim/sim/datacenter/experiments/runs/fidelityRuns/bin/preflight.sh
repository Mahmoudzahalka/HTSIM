#!/bin/bash
# Verify this machine can run the study BEFORE committing days of compute.
# Checks every prerequisite and prints a single PASS/FAIL verdict.
#   usage: HTSIM_ROOT=/path/to/HTSIM/htsim bash bin/preflight.sh
set -u
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HTSIM_ROOT="${HTSIM_ROOT:-$HOME/HTSIM/htsim}"
SIM="$HTSIM_ROOT/sim"; DC="$SIM/datacenter"
ROCE_BIN="${ROCE_BIN:-$DC/htsim_roce}"; UEC_BIN="${UEC_BIN:-$SIM/build/datacenter/htsim_uec}"
PARSE="${PARSE:-$SIM/build/parse_output}"
fail=0
ok   () { printf "  \033[32mPASS\033[0m  %s\n" "$1"; }
bad  () { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; fail=1; }
warn () { printf "  WARN  %s\n" "$1"; }

echo "=== binaries ==="
for b in "$ROCE_BIN" "$UEC_BIN" "$PARSE"; do
  [ -x "$b" ] && ok "$(basename "$b")" || bad "missing/not executable: $b"
done

echo "=== the NVLink speed check is present in the build ==="
# Without it, a wrong -nvlink_linkspeed silently throttles instead of erroring.
# It lives in main_roce.cpp / main_uec.cpp / fat_tree_topology.h (grep NVLINK-SPEED-CHECK).
if [ -x "$ROCE_BIN" ] && strings "$ROCE_BIN" 2>/dev/null | grep -q 'NVLink speed mismatch'; then
  ok "htsim_roce carries NVLINK-SPEED-CHECK"
else bad "htsim_roce lacks NVLINK-SPEED-CHECK -- your checkout predates it; git pull and rebuild"; fi
if [ -x "$UEC_BIN" ] && strings "$UEC_BIN" 2>/dev/null | grep -q 'NVLink speed mismatch'; then
  ok "htsim_uec carries NVLINK-SPEED-CHECK"
else bad "htsim_uec lacks NVLINK-SPEED-CHECK -- your checkout predates it; git pull and rebuild"; fi

echo "=== topologies (expect 15, fabric 400 G, NVLink 3600 G) ==="
nt=$(ls "$FID"/topos/*.topo 2>/dev/null | wc -l)
[ "$nt" = 15 ] && ok "15 topologies present" || bad "found $nt topologies, expected 15"
sp=$(grep -h -oE 'Downlink_speed_Gbps [0-9]+' "$FID"/topos/*.topo 2>/dev/null | awk '{print $2}' | sort -u | paste -sd,)
[ "$sp" = "3600,400" ] && ok "speeds are exactly {400 fabric, 3600 NVLink}" || bad "unexpected speeds: $sp"

echo "=== matrices ==="
miss=0; n=0
while IFS=, read -r _ m rest; do
  [ "$m" = matrix ] && continue
  n=$((n+1)); [ -f "$FID/$m" ] || miss=$((miss+1))
done < <(cut -d, -f1,2 "$FID/MANIFEST.csv" 2>/dev/null)
[ "$miss" = 0 ] && ok "all matrices referenced by the manifest are present" || bad "$miss/$n manifest rows point at a missing matrix -- run: bash bin/regen_matrices.sh"

echo "=== manifest ==="
j=$(( $(wc -l < "$FID/MANIFEST.csv" 2>/dev/null || echo 1) - 1 ))
[ "$j" -gt 0 ] && ok "$j jobs queued" || bad "manifest empty or absent"

echo "=== resources ==="
ram=$(free -g 2>/dev/null | awk '/^Mem:/{print $7}'); cores=$(nproc 2>/dev/null || echo 0)
echo "        RAM available: ${ram:-?} GB   cores: $cores"
[ "${ram:-0}" -ge 60 ] 2>/dev/null && ok "RAM is enough for PARALLEL=6 x 10 GB" \
  || warn "under 60 GB available -- lower PARALLEL or LIGHT_MEM_GB (see the profile in sweep_fidelity.sh)"
avail=$(df -BG --output=avail "${WORKROOT:-$FID}" 2>/dev/null | tail -1 | tr -dc 0-9)
[ "${avail:-0}" -ge 20 ] 2>/dev/null && ok "scratch disk has ${avail} GB free" || warn "scratch disk has only ${avail:-?} GB free"

echo
[ "$fail" = 0 ] && echo "PREFLIGHT PASSED -- safe to start the sweep." \
                || { echo "PREFLIGHT FAILED -- fix the items above before starting."; exit 1; }
