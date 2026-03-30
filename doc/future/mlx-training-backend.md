# Proposal: MLX Training Backend for Apple Silicon

## Status

Future proposal — not scheduled for implementation.

## Motivation

Training the bi-encoder on Apple Silicon Macs using PyTorch MPS is impractical. PyTorch's MPS backend has known memory leak issues (open as of PyTorch 2.7+) where memory grows monotonically during training loops. On a 32 GB Mac, the process reaches 37 GB physical footprint within one epoch, causing heavy swap thrashing. Watermark ratio tuning (`PYTORCH_MPS_HIGH_WATERMARK_RATIO`) reduces the allocation ceiling but triggers OOM errors; aggressive `torch.mps.synchronize()` + `torch.mps.empty_cache()` calls prevent OOM but negate the GPU speed advantage, making MPS training no faster than CPU.

The result: training on a 32 GB M2 Pro must use CPU only, at ~25 seconds per micro-batch — roughly 90 minutes per epoch for 7K training pairs.

## Proposed Solution

[MLX](https://github.com/ml-explore/mlx) is Apple's array framework designed from scratch for Apple Silicon's unified memory architecture. It eliminates CPU↔GPU data transfers entirely — no separate GPU memory pool, no watermark tuning, no copy overhead. Memory management is predictable because the framework was designed around unified memory, not retrofitted onto it.

### Key Differences from PyTorch

| Aspect | PyTorch MPS | MLX |
|--------|-------------|-----|
| Memory model | GPU memory pool with watermarks | Native unified memory |
| Evaluation | Eager by default | Lazy — compute only on `mx.eval()` |
| Gradient style | Autograd (`.backward()`) | Functional (`nn.value_and_grad()`) |
| Training loop | Imperative mutation | Functional: `optimizer.update(model, grads)` |
| Memory leaks during training | Known open issue | Not reported |

### Migration Scope

The training code would need an MLX equivalent of:

1. **BiEncoder model** — port from `torch.nn.Module` to `mlx.nn.Module`. CodeBERT architecture (12-layer transformer) maps directly to MLX transformer blocks.
2. **Training loop** — rewrite to functional gradient style. Replace `loss.backward()` / `optimizer.step()` with `nn.value_and_grad()` / `optimizer.update()` / `mx.eval()`.
3. **Contrastive loss** — rewrite `masked_contrastive_loss` using `mlx.core` ops.
4. **Tokenizer** — `CoqTokenizer` is framework-agnostic (returns dicts of arrays), minimal changes needed.
5. **Checkpoint export** — training produces MLX weights; a conversion step exports to PyTorch format for inference in the Linux container.

### What Does Not Change

- **Inference** remains PyTorch CPU inside the Linux container. MLX is Mac-only.
- **ONNX quantization pipeline** — unchanged, consumes PyTorch checkpoints.
- **Training data loading** — `TrainingDataLoader` and `SQLitePremiseCorpus` are framework-agnostic.
- **Evaluation metrics** — `_compute_recall_at_k` can stay PyTorch or be ported; the bottleneck is model forward passes, not scoring.

## Weight Conversion

MLX models use `safetensors` format. A conversion script would:

1. Load MLX checkpoint
2. Map parameter names from MLX conventions to PyTorch conventions
3. Convert `mx.array` → `numpy` → `torch.Tensor`
4. Save as PyTorch `state_dict`

Apple provides `mlx-lm` utilities for HuggingFace model conversion that can serve as reference.

## Risks

- **CodeBERT initialization**: MLX doesn't load HuggingFace `from_pretrained()` directly. Would need to convert CodeBERT weights to MLX format as a one-time step, or initialize from scratch (the current vocabulary approach already replaces the embedding layer).
- **Operator coverage**: MLX supports standard transformer ops but may lack some PyTorch-specific operations used in CodeBERT. Needs verification.
- **Ecosystem maturity**: MLX is younger than PyTorch — debugging tools, community support, and edge case handling are less developed.

## Expected Gains

Based on MLX benchmarks on M2 Pro:
- 3-5x faster than PyTorch CPU for transformer training
- Predictable memory usage within unified memory budget
- No swap thrashing at 32 GB
- Estimated epoch time: ~15-25 minutes (vs. 90 minutes on CPU)
