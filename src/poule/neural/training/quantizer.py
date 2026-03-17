"""ONNX export and INT8 quantization for the neural encoder."""

from __future__ import annotations

from pathlib import Path

from poule.neural.training.errors import CheckpointNotFoundError, QuantizationError


class ModelQuantizer:
    """Exports a PyTorch checkpoint to INT8-quantized ONNX."""

    @staticmethod
    def quantize(checkpoint_path: Path, output_path: Path) -> None:
        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        # Full quantization pipeline would use torch + onnx + onnxruntime here
        raise NotImplementedError("Full quantization requires torch and onnx")
