#!/usr/bin/env python3
"""Check route_layer0.py's NumPy layer 0 against Hugging Face's Qwen3MoE code.

Builds a 1-layer Qwen3MoeForCausalLM with the real Qwen3-235B-A22B dims, loads the
same layer-0 weights (experts are left tiny/random: they do not affect layer-0
router logits), and compares router logits + top-8 sets on WikiText tokens.
  fp32 reference : should match NumPy to ~1e-4 and agree on ~100% of top-8 sets
  bf16 reference : what a real GPU run would do; reports how many tokens' top-8
                   set differs because of precision alone.
Needs torch + transformers (installed off the system path, see README):
  PYTHONPATH=<pyref> python3 validate_against_hf.py --weights <dir> --tokens 4096
"""
import argparse, os, sys
import numpy as np
import torch
from transformers import Qwen3MoeConfig, Qwen3MoeForCausalLM

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_layer0 import Layer0, wikitext_ids, load_bf16  # noqa: E402


def topk_sets(lg, k):
    return np.sort(np.argpartition(-lg, k - 1, axis=1)[:, :k], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--corpus-dir", required=True, help="where the WikiText parquet lives / is downloaded")
    ap.add_argument("--tokens", type=int, default=4096)
    a = ap.parse_args()
    torch.set_num_threads(os.cpu_count())

    m = Layer0(a.weights)
    ids, _ = wikitext_ids(a.tokens, a.corpus_dir, os.path.join(a.weights, "tokenizer.json"))
    ours = m.router_logits(ids)

    cfg = Qwen3MoeConfig(**{k: v for k, v in m.cfg.items() if k not in ("architectures", "transformers_version", "torch_dtype", "dtype")})
    # experts are irrelevant to layer-0 router logits; 16 keeps them tiny while
    # satisfying torch grouped_mm's 16-byte stride requirement
    cfg.num_hidden_layers, cfg.moe_intermediate_size, cfg.mlp_only_layers = 1, 16, []
    cfg.tie_word_embeddings = False
    cfg._attn_implementation = "eager"
    model = Qwen3MoeForCausalLM(cfg).eval()
    import json
    man = json.load(open(os.path.join(a.weights, "manifest.json")))
    sd = model.state_dict()
    loaded = 0
    for name in man["tensors"]:
        u16 = torch.from_numpy(load_bf16(a.weights, man, name).astype(np.int16))
        t = u16.view(torch.bfloat16)
        assert sd[name].shape == t.shape, (name, sd[name].shape, t.shape)
        sd[name].copy_(t.float()); loaded += 1
    print(f"loaded {loaded} tensors into 1-layer HF Qwen3MoE (transformers)")

    cap = {}
    model.model.layers[0].mlp.gate.register_forward_hook(lambda mod, i, o: cap.__setitem__("o", o))
    res = {}
    for dt in (torch.float32, torch.bfloat16):
        model.to(dt)
        with torch.no_grad():
            model.model(input_ids=torch.from_numpy(ids)[None])
        o = cap["o"]
        o = o[0] if isinstance(o, tuple) else o                # router returns logits (and maybe more)
        if o.shape[-1] != m.E:                                  # some versions return (scores, idx) - fall back to linear
            raise RuntimeError(f"unexpected gate output shape {tuple(o.shape)}")
        res[dt] = o.reshape(-1, m.E).float().numpy()

    for dt, ref in res.items():
        d = np.abs(ref - ours)
        same = (topk_sets(ref, m.K) == topk_sets(ours, m.K)).all(1).mean()
        print(f"{str(dt):15s} max|dlogit| {d.max():.2e}  mean {d.mean():.2e}  "
              f"identical top-{m.K} set: {same * 100:.2f}% of {len(ids)} tokens")


if __name__ == "__main__":
    main()
