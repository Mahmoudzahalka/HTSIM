# Runbook — the 3 outstanding rail runs (need a bigger-memory machine)

> ## ✅ DONE — all three runs completed on the larger box (2026-08-05, commit `5135e73`).
> **The rail study is now 48/48 complete and clean**: every run finished all its
> flows, and all 24 IB runs recorded zero lossless overflow.
>
> | run | makespan | check |
> |---|---|---|
> | `ib.rail`  | **40,940.6 us** | 536576/536576 flows, overflow 0, 2,925,156 PFC pauses |
> | `ib.flat`  | **52,082.5 us** | 536576/536576 flows, overflow 0, 3,027,741 PFC pauses |
> | `uet.flat` | **37,178.9 us** | 536576/536576 flows, Rtx 17,587,253 |
>
> Results are folded into `results_rail.csv` / `utilization_rail.csv`; figures and
> §8 of `notes/DESIGN_AND_VALIDATION.md` are updated. **The rest of this file is
> kept as the reproduction record** — it documents exactly how these three were run.

---

**(Historical, at the time of writing: 45 of 48 runs complete and clean.** Only one
cell was missing: **MoE all-to-all, 2048 GPUs, 100 MB**. It needed more RAM than the
31 GB box had.**)**

---

## 1. Exactly what to run

Three runs, all on the same matrix `rail_alltoall_moe_2048gpu_100MB.cm`:

| # | stack | topology | why it's missing |
|---|-------|----------|------------------|
| 1 | **ib**  | **rail** | OOM-killed at `-q 8000` (31.9 GB, kernel log) |
| 2 | **ib**  | **flat** | never finished (sweep stopped) |
| 3 | **uet** | **flat** | never started (queued behind #2) |

(`uet` + `rail` for this cell already completed OK — makespan 31,203.6 us — so do
**not** re-run it unless you want uniform provenance; see §6.)

## 2. Why they failed here, and what the new box needs

The lossless buffer (`-q`, in packets) has to be big enough that the IB fabric
never overflows, and that costs memory:

| `-q` | overflow at 2048/100MB | peak RSS |
|------|------------------------|----------|
| 1000 | 84,054 (lossless invariant VIOLATED) | ~5 GB |
| 4000 | untested (run was climbing toward OOM) | >29 GB |
| 8000 | **0** (correct) | **~32 GB — OOM'd here** |

**Target machine: >= 64 GB RAM.** Use **`-q 8000`** (proven overflow-free at 2048).
With 64 GB you can also run 2-3 of them in parallel; with 128 GB, all three.

## 3. What to copy over

From this repo (paths relative to `htsim/sim/`):

```
datacenter/htsim_roce                                  # or rebuild: cd build && make htsim_roce
build/datacenter/htsim_uec                             # or: make htsim_uec
build/parse_output                                     # needed for utilization extraction
datacenter/experiments/runs/rail_optimized/topos/rail_2048gpu_8rail.topo
datacenter/experiments/runs/rail_optimized/topos/flat_2048gpu_sameshape.topo
datacenter/experiments/runs/rail_optimized/topos/nvlink_2048gpu_8pergpu.topo
```

**The matrix is NOT in git** (49.6 MB, near GitHub's file limit). Regenerate it --
the generator is deterministic, so it reproduces the identical file:

```bash
cd htsim/sim/datacenter
python3 connection_matrices/gen_rail_aware_alltoall.py \
    experiments/runs/rail_optimized/matrices/rail_alltoall_moe_2048gpu_100MB.cm 2048 8 100000000
# expect: 137216->536576 flows, 14336 intra-server (NVLink), 522240 same-rail, 0 cross-spine
```

**Rebuild rather than copy binaries if the box differs** — and note the build must
include our changes (`Rails N` support in `fat_tree_topology.*`, the `-nvlink_topo`
/ `-nvlink_linkspeed` / `-gpus_per_server` flags in `main_roce.cpp` / `main_uec.cpp`).
Branch: **`study/rail-optimized-nvlink`** — `dev/ib-dcqcn-fix` does *not* carry the
rail/NVLink code (it is the flat-study branch).

## 4. The commands (portable — no harness paths)

Set these once:

```bash
M=rail_alltoall_moe_2048gpu_100MB.cm
NVT=nvlink_2048gpu_8pergpu.topo
NV="-nvlink_topo $NVT -nvlink_linkspeed 3600000 -gpus_per_server 8"
Q=8000
```

**Run 1 — IB on rail**
```bash
./htsim_roce -tm $M -nodes 2048 -topo rail_2048gpu_8rail.topo $NV \
  -linkspeed 200000 -strat ecmp_host -paths 128 \
  -queue_type lossless_input -pfc_thresholds 12 15 -q $Q -dcqcn 8 \
  -end 600000000 -logtime_us 20000 -log tor_downqueue -log tor_upqueue \
  -o util_ib_rail.bin > ib_rail.out 2>&1
```

**Run 2 — IB on flat control** (identical, only `-topo` changes)
```bash
./htsim_roce -tm $M -nodes 2048 -topo flat_2048gpu_sameshape.topo $NV \
  -linkspeed 200000 -strat ecmp_host -paths 128 \
  -queue_type lossless_input -pfc_thresholds 12 15 -q $Q -dcqcn 8 \
  -end 600000000 -logtime_us 20000 -log tor_downqueue -log tor_upqueue \
  -o util_ib_flat.bin > ib_flat.out 2>&1
```

**Run 3 — UET on flat control** (UET needs no `-q`; it is a lossy fabric)
```bash
./htsim_uec -tm $M -sender_cc_only -nodes 2048 -topo flat_2048gpu_sameshape.topo $NV \
  -linkspeed 200000 -end 600000000 \
  -logtime_us 20000 -log tor_downqueue -log tor_upqueue \
  -o util_uet_flat.bin > uet_flat.out 2>&1
```

Expect roughly **20-40 min each**. UET peaked ~10 GB here, so run 3 is low risk.

## 5. How to tell each run succeeded

```bash
for f in ib_rail ib_flat uet_flat; do
  echo "$f: flows=$(grep -c 'finished at' $f.out)/536576" \
       "overflow=$(grep -c 'LOSSLESS not working' $f.out)" \
       "epilogue=$(grep -cE '^(New:|PFC_PAUSES)' $f.out)" \
       "makespan=$(grep -oE 'finished at [0-9.]+' $f.out | awk '{print $3}' | sort -n | tail -1)us"
done
```

All three must hold:
1. **`flows = 536576/536576`** — anything less means it died early.
2. **`overflow = 0`** on the IB runs — otherwise `-q` is still too small and the run
   is mis-configured (raise `-q` and retry). UET has no such requirement.
3. **`epilogue >= 1`** — the `New:` / `PFC_PAUSES` summary lines are present. If they
   are absent the process was killed (OOM shows as exit code **137**), and the run
   is invalid regardless of how many flows finished.

Sanity anchors from runs that already completed here:
- `uet.rail` same cell: makespan **31,203.6 us**, Rtx **17,640,897**
- `ib.rail` at 64 MB: makespan **27,925.1 us**, PFC pauses **1,889,201**

## 6. Optional — uniform provenance

The other 2048 MoE runs (16 MB, 64 MB) were done at `-q 8000`, and the 1024 MoE runs
too, so the grid is already consistent. But if you want every 2048/100MB cell from
one machine, also re-run **`uet` + `rail`** with the run-3 command and
`-topo rail_2048gpu_8rail.topo`. Not required — it completed cleanly here.

Worth knowing: `-q` does **not** change the answer, only whether the buffer is
honestly sized. Measured at 1024/100MB, makespan was **identical (29,603.3 us)** at
`-q` 1000 / 4000 / 8000, because htsim's overflow only *warns* and keeps the packet.
That is why a `-q 1000` run would still give correct timings — it would just be
mislabelled as a 1000-packet buffer when it is effectively unbounded.

## 7. What to send back

Just the three stdout files (`ib_rail.out`, `ib_flat.out`, `uet_flat.out`) and the
three `util_*.bin` plus their `idmap.txt`. I will fold them into
`results_rail.csv` / `utilization_rail.csv` using the existing
`run_one_rail.sh` parsing (33-column superset) and `extract_util.py`.

If it is easier, run them through the harness instead and send the `.row` /
`.urow` files directly:

```bash
cd .../experiments/runs/rail_optimized
SCALE=2048 QSIZE=8000 bash run_one_rail.sh matrices/rail_alltoall_moe_2048gpu_100MB.cm ib  rail
SCALE=2048 QSIZE=8000 bash run_one_rail.sh matrices/rail_alltoall_moe_2048gpu_100MB.cm ib  flat
SCALE=2048 QSIZE=8000 bash run_one_rail.sh matrices/rail_alltoall_moe_2048gpu_100MB.cm uet flat
```
Note `run_one_rail.sh` has **hardcoded absolute paths** (`DC=/home/mahmoud_murad_allaah/...`
and `WORKROOT=/media/.../Data/rail_work`) — edit those two for the new machine.
