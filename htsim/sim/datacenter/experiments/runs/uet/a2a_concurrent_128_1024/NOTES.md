# a2a_conc_128_1024/ — concurrent-global all-to-all sweep notes

Sweep launched 2026-07-06 18:39, Phase A (128n) finished 2026-07-09 08:11.
Phase B (1024n) **stopped by decision** 2026-07-11 after 2 of 9 runs — every
1024n run times out (see §Phase B). Run on the **/csl (Technion) box**, fully
serial (`-P1`), detached via `setsid`.

## What this workload is (and how it differs from a2a_128_1024)

**Concurrent global all-to-all**: one all-to-all over the *whole* topology
(`groupsize = N`), launched **concurrently** — every source posts all (N−1)
peer flows at once.

- Generator: `gen_serialn_alltoall.py <f> N N N (N-1) <bytes> 0 1`
  → `parallel = N-1`, so `Triggers 0` (no trigger chain; all flows `start 0`).
- Contrast with the earlier **`a2a_128_1024`** sweep, which used
  `gen_serial_alltoall.py` (**serial**: one flow in flight per source, chained
  by `send_done_trigger`). That models a naive *linear* a2a.
- **Why concurrent:** it models an optimized **MoE-style collective** a2a
  (NCCL-class: post to all peers, let them pipeline). This is the LLM-training-
  realistic temporal pattern. See the a2a-realism discussion — serial-global is
  the *least* representative point; concurrent-global is the minimal change that
  fixes the temporal behavior without changing topology/grouping.
- Every receiver is therefore a simultaneous **(N−1)-way incast**.

## Coverage

Concurrent global a2a × 3 flow sizes × 3 fabrics × 2 tree sizes.
- **Flow sizes**: 16 MB, 64 MB, 100 MB (bytes = SZ·1e6, matching a2a_128_1024).
- **Fabrics**: 1os (full bisection), 4os, 8os.
- **Tree sizes**: 128 (**all 9 complete**), 1024 (**infeasible — 2 timeout rows only**).
- Connections: 128n = 128·127 = 16 256; 1024n = 1024·1023 = 1 047 552.

## Setup summary

- **Identical runner + metrics to `a2a_128_1024`** — `run_one.sh` diffs only in
  paths (this box) + comments; `extract_util.py` is byte-for-byte the same.
  So FCT stats, transport counters, and per-tier utilization are captured
  exactly as in the prior sweeps.
- htsim branch `study/a3-uec-network-metrics`, local CMake build
  (`sim/build/datacenter/htsim_uec`). NSCC (`-sender_cc_only`), 200 Gbps hosts.
- Topos reused from `../a3_200g/topos_200g/fat_tree_{128,1024}_{1os,4os,8os}.topo`.
- Per-tier utilization sampled at 1 ms (`-log tor_downqueue -log tor_upqueue`).
- Watchdog SIGTERMs htsim the moment `finished at` count == matrix Connections;
  `-end 600000ms` is a safety cap only. `TIMEOUT=86400s` (24 h) hard wall cap.
- **Serial `-P1` throughout** (shared machine — keep memory footprint to a
  single htsim). 128n peak RSS ≈ 314 MB; 1024n ≈ 21 GB.

## Phase A — 128-node results (9/9 `ok`, all 16 256/16 256 flows finished)

### Makespan (ms)

| flow size | 1os | 4os | 8os |
|---|---|---|---|
| 16 MB | 86.4 | 324 | 740 |
| 64 MB | 345 | 1 297 | 2 962 |
| 100 MB | 540 | 2 027 | 4 630 |

- **1os makespan is incast-bound, not a bug.** Concurrent full-bisection a2a =
  every receiver ingests (N−1) flows over its single 200 G downlink, shared
  *equally* → all flows to a node complete in a **synchronized burst** near the
  floor `127·16MB / 200Gbps ≈ 81 ms` (observed 86.4 ms). Nothing finishes early
  at 1os; flows land in a burst at the end.
- **Fabric penalty is steeper than the serial sweeps:** 4os ≈ 3.75×, 8os ≈ 8.6×
  the 1os makespan (serial ring-AR saw ~2.5×/5×). Concurrent a2a punishes
  oversubscription harder because the core is the hard bottleneck under a
  full-fabric incast.
- Makespan scales ~linearly with flow size (64/16 ≈ 4×, 100/16 ≈ 6.25×), as
  expected for bandwidth-bound transfers.

### Congestion loss — NACKs/(New+Rtx), 32-bit-corrected (see caveat)

| flow size | 1os | 4os | 8os |
|---|---|---|---|
| any (16/64/100 MB) | **2.8 %** | **72.7 %** | **88.3 %** |

- **Trim rate is set almost entirely by oversubscription, essentially
  independent of flow size** — the three sizes agree to <0.1 pt. This is the
  headline transport result: at 8os ~88 % of all packet *transmissions* are
  trimmed (each packet trimmed ~7–8× on average); at 1os only 2.8 %.

### Per-tier link utilization (mean)

| | overall | tier0_up (host→ToR) | tier2_up (Agg→Core) |
|---|---|---|---|
| 1os | 0.94 | 0.99 | 0.88 |
| 4os | 0.65 | 0.95 | **1.00** |
| 8os | 0.63 | 0.96 | **1.00** |

- **1os:** balanced, host uplinks saturated (0.99), core not quite (0.88) →
  the receiver downlink / host tier is the limit.
- **4os/8os:** the **core (tier2) pins at 1.00** — the oversubscribed core is
  the bottleneck, matching the makespan blow-up. Host uplinks still read ~0.95,
  but at 8os that "busy" host link is dominated by **retransmissions** (88 %
  trim), not goodput — high tier0_up utilization here is congestion churn.

## Phase B — 1024-node: INFEASIBLE (stopped after 2 runs)

Concurrent 1024n a2a = **1 047 552 flows active simultaneously** = a 1023-way
incast at *every* receiver. The sim-event volume is so high that a full 24 h
wall clock advances only a sliver of the workload:

| run | status | flows finished | wall |
|---|---|---|---|
| 1024n/16MB/1os | timeout | 7 064 / 1 047 552 (**0.67 %**) | 24.0 h |
| 1024n/16MB/4os | timeout | 7 168 / 1 047 552 (**0.68 %**) | 24.0 h |

- **Worse than the *serial* 1024n** (which reached 39 % in 17 h in the prior
  a2a_128_1024 sweep) — concurrency turns the 1023-way incast catastrophic.
- Each of the 7 remaining Phase B runs would likewise burn 24 h for ~1 % data,
  so Phase B was stopped (**~7 days of compute saved**). The in-flight
  `1024n/16MB/8os` run was killed and its partial row discarded.
- **Finding to report as-is:** concurrent global a2a does not scale to 1024
  nodes in stock htsim within a 24 h budget (consistent with A3_STUDY §10 and
  the ring-AR 1024n OOM/infeasibility note). Memory was *not* the limiter here
  (21 GB at -P1); **simulation time** was.

## Caveats

1. **32-bit counter overflow (Rtx, NACKs).** htsim's `New:` epilogue prints
   `Rtx`/`NACKs` as signed 32-bit; they wrap past 2^31 at high scale. Raw
   `results_combined.csv` therefore shows **negative** Rtx/NACKs for the heavy
   rows (e.g. 100MB.8os: `NACKs -1293288061`). Correct with `+2^32` when
   negative — the §Congestion table already applies this. `New` and `ACKs` did
   not overflow at 128n.
2. **`makespan_us` for `timeout` rows is misleading** — it is the max FCT among
   only the flows that *did* finish (0.7 %), **not** the true makespan. Ignore
   it for the two 1024n rows.
3. **1024n util rows are from ~0.7 %-complete runs** — they show a jammed fabric
   (means ~0.97–1.0) but are partial-run artifacts, not steady-state.

## Files

```
NOTES.md                     this file
results_combined.csv         11 rows (9 x 128n ok + 2 x 1024n timeout)
utilization_combined.csv     11 rows (per-tier util; 1024n rows = partial-run)
matrices/                    6 generated .cm (concurrent global a2a)
logs/                        per-run filtered stdout
rows/, util_rows/            per-run CSV fragments
run_one.sh                   single-job runner (watchdog + SIGTERM); == a2a_128_1024 minus paths
sweep.sh                     two-phase driver, -P1 throughout, auto-generates matrices + CSVs
extract_util.py              per-tier utilization extractor (identical to prior sweeps)
sweep.pid, sweep.out         detached driver PID + stdout log
```
