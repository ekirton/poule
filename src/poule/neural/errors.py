"""Error types for the neural retrieval channel."""


class ModelNotFoundError(Exception):
    """Model checkpoint file not found at the expected path."""


class ModelLoadError(Exception):
    """Model file exists but cannot be loaded (invalid ONNX format)."""
