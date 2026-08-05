# Rail-optimized topology — design, simulator interactions, validation

Status: **COMPLETE — rail topology + NVLink plane implemented and validated on both stacks;
full sweep finished 48/48 ok at 1024 and 2048 GPUs (see §8 for results).**

## 1. What was built

A 1024-GPU rail-optimized compute fabric (DGX SuperPOD-class), 2-tier leaf-spine:

```
1024 GPUs = 128 servers x 8 GPUs, each GPU with its own 200G NIC -> its own rail
8 rails; rail r served by 4 leaf switches, each = 32 downlinks + 32 uplinks (64-port)
32 leaves (8 rails x 4)   32 spines (radix 32)   non-blocking   diameter 4
```

Mapping (`Rails 8` in the .topo enables it):
```
GPU g -> rail r = g % 8 ,  server s = g / 8 ,  leaf = r*leaves_per_rail + s/servers_per_leaf
```
So a leaf holds **one GPU from each of 32 servers** (a real rail), not 4 whole servers.

Files:
- `topos/rail_1024gpu_8rail.topo` — the rail fabric
- `topos/flat_1024gpu_sameshape.topo` — **control**: byte-identical shape (32 leaves x 64 ports,
  32 spines), differing *only* by the `Rails 8` line. Lets us separate the effect of the rail
  **assignment** from the effect of the leaf/spine **shape**.
- `topos/validation/probe_0to{1,8}.cm` — single-flow probes used below.

## 2. Simulator changes (shared layer — serves BOTH stacks)

| file | change |
|---|---|
| `fat_tree_topology.h` | `_rails` member; `rails()/servers_per_leaf()/leaves_per_rail()`; rail branch in **`HOST_POD_SWITCH()`** |
| `fat_tree_topology.cpp` | `rails` keyword in `read_cfg()`; rail branch in the **host↔ToR wiring loop**; config validation in `set_custom_params()` |

`HOST_POD_SWITCH()` and the wiring loop are **exact inverses** — they must always be changed
together. Everything else dispatches through `HOST_POD_SWITCH()`, so it follows automatically.

**The rail change needed no edits to `main_uec.cpp` / `main_roce.cpp`** (the NVLink plane in §5 does add flags there).

## 3. Components & interactions reasoned about

| component | interaction | status |
|---|---|---|
| host→leaf wiring | changed (strided) | ✅ changed, inverse-checked |
| `HOST_POD_SWITCH` | changed | ✅ |
| switch routing (`fat_tree_switch.cpp`) | dispatches via `HOST_POD_SWITCH(pkt.dst())` at 4 sites | ✅ follows automatically |
| route construction (both mains) | uses `topo_cfg->HOST_POD_SWITCH(src)` | ✅ follows, no edit |
| host port registration | `switches_lp[HOST_POD_SWITCH(src)]->addHostPort()` | ✅ follows |
| topology sizing (`NTOR/NAGG`) | derived from `nodes/radix_down`, **independent of assignment** | ✅ unchanged |
| pod logic (`HOST_POD`) | meaningless under striding — **avoided by using 2-tier**, where `get_tiers()==2` short-circuits the pod checks | ✅ sidestepped |
| diameter / RTT / BDP (UEC) | `get_two_point_diameter_latency()` compares `HOST_POD_SWITCH` | ✅ follows; diameter=4 |
| ECMP path diversity | 32 spines ⇒ 32 leaf-to-leaf paths; entropy above 32 folds onto 32 | ⚠ note for spray studies |
| PFC / lossless (IB) | orthogonal to assignment | ✅ ran clean |
| DCQCN ECN marking | orthogonal | ✅ |
| UEC oversubscribed CC | `oversub=1` ⇒ not triggered | ✅ n/a |
| connection matrices | unchanged files; **semantics reinterpreted** (GPU g ⇒ server g/8, rail g%8) | ✅ reusable |
| **NVLink / intra-server** | second topology + second egress NIC per node, chosen at connect time | ✅ implemented, see §5 |

## 4. Validation (both stacks)

Discriminating probe — a 1 MB flow, chosen so rail and flat *must* disagree:
- `GPU0→GPU1` = same server, **different rail** ⇒ rail: different leaves (0 vs 4) → via spine; flat: same leaf.
- `GPU0→GPU8` = **same rail**, adjacent servers ⇒ both: same leaf.

| flow | topology | IB FCT (µs) | UET FCT (µs) |
|---|---|---|---|
| 0→1 | **rail** | **49.14** | **49.14** |
| 0→1 | flat | 44.81 | 44.80 |
| 0→8 | **rail** | 44.81 | 44.80 |
| 0→8 | flat | 44.81 | 44.80 |

+4.33 µs = exactly 2 extra hops each way (4 × 1000 ns pipes). Confirms the rail wiring end-to-end
on **both** stacks, and that the flat control behaves classically.

Also verified: reported sizing `NCORE=0 NAGG=32 NTOR=32 NSRV=1024 NPOD=1 tiers=2 radix_down=32
radix_up=32 diameter=4`; layout line `8 rails x 4 leaves/rail = 32 leaves, 32 servers per leaf`;
and that a bad config (`Rails 7`) is rejected with a clear error rather than silently mis-wiring.

## 5. NVLink plane — IMPLEMENTED

`topos/nvlink_1024gpu_8pergpu.topo`: 128 leaves = 128 servers, 8 GPUs each on a
3600 Gbps (450 GB/s per direction, NVLink4-class) non-blocking crossbar, 100 ns links.
Only intra-server flows attach to it, so traffic never leaves a leaf and the inert
Tier-1 sidesteps fabric inflation.

**Selection is made once, at connect time** (a flow's destination is fixed):
`same_server = (src/rails == dst/rails)` -> NVLink topology + NVLink egress; else rail.

New flags (both stacks): `-nvlink_topo <file>` and `-nvlink_linkspeed <Mbps>`.

Why the host *rate* had to change too: the fabric alone is not enough. Measured on the
NVLink path, a 64 MB flow took **2601 us at a 200 G host rate vs 145 us at 3600 G** --
i.e. the host emission rate, not the links, is the binding constraint.

| stack | how the NVLink rate is applied | code touched |
|---|---|---|
| IB | `RoceSrc` takes its rate as a ctor arg -> intra-server sources built at the NVLink rate | `main_roce.cpp` only |
| UEC | rate lives in `UecNIC` (one per node). Instead of adding per-port linkspeeds inside the NIC (hot path), each node gets a **second `UecNIC`** for NVLink; intra-server srcs/sinks are constructed against it | `main_uec.cpp` only |

The second-NIC approach is both **more faithful** (NVLink engine and rail NIC are separate
hardware, so they transmit independently) and **zero-risk**: `uec.cpp` -- the per-packet send
path all existing UET results came from -- was not modified at all.

### Validation (64 MB flows, both stacks)

| flow | config | IB (us) | UEC (us) |
|---|---|---|---|
| 0->1 (same server) | rail only | 2609.5 | 2608.6 |
| 0->1 (same server) | **rail+NVLink** | **144.9** | **144.9** |
| 0->8 (diff server) | rail only | 2605.1 | 2604.3 |
| 0->8 (diff server) | rail+NVLink | **2605.1** (unchanged) | **2604.3** (unchanged) |
| 0->1 **and** 0->8 concurrently | rail+NVLink | 144.9 + 2605.1 | 144.9 + 2604.3 |

- Row 2: the NVLink rate really applies (18x, = the 3600/200 ratio).
- Row 4: cross-server flows are **unaffected** -- they are not mis-routed onto NVLink.
- Row 5: each flow hits its solo time, so the two egress engines are **independent**, not serialised.

Remaining caveat: without **rail-aware collectives**, little traffic exploits NVLink
(intra-server is ~0.7% of a2a flows), so the rail fabric mostly shows its cost (7/8 of
destinations are cross-rail). A hierarchical-allreduce generator is the natural next step.

## 6. Next steps

1. **Rail-aware collective generator** (hierarchical all-reduce: reduce intra-server over NVLink ->
   exchange same-rail across servers -> broadcast back). Without it little traffic uses NVLink and
   the rail fabric mostly shows its cost, so this is what makes the setup meaningful.
2. Sweeps: rail+NVLink vs the shape-matched flat control, both stacks (dirs `ib_dcqcn/`, `uet/` here).
3. Optional: sensitivity to the NVLink rate (`-nvlink_linkspeed`).

## 7. Rail-aware collective + first result (IB, 16 MB, 1024 GPUs)

`connection_matrices/gen_rail_aware_allreduce.py` generates the hierarchical
all-reduce these clusters are built for. Three phases:
1. intra-server ring reduce-scatter (chunk S/8) -> **NVLink**
2. rail-local all-reduce on that chunk, recursive halving/doubling (2*log2(128)=14 steps) -> **same rail**
3. intra-server ring all-gather -> **NVLink**

Partners in phase 2 are `i XOR d` within a rail, so the rail index never changes.
Generated matrices: `matrices/rail_allreduce_1024gpu_{16,64,100}MB.cm` --
**28,672 flows: 14,336 intra-server + 14,336 same-rail, 0 cross-spine** (asserted
by the generator). Dependencies use per-GPU trigger chains.

### Ablation — what each ingredient buys (16 MB, 1024 GPUs, both stacks)

| config | IB (us) | UET (us) |
|---|---|---|
| **rail + NVLink** (full setup) | **1139** | **357** |
| flat + NVLink | 1297 | 356 |
| flat only | 2994 | 1488 |
| rail only, no NVLink | 6602 | 1677 |

Three findings:

1. **NVLink dominates on both stacks** — IB 5.8x on the rail fabric (6602 -> 1139),
   UET 4.7x (1677 -> 357).
2. **Rails are actively HARMFUL without NVLink** (IB 6602 vs 2994 = 2.2x *worse*;
   UET 1677 vs 1488 = 13% worse). Rail assignment deliberately scatters a server's
   8 GPUs across 8 leaves, so the intra-server phases must cross the spine; on the
   flat fabric those GPUs share a leaf. **Rail-optimization only pays off together
   with NVLink** — which is why real deployments ship them as a pair.
3. **Rail-optimization is an IB optimization; UET barely notices it** — *in this cell*.
   With NVLink, rails buy IB ~12% (1139 vs 1297) but buy UET nothing at all (357 vs
   356 — flat is marginally faster, i.e. noise). **Do not generalize this**: §8 shows
   it holds for all-reduce at both scales, but on MoE all-to-all at 2048 GPUs rails
   buy UET up to 16%. Rails are a *locality* optimization: they put
   communicating peers on one leaf to avoid the spine. IB pins each flow to a single
   path, so locality matters to it. UET sprays across all paths and has spare
   bandwidth on a non-blocking fabric, so it is largely indifferent to whether
   traffic is leaf-local or crosses the spine.

Implication for the sweeps: **keep the flat control** — "rails help IB but not UET"
is only demonstrable by running both topologies on both stacks.

## 8. Rail sweep results (48 runs, 48/48 ok)

`results_rail.csv` (33 cols) + `utilization_rail.csv`. 2 rail-aware workloads x
{1024, 2048} GPUs x {16, 64, 100} MB x {rail, flat control} x {IB, UET}, NVLink on
throughout. All 48 complete every flow; all 24 IB runs have **zero** lossless
overflow (`-q 8000` at 2048).

> The last three cells (MoE / 2048 / 100 MB: `ib.rail`, `ib.flat`, `uet.flat`) were
> run on a larger-memory machine -- they need ~32 GB each at `-q 8000` and were
> OOM-killed on the 31 GB box. See `RUN_ON_BIGGER_BOX.md`.

### Makespan: rail vs flat control (negative = rails faster)

| workload | GPUs | 16 MB | 64 MB | 100 MB |
|---|---|---|---|---|
| all-reduce | 1024 | **-12%** | **-15%** | **-21%** |
| all-reduce | 2048 | **-11%** | **-15%** | **-15%** |
| MoE a2a | 1024 | **-33%** | **-16%** | **-7%** |
| MoE a2a | 2048 | **-17%** | **-22%** | **-21%** |

| workload | GPUs | 16 MB | 64 MB | 100 MB |
|---|---|---|---|---|
| UET all-reduce | 1024 | 0% | -5% | +9% |
| UET all-reduce | 2048 | 0% | +2% | +7% |
| UET MoE a2a | 1024 | -3% | -8% | -5% |
| UET MoE a2a | 2048 | **-6%** | **-10%** | **-16%** |

**Rails help IB on all 24 IB runs (-7% to -33%).** That holds at both scales.

**The "UET is indifferent to rails" claim does NOT survive to 2048.** It is still
true for all-reduce (0%..+9%, i.e. noise or slightly worse), but on MoE all-to-all
UET's rail benefit is consistent and *grows with both size and scale*, reaching
**-16% at 2048/100 MB** -- the largest UET rail gain in the grid. The 1024-only
data set had made rails look like an IB-only optimization; the 2048 data shows that
was a scale artifact.

### IB vs UET on the rail fabric (ratio; <1 = IB faster)

| workload | GPUs | 16 MB | 64 MB | 100 MB |
|---|---|---|---|---|
| all-reduce | 1024 | 3.19x | 3.87x | 3.42x |
| all-reduce | 2048 | 3.30x | 4.13x | 3.78x |
| MoE a2a | 1024 | 1.06x | **1.00x** | **0.89x** |
| MoE a2a | 2048 | 1.39x | 1.19x | 1.31x |

On all-reduce UET keeps its usual ~3-4x lead at both scales. On MoE the stacks come
close at both scales, but **IB's 100 MB win does not survive the scale doubling**:
0.89x at 1024 becomes 1.31x at 2048. The convergence is real and reproducible; the
*reversal* was specific to 1024. Doubling the GPU count roughly doubles each
receiver's incast fan-in, and that hurts IB (which must pause) more than UET (which
drops, retransmits, and keeps the pipe full).

### Congestion cost (rail topology)

| workload | GPUs | size | IB pauses | IB pause (ms) | UET Rtx | UET rtx% |
|---|---|---|---|---|---|---|
| all-reduce | 1024 | 100 MB | 11,118 | 44 | 25,069 | 0.1% |
| all-reduce | 2048 | 100 MB | 31,204 | 124 | 44,253 | 0.0% |
| MoE a2a | 1024 | 16 MB | 173,597 | 1,693 | 766,293 | 9.2% |
| MoE a2a | 1024 | 64 MB | 896,004 | 9,729 | 3,834,662 | 11.3% |
| MoE a2a | 1024 | 100 MB | 993,134 | 8,338 | 3,729,592 | 7.4% |
| MoE a2a | 2048 | 16 MB | 319,079 | 3,083 | 1,171,865 | 7.1% |
| MoE a2a | 2048 | 64 MB | 1,889,201 | 33,864 | 16,368,685 | 21.3% |
| MoE a2a | 2048 | 100 MB | 2,925,156 | 51,874 | 17,640,897 | 15.8% |

All-reduce is essentially congestion-free on both stacks (rtx% ~ 0). MoE is where
both stacks pay, and **the cost explodes with scale**: doubling GPUs raises IB's
pause-time 6.2x (8.3 s -> 51.9 s at 100 MB) and UET's retransmits 4.7x
(3.7 M -> 17.6 M). This is the super-linear term that makes MoE the interesting
workload.

### Why rails help UET's *time* without touching its *loss*

Rail locality does **not** reduce UET's retransmissions -- rail vs flat Rtx differs
by only **0.3% to 2.9%** on every MoE cell, at both scales. Yet at 2048 rails still
cut UET's makespan by up to 16%. So the two effects are decoupled:

- **Loss is unchanged** because it is generated at the **receiving endpoint**
  (each GPU takes traffic from 127 rail peers at once), and no topology change can
  relieve an endpoint bottleneck.
- **Time still improves** because rails cut *spine transit* -- fewer hops, less
  spine contention, shorter RTT -- which speeds up the delivery of the packets that
  are not lost, and shortens the retransmit feedback loop.

That the loss count is flat while makespan moves is the cleanest evidence in the
study that MoE all-to-all is **endpoint-bound, not fabric-bound**. It also explains
why IB (which converts the same endpoint pressure into back-pressure rather than
loss) tracks UET so closely on this workload, and why both stacks degrade together
when the fan-in doubles.

### Caveat on two columns

`slowdown_p50/p99/max` and `fairness_jain` are recorded for all 48 runs but are
**not meaningful here**: both workloads are trigger-staged, so a flow's measured
completion includes the time it spent waiting for its trigger. They measure stage
ordering, not congestion. Makespan, FCT, utilization and the congestion counters
are the valid columns.
