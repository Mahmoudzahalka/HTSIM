#!/usr/bin/env python3
"""Compute Qwen3-235B-A22B layer-0 MoE routing decisions on CPU (NumPy only).

Reproduces the input to the MoE workload of Ofan (McClure et al., arXiv
2610.07230, Sec. 6.6): "recording the token-to-expert routing decisions of one
layer" -> a 128 x 128 GPU-to-expert token-count matrix. The paper does not say
which layer; we use layer 0 because its router needs no earlier layer.

Layer 0 forward up to the router (Qwen3MoeDecoderLayer):
    x  = embed[ids]
    h  = RMSNorm_in(x)
    q  = RoPE(RMSNorm_q(h Wq^T per head)),  k = RoPE(RMSNorm_k(h Wk^T)),  v = h Wv^T
    x  = x + softmax_causal(q k^T / sqrt(d)) v Wo^T           (GQA: 64 q / 4 kv heads)
    h2 = RMSNorm_post(x)
    router_logits = h2 Wgate^T  ->  softmax  ->  top-8 experts
Everything is computed in float32 (the reference runs in bf16), so a few
near-tied 8th/9th expert choices can differ from a bf16 GPU run.

Token placement: tokens are packed into --seq-len sequences; GPU g owns the
contiguous tokens [g*T, (g+1)*T), i.e. its own data-parallel micro-batch.

Inputs:
  --input text   : WikiText-103 (train) tokenised with the Qwen3 tokenizer
  --input random : uniform random token ids (the paper's "synthetic input tokens")
Outputs (in --out, file stem routing_<input>):
  .npz  experts[N,8] uint8 (sorted by gate prob), probs[N,8] f16 (renormalised
        top-8, norm_topk_prob=True), gpu_expert_counts[G,128] int64
  .json metadata + summary statistics
"""
import argparse, hashlib, json, os, time, urllib.request
import numpy as np

WIKITEXT_REV = "b08601e04326c79dfdd32d625aee71d232d685c3"  # Salesforce/wikitext, pinned 2026-11-16
WIKITEXT_FILE = "wikitext-103-raw-v1/train-00000-of-00002.parquet"


# ----------------------------------------------------------------------------- weights
def load_bf16(wdir, manifest, name):
    t = manifest["tensors"][name]
    raw = np.fromfile(os.path.join(wdir, name + ".bf16"), dtype=np.uint16)
    assert raw.size * 2 == t["nbytes"], name
    return raw.reshape(t["shape"])


def bf16_to_f32(u16):
    return (u16.astype(np.uint32) << 16).view(np.float32)


class Layer0:
    def __init__(self, wdir):
        man = json.load(open(os.path.join(wdir, "manifest.json")))
        cfg = json.load(open(os.path.join(wdir, "config.json")))
        self.cfg = cfg
        self.revision = man["revision"]
        P = "model.layers.0."
        self.embed16 = load_bf16(wdir, man, "model.embed_tokens.weight")  # kept as bf16 (1.2 GB)
        f = lambda n: bf16_to_f32(load_bf16(wdir, man, P + n))
        self.ln_in, self.ln_post = f("input_layernorm.weight"), f("post_attention_layernorm.weight")
        self.Wq, self.Wk, self.Wv = f("self_attn.q_proj.weight"), f("self_attn.k_proj.weight"), f("self_attn.v_proj.weight")
        self.Wo = f("self_attn.o_proj.weight")
        self.qn, self.kn = f("self_attn.q_norm.weight"), f("self_attn.k_norm.weight")
        self.Wg = f("mlp.gate.weight")
        self.H, self.KV = cfg["num_attention_heads"], cfg["num_key_value_heads"]
        self.D = cfg.get("head_dim") or cfg["hidden_size"] // self.H
        self.E, self.K = cfg["num_experts"], cfg["num_experts_per_tok"]
        self.eps, self.theta = cfg["rms_norm_eps"], cfg["rope_theta"]
        assert cfg["decoder_sparse_step"] == 1 and 0 not in cfg["mlp_only_layers"], "layer 0 must be MoE"
        assert self.Wq.shape == (self.H * self.D, cfg["hidden_size"])
        assert self.Wk.shape == (self.KV * self.D, cfg["hidden_size"])
        assert self.Wg.shape == (self.E, cfg["hidden_size"])

    def rms(self, x, w):
        return x / np.sqrt(np.mean(x * x, axis=-1, keepdims=True) + self.eps) * w

    def rope(self, L):
        inv = 1.0 / (self.theta ** (np.arange(0, self.D, 2, dtype=np.float64) / self.D))
        fr = np.arange(L, dtype=np.float64)[:, None] * inv[None, :]
        emb = np.concatenate([fr, fr], axis=-1)
        return np.cos(emb).astype(np.float32), np.sin(emb).astype(np.float32)

    @staticmethod
    def apply_rope(x, cos, sin):  # x [L, heads, D]; HF rotate_half convention
        h = x.shape[-1] // 2
        rot = np.concatenate([-x[..., h:], x[..., :h]], axis=-1)
        return x * cos[:, None, :] + rot * sin[:, None, :]

    def router_logits(self, ids, qchunk=512):
        L = len(ids)
        x = bf16_to_f32(self.embed16[ids])                       # [L, hid]
        h = self.rms(x, self.ln_in)
        q = (h @ self.Wq.T).reshape(L, self.H, self.D)
        k = (h @ self.Wk.T).reshape(L, self.KV, self.D)
        v = (h @ self.Wv.T).reshape(L, self.KV, self.D)
        q, k = self.rms(q, self.qn), self.rms(k, self.kn)
        cos, sin = self.rope(L)
        q, k = self.apply_rope(q, cos, sin), self.apply_rope(k, cos, sin)
        grp, scale = self.H // self.KV, 1.0 / np.sqrt(self.D)
        out = np.empty((L, self.H, self.D), dtype=np.float32)
        for j in range(self.KV):                                  # GQA: heads [j*grp, (j+1)*grp) share kv head j
            qj = np.ascontiguousarray(q[:, j * grp:(j + 1) * grp, :].transpose(1, 0, 2))  # [grp, L, D]
            kj, vj = k[:, j, :], v[:, j, :]
            for s in range(0, L, qchunk):                         # causal: chunk only sees keys < e
                e = min(s + qchunk, L)
                sc = (qj[:, s:e, :] @ kj[:e].T) * scale           # [grp, c, e]
                sc[:, np.arange(e - s)[:, None] < np.arange(e)[None, :] - s] = -np.inf
                sc -= sc.max(axis=-1, keepdims=True)
                np.exp(sc, out=sc)
                sc /= sc.sum(axis=-1, keepdims=True)
                out[s:e, j * grp:(j + 1) * grp, :] = (sc @ vj[:e]).transpose(1, 0, 2)
        x = x + out.reshape(L, self.H * self.D) @ self.Wo.T
        return self.rms(x, self.ln_post) @ self.Wg.T              # [L, E]


# ----------------------------------------------------------------------------- inputs
def wikitext_ids(n_tokens, data_dir, tok_path):
    from tokenizers import Tokenizer
    import pyarrow.parquet as pq
    p = os.path.join(data_dir, os.path.basename(WIKITEXT_FILE))
    if not os.path.exists(p):
        u = f"https://huggingface.co/datasets/Salesforce/wikitext/resolve/{WIKITEXT_REV}/{WIKITEXT_FILE}"
        print(f"downloading {u}")
        urllib.request.urlretrieve(u, p + ".part")
        os.replace(p + ".part", p)
    tok = Tokenizer.from_file(tok_path)
    pf = pq.ParquetFile(p)
    ids = []
    for rg in range(pf.num_row_groups):
        lines = [t for t in pf.read_row_group(rg, columns=["text"]).column("text").to_pylist() if t.strip()]
        for b in range(0, len(lines), 2000):
            for enc in tok.encode_batch(lines[b:b + 2000], add_special_tokens=False):
                ids.extend(enc.ids)
            if len(ids) >= n_tokens:
                return np.asarray(ids[:n_tokens], dtype=np.int64), {"corpus": f"Salesforce/wikitext@{WIKITEXT_REV}/{WIKITEXT_FILE}"}
    raise RuntimeError(f"corpus too small: {len(ids)} < {n_tokens}")


def random_ids(n_tokens, seed, tok_path):
    from tokenizers import Tokenizer
    nv = Tokenizer.from_file(tok_path).get_vocab_size(with_added_tokens=False)  # exclude special tokens
    return np.random.default_rng(seed).integers(0, nv, n_tokens, dtype=np.int64), {"corpus": f"uniform random ids in [0,{nv})", "seed": seed}


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--input", choices=["text", "random"], default="text")
    ap.add_argument("--gpus", type=int, default=128)
    ap.add_argument("--tokens-per-gpu", type=int, default=8192)
    ap.add_argument("--seq-len", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=0, help="only for --input random")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    N = a.gpus * a.tokens_per_gpu
    assert N % a.seq_len == 0, "gpus*tokens_per_gpu must be a multiple of seq_len"

    m = Layer0(a.weights)
    tok_path = os.path.join(a.weights, "tokenizer.json")
    ids, src = wikitext_ids(N, a.out, tok_path) if a.input == "text" else random_ids(N, a.seed, tok_path)
    print(f"{N} tokens ({a.gpus} GPUs x {a.tokens_per_gpu}), {N // a.seq_len} sequences of {a.seq_len}; {src['corpus']}")

    experts = np.empty((N, m.K), dtype=np.uint8)
    probs = np.empty((N, m.K), dtype=np.float16)
    t0 = time.time()
    for i, s in enumerate(range(0, N, a.seq_len)):
        lg = m.router_logits(ids[s:s + a.seq_len])
        top = np.argpartition(-lg, m.K - 1, axis=1)[:, :m.K]
        top = np.take_along_axis(top, np.argsort(-np.take_along_axis(lg, top, 1), axis=1), 1)
        p = np.exp(lg - lg.max(1, keepdims=True)); p /= p.sum(1, keepdims=True)
        pt = np.take_along_axis(p, top, 1)
        experts[s:s + a.seq_len], probs[s:s + a.seq_len] = top, pt / pt.sum(1, keepdims=True)
        el = time.time() - t0
        print(f"  seq {i + 1}/{N // a.seq_len}  {el:.0f}s elapsed, ETA {el / (i + 1) * (N // a.seq_len - i - 1):.0f}s", flush=True)

    gpu = np.repeat(np.arange(a.gpus), a.tokens_per_gpu)
    counts = np.zeros((a.gpus, m.E), dtype=np.int64)
    np.add.at(counts, (np.repeat(gpu, m.K), experts.ravel()), 1)
    load = counts.sum(0)
    stem = os.path.join(a.out, f"routing_{a.input}")
    np.savez_compressed(stem + ".npz", experts=experts, probs=probs, gpu_expert_counts=counts)
    meta = dict(model=f"Qwen/Qwen3-235B-A22B@{m.revision}", layer=0, input=a.input, **src,
                gpus=a.gpus, tokens_per_gpu=a.tokens_per_gpu, seq_len=a.seq_len, top_k=m.K, experts=m.E,
                token_ids_sha256=hashlib.sha256(ids.tobytes()).hexdigest(), runtime_s=round(time.time() - t0, 1),
                expert_load_max_over_mean=float(load.max() / load.mean()),
                expert_load_min_over_mean=float(load.min() / load.mean()),
                expert_load_cv=float(load.std() / load.mean()),
                experts_never_used=int((load == 0).sum()))
    json.dump(meta, open(stem + ".json", "w"), indent=1)
    print(json.dumps({k: meta[k] for k in meta if k.startswith("expert") or k == "runtime_s"}, indent=1))


if __name__ == "__main__":
    main()
