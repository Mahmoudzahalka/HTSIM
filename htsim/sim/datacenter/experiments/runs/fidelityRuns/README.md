# fidelityRuns — multi-seed repeat study

**Generation: DGX H100 — 400 G fabric + NVLink4 3600 G (ratio 9x).**
The original study paired 200 G NICs (A100-era) with NVLink4 (H100-era), a **18x**
ratio no shipped system has, overstating NVLink's advantage ~2x against the H100
machine this topology otherwise describes. Topologies live in
`shared/topos_h100/` and are the 200 G set with **only** `Downlink_speed_Gbps`
rewritten — shapes, radices and oversubscription are byte-identical, so all 279
cells and every matrix carry over unchanged.

Two knobs per plane, and they do NOT behave the same:

| plane | topology file | flag | if they disagree |
|---|---|---|---|
| fabric | `Downlink_speed_Gbps` | `-linkspeed` | htsim **exits** (`set_linkspeeds`) |
| NVLink | `Downlink_speed_Gbps` | `-nvlink_linkspeed` | htsim **exits** — *added 2026-09-21*; previously **no check**, and the slower silently throttled the faster |

`-nvlink_linkspeed` is the host *source* rate (the `RoceSrc`/`UecNIC` rate) while
the topology sets *link capacity*; nothing verified they matched. See
`NVLINK-SPEED-CHECK` in `main_roce.cpp`, `main_uec.cpp` and `fat_tree_topology.h`.

Re-runs every workload that **completed** in the original study, **5 times each
with a different RNG seed**, and reports means ± spread instead of a single
sample. Everything else (topologies, matrices, transports, metric extraction) is
identical to the original harnesses, so the two are directly comparable.

## Why repeats change anything at all

htsim is a deterministic event simulator: same inputs, same seed, same answer.
The variation comes from `-seed`, which feeds `srand`/`srandom` and through them
`FatTreeSwitch`:

```
fat_tree_switch.cpp:18    _hash_salt = random();           // per-switch ECMP hash salt
fat_tree_switch.cpp:86    start = random()%ecmp_set->size();
fat_tree_switch.cpp:311   permute_paths()                  // path permutation
```

So each seed gives a different ECMP path assignment — a different sample of the
congestion the fabric could have produced.

**No previous sweep ever passed `-seed`.** They all took main's default of 13,
so the entire published dataset is a single draw. Measured on one cell
(`perm_random_128n_16MB`, 1os) during bring-up:

| stack | seed 13 | seed 101 | seed 202 | spread |
|---|---|---|---|---|
| UET | 782.0 µs | 765.9 µs | 769.0 µs | 2.1% |
| IB  | 4449.0 µs | 4676.1 µs | 4352.0 µs | **7.4%** |

For reference, the rail-vs-flat IB gain the study reports is 12%. Single-seed
differences smaller than the seed spread are not results.

Seed 13 is kept as repeat 1. At 200 G it reproduced the published numbers
*exactly* (0.00% across all 90 cells aggregated), which validated the harness.
**At 400 G it will no longer match, and should not** — `--check-rep1` now measures
the generation change rather than gating correctness. Smoke-measured:

| cell | 200 G | 400 G | ratio |
|---|---|---|---|
| perm_random uet 1os | 782.0 us | 397.6 us | 1.97x — pure serialization |
| perm_random ib 1os | 4449.0 us | 2570.4 us | 1.73x — hop latency unchanged |
| allreduce uet rail | 357.2 us | 237.6 us | 1.50x — latency-bound phases gain least |
| allreduce ib rail | 1139.2 us | 391.6 us | **2.91x — superlinear** |

That last row matters: doubling the link bought **more than** a 2x speedup, so a
large part of the 200 G cost was congestion, not serialization. Conclusions drawn
at 200 G about IB congestion should be re-checked, not assumed to carry over.

## Scope

279 cells × 5 seeds = **1395 runs**. Seeds: `13, 101, 202, 303, 404`.

Included: every cell with `status == ok` in the original CSVs.
Excluded, because repeating a run we know does not finish only burns budget:

| cell | original status |
|---|---|
| `a2a_1024n_16MB` uet 1os, 4os | timeout |
| `a2a_1024n_16MB` uet serial 1os | incomplete |
| `incast_random_1024n_{16,64,100}MB` uet 8os | incomplete |

Also excluded entirely: the **PFC-only (no-DCQCN) arm**. In this study "IB"
means RoCE with PFC *and* DCQCN K=8.

## Metrics — the full superset, for every run

All 7 studies now record the same 37 columns, which is a superset of what any
original harness recorded (the UET sweeps only ever wrote 22 columns).

| group | columns |
|---|---|
| identity | study, matrix, workload, size_MB, nodes, conns, stack, topo_kind, seed, rep |
| outcome | status, wall_s, **peak_mb**, flows_fin |
| timing (shared) | makespan_us, fct_min/p50/p99/max_us, total_GB |
| **UET-native** | New, Rtx, RTS, Bounced, ACKs, NACKs, Pulls, sleek, spurious |
| **IB-native** | pfc_pauses, pfc_pause_us, max_queue_bytes, overflow |
| shared derived | slowdown_p50/p99/max, fairness_jain |
| utilization | 42 more in the `.urow`: overall + 6 tier groups × (n, mean, p50, p95, p99, max) |

A stack that cannot produce a counter writes 0 for it, so the schema is uniform
and joins need no special-casing.

## No run ends early

Two separate mechanisms, and only one of them could ever truncate:

1. **Watchdog (what actually stops runs).** Polls stdout, counts `finished at`
   lines, and SIGTERMs the moment the count reaches the matrix's `Connections`.
   Both mains handle SIGTERM by draining the event loop and finalising
   `util.bin` (`main_roce.cpp:727`, `main_uec.cpp:1186`), so this is a clean
   stop *after every flow completed*, not a kill.
2. **`-end` (fallback cap only).** Set to **600 simulated seconds on both
   stacks**. The longest makespan anywhere in the study is 9.53 s — 63× margin.

> **`-end` does not mean the same thing in the two binaries.** `main_roce.cpp:383`
> uses `timeFromUs`, `main_uec.cpp:600` uses `timeFromMs`, though both print
> `endtime(us)`. That is why the old UET sweeps passing `-end 600000` were never
> clipped despite 32 runs exceeding 600,000 µs — they were silently getting 600 s.
> The runner passes `600000000` (IB) and `600000` (UET): both 600 s.

Structurally, a truncated run can never be averaged in: `status=ok` requires
`flows_fin == Connections`, so an `-end` stop lands in `incomplete`. A canary
also warns if any makespan reaches 90% of the cap.

## Machine split

This box is **31 GB / 8 cores**; the other is **~90 GB**. A previous sweep
exhausted RAM+swap here and made the machine unreachable over SSH, so nothing is
left to chance.

| share | jobs | cells | serial time |
|---|---|---|---|
| **local** (this box) | 1335 | 267 | ~915 h → ~10 days at -P4 |
| **bigbox** (~90 GB) | 60 | 12 | ~14 h |

The bigbox share is the **2048-GPU MoE all-to-all** grid — all 12
stack × topology × size combinations, 536,576 connections each:

```
alltoall_moe_rail_aware, 2048 GPUs, {16,64,100} MB, {rail,flat}, {ib,uet}
```

100 MB is *documented* to need ~32 GB at `-q 8000` (it OOM-killed here; see
`rail_optimized/RUN_ON_BIGGER_BOX.md`). 16 MB and 64 MB are sent along because
they share the same connection count and only differ in in-flight bytes — with 5
repeats it is not worth gambling the box on them.

**Two safeguards, because the memory model is only a model.** A short RSS probe
was tried and abandoned: htsim's peak arrives late as queues fill, so a 150 s
probe on the 2048/100 MB cell reported 2.2 GB for a cell known to reach ~32 GB.
Instead:

- every job runs under a hard `ulimit -v`, sized so `PARALLEL × cap` cannot
  overcommit the box (default 4 × 6 GB light, then 1 × 20 GB serial);
- a job that exceeds its cap aborts in seconds as `status=mem_capped` — a
  routing signal, not a result — and `bin/reassign_capped.py` moves that cell
  to the bigbox share.

So a misjudged cell costs a few seconds, never the machine.

## Running it

**This box** (detached — survives closing SSH):

```bash
cd .../experiments/runs/fidelityRuns
bash bin/start_local.sh                 # setsid+nohup, own session, no controlling tty
tail -f sweep_local.progress.log        # watch
kill -TERM -$(cat sweep_local.pgid)     # stop
```

Resumable: any `(cell, seed)` with an `ok` row is skipped, so re-running the
driver after an interruption or a reboot continues where it stopped.

**The big box now runs the WHOLE study** (all 1395 jobs, not just the heavy ones).
This entire directory is the bundle: it is relocatable — topologies in `topos/`,
matrices in `matrices/`, and `MANIFEST.csv` holds matrix paths relative to it.
The 12 rail matrices (218 MB) are NOT shipped — `bin/regen_matrices.sh` rebuilds
them byte-for-byte from the tracked generators. Set `HTSIM_ROOT`, regenerate,
run `bin/preflight.sh`, then `bin/start_sweep.sh`.
Full step-by-step: **`BIGBOX_RUNBOOK.md`**.
The old `bigbox_bundle/` (60 heavy jobs only) has been deleted as superseded. Copy it over, run it, copy `rows/` and `util_rows/`
back into the matching `fidelityRuns/<study>/` directories, and re-run
`bin/aggregate.py`.

## Analysis

```bash
python3 bin/aggregate.py --check-rep1
python3 bin/make_graphs_fidelity.py
```

Writes into `results/`:

| file | contents |
|---|---|
| `runs_all.csv` | every individual run, 37 columns |
| `results_mean.csv` | per cell: mean / std / CV for all 25 numeric metrics, plus `n_runs` |
| `results_summary.csv` | the headline columns only |
| `variability.csv` | cells ranked by makespan CV, with SEM and 95% CI half-width |
| `utilization_all.csv`, `utilization_mean.csv` | the 42 utilization stats, per run and averaged |

`variability.csv` is the point of the exercise: it says which of the study's
conclusions survive their own error bars.

## Layout

```
fidelityRuns/
  MANIFEST.csv            one row per (cell, seed) job — the source of truth
  bin/                    runner, driver, manifest builder, aggregator, graphs
  <study>/rows/           one .row per (cell, seed)
  <study>/util_rows/      one .urow per (cell, seed)
  <study>/logs/           compacted htsim stdout per run
  results/                aggregated CSVs
  graphs/                 figures rebuilt from the means
  bigbox_bundle/          self-contained kit for the ~90 GB machine
```

`<study>` ∈ `uet_perm_incast`, `uet_a2a_concurrent`, `uet_allreduce_ring`,
`ib_perm_incast_a2a`, `ib_allreduce_a2a_serial` (now holds only IB ring all-reduce;
the name is historical), `rail`. Serial all-to-all was dropped from the study on
2026-09-29 as not representative of MoE traffic.

Branch: `study/rail-optimized-nvlink` — the only branch carrying the DCQCN
fixes, the SIGTERM/util finalisation fix, `-logtime_us`, and the rail/NVLink
code at once, so all 1395 runs share one provenance.
