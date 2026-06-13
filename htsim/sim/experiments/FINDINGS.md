# HTSIM ATLAHS/GOAL Trace Study — Findings

_Generated 2026-06-13. Working dir: `htsim/sim/`. Binary: `datacenter/htsim_uec`
(rebuilt this session). All runs: `-sender_cc_only` unless noted, `-linkspeed
200000` (200 Gbps), `-end 250000` us with early-kill on workload completion._

---

## 1. Trace runs on Fat Tree

Three ATLAHS GOAL traces from `experiments/traces/`. All use the **unique-nic**
rank mapping (HTSIM nodes = ranks × 4 NICs), so node counts are:

| Trace | ranks×NIC | Nodes | Topology |
|---|---|---|---|
| `Llama7B_N32_GPU128_PP1_DP128_7B_BS128` | 32×4 | 128 | `fat_tree_128_1os.topo` |
| `MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32` | 16×4 | 64 | `fat_tree_64_1os.topo` * |
| `Llama13B_N16_GPU64_TP4_PP2_DP8_VPP5_BS32` | 16×4 | 64 | `fat_tree_64_1os.topo` * (NOT RUN) |

\* htsim cannot auto-generate a 2- or 3-tier fat tree for 64 nodes, and it rejects
a node/topology size mismatch (can't run 64 nodes on the 128-node `.topo`). So a
**`fat_tree_64_1os.topo`** was created (4 pods × 16 hosts, 16 cores; same pod
structure as the 128 file with core down-radix = 4). Validated: 64 nodes, clean.

### Completed run metrics

| Metric | Llama7B (128n) | MoE8x8B (64n) |
|---|---|---|
| Makespan | **90.227 ms** | **62.486 ms** |
| Per-iteration (÷2, see note) | ≈45.1 ms | ≈31.2 ms |
| Flows (messages) completed | 65,424 | 3,007 |
| in_flight clean (all 0) | yes | yes |
| Total bytes | 11.89 GiB | 2.56 GiB |
| FCT min / mean / max (ms) | 8.15 / 50.97 / 90.23 | 8.63 / 42.31 / 62.49 |
| FCT p50 / p90 / p99 (ms) | 48.16 / 74.87 / 88.11 | 42.41 / 58.04 / 61.77 |
| Packets sent (logical) | 3,172,543 | 684,984 |
| Spurious (dup) log lines | 1,101,042 | 278,160 |

> **Note (trace semantics):** ATLAHS Llama/MoE GOAL traces capture **2 recorded
> iterations** (after 5 discarded warm-up iters), not a full run. Divide makespan
> by 2 for per-iteration time; an N-iteration run ≈ N × (makespan/2).

Raw outputs: `experiments/runs/llama7b_ft128.out`, `moe8x8b_ft64.out`.
Per-run summaries via `datacenter/analyze.sh <outfile>`.

`Llama13B` was deliberately not run (user paused it); it is ready to run on the
new `fat_tree_64_1os.topo`.

---

## 2. The "Spurious" metric — what it means

Each `Spurious <epsn>` line = **one duplicate data packet at a receiver** — a
packet whose sequence number the receiver already has (`uec.cpp:2739`,
`pkt.epsn() < _expected_epsn || _epsn_rx_bitmap[pkt.epsn()]`). The receiver counts
it (`_stats.duplicates`) and immediately ACKs. It is **retransmission waste**, not
a correctness error — every run still completes with `in_flight = 0`.

For Llama7B that is ~1.1M duplicates against ~3.17M logical packets ≈ **35%
duplicate overhead**. High, but the runs are correct.

Two caveats:
- It is a **packet** count (scales with total packets), so normalize before
  comparing traces. MoE's *rate* of trouble is far worse than Llama7B's despite a
  lower absolute count.
- The per-flow debug guard at `uec.cpp:2747`/`2750` is commented out, so the line
  prints for **every** duplicate of every flow (log flood). The real signal is the
  `_stats.duplicates` count, not the line spam.

**Label correction:** the per-flow `RTS <n>` field is `_stats.rts_pkts_sent` =
**Request-To-Send control packets**, NOT "retransmit-on-timeout." `analyze.sh` was
fixed accordingly.

---

## 3. Root cause of the duplicate storm

Retransmissions here are driven by **NACKs from packet trimming**, not by the RTO
timer:

- Queues are sized to **1×BDP with trimming ON**; ECN on; default load balancing
  is **MIXED** (packet spray).
- Under incast, queues overflow → packets **trimmed** → **NACK** to sender →
  retransmit (`processNack` `uec.cpp:1559` → `queueForRtx` `1633`). Spray reorders,
  so a retransmit + a late original both arrive → duplicate.
- The RTO (`_rtx_timeout = send_time + _min_rto`, fixed 100 µs, `uec.cpp:2038`) is
  a backstop that rarely fires; the adaptive `_rtt/_mdev/_rto` fields exist but are
  **never assigned** (no Jacobson/Karels).

---

## 4. Fix attempts — every config lever (MoE)

A `-min_rto <us>` CLI flag was added to `main_uec.cpp` (additive, wires the
existing `UecSrc::setMinRTO`; no effect unless passed) to enable sweeping.

| Lever | Setting | Result vs baseline |
|---|---|---|
| **RTO** | `-min_rto` 100/200/400/800 µs | **byte-identical** — no effect (RTO isn't the cause) |
| **Queue size** | `-queue_size_bdp_factor` 2× | **livelock**: 25k+ flows, 6.5M spurious (~24×), sim ran away past 250 ms, never converged. 4×/8× not attempted |
| **Fast recovery** | `-sleek` | **livelock/regression**: Llama7B 35k/65k flows by 167 ms; MoE 6× spurious, ran past cap |
| **Load balancing** | `-load_balancing_algo ecmp` | converges but **+75% makespan** (109.6 ms), **+54% spurious** (427K) |
| **CC mode** | `-receiver_cc_only` | **livelock** (aborted ~1 s, 1,117 flows, 2.16M spurious) |
| **CC mode** | `-sender_cc -receiver_cc` (both) | converges but **+118% makespan** (136.3 ms), **+180% spurious** (778K) |
| **Baseline** | sender-only, 1×BDP, mixed, 100 µs, no-sleek | **62.5 ms, 278K spurious, clean — OPTIMUM** |

Recurring failure signature for the "worse" knobs: flow-completion events explode
(13k–25k vs the clean 3,007), spurious explodes, sim time runs away past `-end`.

> **Methodology caution learned:** a mid-run check of the "both" mode at 61 ms
> showed 226K spurious and *looked* better than baseline — it was not; the storm
> develops later and it finished at 778K. Judge these runs only at completion.

Result files: `experiments/{rto,qsize,lb,ccmode}_sweep_moe_results.txt`;
raw per-run outputs in `experiments/runs/`.

---

## 5. Conclusion

Across **five independent lever families**, nothing beats the sender-only /
1×BDP / MIXED / 100 µs-RTO / no-sleek baseline. The duplicate (Spurious) rate is
**intrinsic** to this aggressive trim + spray + retransmit transport under MoE
incast — the designed cost of recovering from incast loss, **not** a tunable
misconfiguration. The CC + ECN thresholds are tightly coupled to the 1×BDP queue
assumption; perturbing queue size / recovery / CC mode destabilizes it.

The runs are **correct** (all flows delivered, `in_flight = 0`); the duplicates are
wasted work, not wrong results.

**Recommendation:** keep the sender-only baseline as the operating config and
report the duplicate count as an intrinsic property. A genuine reduction would
require **protocol code changes** to the loss-recovery path (`uec.cpp`) — e.g. a
true adaptive RTO coupled with selective retransmit, and tighter SACK/NACK gap
tracking to suppress retransmitting in-flight packets — validated against ground
truth, which is a separate engineering effort from configuration sweeps.

---

## Appendix — reproduce

```bash
cd htsim/sim/datacenter
# baseline runs (kill when workload completes; see experiments/runs/watch_kill.sh)
./htsim_uec -goal ../experiments/traces/Llama7B_N32_GPU128_PP1_DP128_7B_BS128.bin \
    -sender_cc_only -nodes 128 -end 250000 -topo topologies/fat_tree_128_1os.topo \
    -linkspeed 200000 > out.txt 2>&1
./analyze.sh out.txt
# sweeps:
bash ../experiments/runs/{rto,qsize,lb,ccmode}_sweep_moe.sh
```
