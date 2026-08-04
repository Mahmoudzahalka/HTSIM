# Rail-optimized topology — design, simulator interactions, validation

Status: **COMPLETE — rail topology + NVLink plane implemented and validated on both stacks;
24-run sweep finished 24/24 ok (see §8 for results).**

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
3. **Rail-optimization is an IB optimization; UET barely notices it.** With NVLink,
   rails buy IB ~12% (1139 vs 1297) but buy UET nothing at all (357 vs 356 — flat is
   marginally faster, i.e. noise). Rails are a *locality* optimization: they put
   communicating peers on one leaf to avoid the spine. IB pins each flow to a single
   path, so locality matters to it. UET sprays across all paths and has spare
   bandwidth on a non-blocking fabric, so it is largely indifferent to whether
   traffic is leaf-local or crosses the spine.

Implication for the sweeps: **keep the flat control** — "rails help IB but not UET"
is only demonstrable by running both topologies on both stacks.

## 8. Rail sweep results (24 runs, 24/24 ok)

`results_rail.csv` (33 cols) + `utilization_rail.csv`. 2 rail-aware workloads x
{16,64,100} MB x {rail, flat control} x {IB, UET}, NVLink on throughout.

### Makespan: rail vs flat control

| workload | size | IB rail vs flat | UET rail vs flat |
|---|---|---|---|
| all-reduce | 16 / 64 / 100 MB | **-12% / -15% / -21%** | 0% / -5% / +9% |
| MoE a2a | 16 / 64 / 100 MB | **-33% / -16% / -7%** | -3% / -8% / -5% |

**Rails help IB on every single run (-7% to -33%); UET is flat (+9%..-8%, i.e. noise).**
Note the size trend is NOT consistent: the benefit grows with size for all-reduce but
*shrinks* for MoE, so "rails help more for bigger messages" is not supported.

### IB vs UET on the rail fabric

| workload | 16 MB | 64 MB | 100 MB |
|---|---|---|---|
| all-reduce | 3.19x | 3.87x | 3.42x |
| MoE a2a | 1.06x | **1.00x** | **0.89x** |

On all-reduce UET keeps its usual ~3-4x lead. **On MoE all-to-all the two stacks
converge completely -- and at 100 MB IB is 11% FASTER.** This is the sharpest
reversal we have seen anywhere in the study.

### Congestion cost (rail topology)

| workload | size | IB pauses | IB pause (ms) | UET Rtx |
|---|---|---|---|---|
| all-reduce | 100 MB | 11,118 | 44 | 25,069 |
| MoE a2a | 16 MB | 173,597 | 1,693 | 766,293 |
| MoE a2a | 64 MB | 896,004 | 9,729 | 3,834,662 |
| MoE a2a | 100 MB | 993,134 | 8,338 | 3,729,592 |

### Why rails do nothing for UET

Rail locality does **not** reduce UET's retransmissions (rail vs flat Rtx differs by
0-14%, mostly ~0%). So UET's dominant cost is untouched by locality -- which is
exactly why the topology change buys it nothing.

The likely mechanism: MoE all-to-all makes every GPU receive from its 127 rail peers,
so the bottleneck is **receiver-side incast at the endpoint**, not congestion in the
fabric. Locality cannot help an endpoint bottleneck, and neither can spray -- which
also explains why the two stacks converge on MoE, and why IB's losslessness edges
ahead at the largest size (it is the regime where UET's retransmissions are pure
overhead). Endpoint-bound, not fabric-bound.
