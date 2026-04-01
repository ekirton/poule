"""ONNX export and INT8 quantization for the neural encoder.

Implements spec §4.6: Export to ONNX (opset 17+), apply dynamic INT8
quantization, validate max cosine distance < 0.02 across 100 samples.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from Poule.neural.training.errors import CheckpointNotFoundError, QuantizationError


class ModelQuantizer:
    """Exports a PyTorch checkpoint to INT8-quantized ONNX."""

    @staticmethod
    def quantize(checkpoint_path: Path, output_path: Path) -> None:
        """Convert a trained checkpoint to INT8-quantized ONNX.

        Steps:
        1. Load checkpoint and reconstruct model
        2. Export to ONNX (opset 17+)
        3. Apply dynamic INT8 quantization via ONNX Runtime
        4. Validate: 100 random encodings, assert max cosine distance < 0.02
        5. Write quantized ONNX to output_path

        Args:
            checkpoint_path: Path to a trained PyTorch checkpoint.
            output_path: Path to write the INT8 ONNX model.

        Raises:
            CheckpointNotFoundError: If checkpoint_path does not exist.
            QuantizationError: If max cosine distance >= 0.02.
        """
        checkpoint_path = Path(checkpoint_path)
        output_path = Path(output_path)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        import numpy as np
        import onnxruntime as ort
        import torch
        from onnxruntime.quantization import QuantType, quantize_dynamic

        from Poule.neural.training.model import BiEncoder
        from Poule.neural.training.trainer import load_checkpoint

        # Load model
        checkpoint = load_checkpoint(checkpoint_path)
        hp = checkpoint.get("hyperparams", {})
        max_seq_length = hp.get("max_seq_length", 512)
        vocab_path_str = checkpoint.get("vocabulary_path")

        # Reconstruct model with correct vocab size
        if vocab_path_str and Path(vocab_path_str).exists():
            from Poule.neural.training.vocabulary import CoqTokenizer

            tokenizer = CoqTokenizer(Path(vocab_path_str))
        else:
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")

        model = BiEncoder.from_checkpoint(checkpoint)
        model.eval()

        # Step 1: Export to ONNX
        with tempfile.TemporaryDirectory() as tmpdir:
            fp32_onnx_path = Path(tmpdir) / "model_fp32.onnx"

            # Create dummy inputs for tracing
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
                model,
                (dummy_input_ids, dummy_attention_mask),
                str(fp32_onnx_path),
                opset_version=17,
                input_names=["input_ids", "attention_mask"],
                output_names=["embeddings"],
                dynamic_axes={
                    "input_ids": {0: "batch_size", 1: "seq_length"},
                    "attention_mask": {0: "batch_size", 1: "seq_length"},
                    "embeddings": {0: "batch_size"},
                },
            )

            # Step 2: Apply dynamic INT8 quantization
            quantize_dynamic(
                model_input=str(fp32_onnx_path),
                model_output=str(output_path),
                weight_type=QuantType.QInt8,
            )

            # Step 3: Validate quantization quality
            # Load both models for comparison
            fp32_session = ort.InferenceSession(
                str(fp32_onnx_path),
                providers=["CPUExecutionProvider"],
            )
            int8_session = ort.InferenceSession(
                str(output_path),
                providers=["CPUExecutionProvider"],
            )

            # Generate 100 random test inputs
            max_cosine_dist = 0.0

            for _ in range(100):
                # Random token sequences (valid token IDs)
                seq_len = min(32, max_seq_length)
                input_ids = np.random.randint(
                    0, tokenizer.vocab_size, size=(1, seq_len), dtype=np.int64
                )
                attention_mask = np.ones((1, seq_len), dtype=np.int64)

                fp32_out = fp32_session.run(
                    None,
                    {"input_ids": input_ids, "attention_mask": attention_mask},
                )[0]
                int8_out = int8_session.run(
                    None,
                    {"input_ids": input_ids, "attention_mask": attention_mask},
                )[0]

                # Cosine distance = 1 - cosine_similarity
                fp32_norm = fp32_out / (
                    np.linalg.norm(fp32_out, axis=1, keepdims=True) + 1e-9
                )
                int8_norm = int8_out / (
                    np.linalg.norm(int8_out, axis=1, keepdims=True) + 1e-9
                )
                cosine_sim = np.sum(fp32_norm * int8_norm, axis=1)
                cosine_dist = 1.0 - cosine_sim[0]
                max_cosine_dist = max(max_cosine_dist, float(cosine_dist))

            if max_cosine_dist >= 0.02:
                # Clean up the invalid output
                output_path.unlink(missing_ok=True)
                raise QuantizationError(max_distance=max_cosine_dist)
