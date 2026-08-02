# allreduce_ring_128_1024/ — sweep notes

Ring AllReduce sweep, launched 2026-07-04 13:19, killed 2026-07-05 12:15 after 1024n runs OOM-killed. 128n phase completed cleanly.

## Setup

- Same runner (`run_one.sh`) + extractor (`extract_util.py`) as the previous sweep (`all_workloads_128_1024/`).
- Watchdog SIGTERM on `finished at` count == matrix `Connections`.
- NSCC (`-sender_cc_only`), 200 Gbps host links, 1 ms utilization sampling.
- `-end 300000ms` safety cap (never hit — watchdog fires first when it works).

## Results

### 128-node ring AR (9 runs — all clean)

- All 9 rows `status=ok`, `flows_fin = 32640 / 32640`.
- Makespan (ms):

| flow size | 1os | 4os | 8os |
|---|---|---|---|
| 16 MB | 291 | 795 | 1502 |
| 64 MB | 1213 | 3056 | 6246 |
| 100 MB | 1901 | 4710 | 9526 |

- Fabric penalty: 4os ≈ 2.5×, 8os ≈ 5.0× the 1os makespan.
- NACK/(New+Rtx): 0.12–1.67% across all runs.

Ring AR is bandwidth-heavy (each per-node chain sends 2·(N−1) times), so it stresses the fabric far more than butterfly would. But every host sees a symmetric bidirectional load, so the utilization looks quite uniform across tiers on 1os.

### 1024-node ring AR (all 9 runs OOM-killed) — SKIPPED

- Rows deleted from this sweep's output. See [[project-ar-1024n-oom]].
- Each 1024-node ring run pre-allocates 2,096,128 UecSrc + UecSink instances at setup (matrix file 213 MB) plus multipath routing state + per-tier queue loggers. RSS grew to 40–50 GB per run before OOM.
- 5 runs completed as `incomplete` at 0.5–5.5% flow completion after 5–7 h wall each; 2 more were mid-run when killed; 2 hadn't started.
- Workaround options: (a) drop `-log tor_downqueue/tor_upqueue` (loses per-tier util data, cuts memory by ~half); (b) reduce concurrency to -P1; (c) accept 1024n ring as infeasible under this htsim/topology (matches a3 study §10).

## Files

```
NOTES.md                       this file
results_combined.csv           9 rows (128n only)
utilization_combined.csv       9 rows (128n only, all with full data)
matrices/                      symlinks into all_workloads_128_1024/matrices/
logs/, rows/, util_rows/       per-run outputs
run_one.sh, sweep.sh, extract_util.py    (copies of all_workloads_128_1024 runner)
sweep.pid, sweep.out           sweep driver PID + log
```
