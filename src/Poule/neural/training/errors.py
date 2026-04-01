"""Error types for the neural training pipeline."""


class NeuralTrainingError(Exception):
    """Base class for all training pipeline errors."""


class DataFormatError(NeuralTrainingError):
    """JSONL parse or schema error."""


class CheckpointNotFoundError(NeuralTrainingError):
    """Model checkpoint file missing."""


class TrainingResourceError(NeuralTrainingError):
    """GPU OOM or insufficient compute resources."""


class QuantizationError(NeuralTrainingError):
    """INT8 conversion quality check failed."""

    def __init__(self, message: str = "Quantization validation failed"):
        super().__init__(message)


class InsufficientDataError(NeuralTrainingError):
    """Not enough training data to proceed."""


class TuningError(NeuralTrainingError):
    """Hyperparameter optimization study failed."""


class BackendNotAvailableError(NeuralTrainingError):
    """Requested training backend (e.g. MLX) is not available."""


class WeightConversionError(NeuralTrainingError):
    """MLX → PyTorch weight conversion quality check failed."""

    def __init__(self, max_distance: float | None = None, message: str | None = None):
        self.max_distance = max_distance
        if message is None:
            message = (
                f"Weight conversion validation failed: max cosine distance "
                f"{max_distance:.4f} >= 0.01 threshold"
            )
        super().__init__(message)
