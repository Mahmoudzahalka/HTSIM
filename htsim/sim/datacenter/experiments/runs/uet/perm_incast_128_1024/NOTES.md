# all_workloads_128_1024/ — sweep notes

Sweep launched 2026-07-03 22:38, finished 04:55 (~6 h 17 min). All 90 runs completed.

## Coverage

5 patterns × 3 sizes × 2 tree sizes × 3 fabrics = **90 runs**.

- **Patterns**: `perm_random`, `perm_fullbis`, `incast_random`, `incast_remote`, `outcast_incast`
- **Flow sizes**: 16 MB, 64 MB, 100 MB
- **Tree sizes**: 128, 1024
- **Fabrics**: 1os (full bisection), 4os, 8os

## Setup summary

- htsim branch `study/a3-uec-network-metrics`, built from local CMake (`sim/build/datacenter/htsim_uec`).
- NSCC (`-sender_cc_only`), 200 Gbps host links.
- Topologies reused from `../a3_200g/topos_200g/fat_tree_{128,1024}_{1os,4os,8os}.topo`.
- Per-tier link utilization sampled at 1 ms via `-log tor_downqueue -log tor_upqueue`.
- Sim shutdown: **watchdog** (external, in `run_one.sh`) counts `finished at` stdout lines against the matrix `Connections M`; on match, sends `SIGTERM` to htsim. `main_uec.cpp` has a 10-line SIGTERM handler that breaks the sim loop cleanly so `~Logfile()` + `Logged::dump_idmap()` finalize the binary log and the epilogue `New: ...` summary line still gets printed. This removed the need for per-workload `-end` tuning.
- `-end 30000ms` in `sweep.sh` is a **safety cap only**; the watchdog fires first in every run that completes normally.

## Output CSVs

- **`results_combined.csv`** — 90 rows. FCT / transport metrics per (matrix, fabric).
  - `status`: `ok` (87), `incomplete` (3 — see below).
- **`utilization_combined.csv`** — 90 rows. Per-tier link utilization (overall + 6 tier-direction groups × {n, mean, p50, p95, p99, max}).
  - **8 rows are blanked** (matrix+fabric kept, stats empty/NaN) — see divisor bug below.

## Excluded / Deferred

- **All-to-All**: deferred per user request. Generators exist (`gen_serial_alltoall.py`), but not in this sweep.
- **AllReduce (ring + butterfly)**: **broken in stock htsim main**. Confirmed by isolated test (no watchdog, no logging):
  - `allreduce_ring_128n_16MB`: expected 32,640 flows, got 884 (chain breaks after ~7 rounds).
  - `allreduce_butterfly_128n_16MB`: expected 896, got 128 (only round 0 fires; `recv_done_trigger` cascade doesn't propagate).
  - Needs separate investigation of `uec_snk->setEndTrigger` / `Trigger` class in the connection-matrix layer.

## Corrections applied post-sweep

### 1. Cout-scientific-notation FCT parsing bug

`main_uec.cpp` / `uec.cpp` prints `Flow ... finished at <t>` using default `cout` precision (6), which switches to scientific notation when `t > ~1e6 µs`. The original `run_one.sh` regex `finished at [0-9.]+` clipped the exponent (`4.68919e+06` → captured as `4.68919`). Rows with real sim time > ~1 s reported `makespan_us` off by a factor of 1e6.

**Fixed** in `run_one.sh`. All rows re-derived from `logs/*.log` via `rederive_results.sh` (regex now: `finished at [0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?`). CSV rebuilt — verified sensible.

### 2. Utilization divisor bug (8 rows)

`extract_util.py` divides `_cumarr` (seconds) by `makespan_us / 1e6`. For the 8 rows where the FCT bug (above) put a value ~1e6× smaller than reality into `makespan_us`, the divisor was ~1e6× too small → utilization values saturated at 1.0 (clipped) across all queues. **These 8 util rows have been blanked** — raw `util.bin` files were deleted after extraction (by design, to save disk) so we cannot re-derive without re-running. The blanked rows are:

| Matrix | Fabric | Real makespan (from re-derived CSV) |
|---|---|---|
| incast_random_1024n_64MB | 1os | 3001 ms |
| incast_random_1024n_100MB | 1os | 4689 ms |
| incast_remote_1024n_64MB | 1os / 4os / 8os | 1431 / 1387 / 1387 ms |
| incast_remote_1024n_100MB | 1os / 4os / 8os | 2236 / 2168 / 2167 ms |

To recover utilization for these 8: rerun with `sweep.sh` filtered to just those cases (~1 day at -P2).

### 3. Reporting formula for congestion loss

Do **not** compute `NACK% = NACKs / New` — under heavy trim/spray load NACKs can exceed New because each packet may be trimmed multiple times, each triggering a NACK. Use `NACKs / (New + Rtx)` for a bounded "packets trimmed as fraction of all transmissions". Example: 1024-way incast at 1os shows 89% by this measure — each packet trimmed ~8× on average.

## 3 `incomplete` rows — real transport observation

All three are `incast_random_1024n_*.8os` (16MB, 64MB, 100MB), each showing `flows_fin = 1020 / 1023`. The same 3 source hosts consistently fail to complete at 8:1 oversubscription with 1023-way incast — under 89-91% packet-trim rate, they get stuck in the retransmission loop and never send their last byte before htsim's `-end 30000 ms` safety cap fires. **This is a real observation about UEC behavior at extreme scale**, not a sweep artifact: the same 4 src indices (294, 337, 667, 1023) show up across the three flow sizes on 8os. Report as-is with the `incomplete` status.

## Files

```
NOTES.md                        this file
results_combined.csv            main metrics (90 rows, post-fix)
utilization_combined.csv        util metrics (90 rows, 8 blanked)
matrices/                       42 generated .cm files (only 30 used -- 12 AR excluded)
logs/                           per-run filtered stdout (source of truth for re-derivation)
rows/                           per-run CSV rows (regenerated by rederive_results.sh)
util_rows/                      per-run util CSV rows
run_one.sh                      single-job runner with watchdog + SIGTERM
sweep.sh                        two-phase driver (light -P5, heavy -P2)
gen_all_matrices.sh             matrix generator wrapper
extract_util.py                 per-tier utilization extractor (parse_output -> stats)
rederive_results.sh             re-emit rows/ + results_combined.csv from logs/
blank_bad_utils.sh              blank the 8 divisor-corrupted util rows
sweep.pid                       PID of the sweep driver (1313112)
sweep.out                       sweep driver stdout log
```
