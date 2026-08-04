# IB (RoCE+DCQCN) vs UET (UEC) — data map & comparison guide

Everything you need to compare the two stacks and build a presentation: where each
dataset lives, how it's produced, where the graphs are, and how to line them up.

Two stacks, **same matrices / topology / link speed** (200G, `shared/topos_200g` fat-trees):
- **UET** = `htsim_uec -sender_cc_only` — lossy, per-packet spray + trimming, NSCC congestion control. MTU 4150.
- **IB** = `htsim_roce -queue_type lossless_input -pfc_thresholds 12 15 -dcqcn 8` — lossless PFC fabric, per-flow ECMP, DCQCN. MTU 4000.
  (MTU difference is deliberate & documented — see `IB_DCQCN_README.md`.)

---

## 1. Where the data lives

All under `htsim/sim/datacenter/experiments/runs/`. **Note on git:** the branches
commit the *source* (`rows/*.row`, matrices, scripts); the assembled `*.csv` and
`*.png` are **`.gitignore`d** (`*.csv`, `*.png`, `*.pdf`) and float on disk across
branches. So both datasets are readable no matter which branch is checked out.

| | UET | IB |
|---|---|---|
| home branch | `study/a3-uec-network-metrics` | `dev/ib-dcqcn-fix` |
| dirs | `uet/perm_incast_128_1024/` (90), `uet/a2a_serial_128_1024/` (serial, 10), `uet/a2a_concurrent_128_1024/` (concurrent, 11), `uet/allreduce_ring_128/` (9) | `ib_dcqcn/perm_incast_a2a_128_1024/` (99) |
| per-run rows | `<dir>/rows/*.row` (committed) | `ib_dcqcn/perm_incast_a2a_128_1024/rows/*.row` (untracked) |
| combined CSV | `<dir>/results_combined.csv` (ignored) | `ib_dcqcn/perm_incast_a2a_128_1024/results_ib.csv` (ignored) |
| utilization CSV | `<dir>/utilization_combined.csv` | `ib_dcqcn/perm_incast_a2a_128_1024/utilization_ib.csv` |
| graphs | `graphs/` (fig1–8) | `ib_dcqcn/graphs/` (fig1–8) |

**Comparable subset** (both stacks ran it): **all_workloads 128+1024** (5 patterns ×
3 sizes × 3 OS) **+ a2a-concurrent 128**. IB did **not** run serial-a2a, allreduce,
or a2a-1024; UET has those (and a2a-1024 *timed out*).

---

## 2. How each dataset is produced (extraction)

### UET
```
htsim_uec (per run) -> logs/*.log
rederive_results.sh   -> rows/*.row + results_combined.csv  (+ derived cols)
make_graphs.py, make_graphs_scale.py -> graphs/fig1-8.png
```
- `rederive_results.sh` parses each log (`finished at`, `New:/Rtx:/NACKs:` line,
  `SPURIOUS_COUNT`) into a row, then appends derived columns.
- **Schema (30 cols):** base 22 (`matrix,nodes,conns,fabric,status,wall_s,flows_fin,
  makespan_us,fct_min/p50/p99/max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,
  sleek,spurious`) + `sweep,workload,size_MB,os_ratio,makespan_ms,rtx_corr,nacks_corr,
  nack_pct`. **`rtx_corr`/`nacks_corr`** undo a 32-bit overflow in Rtx/NACK (they hit
  **billions** at 4os/8os a2a); **`nack_pct`** = NACKs/(New+Rtx) = the trim rate.

### IB
```
sweep_compare.sh -> run_one_compare.sh (per matrix,fabric) -> htsim_roce
  parse stdout: makespan/FCT, PFC_PAUSES/PFC_PAUSE_US/MAX_QUEUE_BYTES
  flow_metrics.py: slowdown p50/p99/max + Jain fairness (from per-flow "finished at")
  extract_util.py: per-tier utilization (parse_output on util.bin)
  -> rows/*.row (+util_rows/*.urow) -> results_ib.csv + utilization_ib.csv
make_graphs_ib.py -> ib_dcqcn/graphs/fig1-8.png
```
- **Schema (29 cols):** base 22 (RTS/Bounced/ACKs/Pulls/sleek/spurious = 0, lossless;
  `Rtx`=0; `NACKs` = lossless-overflow count = 0) + **`pfc_pauses,pfc_pause_us,
  max_queue_bytes,slowdown_p50,slowdown_p99,slowdown_max,fairness_jain`**.
- Requires the SIGTERM handler in `main_roce.cpp` (commit `0167684`) or util.bin
  comes out empty. See `IB_DCQCN_README.md` for the full build/run guide.

Utilization CSV (both, 44 cols): `matrix,fabric` + 7 tiers (`overall`,tier0/1/2
up/down) × {n,mean,p50,p95,p99,max}. `overall_max` = hot-link peak.

---

## 3. How to compare the two

**Join key:** `(basename(matrix without .cm), fabric)` — the matrix path prefixes
differ (`/csl/...` for UET vs `/home/...` for IB) but the basename+fabric are identical.

**Ready-made script:** `ib_dcqcn/perm_incast_a2a_128_1024/compare_ib_uet.py`
```bash
cd .../experiments/runs
python3 ib_dcqcn/perm_incast_a2a_128_1024/compare_ib_uet.py
```
It reads `results_ib.csv` + the UET `results_combined.csv`(s) + both utilization CSVs
and prints: (1) completion mismatches, (2) makespan ratio IB/UET by pattern, (3) the
congestion-fingerprint + slowdown/fairness/util table.

### Metric mapping — what's comparable vs stack-specific
| dimension | UET column | IB column | comparable? |
|---|---|---|---|
| completion time | `makespan_us`/`makespan_ms` | same | ✅ direct |
| tail latency | `fct_p99_us` | `fct_p99_us`, `slowdown_p99` | ✅ direct |
| link utilization | `utilization_combined.csv` | `utilization_ib.csv` | ✅ direct |
| **congestion cost** | `nack_pct`, `rtx_corr` (loss+retransmit) | `pfc_pauses`, `pfc_pause_us` (backpressure) | ⚠ **different mechanism** — pair them, don't share an axis |
| fairness | (not recorded) | `fairness_jain` | IB-only |
| robustness | `status` (3 incomplete + 2 a2a timeout) | `status` (all ok) | ✅ direct (IB wins) |

The **common** metrics (makespan, FCT/slowdown, utilization, completion) go head-to-head.
The **congestion** metrics are each stack's *native cost* and must be shown side-by-side,
not overlaid (UET drops+retransmits; IB pauses — opposite failure modes).

---

## 4. The story (for the presentation)

Headline: a clean **speed-vs-robustness tradeoff**.

1. **Robustness — IB completes everything; UET doesn't.** IB: 99/99 ok. UET:
   `incast_random_1024n` @ 8os *incomplete* (all 3 sizes), a2a-1024 *timeout*.
2. **Speed — UET generally faster (IB/UET makespan ≈ 2.2×), IB wins the hard incasts.**
   Biggest gap on **permutation** (IB 3–4× slower: UET sprays across all paths; IB pins
   one ECMP path/flow). IB faster on `incast_random_1024` (0.88×) with a better tail.
3. **Cost each pays.** IB: **0 retransmits** (lossless), pays in PFC pauses (up to
   ~3113 port-sec on 1024 incast) + lower util. UET: retransmits into the **billions
   (overflow 2³¹)** at 4os/8os a2a — each packet sent ~8× under 8× oversub — but
   saturates links (~100% util).

Suggested figure flow (UET `graphs/` + IB `ib_dcqcn/graphs/` are numbered to pair up):
- **Setup:** one slide, the two stacks + the matched knobs (table above).
- **Speed:** IB fig1/fig2 (makespan vs OS) beside UET fig1/fig5.
- **Robustness:** the completion-mismatch list from `compare_ib_uet.py` §1.
- **Cost:** UET fig2 (`nack_pct`) beside IB fig5 (PFC pause-time) — "two ways to pay".
- **Utilization:** IB fig4 beside UET fig3 heatmaps.
- **IB-only depth:** IB fig6 (fairness), fig7 (slowdown), fig8 (peak buffer).
- **Scaling:** IB fig3 / UET fig6 (128 vs 1024).

---

## 5. Reproduce everything
```bash
# UET combined CSVs (from committed rows):
for d in uet/perm_incast_128_1024 uet/a2a_serial_128_1024 uet/a2a_concurrent_128_1024 uet/allreduce_ring_128; do
  bash $d/rederive_results.sh; done
python3 make_graphs.py && python3 make_graphs_scale.py   # -> uet/graphs/

# IB combined CSVs already assembled by the sweep; regenerate graphs:
python3 ib_dcqcn/perm_incast_a2a_128_1024/make_graphs_ib.py           # -> ib_dcqcn/graphs/

# the numeric comparison:
python3 ib_dcqcn/perm_incast_a2a_128_1024/compare_ib_uet.py
```
To (re)run either sweep from scratch, see `IB_DCQCN_README.md` (IB) and each UET dir's
`NOTES.md` / `run_one.sh` / `sweep.sh`.

## 6. Caveats
- **MTU 4000 (IB) vs 4150 (UET)** — deliberate, ~few % proportional effect, documented.
- **a2a-1024 infeasible for both** (UET timeout; IB OOM at 1M flows).
- **UET Rtx/NACK overflow 2³¹** at 4os/8os → use `rtx_corr`/`nacks_corr`, not raw.
- **IB now has serial-a2a + allreduce at 128** (`ib_dcqcn/allreduce_a2a_serial_128`, 18 runs). Only a2a-1024 has no IB
  counterpart yet (would need extra IB sweeps).
- Fairness recorded for IB only; to compare it, recompute UET fairness from its per-flow logs.

---

## 7. Part 2 — rail-optimized cluster + NVLink (added later)

A second study on a **1024-GPU rail-optimized fabric** (128 servers x 8 GPUs, 8 rails,
32 leaves, 32 spines) with a modelled **NVLink** intra-server domain, plus rail-aware
collectives. Everything lives in `rail_optimized/`:

| | |
|---|---|
| results | `rail_optimized/results_rail.csv` (24 runs x 33 cols), `utilization_rail.csv` |
| topologies | `topos/{rail,flat_sameshape,nvlink}_1024gpu*.topo` |
| workloads | `matrices/rail_{allreduce,alltoall_moe}_1024gpu_{16,64,100}MB.cm` |
| generators | `connection_matrices/gen_rail_aware_{allreduce,alltoall}.py` |
| harness | `rail_optimized/run_one_rail.sh`, `sweep_rail.sh` (`PARALLEL` env, default 1) |
| figures | `rail_optimized/graphs/fig1-3` (`make_graphs_rail.py`) |
| design + validation | `rail_optimized/notes/DESIGN_AND_VALIDATION.md` |

Schema is a **superset of both stacks** (33 cols): the common metrics, UET's
Rtx/NACKs/spurious, IB's pfc_pauses/pause_us/max_queue_bytes, plus slowdown and
fairness. NVLink is enabled in **all 24 runs** (rail and flat alike), so rail-vs-flat
isolates only the host->leaf assignment.

Headline results: rails help **IB on every run (-7%..-33%)** but leave **UET
indifferent**; on **MoE all-to-all the two stacks converge and IB wins at 100 MB
(0.89x)**; and rail locality does **not** reduce UET's retransmits, pointing at
receiver-side incast as the real bottleneck. See §8 of the design note.

**Caveat:** `slowdown_*` and `fairness_jain` are recorded but NOT meaningful for these
two workloads — both are trigger-staged, so a flow's finish time includes waiting for
its trigger. Makespan / FCT / utilization / congestion counters are the valid ones.
