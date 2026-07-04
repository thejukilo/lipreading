"""Probe how auto_avsr lays out its tokenizer + model output, so we can wire in a
Dutch tokenizer (Plan B) with matching special-token indices.

Prints: auto_avsr's English token-list length + special-token indices, the
model's actual output-layer sizes (odim), and how your Dutch SP model compares.
Run once and paste the output.

    python -m server.phase3.inspect_tokenizer \
        --dutch-model path\to\dutch_unigram5000.model \
        --auto-avsr-dir <same as training>
"""

from __future__ import annotations

import argparse
import os


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Inspect auto_avsr tokenizer/model layout.")
    ap.add_argument("--base", default=os.environ.get(
        "VSR_CHECKPOINT", "checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth"))
    ap.add_argument("--auto-avsr-dir", default=None)
    ap.add_argument("--dutch-model", default=None, help="Path to dutch_unigram5000.model")
    args = ap.parse_args(argv)

    from ..engine import LipreadingEngine

    eng = LipreadingEngine(args.base, auto_avsr_dir=args.auto_avsr_dir,
                           device="cpu", load_detector=False)
    from datamodule.transforms import TextTransform

    tt = TextTransform()
    print("=== auto_avsr TextTransform ===")
    print("public attrs:", [a for a in dir(tt) if not a.startswith("_")])

    token_list = getattr(tt, "token_list", None)
    if token_list is not None:
        print("token_list length (= model odim):", len(token_list))
        print("  head:", list(token_list[:6]))
        print("  tail:", list(token_list[-6:]))
    hashmap = getattr(tt, "hashmap", {}) or {}
    print("hashmap size:", len(hashmap))
    for tok in ["<blank>", "<unk>", "<eos>", "<sos>", "<sos/eos>", "</s>", "<s>", "<space>"]:
        if tok in hashmap:
            print(f"  special {tok!r} -> id {hashmap[tok]}")

    # A real tokenization so we see the exact id scheme (incl. any blank offset).
    for s in ["DE MENSEN", "HELLO WORLD"]:
        try:
            print(f"  tokenize({s!r}) ->", list(tt.tokenize(s)))
        except Exception as e:
            print(f"  tokenize({s!r}) failed: {e}")

    # Model output sizes — the layers a Dutch vocab swap would touch.
    print("\n=== model output layers (vocab-sized) ===")
    model = eng.modelmodule.model
    for name, p in model.named_parameters():
        low = name.lower()
        if p.dim() >= 1 and (("ctc" in low and ("ctc_lo" in low or "out" in low))
                             or ("decoder" in low and "output_layer" in low)
                             or ("decoder" in low and "embed" in low and p.dim() == 2)):
            print(f"  {name}: {tuple(p.shape)}")

    if args.dutch_model:
        import sentencepiece as spm

        sp = spm.SentencePieceProcessor(model_file=args.dutch_model)
        print("\n=== your Dutch SP model ===")
        print("  pieces:", sp.get_piece_size(),
              "| unk:", sp.unk_id(), "eos:", sp.eos_id(), "bos:", sp.bos_id())
        print("  drop-in size match:", token_list is not None
              and len(token_list) == sp.get_piece_size(),
              "(if False, Dutch head needs reinit — still fine)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
