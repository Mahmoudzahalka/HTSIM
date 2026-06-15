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

## 5. Why it's so brittle: the quick_adapt bistability (and 5 failed fixes)

§3 said "NSCC under-damps." Drilling in revealed *why*, and why it can't be tuned
out. NSCC's `quick_adapt` (`uec.cpp:1226`, called first in `updateCwndOnAck_NSCC`)
is a **bang-bang controller**: when it fires it hard-slams `_cwnd =
max(_achieved_bytes, _min_cwnd)`. Both its trigger (`_qa_threshold = 4 ×
_target_Qdelay`) and its evaluation period (`_qa_endtime = now + _base_rtt +
_target_Qdelay`) scale with `_target_Qdelay`.

**The system is bistable at QA's trigger boundary.** The two failure modes map
exactly onto QA:
- QA fires **too eagerly** → cwnd slammed to floor → throughput collapses → **stall**.
- QA fires **too rarely** → cwnd grows → queue fills → RTT rides RTO → **runaway**.

This is why it's chaotically sensitive: a **0.002 µs** change in `-target_q_delay`
(9.758 default vs 9.76 explicit) flips complete↔stall, because it shifts when/whether
QA fires. The default `qa_gate=3` is a **knife-edge sweet spot** — the *only* value
that completes cleanly; `qa_gate` 1/2/5/8 all stall or over-run.

**Five fixes tried, all failed** (each flag-gated, default = stock; originals kept
as comments in `uec.cpp`):

| Fix | Flag | Result |
|---|---|---|
| Lower NSCC delay setpoint | `-target_q_delay 6/3/1.5` | all stall or runaway |
| Re-tune QA trigger | `-qa_gate 1/2/5/8` | only default (3) is stable |
| Smooth the QA cut magnitude | `-qa_smooth <1` | runaway (softer cut = weaker brake) |
| QA trigger refractory | `-qa_cooldown >1` | stall / no benefit |
| Damp fast_increase post-QA | `-qa_inc_cooldown >0` | drags / worse |

So the bistability is **robust to single-knob interventions** on the setpoint,
trigger timing, cut magnitude, and post-fire recovery. A genuine fix needs a
*coupled* control-law redesign (multiple coordinated changes) + ground-truth
validation — not a tweak.

## 6. Conclusion

**No config lever and no single-knob code change beats the stock baseline**
(sender-only, 1×BDP, MIXED, auto-RTO ≈94 µs, no-sleek: 62.5 ms, 278K spurious,
clean). The runs are **correct** (`in_flight = 0`); the duplicates are wasted
work, not wrong results.

The deliverable is the **characterization**, which is a defensible result on its own:
*stock UEC/NSCC is bistable under AI-incast (MoE expert all-to-all); its quick_adapt
bang-bang has a single knife-edge stable point and resists single-parameter fixes.*
That framing turns the whole study into the motivation for a **"more stable NSCC
variant"** — a legitimate CC contribution where the simulator is the testbed and
stock-vs-variant comparison is the accepted methodology (don't claim it models stock
UEC; claim it improves it). The actual fix is **future work**.

**Two things to carry forward:**
1. The `-rtx_stats` diagnostics (§7) make this debuggable for *any* model, not just MoE.
2. A credible CC fix must (a) not regress cases that already work (e.g. Llama7B), and
   (b) show breadth across workloads/scales — not just one trace.

---

## 7. Code added this study (all additive, flag-gated, default = stock)

**`-rtx_stats`** — opt-in diagnostic; periodically (~0.5 ms sim) prints a global
`[RTXSTATS]` line (periodic so the timeline survives an early-killed runaway):
- **trigger:** `rto` (timeouts), `nack`, `trimmed` — shows the storm is RTO-driven.
- **outcome:** `rtx_needed` (filled a real gap) vs `rtx_spurious` (receiver already
  had it); `recv_dup`.
- **state:** `sends_at_floor` (cwnd collapsed?), `max_ooo_depth` (head-of-line?),
  and **measured RTT** (`avg_rtt`/`max_rtt`, `rtt>rto%`) — the decisive signal.

**Bug fixes:** `_stats.rto_events` was declared but never incremented (fixed).
`-min_rto` was silently clobbered by `main_uec.cpp:720` (fixed with a
`min_rto_user_set` guard).

**Experimental knobs** (default values = exact stock behavior; for future CC work):
`-min_rto <us>`, `-qa_smooth <alpha>`, `-qa_cooldown <periods>`,
`-qa_inc_cooldown <periods>` — see §5. All in `uec.{h,cpp}` + `main_uec.cpp`;
originals preserved as comments.

---

## 8. Reference — diagnosing congestion/retransmit problems in ANY model

A model-agnostic playbook (Llama, dense, MoE, any GOAL trace). The numbers above
are MoE-specific; the *method* generalizes. Keep this as a checklist.

### 8.1 Is something actually wrong? (triage)

Healthy run: completes near the expected makespan, `in_flight = 0` for all flows,
flow-completion count ≈ number of messages in the trace. Suspect a pathology if:

- **Sim time runs past `-end`** / never plateaus → *runaway* (congestion collapse).
- **Flow-completion ("finished at") count ≫ messages in the trace** (e.g. 4–8×) →
  retransmit-inflated; the network is doing huge wasted work.
- **`Spurious` log lines flood** (a duplicate-packet at the receiver).
- **Makespan much higher than a back-of-envelope** (bytes ÷ per-host linkspeed).

A *stall* is the opposite of runaway: the flow count plateaus far **below** the
message count and the watcher thinks it's "done." Always sanity-check the final
flow count against the trace — `1,116 of 3,007` is a stall, not a completion.

### 8.2 First move: re-run with `-rtx_stats`

Add `-rtx_stats` and read the periodic `[RTXSTATS]` line. It's the fastest way to
classify the problem. Key fields and what they tell you:

| Field | Meaning | What a high value implies |
|---|---|---|
| `rto` | RTO timeouts fired | retransmission is **timeout-driven** |
| `nack`, `trimmed` | NACKs / trimmed pkts received | retransmission is **loss-driven** (real drops) |
| `rtx_needed` vs `rtx_spurious` | retransmit filled a gap vs receiver already had it | needed≫spurious = retransmit beats a *delayed* (not lost) original |
| `recv_dup` | duplicate pkts at receiver | ≈ the `Spurious` flood |
| `sends_at_floor` | % sends with cwnd at ~1 MTU | **cwnd collapse** |
| `max_ooo_depth` | peak reorder-buffer at any sink | **head-of-line blocking** |
| `avg_rtt` / `max_rtt` / `rtt>rto%` | measured RTT | **`max_rtt` pinned at the RTO ⇒ RTT-rides-RTO** |

### 8.3 Decision tree (which pathology is it?)

1. **`trimmed`/`nack` large** → genuine loss/incast overflow. Bottleneck is buffer
   capacity → look at queue size, ECN thresholds, or oversubscription.
2. **`rto ≈ sent_rtx`, `trimmed ≈ nack ≈ 0`** → no real loss; it's **RTO/timeout
   driven**. Then check RTT:
   - **`max_rtt` pins to the RTO** (and rises if you raise `-min_rto`) → **RTT
     chases the RTO** = the NSCC quick_adapt bistability (§3, §5). Config won't fix
     it; raising the RTO makes it *worse*. This is the MoE case.
   - `max_rtt` well below RTO yet RTO still fires → look at cwnd-blocked / ACK-path
     delay.
3. **`max_ooo_depth` huge** (10⁴–10⁵) → head-of-line blocking: one missing packet
   stalls cumulative ACK. (Was *not* the MoE cause — depth stayed ~200.)
4. **`sends_at_floor` high** → cwnd collapsed to the floor; throughput crawls.
   (Also *not* the MoE cause — stayed ~0–1%.)

### 8.4 Gotchas that bite every run

- **`-end` is a hard cap, not a stop.** The `Clock` reschedules forever, so htsim
  always idle-ticks to `-end` even after the workload finishes. Set `-end` just
  above the expected makespan, or kill on plateau (`experiments/runs/watch_kill.sh`).
- **Judge only at completion.** A mid-run snapshot can look fine and then storm
  later (we saw 226K spurious mid-run finish at 778K). Don't conclude from partials.
- **Chaotic sensitivity near the stability edge.** A ~0.002 µs setpoint change
  flipped complete↔stall. Tiny param/flag differences can flip outcomes — don't
  over-read a single run; confirm the *trend*.
- **Watch for clobbered flags.** `-min_rto` was silently overwritten in setup
  (`main_uec.cpp:720`). If a flag sweep gives *byte-identical* results, the flag
  isn't taking effect — verify it changed the intended value (grep the run header).
- **Kill leftover `htsim_uec` processes** between runs (`pgrep -x htsim_uec`); a
  detached run idle-ticking to `-end` wastes CPU.

### 8.5 Levers, and the honest expectation

For a **terminal-incast** pathology (RTT-rides-RTO / NSCC bistability), nearly every
lever made it *worse* on MoE: `-min_rto↑`, `-queue_size_bdp_factor↑`, `-sleek`,
`-load_balancing_algo ecmp|reps`, `-receiver_cc_only`, `-sender_cc -receiver_cc`,
`-target_q_delay↓`, `-qa_gate≠3`, and the three QA code knobs. **MIXED spray + 1×BDP
+ default RTO/QA is the tuned baseline.** Treat config tuning as unlikely to help an
incast-bound workload; it's the *communication pattern + CC*, not the fabric.

### 8.6 Topology note (why a bigger fat tree won't help incast)

Many-to-one incast (e.g. MoE expert all-to-all, or any reduce/gather) is bound by
the **receiver's last-hop link**, whose capacity a bigger fabric does not increase.
The runs are already on a **1:1 (full-bisection) fat tree** — the most generous
core per node — so extra fabric has nothing to relieve (`trimmed ≈ 0` confirms the
core isn't overflowing). Scale the fabric only when the bottleneck is *core/cross-
sectional* (oversubscribed tree, or permutation/spread traffic). To ease incast,
reduce the **fan-in** (placement, smaller collective groups, in-network reduction)
or fix the CC — not raw fabric size. (Note: htsim rejects running an N-node trace on
a differently-sized `.topo`, so test *scale* with a larger trace, not a bigger tree
under the same workload.)

### 8.7 When it's NOT a bug

A run that **completes with `in_flight = 0`** but a high `Spurious` count is
*correct* — duplicates are wasted work, not wrong results. For comparative topology/
placement studies the baseline is usable as-is; just report the retransmission
overhead as a caveat. Only chase it if you specifically need the absolute makespan
or are proposing a CC improvement.

---

## Appendix — reproduce

```bash
cd htsim/sim/datacenter
# baseline runs (kill when workload completes; see experiments/runs/watch_kill.sh)
./htsim_uec -goal ../experiments/traces/Llama7B_N32_GPU128_PP1_DP128_7B_BS128.bin \
    -sender_cc_only -nodes 128 -end 250000 -topo topologies/fat_tree_128_1os.topo \
    -linkspeed 200000 > out.txt 2>&1
./analyze.sh out.txt
# config sweeps:
bash ../experiments/runs/{rto,qsize,lb,ccmode,reps}_sweep_moe.sh
# NSCC fix-attempt sweeps (all default-stock; see §5):
bash ../experiments/runs/{targetq,qagate,qasmooth,qacooldown,qaic}_sweep_moe.sh
# mechanism diagnostics (the [RTXSTATS] timeline; baseline vs runaway):
./htsim_uec -goal ../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin \
    -sender_cc_only -rtx_stats -nodes 64 -end 250000 \
    -topo topologies/fat_tree_64_1os.topo -linkspeed 200000 | grep RTXSTATS
#   add `-min_rto 200` to reproduce the runaway (watch max_rtt pin to 200us)
```
