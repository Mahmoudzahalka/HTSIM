# Directory layout (reorganised 2026-08-02)

`experiments/runs/` was flattened into four trees: **`uet/`**, **`ib_dcqcn/`**,
**`shared/`**, **`older_runs/`**. Nothing was deleted — everything unwanted was
*moved* to `older_runs/` and can be restored with a `mv`.

## Current layout

```
shared/topos_200g/         all 9 fat_tree_*.topo  (referenced by BOTH stacks)
shared/topos_gpu_clustered/ Phase-1 8-GPU clustered topo

uet/perm_incast_128_1024/    90 runs + 33 matrices  (matrices also feed the IB runs)
uet/a2a_concurrent_128_1024/ 11 runs + 6 matrices
uet/a2a_serial_128_1024/     10 runs  (matrices live on /media, not here)
uet/allreduce_ring_128/       9 runs + 3 matrices
uet/graphs/                   UET fig1-8

ib_dcqcn/perm_incast_a2a_128_1024/  99 runs  (29-col instrumented; the main sweep)
ib_dcqcn/allreduce_a2a_serial_128/  18 runs  (workload parity)
ib_dcqcn/graphs/                    IB fig1-8

older_runs/                  archived, see below
```

## Old name → new name

| old | new | why |
|---|---|---|
| `a3_200g/topos_200g` | `shared/topos_200g` | **extracted** — every harness needs it |
| `a3_200g` (rest) | `older_runs/a3_200g` | superseded 200G study |
| `all_workloads_128_1024` | `uet/perm_incast_128_1024` | name now says the workloads |
| `a2a_conc_128_1024` | `uet/a2a_concurrent_128_1024` | |
| `a2a_128_1024` | `uet/a2a_serial_128_1024` | it was the *serial* a2a |
| `allreduce_ring_128_1024` | `uet/allreduce_ring_128` | only 128n exists |
| `graphs` | `uet/graphs` | they are the UET figures |
| `ib_uet_compare_128_1024` | `ib_dcqcn/perm_incast_a2a_128_1024` | |
| `ib_workload_parity_128` | `ib_dcqcn/allreduce_a2a_serial_128` | |
| `.../graphs_ib` | `ib_dcqcn/graphs` | |
| `all_workloads_ib_128_1024` | `older_runs/pfc_only_no_dcqcn_128_1024_8192` | PFC-only, no DCQCN (also holds the only 8192 data) |
| `all_workloads_ib_dcqcn_k8_128_1024` | `older_runs/ib_dcqcn_k8_22col_superseded` | 22-col; its 90 runs are all in the 29-col sweep |
| `gpu_clustered_8gpu` | `older_runs/gpu_clustered_scaffolding` | topo kept in `shared/` |
| `A3_STUDY.md`, `OOM_LOG.md` | `older_runs/` | stale notes |

## What was patched at the same time

- **21 shell scripts + 4 Python scripts** — hardcoded `OUT=`, `topo=`, matrix paths.
- **3 `extract_util.py` symlinks** relinked to `uet/perm_incast_128_1024/extract_util.py`.
- **Graph output dirs** — `make_graphs*.py` → `uet/graphs`, `make_graphs_ib.py` → `ib_dcqcn/graphs`.
- **Docs** — `IB_DCQCN_README.md`, `IB_vs_UET_COMPARISON.md`.

Verified after the move: IB harness end-to-end (same 4449 µs makespan as before), all
three graph scripts, and `compare_ib_uet.py`.

## Gotchas if you touch this again

1. **The CSVs contain the OLD names as data** — the `matrix` column holds absolute
   old paths, and the UET `sweep` column holds e.g. `a2a_conc_128_1024`. This is
   harmless (all comparisons join on the *basename*), but it is why
   `make_graphs.py::label()` still compares against the **old** sweep names. Don't
   "fix" that function to the new paths — it reads CSV data, not directories.
2. **Serial-a2a matrices are NOT in the repo** — they live at
   `/media/mahmoud_murad_allaah/Data/a2a_128_1024/matrices/`. Path rewrites were
   scoped to `runs/…` precisely so that absolute path survived. The 210 GB disk has
   no fstab entry, so remount after a reboot:
   `sudo mount /dev/sdb /media/mahmoud_murad_allaah/Data`
3. **Matrices live inside the UET dirs** (`uet/perm_incast_128_1024/matrices` etc.)
   and are used by the IB runs too — those UET dirs are load-bearing for IB.
4. **Scripts under `older_runs/` had their paths rewritten too**, but they are archived
   and not maintained; treat them as historical.
