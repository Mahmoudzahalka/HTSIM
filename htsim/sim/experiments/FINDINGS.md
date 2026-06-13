# HTSIM ATLAHS/GOAL Trace Study — Findings

_Generated 2026-06-13; **substantially corrected 2026-06-14** after adding
retransmit/RTT instrumentation (`-rtx_stats`). The earlier "trimming→NACK"
mechanism and "RTO has no effect" finding were WRONG — see §3/§4. Working dir:
`htsim/sim/`. Binary: `datacenter/htsim_uec` (rebuilt this session). All runs:
`-sender_cc_only` unless noted, `-linkspeed 200000` (200 Gbps), `-end 250000` us
with early-kill on workload completion._

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

## 3. Root cause of the duplicate storm (RESOLVED via instrumentation, 2026-06-14)

> ⚠️ An earlier version of this section claimed "queues overflow → trim → NACK →
> retransmit." **That was wrong.** Instrumentation (`-rtx_stats`, see §6) shows
> `trimmed ≈ 0` and `nack ≈ 0` — the network drops essentially nothing. The
> storm is **RTO-timeout-driven**, and three intermediate hypotheses were also
> disproven by the data (head-of-line blocking, cwnd collapse, RTO-too-aggressive).

The actual mechanism, evidenced by the `-rtx_stats` counters on MoE:

1. **It's RTO-driven.** `rto ≈ sent_rtx` (1:1) and `nack ≈ trimmed ≈ 0`. Every
   retransmission is a timeout, not a loss signal — there is no real packet loss.
2. **The RTO is a ceiling that RTT rises to meet.** Measured RTT (`raw_rtt = now -
   send_time`, `uec.cpp:1032`) pins its max right at the RTO: baseline max_rtt ≈
   93.7 µs at RTO 94 µs; with `-min_rto 200`, max_rtt ≈ 199 µs. avg_rtt ≈ 40–60 µs
   in both. **RTT inflates to fill whatever RTO you set.**
3. **Why:** the MoE incast fills queues (~1×BDP ≈ 13 µs/hop); RTT develops a tail
   that reaches the RTO; any packet whose ACK would arrive later is retransmitted
   *at* the RTO. The retransmit (different sprayed path) usually beats the delayed
   original, which then arrives as the duplicate. That is why `rtx_needed` ≈ 99%,
   `rtx_spurious` is tiny, and measured RTT never exceeds the RTO.
4. **The window/queue equilibrium scales with the RTO**, so a bigger RTO just runs
   the network at higher delay with more in-flight data (slower drain) — it can
   never get "above" the RTT. This is why higher RTO is *worse*, not better (§4).

**Disproven en route** (all from `-rtx_stats`, baseline vs `-min_rto 200`):
- NOT head-of-line blocking — peak reorder depth `max_ooo_depth` ≈ 200 in both.
- NOT cwnd collapse — `sends_at_floor` ≈ 0–1% in both.
- NOT trimming/NACK — `trimmed ≈ nack ≈ 0`.

**True root cause:** NSCC (the sender CC) **fails to bound queue depth** — its
delay target `_target_Qdelay ≈ 9.76 µs` is missed by 4–6× (actual queue delay
~30–50 µs), so queues sit near full and RTT rides the RTO ceiling. The lever is
**NSCC's responsiveness to queue delay** (`uec.cpp:1308`, `_gamma`/`_target_Qdelay`),
NOT the retransmit timer. Evidence: `experiments/runs/moe_rtt_{baseline,rto200}.out`.

---

## 4. Fix attempts — every config lever (MoE)

A `-min_rto <us>` CLI flag was added to `main_uec.cpp`. **Bug found & fixed:**
`_min_rto` is unconditionally recomputed from queue size at `main_uec.cpp:720`
*after* arg-parsing, so the flag was silently clobbered — the *first* RTO sweep
(below, "INVALID") was a no-op. Fixed with a `min_rto_user_set` guard around line
720. The valid sweep then showed RTO matters a great deal.

| Lever | Setting | Result vs baseline |
|---|---|---|
| **RTO (invalid)** | `-min_rto` 100/200/400/800 | byte-identical — **flag was clobbered by `main_uec.cpp:720`; ignore** |
| **RTO (valid, after fix)** | `-min_rto` 50/94/200/400 | **RTO matters**: 50→premature stall; 94 (≈default)→completes; **200/400→runaway**. Raising RTO is *worse* (RTT rises to meet it — see §3) |
| **Queue size** | `-queue_size_bdp_factor` 2× | **livelock** (25k+ flows, 6.5M spurious). *Confound:* line 720 ties RTO to queue size, so q=2 also set RTO≈172 µs (runaway zone) — likely an RTO effect, not pure queue |
| **Fast recovery** | `-sleek` | **livelock/regression**: Llama7B 35k/65k by 167 ms; MoE 6× spurious |
| **Load balancing** | `-load_balancing_algo ecmp` | converges but **+75% makespan**, **+54% spurious** |
| **Load balancing** | `-load_balancing_algo reps` / `reps_legacy` | **both runaway** (~12× spurious); MIXED spray is best |
| **CC mode** | `-receiver_cc_only` | **livelock** (~1 s, 1,117 flows, 2.16M spurious) |
| **CC mode** | `-sender_cc -receiver_cc` (both) | converges but **+118% makespan**, **+180% spurious** |
| **Baseline** | sender-only, 1×BDP, mixed, auto-RTO ≈94 µs, no-sleek | **62.5 ms, 278K spurious, clean — best config found** |

Recurring failure signature for the "worse" knobs: flow-completion events explode
(13k–25k vs the clean 3,007), spurious explodes, sim time runs away past `-end`.
Note (per §3) these aren't independent failures — most reduce to the same
RTT-rides-the-RTO / under-damped-NSCC dynamic.

> **Methodology caution learned:** a mid-run check of the "both" mode at 61 ms
> showed 226K spurious and *looked* better than baseline — it was not; the storm
> develops later and it finished at 778K. Judge these runs only at completion.

Result files: `experiments/{rto,qsize,lb,ccmode,reps}_sweep_moe_results.txt`;
raw per-run outputs in `experiments/runs/`.

---

## 5. Conclusion

**No config lever beats the baseline** (sender-only, 1×BDP, MIXED, auto-RTO ≈94 µs,
no-sleek: 62.5 ms, 278K spurious, clean). But — unlike the earlier draft of this
doc — the duplicate rate is **not** an opaque "intrinsic cost." Instrumentation
pinned the mechanism (§3):

- The storm is **RTO-timeout-driven with no real loss** (`trimmed ≈ nack ≈ 0`).
- **RTT rises to meet whatever RTO you set** (max_rtt: 94→94 µs, 200→199 µs), so
  the RTO can never get above the RTT — that's why raising it is *worse*, not
  better, and why the config sweeps all fail the same way.
- The true root cause is **NSCC under-damping**: its queue-delay target
  (`_target_Qdelay ≈ 9.76 µs`) is missed 4–6×, so queues stay near-full and RTT
  rides the RTO ceiling.

The runs are **correct** (all flows delivered, `in_flight = 0`); the duplicates
are wasted work, not wrong results.

**Recommendation:** the fix is **not** an adaptive RTO (an earlier draft said it
was — but since RTT chases the RTO, an adaptive RTO would track the inflated RTT
and behave like the runaway). The lever is **NSCC's responsiveness to queue
delay** — make its multiplicative decrease (`uec.cpp:1308`, `_gamma` /
`_target_Qdelay`) bound the queue so RTT stops riding the RTO. Validate with
`-rtx_stats` watching `avg_rtt`/`max_rtt` and the spurious counters.

---

## 6. Instrumentation added (`-rtx_stats`)

An opt-in diagnostic (additive; zero output unless `-rtx_stats` is passed) that
periodically (~0.5 ms sim) prints a global `[RTXSTATS]` line — periodic so the
timeline survives even when a runaway is killed before completion. It classifies
retransmissions and exposes the dynamics that resolved §3:

- **trigger:** `rto` (timeouts), `nack`, `trimmed` — shows the storm is RTO-driven.
- **outcome:** `rtx_needed` (filled a real gap) vs `rtx_spurious` (receiver already
  had it); `recv_dup`.
- **state:** `sends_at_floor` (cwnd collapsed?), `max_ooo_depth` (head-of-line?),
  and **measured RTT** (`avg_rtt`/`max_rtt`, `rtt>rto%`) — the decisive signal.

Also fixes a latent bug: `_stats.rto_events` was declared but never incremented.
Counters live in `uec.cpp` (file-scope, gated on `UecSrc::_rtx_stats`); flag parsed
in `main_uec.cpp`.

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
bash ../experiments/runs/{rto,qsize,lb,ccmode,reps}_sweep_moe.sh
# mechanism diagnostics (the [RTXSTATS] timeline; baseline vs runaway):
./htsim_uec -goal ../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin \
    -sender_cc_only -rtx_stats -nodes 64 -end 250000 \
    -topo topologies/fat_tree_64_1os.topo -linkspeed 200000 | grep RTXSTATS
#   add `-min_rto 200` to reproduce the runaway (watch max_rtt pin to 200us)
```
