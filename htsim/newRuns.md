# newRuns.md — additional htsim UEC sweeps beyond the A3 study

_2026-07-04 / 2026-07-05_ — Two new sweep campaigns on top of the A3 study, expanding coverage to more communication patterns and adding per-tier link utilization capture. Both sweeps run on the `study/a3-uec-network-metrics` branch off stock htsim main (`64d199c`), unmodified transport / NSCC / CC code.

## TL;DR

| Sweep dir | Runs | Status | Content |
|---|---|---|---|
| `sim/datacenter/experiments/runs/all_workloads_128_1024/` | 90 | 87 ok, 3 incomplete | 5 patterns × 3 sizes × {128, 1024} × {1os, 4os, 8os} |
| `sim/datacenter/experiments/runs/allreduce_ring_128_1024/` | 9 | all ok | Ring AllReduce × 3 sizes × {128} × {1os, 4os, 8os} |

Ring AR at 1024 nodes was attempted but OOM-killed (40-50 GB RSS per run on a 94 GB box; each 1024n ring matrix has ~2.1M connections). Butterfly AllReduce was excluded entirely — reproducible bug in the stock htsim `recv_done_trigger` cascade (only round 0 flows fire). Both findings documented below.

Each sweep's own `NOTES.md` has finer detail; this file is the entry point.

---

## What ran, and where the results are

### Sweep 1 — `all_workloads_128_1024/`

**Coverage**: 5 patterns × 3 flow sizes × 2 tree sizes × 3 fabrics = **90 runs**.
- Patterns (generators in `sim/datacenter/connection_matrices/`):
  - `perm_random` (`gen_permutation.py`)
  - `perm_fullbis` (`gen_permutation_full_bisection.py`)
  - `incast_random` (`gen_incast.py`, prefer_remote=0, conns=N-1)
  - `incast_remote` (`gen_incast.py`, prefer_remote=1, conns=N/2)
  - `outcast_incast` (`gen_outcast_incast.py`, conns_incast=N/8, conns_outcast=4)
- Flow sizes: **16 MB, 64 MB, 100 MB**
- Tree sizes: **128 and 1024 nodes**
- Fabrics: **1os (full bisection), 4os, 8os** — reused from `../a3_200g/topos_200g/`
- Excluded: AllReduce (both ring + butterfly — trigger bug or scale issues, see below); All-to-All (explicitly deferred by user).

**Runtime**: 22:38 → 04:55 the next day = **~6 h 17 min** wall total. Two-phase concurrency (`-P5` light + `-P2` heavy).

**Outputs**:
- `results_combined.csv` — 90 rows, main FCT / transport metrics.
- `utilization_combined.csv` — 90 rows, per-tier link utilization (8 rows blanked — see "known issues").
- `logs/*.log` — per-run filtered stdout (the source of truth: FCT lines + transport summary line + SIGTERM marker).
- `rows/*.row`, `util_rows/*.urow` — one CSV row per run (the CSVs above are concatenations).
- `NOTES.md` — this sweep's own detailed notes.

### Sweep 2 — `allreduce_ring_128_1024/`

**Coverage**: ring AllReduce × 3 flow sizes × {128 nodes} × 3 fabrics = **9 runs completed cleanly**.
- Generator: `gen_allreduce.py` (2·(N−1) sequential trigger-chained sends per node).
- Flow sizes: 16 MB, 64 MB, 100 MB.
- Fabrics: 1os / 4os / 8os.

The corresponding 9 runs at 1024 nodes were attempted but all OOM-killed at 0.5–5.5% flow completion after 5–7 h wall each (see "known issues"). Their rows have been removed from the final CSVs; only the 9 clean 128-node rows remain.

**Outputs**: same layout as Sweep 1. `NOTES.md` in the sweep dir has more detail.

---

## How runs are driven

Everything below is in each sweep dir. The two sweeps use the same design, just different matrix filters.

### `run_one.sh` — the single-job runner

One `(matrix, fabric)` job. Invocation:
```
bash run_one.sh <matrix_path> <fabric_label>
```

Environment knobs:
- `TIMEOUT` — hard wall-clock cap per run (default 24 h, 48 h for ring AR sweep). If exceeded, `timeout(1)` kills htsim and status is marked `timeout`.
- `END_MS` — htsim `-end` value in ms. Safety cap only; the watchdog usually fires first.
- `LOGTIME_US` — utilization sampling period (default 1000 = 1 ms).

Per-run flow inside `run_one.sh`:
1. Parse `Nodes N` and `Connections M` out of the matrix header — M is the expected flow count.
2. Start htsim in a per-run work dir (so parallel jobs don't collide on `idmap.txt` / `util.bin`):
   ```
   htsim_uec -tm <matrix> -sender_cc_only -nodes N -topo <topo_file> \
             -linkspeed 200000 -end $END_MS \
             -log tor_downqueue -log tor_upqueue -logtime_us $LOGTIME_US \
             -o <work>/util.bin
   ```
   Runs in the background, PID = `$htsim_pid`. Stdout streams into `<work>/htsim.stdout`.
3. **Watchdog** — a background poller that scans `<work>/htsim.stdout` for `finished at` lines every 200 ms. When count ≥ M, sends `SIGTERM` to `$htsim_pid`.
4. `wait $htsim_pid` — the runner blocks until htsim exits (via SIGTERM-clean shutdown, `-end` cap, or `timeout` kill).
5. Post-filter `htsim.stdout` into a small `logs/<tag>.log` (drops per-packet Spurious lines; keeps FCT lines, transport summary, error lines, and the `Received SIGTERM at <t> us` marker).
6. Parse the filtered log:
   - FCT stats — min/p50/p99/max/makespan from the sorted `finished at` times (regex handles both plain floats and scientific notation, so runs with sim time > 1 s parse correctly).
   - Transport counters — `New`/`Rtx`/`RTS`/`Bounced`/`ACKs`/`NACKs`/`Pulls`/`sleek_pkts` from the epilogue `New: ...` line.
   - `status` — `ok` if `flows_fin == M`, `timeout` if `timeout(1)` fired (rc=124), `failed` if 0 flows finished, else `incomplete`.
7. Write `rows/<tag>.row` — one CSV row of main metrics.
8. If `util.bin` and `idmap.txt` exist and status is not `failed`, run `extract_util.py` to compute per-tier utilization → `util_rows/<tag>.urow`.
9. `rm -rf <work>` — bounded disk footprint. Raw binary log is not retained after summary extraction.

### `sweep.sh` — the two-phase driver

Enumerates the sweep's matrix set × fabrics, splits into a **LIGHT** (small, per-run <~1 h wall) and **HEAVY** (long, multi-hour) job list, then runs LIGHT at `-P5` (5 concurrent) and HEAVY at `-P2`.

For sweep 1: LIGHT = 72 runs (all 128-node runs + 1024-node perm + 1024_16MB collectives); HEAVY = 18 runs (1024-node incast/outcast at 64/100 MB).
For sweep 2: LIGHT = 9 (128-node); HEAVY = 9 (1024-node — never completed).

Launched detached with:
```
setsid nohup bash sweep.sh > sweep.out 2>&1 </dev/null &
```
so the sweep survives SSH disconnects. `sweep.pid` records the driver PID.

---

## The watchdog — how htsim exits cleanly on schedule

By default, htsim's `QueueLoggerSampling` keeps rescheduling itself every `-logtime_us` for the whole `-end` cap, even after all flows have finished. So a naive setup with `-end 30 s` would generate 30 s of idle logging per run, producing multi-GB binaries, gating on either predicting each workload's makespan (fragile) or waiting for the safety cap.

Instead we **externally watchdog htsim**:

1. The matrix header tells us the exact expected flow count `M` (`Connections M`).
2. htsim prints `Flow ... finished at ...` on stdout for each completed flow — one line per UecSrc, guarded by `if (_done_sending) {}` in `checkFinished()` so it fires exactly once per flow.
3. The runner's background watchdog counts these lines and sends `SIGTERM` when count reaches M.
4. A small patch to `main_uec.cpp` handles that signal: sets a `volatile sig_atomic_t g_stop_requested` flag; the sim loop checks it between events (`while (!g_stop_requested && eventlist.doNextEvent())`) and breaks cleanly. Nothing else changed — same NSCC, same transport, same logger code.
5. After the loop breaks, `main()`'s epilogue runs normally: `Logged::dump_idmap()` (already called earlier at line 1103), the `New: ...` summary line, then stack unwind → `~Logfile()` → `transposeLog()` produces a valid binary log.

Impact: instead of tuning `-end` per workload, we set a single generous cap (`END_MS=30000` or `300000`), and htsim naturally exits within one watchdog-poll interval (~200 ms) of the last flow completing. In the main sweep, this cut runtimes from an estimated 1–3 days down to **6 h 17 min**.

Verified on 12+ real runs by checking each log's `Received SIGTERM at <t> us` line matches sim-makespan + <200 ms.

---

## Utilization capture — how per-link utilization is derived

### htsim side

`-log tor_downqueue -log tor_upqueue` tells htsim to attach a `QueueLoggerSampling` to every downlink and uplink queue at every tier (despite the "tor" naming — verified by reading `fat_tree_topology.cpp`: the same `_logger_factory` is used for TOR, AGG, and CORE tier queues). Each logger fires periodically (every `-logtime_us`) and writes a `QUEUE_RECORD` binary event containing `_cumarr` — the cumulative "link-busy" time in seconds, i.e. the sum of `queue.drainTime(pkt)` over every enqueue on that queue.

Because `_cumarr` is in seconds and each queue serves a link of known bandwidth, **utilization = _cumarr(final) / makespan_seconds** = fraction of link-time actually transmitting during the workload window.

One small patch to `sim/loggers.cpp`: the ASCII conversion for `CUM_TRAFFIC` events was `<< (int)event._val1`, truncating typical values in the 1e-6 to 1e-2 range to 0. Fixed to print `event._val1` directly (double precision). This affects `parse_output`'s ASCII output only, not the binary log or the transport code.

### Extraction — `extract_util.py`

1. Runs `parse_output <util.bin> -ascii` in a subprocess.
2. Parses each `Type QUEUE_APPROX ... Ev CUM_TRAFFIC CumArr <v>` line; keeps the last-seen `(t, cumarr)` per queue ID.
3. Loads `idmap.txt` and classifies each queue by name into a tier bucket:
   - `SRC%d->LS%d` → tier0_up (host → ToR uplink)
   - `LS%d->DST%d` → tier0_down (ToR → host downlink)
   - `LS%d->US_%d` → tier1_up (ToR → Agg uplink)
   - `US%d->LS_%d` → tier1_down (Agg → ToR downlink)
   - `US%d->CS%d` → tier2_up (Agg → Core uplink)
   - `CS%d->US%d` → tier2_down (Core → Agg downlink)
4. Divides each queue's `cumarr` by the workload's **makespan** (passed in from `run_one.sh` as the last `finished at` sim time). Not by the sample time, so the utilization isn't diluted by any post-workload idle sampling.
5. Emits `n / mean / p50 / p95 / p99 / max` per tier (plus overall).

The raw `util.bin` is deleted immediately after `extract_util.py` finishes, keeping disk footprint bounded regardless of run count.

---

## `extract_util.py`, `rederive_results.sh`, and the small patches

- **`sim/datacenter/main_uec.cpp`** — SIGTERM handler (10 lines added). Watchdog-clean shutdown.
- **`sim/loggers.cpp`** — 1-token change: `(int)event._val1` → `event._val1` in the CUM_TRAFFIC ASCII printer. Utilization numbers.
- **`experiments/runs/all_workloads_128_1024/rederive_results.sh`** — re-parses `logs/*.log` and rebuilds `results_combined.csv`. Used after fixing a regex bug: the original `finished at [0-9.]+` regex clipped scientific-notation exponents (`4.68919e+06`) that htsim's `cout` produces for sim times > ~1 s, so runs with real makespan > 1 s reported values off by 1e6. Fixed regex: `finished at [0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?`. Both the runner and the derivation script use the fixed form.
- **`experiments/runs/all_workloads_128_1024/blank_bad_utils.sh`** — 8 utilization rows had `extract_util.py` divide by the corrupted makespan (~1e6× too small), pinning all values at 1.0. Raw `util.bin` was already deleted so we cannot re-derive; script blanks those 8 rows (keeps matrix + fabric columns, empties the 42 stat columns). Full list in the sweep's `NOTES.md`.

---

## Known issues, deferred work

- **AllReduce (butterfly) is broken in stock htsim.** Direct test at 128n × 16 MB, no logging, `-end 30 s`: only round 0 completes (128 / 896 flows). Deterministic. `recv_done_trigger` cascade doesn't propagate past round 0. Excluded from all runs. Reproduce:
  ```
  htsim_uec -tm allreduce_butterfly_128n_16MB.cm -sender_cc_only -nodes 128 \
            -topo fat_tree_128_1os.topo -linkspeed 200000 -end 30000
  ```
  → `grep -c "finished at"` prints 128.

- **AllReduce (ring) works but is expensive at 1024n.** 128n runs completed cleanly (33 min – 2.6 h wall each depending on flow size). At 1024n, htsim needs to pre-allocate 2,096,128 UecSrc + UecSink instances + trigger targets before the sim starts — RSS grew to 40-50 GB, OOM-killed on the 94 GB dev box.

- **All-to-All (A2A) deferred by design.** Uses the same `send_done_trigger` chaining as ring AR — should work with sufficient `-end`, but needs its own memory-footprint check at 1024n before adding to a sweep.

- **3 flows that never completed at `incast_random_1024n_*.8os`**. Same 4 src indices (294, 337, 667, 1023) fail across all 3 flow sizes on 8:1 oversubscription — under 89-91% NACK/trim rate, they get stuck in retransmission and never emit their last byte before `-end` fires. Reported as `status=incomplete`, not a sweep bug.

- **Butterfly AR debug + A2A sweep** are the natural next steps.
