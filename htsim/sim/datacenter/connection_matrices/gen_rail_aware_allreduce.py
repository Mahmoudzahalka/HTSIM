#!/usr/bin/env python3
"""Rail-aware (hierarchical) all-reduce connection matrix generator.

This is the collective that rail-optimized + NVLink clusters are actually built
for. It is deliberately structured so that EVERY flow is either
  * intra-server  -> rides the NVLink/NVSwitch domain, or
  * same-rail     -> stays inside one rail (leaf -> leaf), never touching a spine.
Nothing crosses rails, which is exactly why the topology pays off.

Three phases (the standard DGX/NCCL hierarchical all-reduce):
  1. intra-server ring reduce-scatter  (G-1 steps, chunk = S/G)   -- NVLink
  2. rail-local all-reduce on that chunk, via recursive halving
     reduce-scatter + recursive doubling all-gather (2*log2(P) steps) -- rail-local
  3. intra-server ring all-gather      (G-1 steps, chunk = S/G)   -- NVLink

GPU numbering assumed by the rail topology (`Rails G`):
    GPU g  ->  server s = g // G ,  rail r = g % G
so server s owns GPUs [s*G, s*G+G) and rail r owns {g : g % G == r}.

Dependencies are expressed with per-GPU trigger chains: each GPU's flows fire in
order (flow k's completion triggers flow k+1). Different GPUs proceed in
parallel. That captures the per-rank serialisation of a collective without
imposing an artificial global barrier between phases.

Usage:
  gen_rail_aware_allreduce.py <out.cm> <nodes> <gpus_per_server> <size_bytes>
"""
import sys


def build(nodes, G, size):
    if nodes % G:
        sys.exit(f"nodes {nodes} must be a multiple of gpus_per_server {G}")
    P = nodes // G                      # servers, and ranks per rail
    if P & (P - 1):
        sys.exit(f"servers ({P}) must be a power of 2 for recursive halving/doubling")

    chains = {g: [] for g in range(nodes)}   # g -> [(dst, bytes), ...] in order
    chunk = max(size // G, 1)

    # ---- phase 1: intra-server ring reduce-scatter (NVLink) ----
    for _ in range(G - 1):
        for s in range(P):
            for k in range(G):
                chains[s * G + k].append((s * G + (k + 1) % G, chunk))

    # ---- phase 2: rail-local all-reduce (recursive halving / doubling) ----
    # rank inside a rail is the server index; partner = i XOR d keeps r fixed,
    # so every one of these flows stays within rail r.
    d, sz = P // 2, max(chunk // 2, 1)
    while d >= 1:                                    # reduce-scatter
        for r in range(G):
            for i in range(P):
                chains[i * G + r].append(((i ^ d) * G + r, sz))
        d //= 2
        sz = max(sz // 2, 1)
    d, sz = 1, max(chunk // P, 1)
    while d < P:                                     # all-gather
        for r in range(G):
            for i in range(P):
                chains[i * G + r].append(((i ^ d) * G + r, sz))
        d *= 2
        sz = max(sz * 2, 1)

    # ---- phase 3: intra-server ring all-gather (NVLink) ----
    for _ in range(G - 1):
        for s in range(P):
            for k in range(G):
                chains[s * G + k].append((s * G + (k + 1) % G, chunk))

    return chains, P


def emit(path, nodes, G, size):
    chains, P = build(nodes, G, size)
    # Format note: a trigger must be DECLARED on its own line ("trigger id N
    # oneshot") after the flow lines, and the header's "Triggers" counts those
    # declarations. So only emit send_done_trigger where a next flow consumes it
    # (the last flow of each chain triggers nothing).
    lines, fid, tid = [], 0, 0
    for g in range(nodes):
        chain = chains[g]
        prev_trig = None
        for k, (dst, sz) in enumerate(chain):
            fid += 1
            start = "start 0" if prev_trig is None else f"trigger {prev_trig}"
            if k < len(chain) - 1:
                tid += 1
                lines.append(f"{g}->{dst} id {fid} {start} size {sz} send_done_trigger {tid}")
                prev_trig = tid
            else:
                lines.append(f"{g}->{dst} id {fid} {start} size {sz}")
    with open(path, "w") as f:
        f.write(f"Nodes {nodes}\nConnections {fid}\nTriggers {tid}\n")
        f.write("\n".join(lines) + "\n")
        f.write("\n".join(f"trigger id {t} oneshot" for t in range(1, tid + 1)) + "\n")

    # locality self-check: every flow must be intra-server or same-rail
    bad = [(g, d) for g in chains for (d, _) in chains[g]
           if (g // G != d // G) and (g % G != d % G)]
    assert not bad, f"{len(bad)} flows cross rails AND servers, e.g. {bad[:3]}"
    intra = sum(1 for g in chains for (d, _) in chains[g] if g // G == d // G)
    print(f"{path}: {fid} flows, {tid} triggers | {P} servers x {G} GPUs | "
          f"{intra} intra-server (NVLink), {fid - intra} same-rail, 0 cross-spine")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    emit(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
