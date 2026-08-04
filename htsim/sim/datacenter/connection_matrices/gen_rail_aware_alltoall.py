#!/usr/bin/env python3
"""Rail-aware (hierarchical) all-to-all — the MoE dispatch/combine pattern.

All-to-all is the defining collective of Mixture-of-Experts models. On a
rail-optimized cluster it is decomposed so that NO flow ever crosses a rail:

  phase 1 (NVLink, intra-server): GPU (s,g) hands its server-mate at rail
      position r everything destined for rail r. 7 sends.
  phase 2 (rail-local): GPU (s,r) now holds ALL of server s's traffic for rail r,
      so it ships to GPU (s',r) exactly that server's share. 127 sends, and every
      one stays inside rail r.

After phase 2 each GPU holds all data addressed to it, so no third phase is
needed. Volume-for-locality trade: ~1.87x the bytes of a direct all-to-all, but
0.875*S of it rides NVLink and the rest is leaf-local instead of crossing spines.

`size` is the TOTAL bytes each GPU dispatches (per-GPU volume, not per-pair --
per-pair would be 1023*size at this scale and is infeasible). Per destination is
size/nodes, so:
    phase 1 flow = (nodes/G) * size/nodes = size/G
    phase 2 flow = G * size/nodes

Sends are chained per GPU, which is physically right: a GPU has one NVLink egress
and one rail NIC, so its sends within a phase serialise on that port anyway.

Usage:
  gen_rail_aware_alltoall.py <out.cm> <nodes> <gpus_per_server> <total_bytes_per_gpu>
"""
import sys


def build(nodes, G, size):
    if nodes % G:
        sys.exit(f"nodes {nodes} must be a multiple of gpus_per_server {G}")
    P = nodes // G                       # servers, and GPUs per rail
    per_dst = max(size // nodes, 1)
    chains = {g: [] for g in range(nodes)}

    # ---- phase 1: NVLink shuffle, group by destination rail ----
    # everything destined for rail r goes to the server-mate sitting on rail r
    sz1 = max(per_dst * P, 1)            # P destinations live on each rail
    for s in range(P):
        for g in range(G):
            for r in range(G):
                if r == g:
                    continue             # own rail's share stays put
                chains[s * G + g].append((s * G + r, sz1))

    # ---- phase 2: rail-local all-to-all ----
    # GPU (s,r) holds server s's traffic for rail r; ship each server its share.
    sz2 = max(per_dst * G, 1)            # G sources per server
    for r in range(G):
        for s in range(P):
            for s2 in range(P):
                if s2 == s:
                    continue
                chains[s * G + r].append((s2 * G + r, sz2))

    return chains, P


def emit(path, nodes, G, size):
    chains, P = build(nodes, G, size)
    lines, fid, tid = [], 0, 0
    for g in range(nodes):
        chain = chains[g]
        prev = None
        for k, (dst, sz) in enumerate(chain):
            fid += 1
            start = "start 0" if prev is None else f"trigger {prev}"
            if k < len(chain) - 1:
                tid += 1
                lines.append(f"{g}->{dst} id {fid} {start} size {sz} send_done_trigger {tid}")
                prev = tid
            else:
                lines.append(f"{g}->{dst} id {fid} {start} size {sz}")
    with open(path, "w") as f:
        f.write(f"Nodes {nodes}\nConnections {fid}\nTriggers {tid}\n")
        f.write("\n".join(lines) + "\n")
        f.write("\n".join(f"trigger id {t} oneshot" for t in range(1, tid + 1)) + "\n")

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
