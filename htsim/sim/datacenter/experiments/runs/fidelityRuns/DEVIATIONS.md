# Deviations from BIGBOX_RUNBOOK.md — 400 G fidelity sweep

Recorded 2026-09-21 on `wrath` (94 GB, 11 cores), branch `study/rail-optimized-nvlink` @ `bb149b5`.
Everything here is a departure from the runbook as written. Read alongside it.

## 1. The sweep runs 1305 jobs, not 1395 — the serial-a2a arms were dropped

The three `matrices/a2a_serial/a2a_128n_{16,64,100}MB.cm` files are **unrecoverable**.
Both original harnesses that used them (`uet/a2a_serial_128_1024/sweep.sh:18` and
`ib_dcqcn/allreduce_a2a_serial_128/sweep_parity.sh:14`) point at
`/media/mahmoud_murad_allaah/Data/a2a_128_1024/matrices` — an external drive that is
not on this box and not in git. Neither harness generated them, so no recipe was recorded.

They *can* be reproduced in shape — `gen_serial_alltoall.py <f> 128 128 128 <bytes> 0 <seed>`
yields exactly `Connections 16256 / Triggers 16128`, matching the manifest — but the
original `randseed` is unknown, and it permutes which peer each node hits first. That
changes fabric locality, so a regenerated file is a *different sample* of the workload,
not the published one. Rather than silently fold a fabricated input into a fidelity
study, the 90 dependent jobs were excluded:

| arm | before | after | lost |
|---|---|---|---|
| `uet_a2a_serial` | 45 | **0** | whole arm |
| `ib_allreduce_a2a_serial` | 90 | **45** | serial-a2a half; the allreduce_ring half is intact |

`MANIFEST.csv` is now the 1305-job active manifest; the original is preserved verbatim as
**`MANIFEST.full.csv`**. Restoring the arms = recover the 3 files, then restore the manifest.

## 2. `matrices/` was missing entirely, not just the 12 rail files

The runbook (step 4) says 36 matrices "are tracked in git and arrive with the clone."
They are not — `.gitignore:47` excludes `**/experiments/runs/fidelityRuns/matrices/`
wholesale, so a fresh clone has **no** matrices at all. Step 4 alone is not enough.

The 36 non-rail files were recovered from the tracked original study directories and
verified file-by-file against `MANIFEST.csv`'s `conns` column (all 36 OK):

| group | n | recovered from |
|---|---|---|
| `perm_incast/` | 30 | `uet/perm_incast_128_1024/matrices/` |
| `allreduce_ring/` | 3 | `uet/allreduce_ring_128/matrices/` |
| `a2a_concurrent/` | 3 | `uet/a2a_concurrent_128_1024/matrices/` |
| `rail/` | 12 | `bin/regen_matrices.sh` (runbook step 4, 210 MB) |

## 3. BUG FIX — `flow_metrics.py` scored every UET run 0.0000

The old regex `finished at ([\d.eE+-]+) total bytes (\d+)` required `total bytes` to sit
directly after the timestamp. That matches RoCE's line but **not** UET's, which reads
`finished at T total messages M total packets P RTS R total bytes B ...`.

Measured: **0 of 128** UET lines matched; 32640 of 32640 RoCE lines matched. So columns
**33–36** (`slowdown_p50/p99/max`, `fairness_jain`) were silently zero on every UET run —
**645 of the 1305 jobs**, across `uet_perm_incast`, `uet_a2a_concurrent`,
`uet_allreduce_ring` and the UET half of `rail`. It fails silently: zero is a plausible
number, and nothing in preflight or the status checks looks at those columns.

The two stacks also mean different things by the same field: RoCE's `total bytes N` is a
**packet count** (bytes = `N * mss`), UET's is **real bytes**. The fix parses the
timestamp and `total bytes` independently and distinguishes the stacks on the presence of
`total packets`. RoCE output is byte-identical before and after (verified by diffing
against the original on an untouched 200 G log). Original kept as `bin/flow_metrics.py.orig`.

## 4. BUG FIX — `BPUS` was still the 200 G constant

`run_one_fidelity.sh` hardcoded `BPUS=25000` ("200 Gbps in bytes/us") while the whole
point of this generation is a 400 G fabric. The slowdown ideal was therefore computed
against half the real link rate, understating slowdown ~2x on every run.

Now derived so it tracks the fabric and cannot drift again:
`BPUS="${BPUS:-$((FABRIC_MBPS/8))}"` → 400000 Mbps / 8 = **50000 B/us**.
Original kept as `bin/run_one_fidelity.sh.orig`.

> Pre-existing caveat, not fixed: `flow_metrics.py` assumes `FCT ~= finish time` because
> "flows start ~0". That is false for trigger-chained matrices (`allreduce_ring`, and the
> dropped serial a2a), where later flows start only when their predecessor finishes.
> Slowdown for those cells is inflated and should be read as a relative, not absolute,
> figure. Makespan and FCT percentiles are unaffected.

## 5. Setup the runbook omits

- **The 7 arm output directories do not exist and nothing creates them.**
  `run_one_fidelity.sh` only `mkdir -p`s its scratch dir, so every run would die
  redirecting into `<arm>/logs/`. Created once, up front.
- **Both path defaults point at the original author's laptop** and must be exported:
  `HTSIM_ROOT` (defaults to `/home/mahmoud_murad_allaah/HTSIM/htsim`) and `WORKROOT`
  (defaults to `/media/mahmoud_murad_allaah/Data/fidelity_work`). The runbook treats
  `WORKROOT` as optional; here it is mandatory.
- **Steps 2 and 3 are no-ops** — this *is* the big box; the bundle is already in place.
- **The progress log is `sweep_bigbox.progress.log`**, not `sweep_run.progress.log` as
  steps 7–8 claim. The driver names it from `MACHINE` (`sweep_fidelity.sh:38`), while
  `start_sweep.sh` writes `sweep_run.out` / `sweep_run.pgid`. Stop still uses
  `kill -TERM -$(cat sweep_run.pgid)`.
- **180 jobs are heavy, not 60.** The runbook describes the heavy phase as the 60-job
  2048-GPU MoE grid, but `HEAVY_MB=1500` catches all 180 rail jobs at 1024 and 2048.
  They run strictly serially; manifest timings put that phase at ~24 h of the total.

## 6. Bring-up validation

Rebuilt from `bb149b5` (the shipped binaries were from 2026-08-04 and lacked
`NVLINK-SPEED-CHECK`; preflight correctly rejected them). After the rebuild both smoke
runs reproduce the runbook's step-9 reference numbers exactly:

| cell | runbook 400 G | measured | flows |
|---|---|---|---|
| `perm_random_128n_16MB` uet 1os s13 | 397.6 us | **397.6 us** | 128/128 |
| `perm_random_128n_16MB` ib 1os s13 | 2570.4 us | **2570.4 us** | 128/128 |

`PREFLIGHT PASSED`. All 37 row columns and all 47 urow fields populated on both stacks;
utilization non-zero, so the SIGTERM/`util.bin` finalisation is working.

## 7. `HEAVY_MEM_GB` raised 40 -> 75 GB

The runbook's 90 GB profile caps heavy jobs at 40 GB. That is too low: the 2048-GPU
MoE all-to-all cells reach **~60-65 GB RSS** when actually run on a box large enough to
let them get there (observed directly; this is the operative number).

Every source in the repo understates it, and consistently in the same direction:

| source | says | why it is low |
|---|---|---|
| `MANIFEST.csv` `est_peak_MB` | 14.2 GB | `how=modelled` — a model, never measured |
| `RUN_ON_BIGGER_BOX.md` | "~32 GB — OOM'd here" | that is a **31 GB box killing the process**, i.e. a lower bound on a peak it never reached |

At `HEAVY_MEM_GB=40` all 180 heavy jobs would have hit the `ulimit -v` and aborted as
`status=mem_capped` — fast and harmless to the machine, but the entire `rail` arm would
have produced nothing, and the failure looks like a routing signal rather than a
misconfiguration. Now `75` (default changed in `bin/sweep_fidelity.sh`), which clears the
observed 65 GB with margin and still leaves ~16 GB free, since the heavy phase is
`xargs -P 1` — strictly one job at a time.

Invariant after the change, on 91 GB available:
- light: `6 x 10 GB = 60 GB`
- heavy: `1 x 75 GB = 75 GB`

> Also noted, not changed: `HEAVY_MB=1500` routes all 180 rail jobs to the serial phase,
> including the 1024-GPU cells whose modelled peak is only ~3.3-3.5 GB. If that model is
> nearer the truth at 1024 than it is at 2048, those 120 jobs are being serialised
> needlessly and the heavy phase is far slower than it needs to be. Worth revisiting once
> real `peak_mb` values land in the rows — column 13 records the measured RSS per run, so
> after the first few heavy jobs the true figures will be available for the first time.

## 8. BUG FIX — `status=mem_capped` was unreachable, so cap failures read as `incomplete`

`run_one_fidelity.sh` sets `mem_capped` when the raw stdout contains `bad_alloc`, then
on the **very next line** runs the truncation check:

```bash
status=mem_capped                                            # line 228
[ "$fin" -lt "$c" ] && [ "$rc" != 124 ] && { ... status=incomplete; }   # line 231
```

A memory-capped run **always** has `fin < c` — that is what being capped means — so the
second line overwrote the first every time. `mem_capped` could never be emitted, which
silently made `bin/reassign_capped.py` a no-op and disguised every cap failure as a
truncated run. Now guarded with `[ "$status" != mem_capped ]`.

This is how 30 real cap failures were mislabelled (see §9). The tell was `rc=134`
(SIGABRT, i.e. `std::bad_alloc`) rather than a clean exit, plus `peak_mb` pinned to the
cap — neither of which the status field reflected.

## 9. 30 `uet_allreduce_ring` runs hit the 10 GB light cap — re-run needed

All 15 `64MB` and all 15 `100MB` `uet_allreduce_ring` runs died with
`terminate called after throwing an instance of 'std::bad_alloc'`, `rc=134`, at
`peak_mb` = 10233-10236 MB against the 10 GB `ulimit -v`. The `16MB` runs all completed.

**This is not the trigger cascade.** The chain advances correctly — the failed runs
reached 26-87% of their 32640 flows before dying, and `16MB` completes 32640/32640.

Measured scaling, which `est_peak_MB` completely misses:

| size | modelled | actual | note |
|---|---|---|---|
| 16 MB | 1063 MB | **3641-5148 MB** | completes; model is ~4x low |
| 64 MB | 1095 MB | **>10 GB** | capped, est. ~15-20 GB |
| 100 MB | 1118 MB | **>10 GB** | capped, est. ~20-30 GB |

The model barely moves with flow size (1063 -> 1118 MB, +5%) while reality scales with
in-flight bytes (6.25x the data). Same systematic underestimate as the heavy rail cells
in §7 — `est_peak_MB` should not be trusted to size a cap for any large-flow workload.

**IB is unaffected.** `ib_allreduce_a2a_serial` uses the same matrices but does not hit
this (confirmed by the study author, and consistent with the IB `a2a_128n_100MB` runs
observed at ~5 GB RSS). It is UET's sender-side CC state that grows on large flows.

**Recovery.** The 30 rows are `incomplete`, and the resume guard only skips `ok`, so a
second pass retries exactly these. After the main sweep finishes:

```bash
PARALLEL=2 LIGHT_MEM_GB=40 bash bin/start_sweep.sh     # 2 x 40 GB = 80 GB
```

Nothing else needs re-running, and no completed work is repeated. With the §8 fix in
place, if 40 GB still is not enough these will now correctly report `mem_capped`
rather than hiding as `incomplete`.
