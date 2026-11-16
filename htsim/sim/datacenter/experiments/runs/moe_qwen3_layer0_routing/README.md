# MoE workload from real Qwen3-235B layer-0 routing (Ofan §6.6 reproduction)

Rebuilds the MoE traffic matrix used in **Ofan** (McClure et al., arXiv 2610.07230,
§6.6) without GPUs. The paper ran one Qwen3-235B training iteration on synthetic
tokens and recorded one layer's token→expert routing. Only the **router decisions**
matter for the network, and **layer 0's router depends on nothing but the
embeddings + layer-0 attention**. So we fetch just those 10 tensors (1.39 GB of the
~470 GB model) and run layer 0 on CPU with NumPy.

## Pipeline

| step | script | output |
|---|---|---|
| 1. fetch weights | `fetch_layer0_weights.py` | 10 layer-0 tensors via HTTP Range out of shards 1–2/118 (pinned HF revision, sha256 in `manifest.json`) |
| 2. validate | `validate_against_hf.py` | NumPy layer 0 vs Hugging Face `Qwen3MoeForCausalLM` (1-layer, same weights) |
| 3. route | `route_layer0.py` | `routing_<input>.npz`: top-8 experts per token, 128×128 GPU→expert counts |
| 4. matrices | `make_moe_cm.py` | htsim `.cm` per mapping seed + per-seed `.json` stats |

Heavy data lives on the Data disk, **not** in git:
`/media/mahmoud_murad_allaah/Data/moe_qwen3_layer0_routing/`
(`weights/`, `routing/`, `pyref/` = torch+transformers used only for step 2, `*.log`).

```bash
D=/media/mahmoud_murad_allaah/Data/moe_qwen3_layer0_routing
python3 fetch_layer0_weights.py --out $D/weights
PYTHONPATH=$D/pyref python3 validate_against_hf.py --weights $D/weights --corpus-dir $D --tokens 4096
python3 route_layer0.py --weights $D/weights --out $D/routing --input text     # WikiText-103
python3 route_layer0.py --weights $D/weights --out $D/routing --input random   # uniform random ids
python3 make_moe_cm.py --routing $D/routing/routing_text.npz --out matrices --seeds 1-10
python3 make_moe_cm.py --routing $D/routing/routing_text.npz --out matrices --seeds 1-10 --eplb
```

Only system NumPy (1.21) + `tokenizers` + `pyarrow` (user site) are needed for
steps 1, 3, 4. `pyref/` is an isolated `pip --target` dir (torch 2.14 CPU,
transformers 5.20, plus newer numpy/scipy/pillow that would clash with the system
ones) — only ever used via `PYTHONPATH=` for step 2.

## How the workload maps to the paper

| paper (§6.6) | here |
|---|---|
| Qwen3-235B, 128 experts, top-8 | same model + pinned revision `8efa617…` |
| "one layer" (unspecified) | **layer 0** (the only one computable without the rest of the model) |
| synthetic input tokens | `--input text` (WikiText-103) and `--input random` |
| 128×128 GPU-to-expert matrix | `gpu_expert_counts` in the `.npz`; GPU g owns tokens [g·T,(g+1)·T), T=8192, packed 4096-token sequences |
| one expert per GPU, random map per run | `--seeds` → fresh permutation per seed, one `.cm` each |
| DeepEP hierarchical dispatch over 8-GPU servers | src GPU → same-rank GPU on the remote server; intra-server copies dropped (NVLink) |
| 8,192 B per token copy | `--bytes-per-token 8192` |
| EPLB, 2 expert slots per GPU | `--eplb` (greedy replication + balanced packing) |
| k=8 fat tree, 128 hosts, 64 KB packets | simulator settings, not in the `.cm` |

Not stated in the paper, so exposed as a switch: `--dispatch per-copy` (each remote
token copy crosses the fabric; default) vs `per-node` (one crossing per token per
remote server, DeepEP-style dedup).

## Validation (step 2, 4096 WikiText tokens)

```
torch.float32   max|dlogit| 2.36e-04  mean 1.63e-06  identical top-8 set: 100.00% of 4096 tokens
torch.bfloat16  max|dlogit| 2.10e-01  mean 1.14e-02  identical top-8 set: 97.24% of 4096 tokens
```
The NumPy implementation is exact (fp32). A bf16 GPU run would choose a different
8-set for ~2.8% of tokens (precision noise at the 8th/9th boundary), which does not
matter for the aggregate traffic matrix.

## Results

### Routing (step 3), WikiText input, 1,048,576 tokens (128 GPUs × 8192), 838 s on 8 CPU cores
Expert load (copies per expert): max/mean **5.04**, min/mean 0.0004, CV 0.77, all 128
experts used. Layer-0 routing is very skewed at the *expert* level.

### Matrices (step 4), `matrices/`, 10 mapping seeds each, mean ± std over seeds
Each `.cm` = 128 nodes, 1,920 flows (every GPU → same-rank GPU on each of the 15
other servers), all `start 0`. Per-seed stats + the expert→GPU layout are in the `.json` next to it.

| variant | fabric send/GPU (MB) | NIC recv max/mean | expert recv max/mean |
|---|---|---|---|
| per-copy | 503.4 ± 0.2 | 1.54 ± 0.12 | 5.05 |
| per-copy + EPLB | 503.4 ± 0.1 | 1.10 ± 0.01 | 1.13 |
| per-node | 420.7 ± 7.9 | 1.45 ± 0.10 | 5.05 |
| per-node + EPLB | 409.0 ± 6.5 | 1.13 ± 0.04 | 1.13 |
| **paper** | **~492** | **1.48** (no EPLB) / **1.13** (EPLB) | |

"NIC recv" = bytes arriving at a host over the fat tree (the same-rank receiver
that forwards over NVLink); "expert recv" = remote bytes ending at the GPU that
hosts the expert. The paper's 1.48× only fits the NIC-level number (expert level
is 5×), and our layer-0 skew lands on it. Volume: per-copy gives 503 MB at T=8192;
`--tokens-per-gpu 8008` gives exactly 492 MB without re-running step 3.

## Simulations (step 5): NSCC + REPS, no EPLB, WikiText per-copy, 10 seeds

```bash
END_MS=30 ./run_moe_nscc.sh moe_qwen3l0_text_128g_T8192_per-copy 1 2 3 4 5 6 7 8 9 10
```
`run_moe_nscc.sh` → `htsim_uec -tm <cm> -nodes 128 -topo topos/fat_tree_128_k8_800g_500ns.topo
-sender_cc_only -sender_cc_algo nscc -load_balancing_algo reps -linkspeed 800000 -mtu 65535
-q 12 -ecn 10 10 -seed <s> -end 30`; results in
`$DATA/sims/moe_qwen3l0_text_128g_T8192_per-copy_nscc_reps/s<seed>/{out,summary.json,time.err}`.

| paper (§6, §6.6) | here |
|---|---|
| 3-tier k=8 fat tree, 128 hosts | `topos/fat_tree_128_k8_800g_500ns.topo` (copy of `shared/topos_h100/fat_tree_128_1os.topo`) |
| 800 Gbps, 0.5 µs/link | 800 Gbps, 500 ns on every tier, 0 switch latency |
| 64 KB packets | `-mtu 65535` (**65536 is impossible**, see below) |
| 800 KB/port buffer | `-q 12` → 12 × 65535 B = 786 KB |
| ECN threshold 10 pkts | `-ecn 10 10` (low = high = 655 KB) |
| NSCC | `-sender_cc_only -sender_cc_algo nscc` |

**Gotcha: `-mtu 65536` silently sends nothing.** htsim stores packet sizes in
`uint16_t` (`network.h:186` `Packet::_size`, `uec.h:213-214` `UecSrc::_mss/_mtu`), so
65536 wraps to 0: the run "finishes" in 0.04 s with `New: 0`. 65535 is the max (payload
65471 B with the 64 B UEC header).

### Results
All 10 runs: 1920/1920 flows finished, 64.45–64.54 GB delivered (= the matrix), 0
spurious retransmits, ~12 s wall, ~57 MB RSS each.

| seed | CCT (µs) | lower bound (µs) | increase |
|---|---|---|---|
| 1 | 9011.0 | 8805.0 | 2.3% |
| 2 | 7742.4 | 7470.0 | 3.6% |
| 3 | 7520.5 | 7309.0 | 2.9% |
| 4 | 7670.8 | 7454.9 | 2.9% |
| 5 | 8575.3 | 8364.8 | 2.5% |
| 6 | 8936.2 | 8716.2 | 2.5% |
| 7 | 7432.9 | 7242.0 | 2.6% |
| 8 | 7571.3 | 7363.1 | 2.8% |
| 9 | 7705.3 | 7452.5 | 3.4% |
| 10 | 7517.4 | 7324.3 | 2.6% |
| **mean** | **7968 ± 196 (SEM)** | | **2.8% ± 0.1% (SEM)** |

Lower bound (the paper's "naive lower bound" for non-permutation workloads): the
busiest host's bytes, sent or received, at 800 Gbps incl. header overhead
(×65535/65471), + 3 µs diameter latency. The spread in CCT across seeds is driven by
the expert→GPU placement (it sets which NIC is the incast hot spot); the inflation over
each seed's own bound is tight (2.3–3.6%).

## IB (RoCE + PFC + DCQCN) vs UET, 400 G flat fat tree (not the paper setup)

Same per-copy no-EPLB matrices, run with the **fidelity study's 400 G configuration**
by calling `fidelityRuns/bin/run_one_fidelity.sh` unchanged (`run_ib_vs_uet_400g.sh`):
topology `fidelityRuns/topos/fat_tree_128_1os.topo` (400 G, k=8 shape, 1 µs/hop, no NVLink);
IB = `htsim_roce -strat ecmp_host -paths 128 -queue_type lossless_input -pfc_thresholds 12 15 -q 1000 -dcqcn 8`;
UET = `htsim_uec -sender_cc_only` (default LB/MTU/queues); `-seed` = matrix seed.
Rows (37-col fidelity format) in `ib_vs_uet_400g/<study>/rows/`, table in
`ib_vs_uet_400g/cct_summary.csv` (`compare_ib_vs_uet_400g.py`). All 20 runs `ok`,
1920/1920 flows, no lossless overflow.

| seed | bound (µs) | IB CCT (µs) | IB over bound | UET CCT (µs) | UET over bound | IB/UET |
|---|---|---|---|---|---|---|
| 1 | 17587 | 32884 | 87% | 18102 | 2.9% | 1.82 |
| 2 | 14919 | 27767 | 86% | 15370 | 3.0% | 1.81 |
| 3 | 14598 | 29533 | 102% | 15058 | 3.2% | 1.96 |
| 4 | 14889 | 27065 | 82% | 15371 | 3.2% | 1.76 |
| 5 | 16707 | 29230 | 75% | 17180 | 2.8% | 1.70 |
| 6 | 17409 | 30524 | 75% | 17907 | 2.9% | 1.71 |
| 7 | 14464 | 28354 | 96% | 14932 | 3.2% | 1.90 |
| 8 | 14706 | 27640 | 88% | 15168 | 3.1% | 1.82 |
| 9 | 14885 | 29128 | 96% | 15377 | 3.3% | 1.89 |
| 10 | 14628 | 29423 | 101% | 15070 | 3.0% | 1.95 |
| **mean** | | **29155 ± 530** | **89%** | **15954 ± 397** | **3.1%** | **1.83** |

Bound = busiest NIC's bytes (sent or received) at 400 Gbps, payload only.
UET tracks the bound exactly (corr 1.00); IB adds 75–102% on top (corr 0.75), with
69k–101k PFC pauses per run.
