# Modeling GPU clustering (8-GPU servers) in htsim — design notes

_Future-work note. Captured 2026-07-06. Not yet implemented — current focus is the flat "normal" topologies (fat_tree_{128,1024,8192}_{1os,4os,8os}). Come back to this to model the real LLM-training network hierarchy._

## Goal

Real LLM training clusters are **2-level**:
- **Intra-server**: 8 GPUs in one box, fully connected by NVLink/NVSwitch — ultra-fast (~900 GB/s ≈ 7200 Gbps), non-blocking crossbar.
- **Inter-server**: boxes connected by the datacenter fabric (InfiniBand / RoCE / UEC over a fat tree), ~200–400 Gbps per GPU NIC.

We want htsim topologies that reflect this so a "node" isn't a bare endpoint but a GPU inside an 8-GPU NVLink domain. This changes how much collective traffic stays local (fast) vs crosses the fabric (slow/congested).

## What htsim supports (verified in code)

- **Per-tier link speed is configurable**: `_downlink_speeds[tier]` is a per-tier array in `datacenter/fat_tree_topology.cpp`. htsim even derives uplink counts from the *ratio* of adjacent tiers' speeds (`no_of_tor_uplinks = no_of_nodes * downlink_speeds[TOR] / (downlink_speeds[AGG] * oversub[TOR])`). So one tier can be NVLink-fast and the tiers above fabric-speed.
- **Custom per-tier `.topo` format** accepts: `tiers`, `podsize`, and per-tier `radix_down`, `radix_up`, `oversubscribed`, `downlink_speed_gbps`, `downlink_latency_ns`, `switch_latency_ns`, `bundle`.
- **Many topology types compiled in**: `fat_tree`, `oversubscribed_fat_tree`, `multihomed_fat_tree`, `dragonfly`, `slimfly`, `bcube`, `vl2`, `star`, `leaf_spine` (see `datacenter/*topology*.cpp`).
- htsim switches are non-blocking (good stand-in for an NVSwitch crossbar).

## Pattern 1 — NVSwitch-per-server (8 GPUs on one intra-node switch)

The DGX/HGX model. Make **Tier 0 the intra-server NVSwitch**:

```
Nodes 1024                 # 1024 GPUs = 128 servers x 8
Tiers 3
Tier 0  (= the 8-GPU server / NVSwitch)
  Radix_Down 8             # 8 GPUs per leaf = one server
  Downlink_speed_Gbps 7200 # NVLink-class intra-node (~900 GB/s)
Tier 1 / Tier 2  (= datacenter fabric)
  Downlink_speed_Gbps 200  # or 400 — NIC/fabric speed
```

- GPU IDs 0–7 = server 0, 8–15 = server 1, … Intra-server traffic rides the fast Tier-0 switch; cross-server traffic drops to fabric speed.
- **Constraint**: tier speed ratios must divide cleanly — the code asserts integer uplink counts. Pick round ratios (e.g. 7200/200 = 36).

## Pattern 2 — Rail-optimized (each GPU → its own rail)

Common in production: each of the 8 GPUs wires to a *different* leaf/rail switch (GPU i → rail i), so intra-server reduce uses NVLink and inter-server uses 8 parallel rails. Different wiring than "8 under one ToR."
- Use **`multihomed_fat_tree_topology`** (a host connected to multiple switches) as the basis. Needs more investigation of its `.topo`/constructor API.

## Workload side matters as much as topology

Clustering only pays off if the collective is hierarchy-aware (reduce locally over NVLink, then across the fabric):
- **Real GPU traces already encode it**: the Llama/MoE `.bin` ATLAHS traces (now symlinked under `/media/.../Data/htsim_traces/`) were captured from real multi-GPU-per-node runs, so their rank→rank pattern already reflects 8-GPU grouping. **Catch: rank→node mapping** — ranks 0–7 must land on server 0's GPUs. Repo already has "GOAL rank layout detection for HTSIM mapping" (see git history) for this.
- **Synthetic generators can express grouping**: `gen_serialn_alltoall.py` with `groupsize=8` = per-server 8-way all-to-alls; `gen_allreduce.py` has a `locality` parameter.

## Caveats (accuracy)

- **Approximation**: htsim runs its UEC/NSCC transport (trimming/CC) on *every* link, including intra-node — real NVLink doesn't. Fine for fabric-level congestion studies; not for NVLink internals.
- Realism depends on **rank layout** matching the topology, more than on the topology alone.

## Concrete next steps (when we pick this up)

1. Build a proof-of-concept topo: 1024 GPUs = 128 servers × 8, NVLink Tier-0 (7200 Gbps) + 200G fabric, 3-tier. Validate it loads and the uplink-count asserts pass.
2. Run one existing workload (e.g. a2a or ring AR) on it vs the flat `fat_tree_1024` and compare makespan — quantify how much 8-GPU locality helps.
3. For trace-driven runs, confirm the GOAL rank layout maps ranks 0–7 into each server.
4. Explore `multihomed_fat_tree` for rail-optimized as a second variant.

## Key files

- `datacenter/fat_tree_topology.cpp` — per-tier speed/radix/bundle parsing + uplink derivation.
- `datacenter/multihomed_fat_tree_topology.{cpp,h}` — rail-optimized basis.
- `datacenter/experiments/runs/a3_200g/topos_200g/fat_tree_*_*.topo` — current flat topos to diff against.
- `datacenter/connection_matrices/gen_serialn_alltoall.py`, `gen_allreduce.py` — grouping/locality knobs.
