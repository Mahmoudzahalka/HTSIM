# A3 Study — UEC Network Metrics on Datacenter Workloads (htsim)

_A packet-level characterization of Ultra Ethernet (UEC/UET) transport behavior across
communication workloads and fabric oversubscription levels, using the htsim reference simulator._

---

## 1. Purpose & context

**Goal:** measure, *faithfully*, how the Ultra Ethernet transport behaves on representative
datacenter / AI-cluster communication patterns — flow completion times, congestion loss, and
how these respond to the network fabric.

**Why htsim:** htsim (the `spcl/HTSIM` tree) is the **reference packet-level simulator used by
the Ultra Ethernet Consortium (UEC) transport working group**. The UEC congestion-control
algorithm **NSCC** has its reference implementation here. No validated UEC model exists on
other simulators (e.g. ns-3 carries RoCE/DCQCN, not UEC), so htsim is the correct tool for a
UEC-fidelity study.

**What this study is (and isn't):** it characterizes UEC behavior under **isolated communication
patterns** driven by static traffic matrices. It is *not* an end-to-end application run — there
is no compute, and no dependency ordering between phases (see §9 Limitations). It answers
"how does UEC behave during pattern X under fabric Y," which is the network-level building block
of real workloads.

---

## 2. Glossary — every term used in this study

### Network / topology terms
- **Fabric / topology** — the physical network structure connecting hosts (switches + links).
- **Fat-tree** — a multi-tier folded-Clos datacenter topology. Hosts attach to leaf (Tier-0)
  switches, which connect up through aggregation (Tier-1) and spine (Tier-2) switches. Standard
  in datacenters and AI clusters.
- **Tier** — a level of the fat-tree (Tier 0 = leaf/ToR nearest hosts; higher = closer to core).
- **Podsize** — number of hosts grouped under a pod (a sub-tree) of the fat-tree.
- **Radix (Radix_Down / Radix_Up)** — a switch's port count facing downward (toward hosts) vs
  upward (toward core). Their ratio sets oversubscription.
- **Oversubscription (1:1 / 4:1 / 8:1, written 1os / 4os / 8os)** — the ratio of host-facing
  bandwidth to core-facing bandwidth at a switch.
  - **1:1 (1os) = full bisection / non-blocking** — the core can carry *any* traffic pattern at
    full host-link speed. Most capable, most expensive.
  - **4:1, 8:1** — the core has 1/4 or 1/8 of the host bandwidth. Cheaper; congests when many
    flows need the core simultaneously (e.g. all-to-all, permutation).
- **Bisection bandwidth** — the bandwidth across a cut that splits the network into two halves.
  Full bisection = no core bottleneck for arbitrary permutations.
- **Link speed** — per-port bandwidth. This study targets **200 Gbps** (UEC / Cray-Slingshot-class).
- **Hop** — one switch-to-switch (or host-to-switch) link traversal on a path.

### Transport / UEC terms
- **UEC / UET** — Ultra Ethernet Consortium / Ultra Ethernet Transport: a modern Ethernet
  transport for AI/HPC, featuring multipath packet **spray**, packet **trimming**, and new
  congestion control.
- **NSCC (Network Signal Congestion Control)** — UEC's sender-based congestion-control algorithm
  (the `-sender_cc_only` mode here). Paces the sender using RTT/queue signals.
- **RCCC (receiver-credit CC)** — UEC's alternative receiver-driven, credit/pull-based CC
  (`-receiver_cc_only`). Not used in this study's main runs.
- **Packet spray (multipath)** — sending a flow's packets across many paths simultaneously to use
  the whole fabric, rather than pinning a flow to one path.
- **Packet trimming** — when a switch queue is congested, instead of dropping a packet it
  **truncates it to just its header** and forwards the header. The receiver learns of the loss
  immediately (even amid reordering) and can request retransmission fast.
- **NACK (negative acknowledgment)** — a receiver/network signal that a packet was lost or
  trimmed; triggers retransmission. **NACK% here = NACKs / packets-sent** — a direct measure of
  in-network congestion loss.
- **ACK (acknowledgment)** — confirmation that data was received.
- **Rtx (retransmissions)** — packets re-sent after loss.
- **RTS (request-to-send)** — a UEC probe/retransmit-timeout-driven control packet. In a healthy
  run with all flows completing, nonzero RTS is just retransmit activity under heavy loss; in a
  stuck flow it can signal a wedge (none observed here — all flows completed).
- **Spurious (spurious duplicate)** — a packet the receiver flags as a duplicate (e.g. arriving
  after its retransmission already did). Logged by htsim; counted here, not stored.

### Measurement terms
- **Flow** — one logical transfer of bytes from a source host to a destination host.
- **FCT (Flow Completion Time)** — the time for a single flow to finish, from its start to the
  delivery of its last byte. The fundamental per-flow performance metric.
- **Makespan** — the **total completion time of the whole workload**: the moment the *last* flow
  finishes. Formally `max(finish_time)` over all flows. (Analogy: in a parallel job, the makespan
  is when the slowest worker finishes — it bounds the whole operation.)
- **p50 / p99 (percentiles)** — the median (p50) and 99th-percentile (p99) of the FCT
  distribution across all flows. **p99 ("tail latency")** captures the slow stragglers, which
  often dominate real performance because a collective can't finish until its slowest flow does.
- **Connection matrix (`.cm` / `.tm`)** — a static text spec of the traffic: `Nodes N`,
  `Connections M`, then lines `src->dst id k size B [start t] [trigger ...]`. Both extensions are
  the same format; htsim loads either with `-tm`.
- **`trigger` / `send_done_trigger`** — dependency hooks in a connection matrix: a flow can be set
  to start only after another completes, encoding (limited) ordering within a collective.

---

## 3. Setup

- **Simulator:** htsim `htsim_uec`, branch **`study/a3-uec-network-metrics`**, branched from
  **stock `main` (64d199c)** — unmodified reference UEC, no congestion-control patches, for a
  defensible "faithful" claim.
- **Engine validation:** ran the bundled `validate_uec_connreuse.txt` suite (`validate.py`) —
  **12/12 PASS**, both NSCC and RCCC, tail-FCT under targets. Confirms the transport reproduces
  its own known-good numbers before any workload runs.
- **Congestion control:** **NSCC** (`-sender_cc_only`).
- **Link speed:** **200 Gbps** (`-linkspeed 200000`).
- **Simulation cap:** `-end 2000` (ms of simulated time; runs finish on workload completion).
- **Fabrics:** fat-tree at **128 / 1024 / 8192** hosts, each at **1os / 4os / 8os**
  oversubscription.

---

## 4. Workloads — what we ran and what each simulates

All are **communication micro-benchmarks**: each isolates one traffic pattern that real
AI/HPC/storage jobs are built from.

| Workload family | Pattern | Real-world scenario it models |
|---|---|---|
| **Permutation** (`perm_*`) | Each host sends to exactly one other (random 1-to-1) | Balanced fabric stress test; data-shuffle phases (MapReduce/Spark, sharded exchange). The textbook test of whether a fabric delivers its bisection bandwidth. |
| **Incast** (`incast_*`, `gen_random/remote_incast`) | Many senders → one receiver | The **gather/reduce phase** of a collective — e.g. AllReduce reduction, parameter-server aggregation; also distributed-storage read storms. The classic datacenter congestion hotspot. |
| **Incast (collateral)** (`incast_collateral_*`) | Incast + background traffic | Incast occurring alongside other tenants'/jobs' traffic (multi-tenant fabric). |
| **Incast (remote vs random)** | Victim/senders forced cross-pod vs random placement | `remote` stresses the **core fabric** (cross-pod), `random` is mixed placement. |
| **All-to-all** (`alltoall_serial_*`) | Every host exchanges with every host | **MoE expert parallelism** (token dispatch/combine); transformer tensor/sequence-parallel exchange; distributed transpose/FFT. (Only small 16-node ran; large `a2a` excluded — malformed file.) |
| **Outcast + incast** (`outcast_incast`) | One→many + many→one | Scatter/broadcast (parameter distribution) combined with gather. |
| **Sanity fixtures** (`bidir`, `one`, `test_cr_*`, `foo2`, `incast_2-1/3-1`) | 1–3 flows | Validation/test cases, not representative load. |

**Swept parameters and their meaning:**
- **flow size** (1 MB → 100 MB) = message / tensor-chunk size.
- **incast degree / concurrency** (2c → 128c) = number of senders converging on the victim
  (collective fan-in).
- **start jitter** (0 µs / 16 µs) = whether senders fire synchronized or staggered.
- **oversubscription** (1os/4os/8os) = the fabric capacity/cost knob (see glossary).
- **tree size** (128/1024/8192) = number of hosts in the fabric.

---

## 5. What we measured, and how

**Metrics captured per run** (one row per workload × fabric):
- **makespan** (µs) — last-flow finish time.
- **FCT distribution** — min, **p50**, **p99**, max (µs).
- **NACKs**, **Rtx**, **RTS**, **ACKs**, **Bounced**, **Pulls** — transport counters.
- **NACK%** = NACKs / packets-sent — the headline loss/congestion metric.
- **spurious** count, **total bytes** transferred, wall-clock run time, completion status.

**How extraction works** (`run_one*.sh`):
1. Run `htsim_uec -tm <matrix> -sender_cc_only -nodes N -topo <fabric> -linkspeed 200000 -end 2000`.
2. Stream htsim's stdout through a filter that **keeps** per-flow `finished at …` lines and the
   final `New: … Rtx: … NACKs: …` summary, **counts but discards** the high-volume `Spurious`
   lines (otherwise they can fill the disk), and keeps any error lines.
3. Compute makespan = max finish time; FCT percentiles from the sorted finish times; transport
   counters parsed token-by-token from the summary line (avoiding the substring trap where
   `ACKs:` matches inside `NACKs:`).
4. Write one CSV row; rows are assembled into `results_combined.csv`.

**Sweep mechanics:** runs were driven in parallel (`xargs -P`), launched detached
(`setsid nohup … & disown`) so they survive SSH disconnects, with per-run timeouts and
concurrency tuned to the box (8 cores, 31 GB RAM, ~3.7 GB disk). Memory-heavy 8192-node
full-bisection runs (~10 GB each) were run at low/serial concurrency to avoid OOM.

---

## 6. The fabric (oversubscription) dimension — and a link-speed correction

The fabric was swept over oversubscription (1os/4os/8os) at each tree size. **During analysis we
discovered the stock `.topo` files hardcode `Downlink_speed_Gbps` and ignore `-linkspeed`:**
128 & 8192 fabrics ran at **100 G**, 1024_1os/4os at **200 G**, 1024_8os at **100 G**, while the
auto-generated topology honored 200 G. This made cross-fabric/cross-scale absolute numbers
inconsistent.

**Resolution:** an initial mixed-speed sweep exposed the inconsistency; it was **discarded** and
re-run cleanly. The retained set, **`a3_200g/`**, uses experiment-local **200 G** copies of all
topo files (stock files untouched), explicit fabrics 1os/4os/8os, and is **294 rows, 0 failures**
— fully comparable across both fabric and tree size. Oversubscription *labels* were verified
correct across tiers (e.g. 128_4os = Tier0 1:1 × Tier1 4:1 = 4:1). (The earlier mixed-speed run
directory was deleted; only the corrected 200 G set is kept.)

---

## 7. Key results (consistent 200 G, `a3_200g/`)

**Permutation @ 8192 — makespan scales linearly with flow size; oversubscription shifts the whole
curve up by a near-constant factor:**

| flow size | 1os | 4os | 8os |
|---|---|---|---|
| 16 MB | 0.8 ms / 0% | 3.0 ms / 2.2% | 5.4 ms / 2.9% |
| 64 MB | 3.1 ms / 0% | 11.9 ms / 0.7% | 21.4 ms / 1.2% |
| 100 MB | 5.0 ms / 0% | 18.2 ms / 0.6% | 33.4 ms / 1.0% |

_(makespan / NACK%.)_ Three findings: (1) **full bisection carries uniform permutation
losslessly** (0% NACK at all sizes); (2) **4os ≈ 3.7×, 8os ≈ 6.7×** the 1os makespan, tracking
reduced core bandwidth; (3) **NACK% falls as flows grow** — the loss is a front-loaded congestion
burst that large flows amortize.

**Tree-size scaling (permutation 2 MB, 128/1024/8192):** makespan is **essentially
scale-invariant** — 1os ≈ 110/111/113 µs across all three sizes. Node count barely matters;
**oversubscription sets the level** (4os ≈ 390–446 µs, 8os ≈ 718–738 µs).

**Incast (~128-way, 2 MB):** makespan ≈ **10.4 ms regardless of tree size or oversubscription**
(only ~6% higher on the 8192 tree from extra hops). Incast is **receiver-bound** — the victim's
edge link (254 MB / 200 Gbps ≈ 10.2 ms) is the bottleneck, so neither core capacity nor scale
changes it. NACK% ≈ 27% (heavy fan-in loss). This is the opposite regime from permutation, where
oversubscription dominated.

---

## 8. Artifacts (file index)

```
experiments/runs/
├── A3_STUDY.md                     ← this document
└── a3_200g/        (CONSISTENT 200G — the kept, trustworthy run)
    ├── results_combined.csv        294 rows (workload × fabric)
    ├── results_wide_200g.csv       spreadsheet pivot
    ├── a3_report_200g.md           human-readable report
    ├── analyze_200g.py             report generator
    ├── plot_results.py             plotting (matplotlib)
    ├── plots/                      9 PNGs (size / fan-in / oversub / tree-size sweeps)
    ├── topos_200g/                 200G topo copies (stock files untouched)
    ├── run_one_200g.sh / sweep_200g.sh   sweep drivers
    └── logs/ , rows/               per-run filtered logs + CSV row files
```
_(An earlier mixed-speed run and an initial single-fabric sweep were removed; only the corrected
200 G set is retained.)_

**Reproduce:** rebuild on the branch, then re-run `sweep_200g.sh`; regenerate report/plots with
`analyze_200g.py` and `plot_results.py`.

---

## 9. Limitations & caveats

- **Static load, no application timeline.** Connection matrices specify *who sends what to whom*,
  but not the **compute phases** or **dependency ordering** of a real job. So results describe how
  UEC behaves during each *isolated pattern*, not the real arrival timing/overlap of a full
  training step. (The `trigger` mechanism gives only limited intra-collective ordering.)
- **No makespan-of-an-application.** Because there's no compute DAG, these makespans are
  per-pattern, not per-iteration of a real workload. End-to-end iteration time would require the
  trace-driven (GOAL) path.
- **All-to-all under-represented** — only the 16-node serial case ran; the large `a2a` matrix was
  excluded (malformed). MoE/all-to-all studies would need a regenerated matrix.
- **Cross-tree comparisons are sparse** — only **permutation 2 MB** spans all three tree sizes
  cleanly; a `~128-way incast 2 MB` 2-point (128 vs 8192) comparison exists but with differing
  victim placement. The 1024-node scale has few matrices.
- **Link-speed inconsistency in the stock topo files** — see §6; this is why the kept `a3_200g/`
  set uses local 200 G topo copies. (The earlier mixed-speed run was discarded for this reason.)

---

## 10. Possible next steps

- Generate **matched matrices** (same flow size + fan-in across 128/1024/8192) for proper
  cross-tree scaling of incast and all-to-all (generators: `gen_incast.py`,
  `gen_serial_alltoall.py`, `gen_allreduce.py`).
- Add the missing **AllReduce** collective (the real data-parallel training pattern).
- Move to the **makespan / application path** (replay a small GOAL trace) to turn per-pattern
  metrics into end-to-end iteration time.
- Sweep additional axes: **RCCC** (receiver-credit CC) vs NSCC; buffer sizing; link speed.
