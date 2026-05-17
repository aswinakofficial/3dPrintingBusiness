#!/usr/bin/env python3
"""
Patch TRELLIS.2 and transformers for compatibility with HuggingFace models loaded
via trust_remote_code=True (BiRefNet / RMBG-2.0 inherit from nn.Module, not
PreTrainedModel, and are missing attributes the transformers loading machinery
expects such as _named_pretrained_submodules and all_tied_weights_keys).
"""
import pathlib
import re
import sys


def patch_conversion_mapping():
    """
    conversion_mapping.py: _named_pretrained_submodules is iterated as a plain
    list; default to [] so nn.Module subclasses (BiRefNet) don't crash at load.
    """
    found = False
    for tf_path in pathlib.Path("/usr/local/lib").rglob(
        "transformers/conversion_mapping.py"
    ):
        found = True
        content = tf_path.read_text()
        old = "model._named_pretrained_submodules"
        new = "getattr(model, '_named_pretrained_submodules', [])"
        if old in content:
            tf_path.write_text(content.replace(old, new))
            print(
                f"[OK] conversion_mapping: patched _named_pretrained_submodules → {tf_path}"
            )
        else:
            print(
                f"[SKIP] conversion_mapping: pattern not found (already patched) → {tf_path}"
            )
    if not found:
        print(
            "[WARN] transformers/conversion_mapping.py not found under /usr/local/lib"
        )


def patch_trellis2_pipeline():
    """
    trellis2_image_to_3d.py — two changes:

    A. Wrap rembg model loading in try/except so a broken model (BiRefNet missing
       PreTrainedModel attrs such as all_tied_weights_keys) doesn't abort the whole
       pipeline load.  Sets rembg_model = None on failure.

    B. Guard the self.rembg_model(input) call in preprocess_image so None is safe.
       Callers should pass pre-processed RGBA images with real alpha so that
       preprocess_image detects has_alpha=True and skips the rembg call entirely.
    """
    p = pathlib.Path("/opt/trellis2-repo/trellis2/pipelines/trellis2_image_to_3d.py")
    if not p.exists():
        print(f"[ERROR] not found: {p}", file=sys.stderr)
        sys.exit(1)

    content = p.read_text()
    changed = False

    # ── Patch A: wrap rembg loading ──────────────────────────────────────────
    m = re.search(
        r"([ \t]+)(pipeline\.rembg_model = getattr\(rembg,[^\n]+\))",
        content,
    )
    if m:
        indent = m.group(1)
        orig_line = m.group(2)
        replacement = (
            f"{indent}try:\n"
            f"{indent}    {orig_line}\n"
            f"{indent}except Exception as _rembg_err:\n"
            f"{indent}    import warnings\n"
            f"{indent}    warnings.warn(\n"
            f'{indent}        f"[TRELLIS2] rembg model load failed ({{_rembg_err}}); "\n'
            f'{indent}        "background removal disabled — pass pre-processed RGBA images"\n'
            f"{indent}    )\n"
            f"{indent}    pipeline.rembg_model = None"
        )
        content = content[: m.start()] + replacement + content[m.end() :]
        print("[OK] trellis2_image_to_3d: wrapped rembg loading in try/except")
        changed = True
    else:
        print(
            "[SKIP] rembg loading patch: pattern not found (already patched or changed upstream)"
        )

    # ── Patch B: None-safe rembg call in preprocess_image ───────────────────
    m2 = re.search(
        r"([ \t]+)(output = self\.rembg_model\(input\))",
        content,
    )
    if m2:
        indent2 = m2.group(1)
        replacement2 = (
            f"{indent2}if self.rembg_model is None:\n"
            f"{indent2}    output = input\n"
            f"{indent2}else:\n"
            f"{indent2}    output = self.rembg_model(input)"
        )
        content = content[: m2.start()] + replacement2 + content[m2.end() :]
        print(
            "[OK] trellis2_image_to_3d: None-safe rembg_model call in preprocess_image"
        )
        changed = True
    else:
        print(
            "[SKIP] None-safe rembg patch: pattern not found (already patched or changed upstream)"
        )

    if changed:
        p.write_text(content)
        print(f"[DONE] wrote patches to {p}")
    else:
        print("[DONE] no changes needed")


if __name__ == "__main__":
    patch_conversion_mapping()
    patch_trellis2_pipeline()
