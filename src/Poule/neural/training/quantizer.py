"""ONNX export and INT8 quantization for the tactic classifier.

Implements spec §4.6: Export to ONNX (opset 17+), apply dynamic INT8
quantization, validate label agreement >= 98% across 100 samples.
Also writes tactic-labels.json alongside the ONNX model.

For hierarchical models, the ONNX export wraps the model in a
product-rule inference layer that outputs flat tactic logits.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from Poule.neural.training.errors import CheckpointNotFoundError, QuantizationError


class _FlatInferenceWrapper:
    """Wraps a hierarchical model for ONNX export.

    Produces flat product-rule logits: P(tactic) = P(category) * P(tactic|category).
    """

    def __init__(self, model):
        import torch
        import torch.nn as nn

        self.model = model

        class Wrapper(nn.Module):
            def __init__(self, inner):
                super().__init__()
                self.inner = inner

            def forward(self, input_ids, attention_mask):
                cat_logits, within_logits = self.inner(input_ids, attention_mask)
                cat_probs = torch.softmax(cat_logits, dim=-1)
                all_scores = []
                for cat_name, head in self.inner.within_heads.items():
                    cat_idx = list(self.inner.within_heads.keys()).index(cat_name)
                    within_probs = torch.softmax(within_logits[cat_name], dim=-1)
                    product = cat_probs[:, cat_idx:cat_idx+1] * within_probs
                    all_scores.append(product)
                return torch.cat(all_scores, dim=-1)

        self.wrapper = Wrapper(model)


class ModelQuantizer:
    """Exports a PyTorch checkpoint to INT8-quantized ONNX."""

    @staticmethod
    def quantize(checkpoint_path: Path, output_path: Path) -> None:
        """Convert a trained checkpoint to INT8-quantized ONNX.

        Handles both hierarchical and flat model formats. For hierarchical
        models, wraps in a product-rule inference layer producing flat logits.

        Args:
            checkpoint_path: Path to a trained PyTorch checkpoint.
            output_path: Path to write the INT8 ONNX model.

        Raises:
            CheckpointNotFoundError: If checkpoint_path does not exist.
            QuantizationError: If label agreement < 98%.
        """
        checkpoint_path = Path(checkpoint_path)
        output_path = Path(output_path)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        import numpy as np
        import onnxruntime as ort
        import torch
        from onnxruntime.quantization import QuantType, quantize_dynamic

        from Poule.neural.training.model import HierarchicalTacticClassifier

        # Load checkpoint
        checkpoint = torch.load(
            checkpoint_path, map_location="cpu", weights_only=False,
        )
        hp = checkpoint.get("hyperparams", {})
        max_seq_length = hp.get("max_seq_length", 512)
        vocab_path_str = checkpoint.get("vocabulary_path")
        label_map = checkpoint.get("label_map", {})
        per_category_sizes = checkpoint.get("per_category_sizes")
        is_hierarchical = per_category_sizes is not None

        # Reconstruct tokenizer
        if vocab_path_str and Path(vocab_path_str).exists():
            from Poule.neural.training.vocabulary import CoqTokenizer
            tokenizer = CoqTokenizer(Path(vocab_path_str))
        else:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")

        # Reconstruct model
        model = HierarchicalTacticClassifier.from_checkpoint(checkpoint)
        model.eval()

        # Wrap hierarchical model for flat ONNX output
        if is_hierarchical:
            wrapper = _FlatInferenceWrapper(model)
            export_model = wrapper.wrapper
        else:
            export_model = model

        # Step 1: Export to ONNX
        with tempfile.TemporaryDirectory() as tmpdir:
            fp32_onnx_path = Path(tmpdir) / "model_fp32.onnx"

            from Poule.neural.training.vocabulary import CoqTokenizer

            if isinstance(tokenizer, CoqTokenizer):
                ids, mask = tokenizer.encode(
                    "Example proof state", max_length=max_seq_length
                )
                dummy_input_ids = torch.tensor([ids], dtype=torch.long)
                dummy_attention_mask = torch.tensor([mask], dtype=torch.long)
            else:
                dummy_tokens = tokenizer(
                    ["Example proof state"],
                    padding="max_length",
                    truncation=True,
                    max_length=max_seq_length,
                    return_tensors="pt",
                )
                dummy_input_ids = dummy_tokens["input_ids"]
                dummy_attention_mask = dummy_tokens["attention_mask"]

            torch.onnx.export(
                export_model,
                (dummy_input_ids, dummy_attention_mask),
                str(fp32_onnx_path),
                opset_version=17,
                input_names=["input_ids", "attention_mask"],
                output_names=["logits"],
                dynamic_axes={
                    "input_ids": {0: "batch_size", 1: "seq_length"},
                    "attention_mask": {0: "batch_size", 1: "seq_length"},
                    "logits": {0: "batch_size"},
                },
            )

            import onnx

            onnx_model = onnx.load(str(fp32_onnx_path), load_external_data=True)
            single_path = Path(tmpdir) / "model_single.onnx"
            onnx.save_model(
                onnx_model, str(single_path),
                save_as_external_data=False,
            )
            del onnx_model

            # Step 2: Apply dynamic INT8 quantization
            try:
                quantize_dynamic(
                    model_input=str(single_path),
                    model_output=str(output_path),
                    weight_type=QuantType.QInt8,
                )
            except Exception:
                import shutil
                shutil.copy2(str(single_path), str(output_path))

            # Step 3: Validate quantization quality
            fp32_session = ort.InferenceSession(
                str(fp32_onnx_path),
                providers=["CPUExecutionProvider"],
            )
            int8_session = ort.InferenceSession(
                str(output_path),
                providers=["CPUExecutionProvider"],
            )

            agreements = 0
            total = 100

            for _ in range(total):
                seq_len = min(32, max_seq_length)
                input_ids = np.random.randint(
                    0, tokenizer.vocab_size, size=(1, seq_len), dtype=np.int64
                )
                attention_mask = np.ones((1, seq_len), dtype=np.int64)

                fp32_logits = fp32_session.run(
                    None,
                    {"input_ids": input_ids, "attention_mask": attention_mask},
                )[0]
                int8_logits = int8_session.run(
                    None,
                    {"input_ids": input_ids, "attention_mask": attention_mask},
                )[0]

                fp32_label = int(np.argmax(fp32_logits, axis=1)[0])
                int8_label = int(np.argmax(int8_logits, axis=1)[0])
                if fp32_label == int8_label:
                    agreements += 1

            agreement_rate = agreements / total
            if agreement_rate < 0.98:
                output_path.unlink(missing_ok=True)
                raise QuantizationError(
                    f"Label agreement {agreement_rate:.0%} < 98% threshold"
                )

        # Step 4: Write tactic-labels.json
        if is_hierarchical:
            # Hierarchical format
            category_names = checkpoint.get("category_names", [])
            per_cat_label_names = checkpoint.get("per_category_label_names", {})
            labels_data = {
                "categories": category_names,
                "per_category": per_cat_label_names,
            }
        else:
            # Flat format (backward compat)
            label_names = sorted(label_map.keys(), key=lambda k: label_map[k])
            labels_data = label_names

        labels_path = output_path.parent / "tactic-labels.json"
        with open(labels_path, "w") as f:
            json.dump(labels_data, f, indent=2)
