#!/usr/bin/env python3
"""Turn layer-0 routing decisions into htsim connection matrices (.cm), Ofan-style.

Follows Ofan (arXiv 2610.07230) Sec. 6.6:
  * 128 GPUs = 16 servers x 8 GPUs on a k=8 fat tree (one fat-tree host per GPU).
  * Each run maps the 128 experts to the 128 GPUs with a fresh random permutation
    (one expert per GPU) -> one .cm per seed.
  * DeepEP-style hierarchical dispatch: a token copy for an expert on a REMOTE
    server is sent by the source GPU to its SAME-RANK peer on that server, which
    forwards it over NVLink. Copies for experts on the source's own server never
    touch the fat tree. So the fabric sees at most 15 flows per GPU:
        src g  ->  server(dst)*8 + rank(g)
  * Each token copy carries 8,192 B (hidden 4096 x BF16).
  * Optional --eplb: 2 expert slots per GPU (256 slots); the 128 spare slots
    replicate the most loaded experts (greedy on load/replica, as DeepSeek EPLB),
    then replicas are packed onto GPUs largest-first onto the least-loaded GPU
    that still has a free slot and does not already host that expert. A
    replicated expert's tokens are split round-robin over its replicas.

Open choice the paper does not state (--dispatch):
  per-copy : every remote (token, expert) copy crosses the fabric once (default;
             matches "each token copy carries 8,192 B").
  per-node : a token crosses once per distinct remote server (DeepEP dedups
             copies bound for the same node and fans out over NVLink).

Paper reference numbers (no EPLB): ~492 MB sent per GPU on average, busiest GPU
receives 1.48x the mean (728 MB); with EPLB the skew drops to 1.13x.
"""
import argparse, json, os
import numpy as np

UINT32_MAX = 2 ** 32 - 1


def eplb_layout(load, n_gpus, slots, rng):
    E = len(load)
    rep = np.ones(E, dtype=np.int64)
    for _ in range(n_gpus * slots - E):                      # replicate hottest per-replica load
        rep[np.argmax(load / rep)] += 1
    items = [(load[e] / rep[e], e) for e in range(E) for _ in range(rep[e])]
    items.sort(key=lambda t: -t[0])
    order = rng.permutation(n_gpus)                          # random tie-break among equal GPUs
    gload, gfree = np.zeros(n_gpus), np.full(n_gpus, slots)
    hosts = [[] for _ in range(E)]
    for w, e in items:
        cand = [g for g in order if gfree[g] > 0 and g not in hosts[e]]
        g = min(cand, key=lambda g: gload[g])
        hosts[e].append(g); gload[g] += w; gfree[g] -= 1
    return [np.array(h) for h in hosts]


def build(experts, T_avail, T, G, gps, seed, dispatch, eplb, bpt):
    rng = np.random.default_rng(seed)
    K = experts.shape[1]
    E = int(experts.max()) + 1 if experts.size else 0
    E = max(E, 128)
    # first T tokens of each GPU's block
    idx = (np.arange(G)[:, None] * T_avail + np.arange(T)[None, :]).ravel()
    ex = experts[idx].astype(np.int64)                       # [G*T, K]
    src = np.repeat(np.arange(G), T)                         # source GPU per token
    if eplb:
        load = np.bincount(ex.ravel(), minlength=E).astype(float)
        hosts = eplb_layout(load, G, 2, rng)
        nrep = np.array([len(h) for h in hosts])
        tok = np.arange(len(ex))[:, None]
        pick = tok % nrep[ex]                                # round-robin replica per token
        maxr = nrep.max()
        table = np.full((E, maxr), -1)
        for e, h in enumerate(hosts):
            table[e, :len(h)] = h
        dst = table[ex, pick]                                # [G*T, K] destination GPU
        layout = {int(e): [int(x) for x in h] for e, h in enumerate(hosts)}
    else:
        perm = rng.permutation(G)                            # expert e lives on GPU perm[e]
        dst = perm[ex]
        layout = {int(e): [int(perm[e])] for e in range(E)}

    s_srv, d_srv = src // gps, dst // gps                    # [N], [N,K]
    remote = d_srv != s_srv[:, None]
    # final per-GPU receive (all copies, any path), and remote-only receive
    recv_all = np.bincount(dst.ravel(), minlength=G) * bpt
    recv_remote = np.bincount(dst[remote], minlength=G) * bpt

    if dispatch == "per-copy":
        pairs_src = np.broadcast_to(src[:, None], dst.shape)[remote]
        pairs_srv = d_srv[remote]
    else:  # per-node: unique (token, remote server)
        tok = np.broadcast_to(np.arange(len(src))[:, None], dst.shape)[remote]
        srv = d_srv[remote]
        key = np.unique(tok * (G // gps) + srv)
        tk, pairs_srv = key // (G // gps), key % (G // gps)
        pairs_src = src[tk]
    peer = pairs_srv * gps + pairs_src % gps
    M = np.zeros((G, G), dtype=np.int64)
    np.add.at(M, (pairs_src, peer), bpt)

    # --- NVLink (intra-server) traffic, used only with --nvlink -------------
    # (a) local copies: token on GPU g for an expert on another GPU of g's own server
    # (b) forward hop: the same-rank receiver p on the remote server forwards each
    #     remote copy to the GPU d hosting the expert (p == d needs no transfer).
    # Forwarding is per copy even with --dispatch per-node (DeepEP fans out over
    # NVLink after the deduplicated RDMA). Copies with src == dst are a local
    # memory copy and never reach a network.
    src_b = np.broadcast_to(src[:, None], dst.shape)
    local = ~remote & (src_b != dst)
    fwd_from = (d_srv * gps + src_b % gps)[remote]
    fwd_to = dst[remote]
    fwd = fwd_from != fwd_to
    NV = np.zeros((G, G), dtype=np.int64)
    np.add.at(NV, (src_b[local], dst[local]), bpt)
    np.add.at(NV, (fwd_from[fwd], fwd_to[fwd]), bpt)
    nv_parts = dict(nvlink_local_GB=float(local.sum() * bpt / 1e9),
                    nvlink_forward_GB=float(fwd.sum() * bpt / 1e9))
    return M, recv_all, recv_remote, layout, NV, nv_parts


def stats(M, recv_all, recv_remote):
    send, recv = M.sum(1), M.sum(0)
    r = lambda v: dict(mean_MB=float(v.mean() / 1e6), max_MB=float(v.max() / 1e6),
                       max_over_mean=float(v.max() / v.mean()) if v.mean() else None)
    return dict(flows=int((M > 0).sum()), total_GB=float(M.sum() / 1e9),
                fabric_send_per_gpu=r(send), fabric_recv_per_nic=r(recv),
                expert_recv_remote_per_gpu=r(recv_remote), expert_recv_all_per_gpu=r(recv_all),
                largest_flow_MB=float(M.max() / 1e6))


def write_cm(path, M):
    src, dst = np.nonzero(M)
    assert M.max() <= UINT32_MAX, "flow larger than htsim's uint32 size field"
    with open(path, "w") as f:
        f.write(f"Nodes {M.shape[0]}\nConnections {len(src)}\n")
        for s, d in zip(src, dst):
            f.write(f"{s}->{d} start 0 size {M[s, d]}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--routing", required=True, help="routing_<input>.npz from route_layer0.py")
    ap.add_argument("--out", required=True, help="output directory for .cm + .json")
    ap.add_argument("--seeds", default="1-10", help="mapping seeds, e.g. 1-10 or 3,7")
    ap.add_argument("--tokens-per-gpu", type=int, default=None, help="use the first T tokens of each GPU (default: all)")
    ap.add_argument("--gpus-per-server", type=int, default=8)
    ap.add_argument("--bytes-per-token", type=int, default=8192)
    ap.add_argument("--dispatch", choices=["per-copy", "per-node"], default="per-copy")
    ap.add_argument("--eplb", action="store_true")
    ap.add_argument("--nvlink", action="store_true",
                    help="also emit the intra-server (NVLink) flows instead of dropping them: local copies + "
                         "the same-rank receiver's forward hop; all start at 0 (forwarding is not gated on "
                         "RDMA arrival). Run with -nvlink_topo so htsim puts same-server flows on NVLink.")
    a = ap.parse_args()

    meta = json.load(open(a.routing.replace(".npz", ".json")))
    experts = np.load(a.routing)["experts"]
    G, T_avail = meta["gpus"], meta["tokens_per_gpu"]
    T = a.tokens_per_gpu or T_avail
    assert T <= T_avail and G % a.gpus_per_server == 0
    seeds = [int(x) for p in a.seeds.split(",") for x in
             (range(int(p.split("-")[0]), int(p.split("-")[1]) + 1) if "-" in p else [p])]
    os.makedirs(a.out, exist_ok=True)
    tag = f"moe_qwen3l0_{meta['input']}_{G}g_T{T}_{a.dispatch}{'_eplb' if a.eplb else ''}{'_nvl' if a.nvlink else ''}"
    allstats = []
    for sd in seeds:
        M, ra, rr, layout, NV, nv_parts = build(experts, T_avail, T, G, a.gpus_per_server, sd, a.dispatch, a.eplb, a.bytes_per_token)
        name = f"{tag}_s{sd}"
        # ORIGINAL (fabric-only, kept as the default): write_cm(..., M)
        write_cm(os.path.join(a.out, name + ".cm"), M + NV if a.nvlink else M)
        st = dict(seed=sd, **stats(M, ra, rr))   # fabric stats are unchanged by --nvlink
        if a.nvlink:
            st.update(nvlink_flows=int((NV > 0).sum()), nvlink_total_GB=float(NV.sum() / 1e9),
                      nvlink_send_per_gpu_max_MB=float(NV.sum(1).max() / 1e6),
                      nvlink_recv_per_gpu_max_MB=float(NV.sum(0).max() / 1e6), **nv_parts)
        json.dump(dict(source=meta, tokens_per_gpu=T, dispatch=a.dispatch, eplb=a.eplb,
                       bytes_per_token=a.bytes_per_token, gpus_per_server=a.gpus_per_server,
                       expert_to_gpus=layout, **st), open(os.path.join(a.out, name + ".json"), "w"), indent=1)
        allstats.append(st)
        print(f"{name}: {st['flows']} flows, send/GPU mean {st['fabric_send_per_gpu']['mean_MB']:.0f} MB, "
              f"NIC recv max/mean {st['fabric_recv_per_nic']['max_over_mean']:.2f}, "
              f"expert remote-recv max/mean {st['expert_recv_remote_per_gpu']['max_over_mean']:.2f}"
              + (f" | +{st['nvlink_flows']} NVLink flows, {st['nvlink_total_GB']:.1f} GB "
                 f"(local {st['nvlink_local_GB']:.1f} + fwd {st['nvlink_forward_GB']:.1f})" if a.nvlink else ""))
    agg = lambda k1, k2: (float(np.mean([s[k1][k2] for s in allstats])), float(np.std([s[k1][k2] for s in allstats])))
    print(f"\n{tag} over {len(seeds)} seeds (mean ± std):")
    for k in ("fabric_send_per_gpu", "fabric_recv_per_nic", "expert_recv_remote_per_gpu"):
        m1, s1 = agg(k, "mean_MB"); m2, s2 = agg(k, "max_over_mean")
        print(f"  {k:28s} mean {m1:7.1f} ± {s1:5.1f} MB   max/mean {m2:.3f} ± {s2:.3f}")
    print("  paper (no EPLB): send mean ~492 MB, busiest receiver 1.48x (728 MB); EPLB: 1.13x")


if __name__ == "__main__":
    main()
