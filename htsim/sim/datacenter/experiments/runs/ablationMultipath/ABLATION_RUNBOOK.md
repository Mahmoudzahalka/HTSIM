# Multipath ablation — big-box runbook (90 GB machine)

How to run the multipath ablation on the ~90 GB machine, top to bottom. Each step
says how to confirm it worked before you move on. **Nothing here touches the
fidelity study's results**: the ablation writes only into `ablationMultipath/`.

## What the ablation is

The question is how much of the IB-vs-UET gap is **multipath** and how much is
the **transport**. Each stack runs single-path and multipath; everything else
stays the same as the fidelity study (400 G DGX-H100 fabric).

| stack | arm | flags on top of the fidelity command | source of rows |
|---|---|---|---|
| RoCE (IB) | **qp1**: 1 QP per flow (baseline) | none | fidelity `runs_all.csv` (already run) |
| RoCE (IB) | **qp2 / qp4 / qp8** | `-qps K`: each flow split statically into K equal parts, one per queue pair; **each QP has its own DCQCN, PFC and go-back-N**, and its own ECMP hash | **new** |
| UET | **spray** (baseline) | none (default `mixed` load balancing) | fidelity `runs_all.csv` (already run) |
| UET | **ecmp** | `-load_balancing_algo ecmp`: one path per flow, nothing else changed | **new** |

That gives a transport × multipath 2×2 (IB single path, IB K QPs, UET ECMP, UET
spray) and a K curve for IB.

**Common to every run** (identical to the fidelity study): 400 G fabric
(`-linkspeed 400000`), the same **5 seeds (13, 101, 202, 303, 404)**, `-strat ecmp_host -paths 128`. IB adds
`-queue_type lossless_input -pfc_thresholds 12 15 -q 1000 -dcqcn 8`; UET adds
`-sender_cc_only`. ToR up/down queue logging is on, so utilization rows are
produced.

### Scope: 1:1 oversubscription only, flat fat tree, no NVLink

| nodes | topology | workloads | sizes |
|---|---|---|---|
| 128 | `fidelityRuns/topos/fat_tree_128_1os.topo` | perm_random, perm_fullbis, incast_random, incast_remote, outcast_incast, a2a_concurrent, allreduce_ring | 16 / 64 / 100 MB |
| 1024 | `fidelityRuns/topos/fat_tree_1024_1os.topo` | perm_random, perm_fullbis, incast_random, incast_remote, outcast_incast | 16 / 64 / 100 MB |

Not included: 4:1 and 8:1, rail/flat-with-NVLink, 2048/8192, and a2a or ring at
1024 (those don't exist in the fidelity baseline either).

**710 new runs** = 142 cells × 5 seeds:

| arm | runs | pilot (128 n, 16 MB, seed 13 only) | main |
|---|---|---|---|
| `abl_ib_qp2` | 180 (36 × 5) | 7 | 173 |
| `abl_ib_qp4` | 180 (36 × 5) | 7 | 173 |
| `abl_ib_qp8` | 180 (36 × 5) | 7 | 173 |
| `abl_uet_ecmp` | 170 (34 × 5) | 7 | 163 |

UET has 34 cells, not 36, because the UET ring 64/100 MB cells were dropped from the
fidelity study (they hit the memory cap), so they have no spray baseline.
`--include-uet-ring-large` adds them back if you want them anyway.

### Why the baselines can be reused instead of rerun
- **IB qp1:** the current `htsim_roce` (with `-qps` and BUGFIX #11) produces
  byte-identical stdout to the pre-change binary. It also reproduces the recorded
  seed-13 fidelity rows exactly (makespan, PFC pauses, max queue) for perm 1os,
  incast 4os, outcast 8os, ring 1os and rail-allreduce 1024 flat.
- **UET spray:** the preflight (step 4) checks this on the big box before
  anything else runs. It must reproduce the recorded row exactly.
- **Matrices:** the fidelity bundle's `matrices/` folder is not in git. The
  ablation uses the identical files tracked in git under
  `uet/perm_incast_128_1024/matrices/` and
  `uet/a2a_concurrent_128_1024/matrices/`; the preflight's exact baseline match
  confirms they're the same.

---

## Step 1 — Code and build

```bash
cd ~/HTSIM            # your checkout on the big box
git fetch && git checkout ablations && git pull
cd htsim/sim/build && make htsim_roce htsim_uec parse_output -j"$(nproc)"
```

The branch must contain:
- `-qps K` in `datacenter/main_roce.cpp` (look for `MULTI-QP`);
- `BUGFIX(#11)` in `roce.cpp` and `dcqcn.cpp`. This fixes a PFC-pause packet
  leak. Without it, ring runs at K>1 grow by ~1.8 MB per finished flow and run
  out of memory. The fix doesn't change results.
- the ablation hooks in `fidelityRuns/bin/run_one_fidelity.sh` (`ARM`,
  `ARM_ARGS`, `OUTROOT`; empty by default, so fidelity behaviour is unchanged);
- this folder, `datacenter/experiments/runs/ablationMultipath/`.

The step 4 preflight checks all of these, including that the binaries are newer
than the sources.

## Step 2 — Environment

```bash
export HTSIM_ROOT=$HOME/HTSIM/htsim          # the directory that CONTAINS sim/
export WORKROOT=/big/disk/ablation_work      # per-run scratch: util.bin + raw stdout
cd $HTSIM_ROOT/sim/datacenter/experiments/runs/ablationMultipath
```

**`WORKROOT` must be on a large, mounted disk (≥ 50 GB free).** Each running job
writes its queue log (`util.bin`) and full stdout there, and deletes them when it
finishes. The long ring and a2a runs can each hold several GB while running.
Check with `df -h $WORKROOT` that it really is the big disk, not the root
filesystem: on the 31 GB box `/media/.../Data` was once unmounted, its path
silently pointed at root, and a test filled `/`.

## Step 3 — (Optional) rebuild the manifest

`MANIFEST.csv` is committed with the 5 fidelity seeds (710 jobs). Rebuild only if you
change seeds or scope:

```bash
python3 bin/build_ablation_manifest.py                  # 5 fidelity seeds (default), 710 jobs
python3 bin/build_ablation_manifest.py --seeds 13       # seed 13 only, 142 jobs
```

The pilot phase is always seed 13 only (28 runs); everything else is `main`.

## Step 4 — Preflight (do not skip)

```bash
bash bin/preflight_ablation.sh
```

It checks:
- the source and binaries carry `-qps`, `BUGFIX(#11)`, the runner hooks and
  `-load_balancing_algo`;
- the binaries are newer than the sources;
- the topologies (400 G) and every manifest matrix are present;
- the baseline file is present, and RAM and `WORKROOT` disk are sufficient.

Then it runs **4 short sims** (about a minute) on perm_random_128n_16MB, 1os,
seed 13:
1. IB with no arm and UET with no arm. Each must **exactly** match its recorded
   fidelity row (IB: makespan, p99 FCT, PFC pauses, max queue; UET: makespan,
   p99 FCT, New, Rtx, NACKs).
2. IB `-qps 2` and UET ECMP. Each must finish `ok` and **differ** from the
   baseline, which proves the flag took effect.

It must end with `PREFLIGHT PASSED`. If a baseline doesn't reproduce, stop:
the baselines can't be reused and you'd have to rerun them too.

## Step 5 — Pilot (28 runs)

The pilot covers all 4 arms on every 128-node 16 MB cell. That includes ring and
a2a, the jobs whose K>1 memory and time are unknown.

```bash
PHASE=pilot bash bin/start_ablation.sh
tail -f sweep_ablation.progress.log
```

Defaults are sized for 90 GB:

| knob | default | applies to |
|---|---|---|
| `PARALLEL` | 6 | light jobs (perm, incast, outcast) |
| `LIGHT_MEM_GB` | 10 | per-job memory cap, light |
| `HEAVY_PARALLEL` | 2 | heavy jobs (allreduce_ring, a2a_concurrent), after the light ones |
| `HEAVY_MEM_GB` | 40 | per-job memory cap, heavy |

Keep `PARALLEL × LIGHT_MEM_GB` and `HEAVY_PARALLEL × HEAVY_MEM_GB` below usable
RAM. A job that exceeds its cap aborts within seconds as `status=mem_capped`,
instead of taking the machine down.

Expect about 1 h, dominated by ring and a2a at 16 MB (about 1 h each at K=1 on
this box). When it finishes, check the following before starting `main`:

```bash
cat abl_*/rows/*.row | awk -F, '{print $1, $3, $11, "peak="$13"MB", "wall="$12"s", "ovf="$37}' | sort
```

| what you see | meaning | what to do |
|---|---|---|
| all `ok`, `ovf=0` | good | continue to main |
| `lossless_overflow` (IB) | the `-q 1000` lossless buffer overflowed: the fabric was mis-configured, so this isn't a result | raise `QSIZE` for that workload (as the fidelity study did for rail MoE); `-q` doesn't change results when nothing overflows |
| `mem_capped` | over the cap | raise `HEAVY_MEM_GB` (and lower `HEAVY_PARALLEL` to match) |
| `timeout` / `incomplete` | something's stuck | inspect `abl_*/logs/<tag>.log`; don't start main |

**Size the heavy phase from the pilot.** Take the largest heavy `peak_mb` at
qp8, multiply by about 1.7 for 100 MB (fidelity IB ring went 2.6 → 4.3 GB from
16 to 100 MB at K=1), then set `HEAVY_MEM_GB` to about 1.5× that, and
`HEAVY_PARALLEL = floor(85 / HEAVY_MEM_GB)`. For example, a 4 GB pilot peak
gives about 7 GB at 100 MB, so a 12 GB cap and `HEAVY_PARALLEL=6`.

## Step 6 — Main (682 runs)

```bash
PHASE=main HEAVY_PARALLEL=<from pilot> HEAVY_MEM_GB=<from pilot> bash bin/start_ablation.sh
```

**Expected time.** Per seed, the 1os fidelity runs on this box took 27.5 h serial
for IB and about 10 h for UET (excluding the dropped ring cells). The K>1 runs were
up to about 1.5× slower per run in tests (more QPs, more PFC). Rough total:
**about 130 CPU-hours per seed, about 650 CPU-hours for 5 seeds**. About 85% of
that is the heavy jobs: IB ring 100 MB (8.5 h at K=1) and IB a2a 100 MB (5.5 h at
K=1), times 3 arms and 5 seeds. So `HEAVY_PARALLEL` sets the wall time: at 6
about **4–5 days**, at 2 about 2 weeks. That's why sizing it from the pilot
(step 5) matters.

**Stop / resume:** `kill -TERM -$(cat sweep_ablation.pgid)`. Rerunning the same
`start_ablation.sh` command skips every job whose row is already `ok`.

## Step 7 — Monitor

```bash
tail -f sweep_ablation.progress.log
grep -c '^\[done' sweep_ablation.progress.log                       # runs completed
cat abl_*/rows/*.row | awk -F, '{c[$11]++} END{for(s in c) print s, c[s]}'   # status tally
python3 bin/compare_ablation.py                                       # partial tables, any time
```

## Step 8 — Verify

Every ablation row needs:
- `status == ok` (column 11);
- `flows_fin == conns` (columns 14 and 6);
- `overflow == 0` (column 37; IB only).

`compare_ablation.py` prints the not-ok runs at the end.

## Step 9 — Results

`compare_ablation.py` runs automatically at the end of each phase. It writes:

- `results/ablation_wide.csv`, one row per cell with:
  - makespan for all six arms (`ib_qp1/2/4/8`, `uet_spray`, `uet_ecmp`);
  - multipath gains `ib_gain_qpK = qp1/qpK` and `uet_gain_spray = ecmp/spray`
    (> 1 means multipath helps);
  - the transport gap without multipath, `gap_single_path_ib_over_uet = qp1/ecmp`;
  - the transport gap with multipath, `gap_multipath_ib_qp8_over_uet = qp8/spray`.
- `results/ablation_long.csv`, one row per (cell, arm), with:
  - status and the key metrics (makespan, FCT p50/p99, slowdown p99, Jain,
    PFC pauses and pause time, max queue, Rtx, NACKs, spurious, peak memory,
    wall time);
  - the ratio to that stack's baseline;
  - `within_seed_noise` (single-seed view), which is true when the change is smaller than the
    baseline cell's 5-seed (max−min)/mean spread in the fidelity study. Treat
    those cells as "no measurable effect".
- `results/ablation_mean.csv`, **the main table for conclusions**: one row per
  (cell, stack, arm) across the 5 seeds, with n, mean/std/min/max makespan,
  `gain_vs_baseline` (baseline mean / arm mean; > 1 means multipath helps) and
  `ranges_overlap_baseline` (true means the arm's seed range overlaps the
  baseline's, so the effect isn't separable from seed noise).

## Step 10 — Bring results back

Rows are small; logs and work dirs are not needed.

```bash
cd $HTSIM_ROOT/sim/datacenter/experiments/runs
tar czf ablation_results.tgz ablationMultipath/abl_*/rows ablationMultipath/abl_*/util_rows \
    ablationMultipath/results ablationMultipath/sweep_ablation.progress.log
```

Copy the archive back (or commit those paths on `ablations` and push).

---

## Caveats to state with the results

- **Static split, not NCCL chunking.** Each flow is divided once into K equal
  byte ranges. Real NCCL posts about 512 KB chunks round-robin over QPs, with an
  8-chunk credit window that couples the QPs (a slow QP stalls the window). The
  static split gets the bytes per QP right but not that coupling, so it is
  likely an **upper bound** on the RoCE multipath gain.
- **QPs start at full line rate.** All K QPs of a flow start at 400 G and DCQCN
  adapts each one. The excess queues at the sending host's NIC (bounded by the
  flow size); this is how the simulator already treats hosts with many flows.
- **Seeds.** ECMP results depend strongly on the seed (hash collisions). Judge
  effects from `ablation_mean.csv` (mean over the 5 seeds, and whether the seed
  ranges overlap the baseline's), not from single-seed rows. The seed changes the
  switch hash salt and the per-flow (per-QP) path choice, exactly as in the
  fidelity study, so each ablation seed pairs with the same baseline seed.
- **Path diversity:** ECMP paths come from a per-flow (per-QP) hash in the
  switches. IB passes `-paths 128`; UET passes no `-paths`, so it uses its
  default of 64 entropies. Both match their baselines.
- **Baseline memory peaks include the old leak.** The fidelity IB peaks were
  measured before BUGFIX(#11), so ring/serial workloads will now peak *lower*
  than the baseline `peak_mb` column suggests. Makespan and all other results
  are unaffected.
