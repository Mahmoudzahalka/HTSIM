# Big-box runbook — running the **entire** fidelity study

Everything needed to run the whole multi-seed study on the ~90 GB machine.
Follow top to bottom; each step says how to confirm it worked before moving on.

> **This supersedes the earlier `bigbox_bundle/`**, which held only the 60 heavy
> 2048-GPU jobs. That directory has been deleted — its job list and matrix paths
> are no longer valid. **This whole `fidelityRuns/` directory is now the bundle.**

## What you are running

```
1395 runs  =  279 cells x 5 seeds (13, 101, 202, 303, 404)
generation :  DGX H100 -- 400 G fabric + NVLink4 3600 G (ratio 9x)
stacks     :  ib (RoCE + PFC + DCQCN K=8)  and  uet
scales     :  128, 1024, 2048 GPUs
```

**Workflow:** the sweep runs on the big box; analysis happens wherever you like.
Results are ~1.2 MB of `.row`/`.urow` files, so you copy those back and leave the
3.2 GB of logs behind — see steps 10 and 11.

Seven study arms, all in one manifest:

| arm | jobs | what |
|---|---|---|
| `uet_perm_incast` | 435 | perm_random, perm_fullbis, incast_random, incast_remote, outcast_incast |
| `ib_perm_incast_a2a` | 495 | the same five, plus concurrent a2a |
| `rail` | 240 | rail-aware all-reduce + MoE all-to-all, rail vs flat, 1024 + 2048 |
| `uet_allreduce_ring` | 45 | ring all-reduce |
| `uet_a2a_concurrent` | 45 | concurrent all-to-all |
| `uet_a2a_serial` | 45 | serial-triggered all-to-all |
| `ib_allreduce_a2a_serial` | 90 | IB parity arm |

**Runtime.** The manifest's `orig_wall_s` totals **929 h serial**, but those are
*200 G* timings — at 400 G runs are 1.5–3x faster, so expect roughly **400–600 h
serial**, i.e. **3–5 days at `PARALLEL=6`**. On the 31 GB box the observed
effective parallelism was 6.7x at `-P4`, so this is a conservative estimate.

Excluded: 6 cells that timed out or went incomplete in the original study, and the
PFC-only (no-DCQCN) arm entirely. In this study **"IB" always means PFC + DCQCN**.

## What is in the bundle

```
fidelityRuns/
  MANIFEST.csv          1395 jobs; matrix paths are RELATIVE, so this directory moves
  bin/                  runner, driver, preflight, manifest builder, aggregator, graphs
  topos/                15 topologies (fabric 400 G, NVLink 3600 G)
  matrices/             36 tracked matrices; matrices/rail/ is EMPTY until step 4
  <arm>/rows|util_rows|logs/   results land here
  results/ graphs/      aggregated output
```

Total ~16 MB (the 12 rail matrices, 218 MB, are regenerated in step 4).

---

## Step 1 — Code and build

Check out **`study/rail-optimized-nvlink`** — the only branch carrying the `Rails N`
topology support, the `-nvlink_topo` flags, the DCQCN fixes, and the SIGTERM handler
that finalises `util.bin` (without it every utilization number is zero).

```bash
git clone <repo> HTSIM && cd HTSIM
git checkout study/rail-optimized-nvlink
git pull                                   # make sure you have the NVLink speed check
cd htsim/sim/build && make htsim_roce htsim_uec parse_output -j"$(nproc)"
```

**Your checkout must include the NVLink speed check** (`grep -r NVLINK-SPEED-CHECK
htsim/sim/datacenter/`). It makes htsim *exit* when `-nvlink_linkspeed` disagrees with
the NVLink topology's capacity — the flag sets the host *source rate* while the
topology sets *link capacity*, and without the guard the slower one silently throttles
the faster, giving a plausible-looking but wrong result. Step 5 verifies the built
binary actually contains it, so you cannot start the sweep without it by accident.

## Step 2 — Copy the bundle over

```bash
tar czf fidelityRuns.tar.gz fidelityRuns/     # ~5 MB
scp fidelityRuns.tar.gz user@bigbox:~/
ssh user@bigbox 'tar xzf fidelityRuns.tar.gz'
```

## Step 3 — Point it at your checkout

```bash
export HTSIM_ROOT=$HOME/HTSIM/htsim      # the directory that CONTAINS sim/
```

Everything else derives from that. Override `ROCE_BIN`, `UEC_BIN` or `PARSE`
individually if your build layout differs.

## Step 4 — Regenerate the 12 rail matrices

The study needs 48 connection matrices. **36 are tracked in git** and arrive with the
clone. The other **12 are not** — they are 218 MB, too big to commit sensibly — so the
bundle ships without them and you regenerate them here:

```bash
cd ~/fidelityRuns
HTSIM_ROOT=$HOME/HTSIM/htsim bash bin/regen_matrices.sh      # ~2 minutes
```

The two generators (`gen_rail_aware_allreduce.py`, `gen_rail_aware_alltoall.py`) are
deterministic — no RNG — so this reproduces the files **byte-for-byte**, verified with
`cmp` against the originals. The script additionally checks each file's connection
count against what `MANIFEST.csv` expects, so a silent mismatch cannot slip through.

Expected output — 12 lines, all `OK`:

```
  rail_allreduce_1024gpu_16MB.cm          28672 flows  OK
  rail_alltoall_moe_1024gpu_16MB.cm      137216 flows  OK
  ...
  rail_alltoall_moe_2048gpu_100MB.cm     536576 flows  OK
All 12 regenerated and verified against MANIFEST.csv.
```

If any line says `MISMATCH`, stop — the matrices would not match the rest of the study.

## Step 5 — Preflight (do not skip)

```bash
cd ~/fidelityRuns
bash bin/preflight.sh
```

It verifies the binaries exist, **that they contain the NVLink speed check** (it greps
the compiled binary for the error string), that all 15 topologies are present at the right speeds,
that every matrix the manifest references exists, and that RAM and disk are adequate.

It must print `PREFLIGHT PASSED`. Warnings about RAM or disk are advisory; failures
are not — fix them first.

## Step 6 — Tune the profile for the box

The invariant that keeps a machine alive is:

```
PARALLEL x LIGHT_MEM_GB  <=  usable RAM
```

| box | PARALLEL | LIGHT_MEM_GB | HEAVY_MEM_GB | worst case |
|---|---|---|---|---|
| **~90 GB (this one)** | **6** | **10** | **40** | 60 GB |
| 31 GB | 4 | 6 | 20 | 24 GB |

Defaults are already the 90 GB row. Heavy jobs — the 2048-GPU MoE grid, ~32 GB each
on IB — are detected by estimated footprint and run **strictly serially after** the
light ones, with the larger cap. A job exceeding its cap aborts in seconds as
`status=mem_capped` rather than taking the machine down.

Also point scratch at a roomy disk if `$HOME` is small:

```bash
export WORKROOT=/big/disk/fidelity_work
```

## Step 7 — Launch, detached

`setsid` gives the sweep its own session with no controlling terminal, so the SIGHUP
sent when your SSH connection drops never reaches it.

```bash
PARALLEL=6 bash bin/start_sweep.sh
```

It prints the pgid and where to watch. To stop:

```bash
kill -TERM -$(cat sweep_run.pgid)
```

**It is resumable.** Any `(cell, seed)` that already has an `ok` row is skipped, so
you can stop, reboot, and re-run the same command to continue where it left off.

## Step 8 — Monitor

```bash
tail -f sweep_run.progress.log                       # live
grep -c '^\[done' sweep_run.progress.log             # runs completed
cat */rows/*.row | awk -F, '{c[$11]++} END{for(s in c) print s, c[s]}'   # status tally
```

Everything should be `ok`. Anything else is covered in Troubleshooting.

You can aggregate at any time without stopping the sweep:

```bash
python3 bin/aggregate.py
```

## Step 9 — Verify

Three conditions per run:

| field | column | required |
|---|---|---|
| status | 11 | `ok` |
| flows_fin | 14 | equals the cell's `conns` |
| overflow | 37 | `0` on **IB** runs |

```bash
cat */rows/*.row | awk -F, '$11!="ok" || $37!=0 {print $11, $37, $2}' | sort | uniq -c
```
Empty output means everything is clean.

> **Why overflow matters more than it looks.** htsim only *warns* on lossless
> overflow and keeps the packet, so the timings would silently correspond to a
> larger buffer than `-q` asked for. The runner already refuses to call these `ok` —
> it marks them `lossless_overflow`.

**Note on seed 13.** At 200 G it reproduced the published numbers exactly, which is
how the harness was validated. **At 400 G it will not, and should not** — the fabric
changed. `aggregate.py --check-rep1` now *measures* that change rather than gating on
it. Reference deltas measured during bring-up:

| cell | 200 G | 400 G | ratio |
|---|---|---|---|
| perm_random uet 1os | 782.0 us | 397.6 us | 1.97x |
| perm_random ib 1os | 4449.0 us | 2570.4 us | 1.73x |
| allreduce uet rail | 357.2 us | 237.6 us | 1.50x |
| allreduce ib rail | 1139.2 us | 391.6 us | **2.91x (superlinear)** |

## Step 10 — Where results land, and what to bring home

Each run writes three files, into the bundle itself:

| what | where | size |
|---|---|---|
| `.row` — the 37 metrics for one run | `<arm>/rows/<tag>.row` | ~330 B |
| `.urow` — the 42 utilization stats | `<arm>/util_rows/<tag>.urow` | ~520 B |
| `.log` — compacted htsim stdout | `<arm>/logs/<tag>.log` | **large** |

`<tag>` is `<matrix>.<stack>.<topo>.s<seed>`, so every run is uniquely named and
nothing is overwritten across seeds.

**Bring back the rows, leave the logs.** For the full 1395-run study:

```
1395 .row  + 1395 .urow   ~=   1.2 MB     <- copy these
1395 .log  (52 M flow lines) ~=  3.2 GB   <- leave on the big box
```

The logs hold one line per finished flow. You only need one if a specific run
misbehaves, and then you fetch that single file.

```bash
# on the big box
bash bin/package_results.sh          # -> fidelity_results.tar.gz, ~1 MB
scp fidelity_results.tar.gz you@analysisbox:~
```

It also prints a status tally and how many of the 1395 jobs are covered, so you can
see at a glance whether the sweep actually finished.

**You can do this mid-run.** The sweep is resumable and the packager only reads
finished rows, so packaging a partial result set is safe and does not disturb
anything.

## Step 11 — Analyse on the other machine

The tarball preserves the `<arm>/rows/...` layout, so it unpacks straight into the
analysis machine's own copy of `fidelityRuns/`:

```bash
cd .../experiments/runs/fidelityRuns
tar xzf ~/fidelity_results.tar.gz
python3 bin/aggregate.py --check-rep1
python3 bin/make_graphs_fidelity.py
```

Analysis needs **nothing but the rows** — not the matrices, not the topologies, not
htsim. So the analysis machine does not need a working build or the 218 MB of
regenerated matrices.

`--check-rep1` is best run here: it diffs against the original published CSVs in
`../uet/`, `../ib_dcqcn/` and `../rail_optimized/`, which live in this repo.

Writes into `results/`:

| file | contents |
|---|---|
| `runs_all.csv` | every individual run, 37 columns |
| `results_mean.csv` | per cell: mean / std / CV for all 25 metrics, plus `n_runs` |
| `results_summary.csv` | headline columns only |
| `variability.csv` | cells ranked by makespan CV, with SEM and 95% CI |
| `utilization_all.csv`, `utilization_mean.csv` | the 42 utilization stats, per run and averaged |

`variability.csv` is the point of the exercise: it says which conclusions survive
their own error bars.

---

## Troubleshooting

**Preflight says the binary lacks NVLINK-SPEED-CHECK**
Your checkout predates that commit, or you built before pulling. `git pull`, rebuild,
re-run preflight.

**Preflight says N manifest rows point at a missing matrix**
You skipped step 4. Run `bash bin/regen_matrices.sh`.

**`FATAL: not executable: .../htsim_roce`**
Step 1 or 3. If the build put it in `sim/build/datacenter/`, set `ROCE_BIN` to that path.

**`NVLink speed mismatch: ... says X Gbps but ... declares Y Gbps`**
Working as intended — it caught a real misconfiguration. Make `-nvlink_linkspeed` match
the NVLink topology's `Downlink_speed_Gbps` (both should be 3600).

**`Don't set linkspeeds using both the constructor and set_tier_parameters`**
The fabric equivalent: `-linkspeed` disagrees with the topology's
`Downlink_speed_Gbps`. Both must be 400 G here.

**Status `mem_capped`**
That cell needs more RAM than its phase cap allows. Raise `LIGHT_MEM_GB`/`HEAVY_MEM_GB`
(keeping `PARALLEL x LIGHT_MEM_GB <= RAM`), or run `python3 bin/reassign_capped.py` and
handle those cells separately. Completed cells are skipped on a restart, so nothing is lost.

**Status `lossless_overflow` on an IB run**
`-q` was too small for that cell. Re-run it with a bigger buffer:
```bash
QSIZE=16000 LOGTIME_US=20000 bash bin/run_one_fidelity.sh \
    rail matrices/rail/rail_alltoall_moe_2048gpu_100MB.cm ib rail 13 1
```
`-q` does not change the answer, only whether the buffer is honestly sized.

**Status `incomplete`**
The run stopped before all flows finished. Should not happen: the `-end` cap is 600
simulated seconds and the longest makespan in the study is under 10 s. Check
`<arm>/logs/<tag>.log`.

**Utilization columns are all zero**
Wrong branch — the SIGTERM handler that finalises `util.bin` is only on
`study/rail-optimized-nvlink`.

**The machine starts swapping**
Lower `PARALLEL`. A previous sweep exhausted RAM+swap on the small box and made it
unreachable over SSH; the per-job caps exist to prevent exactly that.

---

## Reference — the 37 columns in a `.row`

```
 1 study        11 status        21 New          31 pfc_pause_us
 2 matrix       12 wall_s        22 Rtx          32 max_queue_bytes
 3 workload     13 peak_mb       23 RTS          33 slowdown_p50
 4 size_MB      14 flows_fin     24 Bounced      34 slowdown_p99
 5 nodes        15 makespan_us   25 ACKs         35 slowdown_max
 6 conns        16 fct_min_us    26 NACKs        36 fairness_jain
 7 stack        17 fct_p50_us    27 Pulls        37 overflow
 8 topo_kind    18 fct_p99_us    28 sleek
 9 seed         19 fct_max_us    29 spurious
10 rep          20 total_GB      30 pfc_pauses
```

Columns 21–29 are UET-native (zero on IB); 30–32 and 37 are IB-native (zero on UET).
The `.urow` carries 5 identity fields plus 42 utilization statistics (overall + 6 tier
groups x n/mean/p50/p95/p99/max).

## Appendix — the two speed knobs

Each plane has a topology-file capacity **and** a command-line source rate, and they
are enforced differently:

| plane | topology file | flag | on disagreement |
|---|---|---|---|
| fabric | `Downlink_speed_Gbps 400` | `-linkspeed 400000` | htsim exits (`set_linkspeeds`) |
| NVLink | `Downlink_speed_Gbps 3600` | `-nvlink_linkspeed 3600000` | htsim exits (added 2026-09-21) |

Changing all tiers together is shape-preserving: the uplink count depends on the
*ratio* of tier speeds, so `topos/` is the 200 G set with only the speed rewritten —
radices, oversubscription and every matrix carry over unchanged.

Note also that `-end` means **microseconds** in `main_roce.cpp` but **milliseconds** in
`main_uec.cpp`, despite both printing `endtime(us)`. The runner passes `600000000` and
`600000` respectively: both are 600 simulated seconds.
