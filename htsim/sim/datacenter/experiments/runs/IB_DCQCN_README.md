# IB (RoCE + DCQCN) in htsim — work log, results, and reproduction guide

This documents the work to get an **IB-like lossless stack** (RoCE transport + DCQCN
congestion control + PFC lossless fabric) working in htsim, the sweeps run with it,
and how to reproduce everything and compare against the UET (UEC) stack.

- **Repo:** `htsim/sim` (this tree)
- **Branch:** `dev/ib-dcqcn-fix`
- **Key commits:**
  - `e6b7866` — base (roce: restore queue sizes after from-file topo load)
  - `18cf6d7` — partial DCQCN fixes (stop CC timer after completion, gate debug couts, switch configureLossless)
  - `04674ec` — **the DCQCN fixes** (see §1)
  - `0167684` — **IB congestion instrumentation + DCQCN sweep runs** (see §2)

---

## 0. TL;DR — what this is

The "IB-like" stack = `htsim_roce` run with:
```
-queue_type lossless_input -pfc_thresholds 12 15   # lossless PFC fabric (input-buffered)
-dcqcn <K>                                          # DCQCN: ECN mark @ egress when queue > K packets
-strat ecmp_host -paths 128                         # per-flow ECMP (single path/flow, in-order; RoCE needs it)
```
It is the RoCE analogue of the UET/UEC runs (`uet/perm_incast_128_1024`, `uet/a2a_concurrent_128_1024`),
using the **same matrices, topology, and link speed** so results are comparable.

**Headline result** (see §6): a clean **speed-vs-robustness tradeoff**. UET is ~2–4× faster on
well-behaved/permutation traffic (per-packet spray, ~100% link util) but retransmits enormously
under congestion (counters overflow 2³¹ at high oversubscription) and *fails to complete* the
most extreme incasts. IB is slower but **lossless (0 retransmits), completes every workload UET
can't, and has a better tail on the heavy 1024-node incasts** — paying in PFC backpressure.

---

## 1. DCQCN bug fixes (commit `04674ec`)

DCQCN was implemented but **did not work out of the box**. Files: `dcqcn.cpp/.h`, `roce.cpp`,
`dcqcn_logger.cpp`. Ten bugs found and fixed (all comment-preserved with `BUGFIX(#n)` tags):

| # | Bug | Fix |
|---|-----|-----|
| 1 | `_alpha` was `static` → one global α shared by ALL flows (cross-talk) | made per-instance (`dcqcn.h`) |
| 2 | No rate floor → `_RC` (uint64) truncates to 0 → div-by-0 in `update_spacing` → stall/abort | `_min_rate = rate/100000`, clamp in `processCNP` |
| 3 | Byte-counter used packets but `_B` is bytes → BC increase never fired | `*= _mss` (`dcqcn.cpp`) |
| 4 | α-decay timer never advanced `_last_alpha_update` → decayed every tick | set timestamp in the if |
| 5 | Base `RoceSrc::doNextEvent` never stopped after completion (line-329 packets-vs-bytes unit bug); dev `_done` guard was mis-placed | `if(_done)return` at top of `RoceSrc::doNextEvent` + fixed the unit compare |
| 6 | Packet leak on `_done` early-return | `pkt.free()` before return (roce.cpp + dcqcn.cpp) |
| 7 | `_RAI`/`_RHAI` static but set per-instance | made per-instance |
| 8 | `_T`/`_BC` uint16 → overflow ~3.6 s | widened to uint32 |
| 9 | Sink logger type mismatch (`DCQCN_SINK` vs `HPCC_SINK`) | fixed `event_to_str` |
| 10 | Ungated base `RoceSrc` `PAUSE`/`RESUME` couts (209k lines on one 128-incast) | gated behind `_log_me` |

Smoke-tested: DCQCN completes + drains, and makespan tracks the ECN threshold K monotonically
(PFC 82.6ms → K=30 87ms → K=8 95ms → K=2 148ms on a 128-node incast) — i.e. the control loop is live.

## 2. IB congestion instrumentation (commit `0167684`)

To characterize IB's congestion behavior (analogue of UET's Rtx/NACK/spurious counters):

**Tier 1 — binary** (`queue_lossless_input.{h,cpp}`, printed by `main_roce.cpp`):
- `PFC_PAUSES` — number of PFC pause episodes (queue crosses high threshold)
- `PFC_PAUSE_US` — summed port-time spent paused (backpressure)
- `MAX_QUEUE_BYTES` — peak input-queue (PFC buffer) high-water mark

**Tier 2 — harness** (`flow_metrics.py`, from per-flow "finished at" lines):
- `slowdown_p50/p99/max` — FCT ÷ ideal (ideal = flow_bytes / linkrate)
- `fairness_jain` — Jain index over per-flow rates

Also in `0167684`: `main_roce.cpp` gained the **SIGTERM handler** (`roce_handle_sigterm`) so the
watchdog-killed runs finalize `util.bin` cleanly (without it, parse_output reads 0 records →
all-zero utilization), and the `-logtime_us` util-sampling flag.

---

## 3. The runs / sweeps

All under `datacenter/experiments/runs/`. Matrices are reused from `uet/perm_incast_128_1024/matrices/`
(transport-independent `.cm` files); topologies from `shared/topos_200g/fat_tree_${n}_${fabric}.topo`.

| dir | what | status |
|-----|------|--------|
| **`ib_dcqcn/perm_incast_a2a_128_1024/`** | **FINAL instrumented IB sweep** (DCQCN K=8, MTU 4000, 29-col schema). all_workloads 128+1024 + a2a-128. | ✅ 99/99 ok — **use this** |
| `older_runs/ib_dcqcn_k8_22col_superseded/` | first DCQCN K=8 sweep (no PFC/fairness metrics) | superseded by the above |
| `older_runs/pfc_only_no_dcqcn_128_1024_8192/` | PFC-only baseline (no DCQCN) — only run because DCQCN wasn't fixed yet | 90/90 ok, of historical interest |
| `uet/perm_incast_128_1024/` | **UET** all_workloads sweep (compare target) | 45×128 ok, 42×1024 ok, 3×1024 incomplete |
| `uet/a2a_concurrent_128_1024/` | **UET** concurrent all-to-all sweep (compare target) | 9×128 ok, 2×1024 timeout |

**Config for the IB runs** (from `ib_dcqcn/perm_incast_a2a_128_1024/run_one_compare.sh`):
```
htsim_roce -tm <matrix> -nodes <n> -topo <topo> -linkspeed 200000 \
  -strat ecmp_host -paths 128 \
  -queue_type lossless_input -pfc_thresholds 12 15 -q 1000 \
  -dcqcn 8 \
  -end 120000000 -logtime_us <1000|20000> \
  -log tor_downqueue -log tor_upqueue -o util.bin
```
- DCQCN K=8 (ECN threshold in packets; PFC pauses at 12/15). First sweep = one sensible K; tune later.
- MTU **4000** (main_roce default) — deliberately kept ≠ UET's 4150, documented as a stack difference.
- `-logtime_us` is 1000 (perm) / 20000 (incast/outcast/a2a, coarse — utilization is
  sampling-independent, keeps util.bin bounded).
- A **watchdog** SIGTERMs htsim once all flows finish (the util sampler would otherwise run to `-end`).

**a2a note:** a2a is memory-heavy (~8 GB/run — all-to-all route explosion for 16k flows) so it runs
in its own `-P2` phase. **a2a-1024 (1M flows) is infeasible** (OOM); UET timed out there too.

---

## 4. Results & schema

**`ib_dcqcn/perm_incast_a2a_128_1024/results_ib.csv`** — 99 rows, **29 columns**:
```
matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,
fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious,
pfc_pauses,pfc_pause_us,max_queue_bytes,slowdown_p50,slowdown_p99,slowdown_max,fairness_jain
```
- cols 1–22 = the UET-comparable schema (RTS/Bounced/ACKs/Pulls/sleek/spurious are UEC-only → 0
  for RoCE; `NACKs` carries the lossless overflow count, should be 0; `Rtx`=0 since lossless).
- cols 23–29 = the new IB metrics (§2).

**`ib_dcqcn/perm_incast_a2a_128_1024/utilization_ib.csv`** — 99 rows, 44 cols: per-tier link utilization
(`overall` + tier0/1/2 up/down) × {n,mean,p50,p95,p99,max}. `overall_max` (col 8) = hot-link peak.

**UET results:** `uet/perm_incast_128_1024/results_combined.csv` (+`utilization_combined.csv`) and
`uet/a2a_concurrent_128_1024/results_combined.csv`. Same 22-col base + UET's own metadata cols. Their
`Rtx`/`NACKs` columns are the UET congestion fingerprint (⚠ they **overflow 2³¹** at 4os/8os a2a).

---

## 5. How to reproduce

**Build** (CMake):
```bash
cd htsim/sim/build && make htsim_roce      # -> htsim/sim/datacenter/htsim_roce (symlink)
```

**One run** (through the instrumented harness):
```bash
cd htsim/sim/datacenter/experiments/runs/ib_dcqcn/perm_incast_a2a_128_1024
M=../../uet/perm_incast_128_1024/matrices/incast_random_128n_16MB.cm
bash run_one_compare.sh "$M" 1os          # -> rows/<tag>.row (29 cols) + util_rows/<tag>.urow
```

**Full sweep** (detached; ~many hours — the 1024 incasts + a2a-100MB are slow):
```bash
cd .../ib_dcqcn/perm_incast_a2a_128_1024
nohup bash sweep_compare.sh > sweep.log 2>&1 &
# phases: light(128 all_workloads)@-P6 -> heavy(1024)@-P2 -> a2a-128@-P2
# resume-aware (skips rows already ok+util); results assembled into results_ib.csv on completion
```
Env knobs: `DCQCN_K` (default 8), `WORKROOT` (scratch disk, default `/media/.../Data/ib_compare_work`),
`END_US`, `LOGTIME_US`, `QSIZE`, `MSS` (MTU, 4000), `LOGTIME_COARSE_US` (20000).

**Utilization extraction** is automatic in the harness (`extract_util.py` runs `parse_output` on
util.bin). Requires the SIGTERM handler (commit `0167684`) or util.bin comes out empty.

## 5b. Scratch-disk / machine notes (important)

- This box is **~31 GB RAM, small root fs**. Heavy scratch (util.bin, raw stdout) goes to the
  **210 GB disk** `/media/mahmoud_murad_allaah/Data` (`/dev/sdb`). It has **no fstab entry** →
  a reboot drops the mount; remount with `sudo mount /dev/sdb /media/mahmoud_murad_allaah/Data`.
- `WORKROOT` must point there for 1024-node/a2a runs or the root fs fills.
- 1024-node incast util.bin balloons at 1 ms sampling → the harness coarse-samples incast/outcast/a2a.

---

## 6. Key findings (IB vs UET)

Run the comparison: `python3 ib_dcqcn/perm_incast_a2a_128_1024/compare_ib_uet.py`

1. **Robustness — IB completes everything; UET doesn't.** IB finished all 99. UET was *incomplete*
   on all 3 `incast_random_1024n` @ 8os. a2a-1024: both fail.
2. **Speed — UET generally faster (IB/UET mean ≈ 2.2×), IB wins the hard incasts.** Biggest gap on
   permutation (IB 3.3–4.2× slower: UET sprays across all paths, IB pins one ECMP path/flow). IB is
   faster on `incast_random_1024` (0.88×) and `incast_remote_1024` (0.96×), with a better tail.
3. **Cost each stack pays.** IB: **0 retransmits** (lossless), pays in PFC pauses (up to ~3113
   port-sec on 1024 incast) and lower util (0.66–0.99, DCQCN paces). UET: retransmits into the
   **billions, overflowing 2³¹** at 4os/8os a2a, but saturates links (~1.000 util).

**Caveats:** MTU 4000 (IB) vs 4150 (UET) — small, documented; UET Rtx counters overflow at 4os/8os;
fairness computed for IB only (UET would need per-flow logs); a2a-1024 infeasible for both; the perm
gap partly reflects IB's single-path ECMP vs UET spray (intrinsic to each stack — IB *could* use
`-strat ecmp_ar` adaptive routing).

---

## 7. Open / next steps

- **Tune DCQCN K** (and `_min_rate`, `_B`) — K=8 was a first sensible value; a K-sweep on a subset.
- **Symmetric fairness** — recompute UET Jain fairness from its per-flow logs for a like-for-like column.
- **UET counter overflow** — widen UET Rtx/NACK counters to uint64 for exact magnitudes at 4os/8os.
- **Adaptive routing for IB** (`-strat ecmp_ar`) — would close much of the permutation gap; worth a run.
- The **PFC-only baseline** (`older_runs/pfc_only_no_dcqcn_128_1024_8192`) predates the DCQCN fixes and MTU/metrics; it
  is not the comparison of record.
