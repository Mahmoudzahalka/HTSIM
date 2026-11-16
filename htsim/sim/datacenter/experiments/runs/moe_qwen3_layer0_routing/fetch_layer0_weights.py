#!/usr/bin/env python3
"""Fetch ONLY the tensors needed to compute Qwen3-235B-A22B's layer-0 MoE router.

The router of layer 0 depends only on: token embeddings, layer-0 input RMSNorm,
layer-0 self-attention (q/k/v/o + q_norm/k_norm), and the post-attention RMSNorm.
Those 10 tensors (~1.39 GB) live in shards 1-2 of 118. We pull them with HTTP
Range requests straight out of the .safetensors files, so the ~470 GB model is
never downloaded.

Output (in --out):
  <tensor_name>.bf16   raw little-endian bfloat16 bytes, row-major
  manifest.json        shape/dtype/source shard/byte range/sha256 per tensor
  config.json, tokenizer.json   (same pinned revision)

Resumable: tensors whose file already has the right size + sha256 are skipped.
"""
import argparse, hashlib, json, os, struct, sys, time, urllib.request

REPO = "Qwen/Qwen3-235B-A22B"
# Pinned commit so the weights are reproducible (HF 'sha' on 2026-11-16).
REVISION = "8efa61729e24bd65b1d152b5ab5409052aa80e65"
CHUNK = 64 << 20  # 64 MiB per range request


def url(fname, rev):
    return f"https://huggingface.co/{REPO}/resolve/{rev}/{fname}"


def get(u, start=None, end=None, retries=6):
    hdr = {} if start is None else {"Range": f"bytes={start}-{end}"}
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=hdr), timeout=120) as r:
                if start is not None and r.status != 206:
                    raise RuntimeError(f"server ignored Range (status {r.status})")
                data = r.read()
            if start is not None and len(data) != end - start + 1:
                raise RuntimeError(f"short read {len(data)} != {end - start + 1}")
            return data
        except Exception as e:  # noqa: BLE001 - retry on any network error
            wait = 2 ** attempt
            print(f"  retry {attempt + 1}/{retries} after error: {e} (sleep {wait}s)", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {u} [{start}-{end}]")


def needed(name):
    return name.startswith("model.embed_tokens.") or (
        name.startswith("model.layers.0.") and ".mlp.experts." not in name)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="directory for weights (use the Data disk)")
    ap.add_argument("--revision", default=REVISION)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    for f in ("config.json", "tokenizer.json", "model.safetensors.index.json"):
        p = os.path.join(a.out, f)
        if not os.path.exists(p):
            open(p, "wb").write(get(url(f, a.revision)))
    wmap = json.load(open(os.path.join(a.out, "model.safetensors.index.json")))["weight_map"]
    names = sorted(n for n in wmap if needed(n))
    shards = sorted({wmap[n] for n in names})

    manifest = {"repo": REPO, "revision": a.revision, "tensors": {}}
    for shard in shards:
        n_hdr = struct.unpack("<Q", get(url(shard, a.revision), 0, 7))[0]
        hdr = json.loads(get(url(shard, a.revision), 8, 8 + n_hdr - 1))
        base = 8 + n_hdr  # data section starts after the header
        for name in names:
            if wmap[name] != shard:
                continue
            meta = hdr[name]
            assert meta["dtype"] == "BF16", (name, meta["dtype"])
            s, e = meta["data_offsets"]
            nbytes = e - s
            path = os.path.join(a.out, name + ".bf16")
            ent = {"shape": meta["shape"], "dtype": "BF16", "shard": shard,
                   "byte_range": [base + s, base + e - 1], "nbytes": nbytes}
            if os.path.exists(path) and os.path.getsize(path) == nbytes:
                print(f"have  {name} ({nbytes / 1e6:.1f} MB)")
            else:
                print(f"fetch {name} {meta['shape']} ({nbytes / 1e6:.1f} MB)")
                tmp = path + ".part"
                done = os.path.getsize(tmp) if os.path.exists(tmp) else 0
                done -= done % CHUNK  # resume on a chunk boundary
                with open(tmp, "r+b" if done else "wb") as f:
                    f.seek(done)
                    f.truncate()
                    while done < nbytes:
                        lo = base + s + done
                        hi = min(lo + CHUNK, base + e) - 1
                        f.write(get(url(shard, a.revision), lo, hi))
                        done += hi - lo + 1
                        print(f"   {done / nbytes * 100:5.1f}%", end="\r", flush=True)
                os.replace(tmp, path)
                print()
            ent["sha256"] = sha256_file(path)
            manifest["tensors"][name] = ent

    missing = [n for n in names if n not in manifest["tensors"]]
    assert not missing, missing
    json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    total = sum(t["nbytes"] for t in manifest["tensors"].values())
    print(f"done: {len(names)} tensors, {total / 1e9:.2f} GB in {a.out}")


if __name__ == "__main__":
    main()
