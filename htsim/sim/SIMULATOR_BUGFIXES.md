# Simulator bug fixes

This document lists the bugs we found and fixed in the htsim network simulator. For each one it gives the location, the original code, the fix, why it is a bug, and whether it changes simulation results.

**Base version.** Our fork starts at commit `64d199c` (SPCL/ATLAHS, 2026-05-12). Its RoCE/DCQCN code (`roce.cpp`, `dcqcn.cpp`, `main_roce.cpp`, `network.cpp`) is byte-identical to the public [`ultraethernet/uet-htsim`](https://github.com/ultraethernet/uet-htsim). So the bugs below are in the original simulator, not in the ATLAHS additions.

**Conventions in the code.**
- Every fix is tagged `BUGFIX(#n)` in the source. The numbers in this document are the same tags, so `grep -n "BUGFIX(#5)"` finds the fix.
- The original line is kept as a comment next to the fix, so any fix can be reverted by hand.
- Line numbers refer to branch `MoEWorkloads` as of 2026-11-19.

**Sections**
1. [RoCE transport](#1-roce-transport-rocecpp-roceh): `roce.cpp`, `roce.h`
2. [Lossless switch and queues (PFC)](#2-lossless-switch-and-queues-pfc-switchcpp-queue_lossless_inputcpph): `switch.cpp`, `queue_lossless_input.cpp/.h`
3. [Queue logger](#3-queue-logger-loggerscpp): `loggers.cpp`
4. [Fat-tree topology](#4-fat-tree-topology-datacenterfat_tree_topologycpp): `datacenter/fat_tree_topology.cpp`, switch-radix asserts only for now
5. DCQCN: *to be added*

Sections 2–4 contain changes that have no `BUGFIX(#n)` tag in the code. They are listed by name, with the commit that introduced them.

---

## 1. RoCE transport (`roce.cpp`, `roce.h`)

### Background: packets vs. bytes

Most RoCE bugs come from mixing two units in `RoceSrc`:

| Variable | Unit | Evidence |
|---|---|---|
| `_highest_sent` | **packets** | incremented once per packet: `_highest_sent ++;` ([roce.cpp:326](roce.cpp#L326)); also the on-wire sequence number: `newpkt(..., _highest_sent+1, ...)` |
| `_last_acked` | **packets** | set from the sink's cumulative ACK, which counts packets |
| `_flow_size` | **bytes** | set straight from the connection-matrix `size` field |
| `_mss` | bytes per packet | `Packet::data_packet_size()`, 4000 B by default in `main_roce` |

Comparing `_highest_sent` or `_last_acked` with `_flow_size` therefore needs `* _mss`. We kept `_highest_sent` and `_last_acked` as packet counts and added `* _mss` where they meet a byte quantity. Switching them to bytes would also have meant changing the sink, ACKs, NACKs and go-back-N.

All sites where these variables meet `_flow_size`:

| Location | Expression | Status |
|---|---|---|
| [roce.cpp:159](roce.cpp#L159) `processNack` restart | `_highest_sent * _mss >= _flow_size && _last_acked * _mss < _flow_size` | **fixed, #12** |
| `receivePacket` stop-time | `_flow_size = _highest_sent * _mss + _mss` | original already correct |
| [roce.cpp:301](roce.cpp#L301) `send_packet` guard | `_last_acked * _mss >= _flow_size \|\| _highest_sent * _mss > _flow_size` | original, in bytes but off by one (`>`); see #5 |
| `send_packet` last-packet flag | `(_highest_sent + 1) * _mss >= _flow_size` | original already correct |
| [roce.cpp:365](roce.cpp#L365) `doNextEvent` stop | `_highest_sent * _mss >= _flow_size` | **fixed, #5** |

### Summary

| # | Bug | Changes results? |
|---|---|---|
| [#5](#5-the-source-never-stops-ticking) | Source never stops ticking after its last packet; one extra packet past the end of the flow | Runtime; one extra packet per flow removed |
| [#6](#6-packets-arriving-after-completion-are-leaked) | Packets arriving after the flow finished are leaked | No (memory only) |
| [#10](#10-unconditional-pause-and-resume-log-spam) | Ungated `PAUSE` / `RESUME` prints | No (output only) |
| [#11](#11-pause-packets-arriving-before-the-flow-starts-are-leaked) | Pause packets arriving before the flow started are leaked | No (memory only) |
| [#12](#12-tail-loss-recovery-guard-never-fires) | `processNack` restart guard never fires (latent since #5) | No for our runs; a stuck flow on lossy setups |

---

### #5 The source never stops ticking

**Where:** `RoceSrc::doNextEvent()`. Two changes:
- an early return at [roce.cpp:345](roce.cpp#L345)
- a units fix at [roce.cpp:365](roce.cpp#L365)

**Original**
```cpp
void RoceSrc::doNextEvent() {
    ...
    if (_flow_size && _highest_sent >= _flow_size) {   // packets >= bytes
        return;                                        // stop sending
    }
    ...send if pacing allows...
    eventlist().sourceIsPending(*this, next_send);     // reschedule self
}
```

**Fix**
```cpp
    if (_done)                                          // new: finished -> stop
        return;
    ...
    //if (_flow_size && _highest_sent >= _flow_size) {   // original, kept
    if (_flow_size && _highest_sent * _mss >= _flow_size) {
```

**Why it is a bug.** The stop check compares packets to bytes. A 100 MB flow is 25,000 packets against 100,000,000 bytes, so the check never fires. After its last packet, every source keeps rescheduling itself once per packet-spacing interval for the rest of the simulation, even after `_done` is set. This has two consequences:

1. **The event list never empties.** A run cannot end on its own. It only stops at `-end` or when the external watchdog sends SIGTERM, and each finished flow keeps generating events, which made runs far slower.
2. **One extra packet past the end of the flow.** The send guard in `send_packet()` ([roce.cpp:301](roce.cpp#L301)) is off by one: `_highest_sent * _mss > _flow_size` uses `>`, not `>=`. When the flow size is an exact multiple of the MTU, the tick right after the last packet N passes that guard and sends packet N+1. The sink accepts it because it arrives in order. All our 16/64/100 MB matrices are exact multiples of 4000 B (e.g. 100,000,000 % 4000 = 0).

**Effect of the fix.** Finished sources stop, so runs end on their own as soon as the last flow finishes. The extra packet per flow is gone: that is a difference from upstream htsim of one packet per flow, about 0.016% of a 100 MB flow. All our published IB numbers were produced with this fix in place.

**Note.** The code comment at [roce.cpp:362](roce.cpp#L362) says the new check "matches the correct check in `send_packet()`". It doesn't quite: `send_packet()` uses `>` and the new check uses `>=`. The new check is the correct one, and once it is in place the off-by-one in `send_packet()` can no longer be reached.

**Side effect.** Fix #5 made another original guard matter; see #12.

---

### #6 Packets arriving after completion are leaked

**Where:** two places, one per source class (`DCQCNSrc` overrides `receivePacket` and does not call the RoCE version):
- [roce.cpp:268](roce.cpp#L268), `RoceSrc::receivePacket`
- [dcqcn.cpp:188](dcqcn.cpp#L188), `DCQCNSrc::receivePacket`

**Original → fix**
```cpp
if (_done)                 if (_done) {
    return;                    pkt.free();
                               return;
                           }
```

**What "finished" means.** `processAck` sets `_done = true` ([roce.cpp:224](roce.cpp#L224)) when the ACK covering the last packet arrives (`ackno * _mss >= _flow_size`). This is only a flag. The source object stays alive and stays connected to the network:
- it is still the destination of its reverse route (ACKs, NACKs, CNPs);
- it is still in its host queue's sender list. Nothing ever removes it, and there is no `removeHostSender` in the code.

So any packet still addressed to it is delivered and reaches the `if (_done)` line.

**How a packet reaches a finished source**

1. **PFC pause/resume broadcast.** This is the main path, in both RoCE and DCQCN runs.
   - When a switch ingress port crosses its PFC threshold, `LosslessInputQueue::sendPause()` ([queue_lossless_input.cpp:117](queue_lossless_input.cpp#L117)) sends a pause up the wire to the host's NIC queue.
   - The host queue then creates a **new pause packet for every registered sender** ([queue.cpp:286-291](queue.cpp#L286-L291)):
     ```cpp
     // inside HostQueue::receivePacket(Packet& pkt), pkt = the ORIGINAL pause from the switch
     for (uint32_t i = 0;i<_senders.size();i++){
         EthPausePacket* e = EthPausePacket::newpkt(p->sleepTime(),p->senderID());  // new copy per sender
         _senders[i]->receivePacket(*e);    // hand copy e to sender i
     }
     pkt.free();                            // host queue frees the ORIGINAL itself
     ```
   - Finished flows are never removed from `_senders`, so every pause and every resume on that host delivers a copy to each finished flow. A 128-node incast produces about 40,000 pause episodes.
2. **A CNP right after the final ACK (DCQCN only).** `DCQCNSink::receivePacket` first calls `RoceSink::receivePacket`, which sends the ACK. Only after that does it send a CNP, if the packet was ECN-marked. There are two cases:
   - If the last data packet was marked, the CNP follows the final ACK on the same reverse path and arrives just after the flow became done.
   - The sink's CNP timer can also send a CNP up to 50 µs later if marked packets have accumulated.
3. **The ACK for the extra packet** (original code only). Before #5, flows whose size is an exact multiple of the MTU sent an extra packet whose ACK arrived after `_done`. Fix #5 removed this path.

NACKs after completion would also be possible on a lossy fabric. Our runs never produce NACKs; see #12.

**What `pkt` is, and why freeing it is correct.** For a pause, `pkt` is **this flow's own copy `e`** from the loop above. It is not the switch's original pause, which the host queue frees itself.
- **Ownership passes to the receiver.** After `_senders[i]->receivePacket(*e)` returns, the host queue never touches `e` again and keeps no pointer to it. If the source doesn't free it, nobody does.
- **It is the rule the original code already follows** for a live flow: the `case ETH_PAUSE:` branch does `processPause(...); pkt.free();`. Fix #6 applies the same rule when the flow is done.
- **It returns to the right pool.** `pkt` is declared as `Packet&`, but `Packet::free()` is `virtual` ([network.h:79](network.h#L79)). The call therefore reaches `EthPausePacket::free()` ([eth_pause_packet.h](eth_pause_packet.h)), which puts the packet back on the pause pool's free list for the next `newpkt` to reuse.

**Why it is a bug.** htsim packets come from per-type pools. Without the free, each of these packets stays allocated for the rest of the run, and the pool allocates new ones with `new` instead of reusing them. Memory grows with (pause events × finished flows on the host).

**Effect of the fix.** Memory only. The original code already returned without processing the packet; we only free it. A finished flow ignores pauses and CNPs either way, so the simulated network is identical.

---

### #10 Unconditional PAUSE and RESUME log spam

**Where:**
- `RoceSrc::doNextEvent` paused branch, [roce.cpp:357](roce.cpp#L357)
- `RoceSrc::processPause`, [roce.cpp:243](roce.cpp#L243)

**Original → fix**
```cpp
// doNextEvent, while paused:
cout << "PAUSE" << endl;                    // removed (commented out)

// processPause, on resume:
cout << "Source " << str() << " RESUME " ...;   // now only if (_log_me)
```

**Why it is a bug.** Both prints were unconditional. All other per-event debug output in `RoceSrc` is gated on `_log_me`. On a 128-node incast they produced 209,000 lines of stdout, slowing runs and filling disks. The `PAUSE` line is also redundant: the gated `"Src ... paused"` line just above it already reports the same thing.

**Effect of the fix.** Output only. None of our log-parsing patterns match these lines.

---

### #11 Pause packets arriving before the flow starts are leaked

This is the same leak as #6, at the other end of a flow's life. #6 frees packets that arrive **after** a flow finished; #11 frees packets that arrive **before** it started.

**Where:** two places, one per source class:
- [roce.cpp:251](roce.cpp#L251), `RoceSrc::receivePacket`
- [dcqcn.cpp:171](dcqcn.cpp#L171), `DCQCNSrc::receivePacket`

**Original → fix**
```cpp
if (!_flow_started){                  if (!_flow_started){
    assert(pkt.type()==ETH_PAUSE);        assert(pkt.type()==ETH_PAUSE);
    return;                               pkt.free();
}                                         return;
                                      }
```

**What "not yet started" means.** `_flow_started` is false from construction until `startflow()` runs. A flow starts in one of two ways:
- **Scheduled start:** `connect()` queues the source for its matrix start time. At that time `doNextEvent()` sees `!_flow_started` and calls `startflow()` ([roce.cpp:335](roce.cpp#L335)).
- **Triggered start** (`TRIGGER_START`): nothing is scheduled. The flow waits until another flow's end trigger calls `activate()` → `startflow()` ([roce.h:62](roce.h#L62)). This is how dependent workloads, such as the steps of a ring allreduce, are chained.

**Registration with the host queue does not wait for the start.** `main_roce` calls `addHostSender(roceSrc)` for every connection during setup, at time 0 ([datacenter/main_roce.cpp:799](datacenter/main_roce.cpp#L799)). So from the first event on, every flow is in its host's sender list, including flows that will not start until much later.

**Which packet arrives, and what `pkt` is.** It is the same broadcast loop as in #6 ([queue.cpp:286-291](queue.cpp#L286-L291)). On every pause or resume, the host queue creates a new `EthPausePacket` copy for every registered sender, started or not, and `pkt` is **this flow's own copy `e`**. The host queue frees the switch's original pause itself and never touches `e` again, so the source owns it. `free()` is virtual, so the copy goes back to the pause pool.

The `assert(pkt.type()==ETH_PAUSE)` records why pauses are the only packets that can arrive here: a flow that has not started has sent no data, so there can be no ACK, NACK or CNP for it.

**Why it is a bug.** Each pause or resume on a host leaked one packet **per not-yet-started flow on that host**, so memory grows with (pause events × waiting flows). This is worst for:
- **Ring allreduce:** every step is trigger-started by the previous one, so most of a host's flows sit registered but not started for most of the run.
- **`-qps K`:** each flow becomes K registered sources, so each broadcast creates K times more copies.

Together these leaked about 1.8 MB per flow and ran the 128-node ring at `-qps 4` out of memory.

**Effect of the fix.** Memory only. The original code already ignored the pause, and we still ignore it; we only free it.

**Original behaviour we kept.** Because a not-yet-started flow ignores pauses, a flow that starts *during* a pause begins in `READY` state. It then paces packets into its host queue until the next pause or resume reaches it. Nothing is lost: the host queue is itself paused and has no drop path, so those packets just wait. A flow that was already running would have held off instead. This is a small modeling quirk of the original simulator, unchanged by our fix.

---

### #12 Tail-loss recovery guard never fires

**Where:** `RoceSrc::processNack`, [roce.cpp:159](roce.cpp#L159).

**Original → fix**
```cpp
//if (_flow_size && _highest_sent>=_flow_size && _last_acked < _flow_size){          // original, kept
if (_flow_size && _highest_sent * _mss >= _flow_size && _last_acked * _mss < _flow_size){
    eventlist().sourceIsPendingRel(*this,0);   // restart the source
}
```

**Background: how RoCE recovers from loss in this model.** RoCE here is go-back-N with **no retransmit timer**: `_rto` is computed but nothing ever fires on it. Recovery works like this:
1. The sink sees a sequence gap and sends a NACK.
2. `processNack` resets `_highest_sent = _last_acked`.
3. The source, if it is still ticking, resends from that point on its next tick.

**Why it is a bug.** The restart guard compares packets to bytes, the same mistake as #5, so it never fires.
- **Before fix #5** this did not matter, because the source ticked forever and always picked up the reset.
- **After fix #5** the source stops after its last packet. If a packet in the final window is lost, the NACK arrives at a source that is no longer ticking, the guard fails to restart it, and no timer will ever resend. The flow never finishes.

So #12 is a latent bug that fix #5 exposed. The fix uses the same byte-based stop condition as `doNextEvent()`.

**Effect on our results: none.** A NACK needs a dropped or reordered packet, and our runs produce neither:
- Every IB run uses `-queue_type lossless_input`, which never drops. All 127 IB logs report `OVERFLOW_COUNT 0`.
- `-strat ecmp_host` pins each flow (and each QP) to a single path, so packets arrive in order, and no run used `-ooo`.
- Every IB result row is `status=ok` with all flows finished: rail 48/48, parity 18/18, perm/incast/a2a 99/99, fidelity 660/660, and the MoE runs. The run harness marks a run `incomplete` whenever finished flows < connections, so a stuck flow would have shown up.

The fix matters for anyone running the code on a lossy configuration.

---

### Other RoCE change (not a bug fix): multi-QP hook

`roce.h` gains `bool _qp_member` ([roce.h:123](roce.h#L123), default `false`). When a source is one QP of a flow split by `main_roce -qps K`, its completion prints `QP … done at` instead of `Flow … finished at` ([roce.cpp:220](roce.cpp#L220)). The `RoceQpGroup` in `main_roce` then prints the single per-flow `finished at` line, so the watchdog and `flow_metrics.py` still count one line per connection. With K=1 the behaviour is unchanged.

### Verification

We ran two IB workloads on the binary before and after #12: a 128-node random permutation and a 128-node random incast, 16 MB each. Setup: `topos_h100/fat_tree_128_4os.topo`, 400 Gb/s, `lossless_input`, PFC 12/15, `-q 1000`, `-dcqcn 8`, `-strat ecmp_host`, seed 1. Results:
- the same flows finished in both: 128/128 and 127/127;
- identical PFC counters (incast: 39,512 pauses);
- byte-identical `.bin` logs;
- stdout differs only in the output-file name.

### Known limitations of the original RoCE model (not changed)

- **No retransmit timer.** The model is only valid on a lossless fabric (PFC). This is how we use it.
- **Lossy queues trim instead of drop.** `main_roce`'s only lossy queue types (`composite`, `composite_ecn`) trim packets to a header, and there is no flag to disable trimming. `RoceSink` ignores the header-only flag (`_is_header`), so a trimmed RoCE packet is counted as delivered. RoCE results are therefore only meaningful with `lossless` / `lossless_input`.
- **"total bytes" in the finish line is a packet count.** The `Flow … finished at T total bytes N` line prints the cumulative ACK, i.e. packets. Our analysis scripts multiply by the MTU (`flow_metrics.py`), and 4000 B matches `main_roce`'s default.
- **A flow that starts during a pause begins `READY`.** See the note under #11.

---

## 2. Lossless switch and queues (PFC) (`switch.cpp`, `queue_lossless_input.cpp/.h`)

### Background: htsim's two PFC models

Both lossless modes exist in the original simulator. We added neither one: `main_roce` already accepts `-queue_type lossless` and `-queue_type lossless_input`, and the queue classes are in `ultraethernet/uet-htsim`. `queue_lossless.cpp/.h` and `queue_lossless_output.cpp/.h` are unchanged. In `queue_lossless_input.cpp/.h` we only added the counters in §2.2.

| `-queue_type` | Queue at each switch port | Who decides to pause | Used in our runs? |
|---|---|---|---|
| `lossless` | `LosslessQueue` (output side) | the output queue, via `Switch::sendPause` to all other ports | no |
| `lossless_input` | `LosslessOutputQueue`, plus a `LosslessInputQueue` on every ingress link | the ingress accounting queue | **yes, every IB run** |

How `lossless_input` works:
- **Where the input queues are.** Every switch ingress link gets a `LosslessInputQueue`: host→ToR ([datacenter/fat_tree_topology.cpp:923](datacenter/fat_tree_topology.cpp#L923)), ToR↔agg and agg↔core. Hosts have no input queue, so they never pause anyone.
- **What it counts.** The input queue holds no packets. It only counts the bytes that arrived on that ingress and have not yet left the switch: `receivePacket` adds a packet's size, and `completedService` subtracts it when the output port finishes sending it.
- **When it pauses.** Above the high threshold (`-pfc_thresholds 12 15` → 15 × 4000 B = 60 KB) it sends PAUSE upstream. Below the low threshold (48 KB) it sends RESUME.

---

### 2.1 `Switch::configureLossless()` calls `setSwitch` twice (crash)

**Where:** [switch.cpp:34](switch.cpp#L34) (the redundant call is commented out at [line 41](switch.cpp#L41)). Commit `9e0c609`.

**Original → fix**
```cpp
void Switch::configureLossless(){             void Switch::configureLossless(){
    for (each port q of this switch) {            for (each port q of this switch) {
        q->setSwitch(this);                           // q->setSwitch(this);   (commented out)
        q->initThresholds();                          q->initThresholds();
    }                                             }
}                                             }
```

**Why it is a bug.**
- Every port is added with `Switch::addPort()`, which already calls `q->setSwitch(this)` ([switch.cpp:14](switch.cpp#L14)).
- `setSwitch` refuses to run twice: `{assert(!_switch); _switch = s;}` ([queue.h:40](queue.h#L40)). So the second call in `configureLossless()` always fails the assert.
- Our build keeps asserts on (`CMakeLists.txt` deliberately avoids `-DNDEBUG`), so any run that reached this function **aborted while building the topology**.

**When it is reached.** Only with `-queue_type lossless`. The fat tree calls `configureLossless()` only when `_qt == LOSSLESS` ([datacenter/fat_tree_topology.cpp:1124](datacenter/fat_tree_topology.cpp#L1124)). In other words, the original `lossless` mode could not run at all in this version of the simulator.

**The fix.** Comment out the redundant call. The switch is already set, and the call's real purpose, `initThresholds()`, still runs.

**Effect on results: none.** All IB runs use `lossless_input`, which never calls this function. The fix only makes the other original PFC mode usable; we never used it.

---

### 2.2 PFC instrumentation (new counters, no behaviour change)

**Where:** [queue_lossless_input.cpp](queue_lossless_input.cpp) and [queue_lossless_input.h](queue_lossless_input.h), commit `720a41d`. The values are printed once at the end of `main_roce` ([datacenter/main_roce.cpp:910](datacenter/main_roce.cpp#L910)):
```
PFC_PAUSES <n> PFC_PAUSE_US <t> MAX_QUEUE_BYTES <b>
```

**What was added**

| Member | Kind | Updated at | Meaning |
|---|---|---|---|
| `_total_pauses` | `static` | READY→PAUSED transition ([line 81](queue_lossless_input.cpp#L81)) | number of pause **episodes**. Each episode is one PAUSE and one RESUME frame from the switch; the host's fan-out to its senders (RoCE #6/#11) is not counted |
| `_total_pause_time` | `static` | PAUSED→READY transition ([line 112](queue_lossless_input.cpp#L112)) | sum of all episode lengths, over all ports |
| `_max_occupancy` | `static` | every arrival ([line 73](queue_lossless_input.cpp#L73)) | largest ingress byte count seen on any port |
| `_pause_start` | **per-object** | READY→PAUSED transition ([line 80](queue_lossless_input.cpp#L80)) | when *this* port entered PAUSED |

**How "summed over all ports" works.** A `static` member is **one variable shared by every `LosslessInputQueue` object**. There are no per-port counters to add up afterwards. Each port adds its own episode length into the shared total when the episode ends:
```cpp
_total_pause_time += eventlist().now() - _pause_start;   // this port's episode length
```
At the end of the run that variable already holds the sum over every ingress port. The scripts take the printed value as-is: the runners read the single `PFC_PAUSE_US` line into the `pfc_pause_us` column, and the figure and number scripts only convert units (`/1e6`) and average over seeds. Nothing adds per-port values together again, so there is no double counting.

`_pause_start` must be per-object, and it is ([queue_lossless_input.h:52](queue_lossless_input.h#L52)). If it were static, ports with overlapping pause episodes would overwrite each other's start time.

**Port-seconds.** Overlapping pauses all count: 10 ports paused during the same 1 ms add 10 ms. So the total can exceed the run's duration. This is why the paper reports it in port-seconds ("cumulative PFC pause time summed over all ports").

**Correctness checks**
- **No behaviour change.** The counters only read and write their own new variables. The before/after regression run (§1, Verification) produced byte-identical logs.
- **`_pause_start` is never read uninitialised.** It is not set in the constructor, but it is only read in the PAUSED state, and the only place that enters PAUSED also sets it.
- **Open episodes are not counted.** An episode still open when the run stops is not added to the total. At a natural drain every queue empties, so every episode has closed. When the watchdog sends SIGTERM, all flows have already finished, so at most a few in-flight ACKs remain and no episode is open.
- **The peak occupancy is plausible.** Our runs peak at about 0.167 MB, roughly 42 packets, against a pause threshold of 15 packets. The overshoot is the data already in flight while the PAUSE travels upstream, i.e. PFC headroom.
- **What "never exceeded its buffer" is checked against.** The paper's claim relies on the `LOSSLESS not working!` message (`OVERFLOW_COUNT`). That message fires above two limits:
  - the output queue's `-q 1000` packets (4 MB);
  - the input queue's fixed 2000 packets (8 MB). This limit is hard-coded at [line 17](queue_lossless_input.cpp#L17) and does not depend on `-q`.

  Both are far above 0.17 MB.

**⚠️ Caveat: rail/NVLink runs also count NVLink-plane pauses.**
- With `-nvlink_topo`, `main_roce` builds a second topology with the same `lossless_input` queue type ([datacenter/main_roce.cpp:535](datacenter/main_roce.cpp#L535)). Its switches get `LosslessInputQueue`s too.
- Because the counters are global, `PFC_PAUSES`, `PFC_PAUSE_US` and `MAX_QUEUE_BYTES` then add up **both the fabric and the NVLink plane**.
- **Fat-tree results** (1os/4os/8os) have no NVLink plane, so their numbers are fabric-only.
- **Rail and flat-placement results** use the NVLink plane, so their PFC figures include any back-pressure inside NVLink servers. Real NVLink uses credit-based flow control, not PFC.

**Status: open.** The size of the NVLink share has not been measured. Either split the counters per plane and rerun a few rail cells, or state in the paper that the metric covers both planes.

---

## 3. Queue logger (`loggers.cpp`)

### 3.1 `CUM_TRAFFIC` values printed as integers

**Where:** `QueueLoggerSampling::event_to_str`, [loggers.cpp:308](loggers.cpp#L308). Commit `66e66cb`.

**Original → fix**
```cpp
// ORIGINAL
ss << " Ev CUM_TRAFFIC CumArr " << (int)event._val1
   << " CumIdle " << (int)event._val2 << " CumDrop " << (int)event._val3;
// FIX: the same line without the (int) casts
ss << " Ev CUM_TRAFFIC CumArr " << event._val1
   << " CumIdle " << event._val2 << " CumDrop " << event._val3;
```

**Why it is a bug.** The sampling queue logger accumulates three `double`s in **seconds of link time** ([loggers.cpp:216-266](loggers.cpp#L216-L266)):
- `_cumarr`: for every arriving packet, its transmit time at the link's speed, i.e. how long the link must be busy to send it;
- `_cumidle`: time the queue sat empty;
- `_cumdrop`: transmit time of dropped packets.

For a run lasting a few milliseconds, these are values like 0.0031. The binary `.bin` log stores the doubles correctly. But `parse_output -ascii` turns records into text through exactly this function ([parse_output.cpp:265](parse_output.cpp#L265)), and `(int)0.0031` is `0`, so every value below one second printed as 0.

The other records in the same function (`QUEUE_RANGE`, `OVERFLOW`) carry byte counts, so their `(int)` casts are fine. This record copied the same pattern for values that are not integers.

**Effect on results: all our utilization numbers depend on this fix.**
- `extract_util.py` computes per-link utilization as `CumArr / makespan` from exactly this text. Without the fix, every link reads 0% utilization.
- The fix landed on 2026-07-05, before any sweep that recorded utilization. So every utilization number in the paper was produced with it.
- The same logger serves both stacks, so UET utilization depends on it too.

**Original quirk kept.** The record is labelled `Type QUEUE_APPROX` although it is a `QUEUE_RECORD`. Our parser matches on that label, so we left it unchanged.

---

## 4. Fat-tree topology (`datacenter/fat_tree_topology.cpp`)

*Only the switch-radix asserts so far. The rail-optimized wiring and degraded-link options will be added later.*

### 4.1 Switch-radix sanity asserts raised from `< 128` to `< 1024`

**Where:** [datacenter/fat_tree_topology.cpp:1001-1002](datacenter/fat_tree_topology.cpp#L1001-L1002). Commit `4e1194e`.

**What the assert checks.** `Switch::addPort()` adds a queue to the switch's port list and returns its **index**, i.e. the number of ports the switch had before ([switch.cpp:12](switch.cpp#L12)):
```cpp
int Switch::addPort(BaseQueue* q){
    _ports.push_back(q);
    q->setSwitch(this);
    return _ports.size()-1;
}
```
The fat tree wraps each call in an assert on that index, so each assert caps the **switch's radix** (port count):

| Line | Switch | Ports being added | Original cap | Now |
|---|---|---|---|---|
| [919](datacenter/fat_tree_topology.cpp#L919) | ToR / leaf | host-facing downlinks | `< 96` | unchanged |
| [1001](datacenter/fat_tree_topology.cpp#L1001) | ToR / leaf | uplinks to tier 1 | `< 128` | **`< 1024`** |
| [1002](datacenter/fat_tree_topology.cpp#L1002) | Agg / spine | downlinks to leaves | `< 128` | **`< 1024`** |
| [1087-1088](datacenter/fat_tree_topology.cpp#L1087-L1088) | Agg ↔ core | tier-2 links | `< 64` | unchanged |

**It is only a sanity cap.**
- Ports live in a growable `vector<BaseQueue*> _ports` ([switch.h:66](switch.h#L66)), and `getPort()` is bounds-checked.
- Routing works on `Route*` FIB entries.
- Nothing in the switch or routing uses a fixed-size array or a small integer type for port numbers.

So the 128 never protected memory. It roughly reflects real switch radixes (64–128 ports) and catches badly sized topologies.

**Why we raised it: the NVLink plane at 2048 GPUs.** The NVLink plane is a 2-tier tree with **one leaf per server** (`Radix_Down 8` = 8 GPUs, `Radix_Up 1`). In a 2-tier leaf-spine every spine connects to every leaf, so a spine's radix equals the number of leaves:

| Topology | Leaves | Spine radix | Under `< 128`? |
|---|---|---|---|
| `nvlink_1024gpu_8pergpu.topo` | 1024/8 = 128 | 128 → largest index 127 | just passes |
| `nvlink_2048gpu_8pergpu.topo` | 2048/8 = 256 | 256 → largest index 255 | **fails: abort while building the topology** |

Asserts are compiled in. So without this change, every 2048-GPU rail or flat run with NVLink would have crashed before simulating anything, and the paper's 2048-GPU rail results depend on it. All other topologies stay far below the old cap; the largest, the flat/rail 2048 fabric, has a 64-port spine.

**A 256-port "spine" is not a modeling claim.** That spine tier exists only because htsim's fat tree needs at least two tiers. It carries **no traffic**: only same-server flows attach to the NVLink plane, and their source and destination hang off the same leaf. We are not modeling a 256-port NVSwitch.

**Effect on results: none for any topology that ran before.** A topology that passed `< 128` also passes `< 1024`, and the assert does not affect how the network is built.

---

## 5. DCQCN

*To be added.*
