# OOM & infeasibility log — UEC topology sweeps

Record of every out-of-memory (and adjacent "couldn't finish") event across the
htsim UEC sweeps, so we don't re-learn the walls. Last updated 2026-07-11.

## Machines involved

| Box | RAM | Swap | Root disk | Used for |
|---|---|---|---|---|
| **this dev box** | **31 GB** | 3.6 GB | ~2 GB free (now ~15 GB after trace relocation) | a2a_128_1024 (our session) |
| **Technion /csl box** | **94 GB** | — | — | a3_200g, all_workloads, allreduce_ring, a2a_conc |

## The two walls (why things die)

1. **Memory** — htsim pre-allocates **one `UecSrc`+`UecSink` per connection** (~20–25 KB each) at setup, *before* the sim runs. Connection count is **O(N) for point-to-point** but **O(N²) for all-to-all / collectives**. On the stock `study/a3` branch there's also a **~21 KB/flow leak** → memory *grows during the run*, not just at setup.
2. **Runtime** — single-threaded discrete-event sim; huge flow counts take days–months of wall clock **regardless of RAM**. More cores/RAM don't speed a single run.

## Actual OOM events (observed)

| Workload | Scale | Machine | Connections | RAM at kill | Outcome | Cause |
|---|---|---|---|---|---|---|
| **a2a (serial)** | 1024n | 31 GB (this box) | 1,047,552 | ~32 GB (RAM 29 GB + swap 3.6 GB, both full) | **OOM-killed at 39%** (413,150 / 1,047,552) after **17.4 h** | ~25 GB setup + flow-leak growth exceeded 31 GB |
| **ring AllReduce** | 1024n | 94 GB (/csl) | ~2,096,128 | 40–50 GB **per run**, run at **-P2** → ~90–100 GB | **all 9 runs OOM-killed** at 0.5–5.5% completion | 2× a2a's connections × 2-way concurrency > 94 GB |

## NOT an OOM — timeout (logged for contrast)

| Workload | Scale | Machine | Connections | RAM | Outcome | Cause |
|---|---|---|---|---|---|---|
| **a2a (concurrent)** | 1024n | 94 GB (/csl) | 1,047,552 | **21 GB (fine)** | **TIMEOUT** at 24 h wall, only 0.67–0.68% done (2 runs, then stopped) | **runtime**, not memory |

Key insight: concurrency did **not** change memory (still 21 GB) — it made *runtime* catastrophic (worse than serial's 39% in 17 h). Memory and runtime are independent walls.

## Projected-infeasible — never attempted (would OOM by orders of magnitude)

| Workload | Scale | Connections | Projected RAM | Note |
|---|---|---|---|---|
| **a2a** | 8192n | 67,100,672 | **~1.5 TB** | 64× the 1024n a2a; also ~months of runtime |
| **ring AllReduce** | 8192n | 134,201,344 | **~3 TB** | 2× a2a@8192 |

These were **never run** — the numbers are projections from the ~20–25 KB/connection setup cost. No 8192 collective/a2a has ever been attempted.

## What does NOT OOM (for reference)

- **All point-to-point patterns** (perm, incast_random/remote, outcast_incast) at 128 / 1024 / **8192**: O(N) connections = only **4k–8k** endpoints. Memory is driven by the *topology* (switches/queues), not the flows. The a3 study ran perm + incast at **8192 = 264/264 `ok`, zero OOM**.
- **a2a / ring @128**: 16k / 32k connections — trivial.

## Related OOM from the GOAL/Llama study (different workload, same machine limits)

- **Llama7B GOAL trace** (ATLAHS, packet-level): OOM-killed at ~15 GB RSS on a 15 GB box — a *different* study (GOAL traces, not topology sweeps), noted here for completeness. See memory `uec-rto-wedge-deadlock-fix`.

## Thresholds / lessons

- **a2a @1024** to completion: ~45–60 GB (leaky branch) / ~30–40 GB (leak fixed) → a **64 GB** box suffices.
- **ring @1024**: a *single* run needs ~50 GB; it OOM'd on 94 GB only because of `-P2`. At `-P1` it fits.
- **8192 collectives / a2a**: need **TB-scale** RAM → out of reach; use **LogGOPSim / analytical** for that regime, not packet-level htsim.
- **Fix the flow-leak** (`dev/flow-leak-fix`) before any multi-day 1024 run — otherwise memory climbs to OOM even on a big box.
- Dropping `-log tor_*queue` roughly halves footprint (per-queue loggers) — last-resort memory lever, costs per-tier utilization.

See also: `a2a_128_1024/` (serial), `a2a_conc_128_1024/NOTES.md` (concurrent), `allreduce_ring_128_1024/NOTES.md` (ring), and memory note `a2a-sweep-and-machine-constraints`.
