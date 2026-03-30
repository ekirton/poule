"""MLX training backend for Apple Silicon.

This package provides an alternative training backend using Apple's MLX
framework, designed for Apple Silicon's unified memory architecture.
It produces checkpoints in MLX safetensors format that are converted
to PyTorch for the inference pipeline.

Requires: mlx (macOS with Apple Silicon only).
"""
