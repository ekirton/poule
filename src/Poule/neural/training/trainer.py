"""Bi-encoder trainer with masked contrastive loss and early stopping."""

from __future__ import annotations

import logging
import pickle
import random
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from Poule.neural.training.data import TrainingDataset
from Poule.neural.training.errors import (
    CheckpointNotFoundError,
    InsufficientDataError,
    TrainingResourceError,
)
from Poule.neural.training.negatives import sample_hard_negatives

logger = logging.getLogger(__name__)

DEFAULT_HYPERPARAMS = {
    "batch_size": 128,
    "learning_rate": 5e-5,
    "weight_decay": 1e-2,
    "temperature": 0.05,
    "hard_negatives_per_state": 3,
    "max_seq_length": 256,
    "max_epochs": 20,
    "early_stopping_patience": 3,
    "embedding_dim": 768,
}

FINE_TUNE_OVERRIDES = {
    "learning_rate": 5e-6,
    "max_epochs": 10,
}


class EarlyStoppingTracker:
    """Tracks validation Recall@32 and signals when to stop training."""

    def __init__(self, patience: int):
        self.patience = patience
        self.best_recall = -1.0
        self.best_epoch = 0
        self._epochs_without_improvement = 0
        self._epoch = 0

    def should_stop(self, recall_at_32: float) -> bool:
        self._epoch += 1
        if recall_at_32 > self.best_recall:
            self.best_recall = recall_at_32
            self.best_epoch = self._epoch
            self._epochs_without_improvement = 0
        else:
            self._epochs_without_improvement += 1

        return self._epochs_without_improvement >= self.patience


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------


def _get_device():
    """Select compute device: CUDA > MPS > CPU.

    spec §4.9: Returns a torch.device in priority order.
    """
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Loss and encoding helpers (require torch — imported lazily)
# ---------------------------------------------------------------------------


def masked_contrastive_loss(state_embs, premise_embs, positive_indices, temperature):
    """Compute masked contrastive loss (InfoNCE with premise masking).

    spec §4.3: For each positive pair (s_i, p_ij), the candidate set is
    {p_ij} ∪ N_i ∪ {all p_kl for k ≠ i where p_kl ∉ P_i}. Temperature τ
    is applied as a divisor inside the exponential.

    Args:
        state_embs: [B, dim] L2-normalized state embeddings.
        premise_embs: [P, dim] L2-normalized premise embeddings.
        positive_indices: list[list[int]] — positive_indices[i] gives the
            premise indices that are positive for state i.
        temperature: τ scalar.

    Returns:
        Scalar loss averaged over all positive pairs.
    """
    import torch

    B = state_embs.size(0)
    P = premise_embs.size(0)

    # Cosine similarity (both are L2-normalized) scaled by temperature
    sim = torch.mm(state_embs, premise_embs.t()) / temperature  # [B, P]

    total_loss = torch.tensor(0.0, device=state_embs.device)
    count = 0

    for i in range(B):
        pos_set = set(positive_indices[i])
        if not pos_set:
            continue

        for j in positive_indices[i]:
            # Mask: exclude other positives for this state
            mask = torch.ones(P, dtype=torch.bool, device=state_embs.device)
            for p in pos_set:
                if p != j:
                    mask[p] = False

            pos_logit = sim[i, j]
            candidate_logits = sim[i][mask]
            loss_ij = -pos_logit + torch.logsumexp(candidate_logits, dim=0)
            total_loss = total_loss + loss_ij
            count += 1

    if count == 0:
        return torch.tensor(0.0, device=state_embs.device, requires_grad=True)

    return total_loss / count


def _tokenize_batch(tokenizer, texts, max_seq_length):
    """Tokenize a batch of texts using either CoqTokenizer or HuggingFace tokenizer."""
    from Poule.neural.training.vocabulary import CoqTokenizer

    if isinstance(tokenizer, CoqTokenizer):
        result = tokenizer.encode_batch(texts, max_length=max_seq_length)
        import torch

        return {
            "input_ids": torch.tensor(result["input_ids"], dtype=torch.long)
            if not isinstance(result["input_ids"], torch.Tensor)
            else result["input_ids"],
            "attention_mask": torch.tensor(
                result["attention_mask"], dtype=torch.long
            )
            if not isinstance(result["attention_mask"], torch.Tensor)
            else result["attention_mask"],
        }
    else:
        return tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_seq_length,
            return_tensors="pt",
        )


def _encode_texts_batched(model, tokenizer, texts, max_seq_length, device, batch_size=64):
    """Encode texts through the model in batches. Returns a CPU tensor."""
    import torch

    if not texts:
        return torch.zeros(0, model.embedding_dim)

    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        tokens = _tokenize_batch(tokenizer, batch, max_seq_length)
        embs = model(
            tokens["input_ids"].to(device),
            tokens["attention_mask"].to(device),
        )
        all_embs.append(embs.detach().cpu())
    return torch.cat(all_embs, dim=0)


def _compute_recall_at_k(model, tokenizer, pairs, premise_corpus, max_seq_length, device, k=32):
    """Compute Recall@k on (state, positive_names) pairs using current model.

    Encodes premises in chunks to avoid materializing a full N×768 tensor
    (118K premises → 363 MB). Instead, scores are computed per-chunk and
    only the top-k indices are retained.
    """
    import torch

    if not pairs:
        return 0.0

    model.eval()
    premise_names = list(premise_corpus.keys())

    # Build chunk list: resolve premise texts via get_batch when
    # available (single DB round-trip per chunk), else fall back to
    # individual lookups.
    _CHUNK = 64
    premise_chunks = []
    get_batch = getattr(premise_corpus, "get_batch", None)
    for start in range(0, len(premise_names), _CHUNK):
        chunk_names = premise_names[start:start + _CHUNK]
        if get_batch is not None:
            chunk_texts = get_batch(chunk_names)
        else:
            chunk_texts = [premise_corpus[n] for n in chunk_names]
        premise_chunks.append((start, chunk_texts))

    with torch.no_grad():
        hits = 0
        for state_text, positive_names in pairs:
            state_emb = _encode_texts_batched(
                model, tokenizer, [state_text], max_seq_length, device
            )
            # Compute top-k across all chunks without holding full matrix
            top_k_scores = torch.full((k,), -float("inf"))
            top_k_indices = torch.zeros(k, dtype=torch.long)

            for chunk_start, chunk_texts in premise_chunks:
                chunk_embs = _encode_texts_batched(
                    model, tokenizer, chunk_texts, max_seq_length, device
                )
                chunk_scores = torch.mm(state_emb, chunk_embs.t()).squeeze(0)
                # Merge this chunk's scores with running top-k
                combined_scores = torch.cat([top_k_scores, chunk_scores])
                combined_indices = torch.cat([
                    top_k_indices,
                    torch.arange(chunk_start, chunk_start + len(chunk_texts)),
                ])
                sel = torch.topk(combined_scores, min(k, len(combined_scores))).indices
                top_k_scores = combined_scores[sel]
                top_k_indices = combined_indices[sel]

            top_k_names = {premise_names[i] for i in top_k_indices.tolist()}
            if set(positive_names) & top_k_names:
                hits += 1

    return hits / len(pairs)


def _prepare_batch(items, tokenizer, premise_corpus, max_seq_length):
    """Tokenize a micro-batch and build positive-index maps.

    Args:
        items: list of (state_text, positive_names, hard_neg_names) tuples.
        tokenizer: HuggingFace tokenizer.
        premise_corpus: name -> statement text mapping.
        max_seq_length: maximum token sequence length.

    Returns:
        dict with tokenized tensors and positive_indices, or None if empty.
    """
    state_texts = []
    unique_premises: dict[str, int] = {}  # name -> index
    positive_indices: list[list[int]] = []

    for state_text, pos_names, neg_names in items:
        state_texts.append(state_text)

        # Add all premises to the unique set
        for name in list(pos_names) + list(neg_names):
            if name in premise_corpus and name not in unique_premises:
                unique_premises[name] = len(unique_premises)

        # Map positive names to indices
        pos_idx = [unique_premises[n] for n in pos_names if n in unique_premises]
        positive_indices.append(pos_idx)

    if not unique_premises:
        return None

    premise_names = list(unique_premises.keys())
    get_batch = getattr(premise_corpus, "get_batch", None)
    if get_batch is not None:
        premise_texts = get_batch(premise_names)
    else:
        premise_texts = [premise_corpus[n] for n in premise_names]

    state_tokens = _tokenize_batch(tokenizer, state_texts, max_seq_length)
    premise_tokens = _tokenize_batch(tokenizer, premise_texts, max_seq_length)

    return {
        "state_input_ids": state_tokens["input_ids"],
        "state_attention_mask": state_tokens["attention_mask"],
        "premise_input_ids": premise_tokens["input_ids"],
        "premise_attention_mask": premise_tokens["attention_mask"],
        "positive_indices": positive_indices,
    }


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class BiEncoderTrainer:
    """Trains a bi-encoder model using masked contrastive loss."""

    def __init__(self, hyperparams: dict[str, Any] | None = None):
        self.hyperparams = dict(DEFAULT_HYPERPARAMS)
        if hyperparams:
            self.hyperparams.update(hyperparams)

    def train(
        self,
        dataset,
        output_path: Path,
        vocabulary_path: Path | None = None,
        hyperparams: dict | None = None,
        sample: float | None = None,
        epoch_callback=None,
    ):
        """Train a bi-encoder from scratch.

        spec §4.3: Requires at least 1,000 training pairs (after sampling).
        When vocabulary_path is provided, uses the closed vocabulary
        tokenizer and reinitializes the embedding layer.
        sample: optional float in (0.0, 1.0] — sub-samples the training
        split to ceil(len * sample) pairs. Validation and test are not affected.
        epoch_callback: optional (epoch, val_recall) -> None, invoked
        after each epoch's validation. If it raises, training terminates.
        """
        if sample is not None and sample < 1.0:
            import math
            n = math.ceil(len(dataset.train) * sample)
            sampled_train = random.sample(dataset.train, n)
            dataset = TrainingDataset(
                train=sampled_train,
                val=dataset.val,
                test=dataset.test,
                premise_corpus=dataset.premise_corpus,
            )

        if len(dataset.train) < 1000:
            raise InsufficientDataError(
                f"Training requires at least 1,000 pairs, got {len(dataset.train)}"
            )

        hp = dict(self.hyperparams)
        if hyperparams:
            hp.update(hyperparams)

        self._train_impl(
            dataset, Path(output_path), hp, vocabulary_path=vocabulary_path,
            epoch_callback=epoch_callback,
        )

    def fine_tune(
        self,
        checkpoint_path: Path,
        dataset,
        output_path: Path,
        hyperparams: dict | None = None,
        epoch_callback=None,
    ):
        """Fine-tune from a pre-trained checkpoint.

        spec §4.4: Uses lower learning rate (5e-6) and fewer epochs (10).
        Inherits the vocabulary_path from the checkpoint.
        epoch_callback: optional (epoch, val_recall) -> None, invoked
        after each epoch's validation. If it raises, training terminates.
        """
        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        hp = get_fine_tune_hyperparams(hyperparams)
        checkpoint = load_checkpoint(checkpoint_path)

        vocab_path_str = checkpoint.get("vocabulary_path")
        vocab_path = Path(vocab_path_str) if vocab_path_str else None

        self._train_impl(
            dataset,
            Path(output_path),
            hp,
            initial_state_dict=checkpoint.get("model_state_dict"),
            vocabulary_path=vocab_path,
            epoch_callback=epoch_callback,
        )

    # -----------------------------------------------------------------------
    # Core training loop
    # -----------------------------------------------------------------------

    def _train_impl(
        self, dataset, output_path, hp, initial_state_dict=None,
        vocabulary_path=None, epoch_callback=None,
    ):
        """Shared training loop for train() and fine_tune()."""
        import gc
        import torch

        from Poule.neural.training.model import BiEncoder

        output_path = Path(output_path)
        device = _get_device()

        # Tokenizer: closed vocabulary or CodeBERT default
        if vocabulary_path is not None:
            from Poule.neural.training.vocabulary import CoqTokenizer

            tokenizer = CoqTokenizer(Path(vocabulary_path))
            model = BiEncoder(vocab_size=tokenizer.vocab_size)
        else:
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
            model = BiEncoder()

        # Free transient allocations from model loading before
        # the optimizer doubles the memory footprint.
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        if initial_state_dict is not None:
            model.load_state_dict(initial_state_dict)
        model = model.to(device)

        # Optimizer
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=hp["learning_rate"],
            weight_decay=hp["weight_decay"],
        )

        # Mixed precision (GPU only)
        use_amp = device.type == "cuda"
        scaler = None
        autocast_ctx = nullcontext
        if use_amp:
            try:
                from torch.amp import GradScaler, autocast

                scaler = GradScaler("cuda")
                autocast_ctx = lambda: autocast(device_type="cuda", dtype=torch.float16)
            except ImportError:
                from torch.cuda.amp import GradScaler, autocast as _autocast

                scaler = GradScaler()
                autocast_ctx = _autocast

        # Gradient accumulation
        micro_batch_size = min(32, hp["batch_size"])
        accumulation_steps = max(1, hp["batch_size"] // micro_batch_size)
        all_premise_names = set(dataset.premise_corpus.keys())

        tracker = EarlyStoppingTracker(hp["early_stopping_patience"])
        best_recall = -1.0
        final_epoch = 0

        for epoch in range(1, hp["max_epochs"] + 1):
            final_epoch = epoch
            model.train()
            epoch_loss = 0.0
            n_micro = 0

            indices = list(range(len(dataset.train)))
            random.shuffle(indices)

            optimizer.zero_grad()
            accum_count = 0

            for batch_start in range(0, len(indices), micro_batch_size):
                batch_indices = indices[batch_start : batch_start + micro_batch_size]

                # Build micro-batch with hard negatives
                # Cap positives per pair to bound memory.  The
                # extraction can record thousands of transitive
                # premises per tactic step; encoding them all in
                # one backward pass would OOM.
                _MAX_POS = 16
                items = []
                for idx in batch_indices:
                    state_text, raw_pos = dataset.train[idx]
                    pos_names = (
                        random.sample(raw_pos, _MAX_POS)
                        if len(raw_pos) > _MAX_POS
                        else raw_pos
                    )

                    # Accessible premises (spec §4.2)
                    source = (
                        dataset.train_files[idx]
                        if idx < len(dataset.train_files)
                        else ""
                    )
                    accessible: set[str] = set()
                    if source and source in dataset.file_deps:
                        for dep_file in dataset.file_deps[source]:
                            accessible.update(
                                dataset.file_premises.get(dep_file, set())
                            )

                    neg_names = sample_hard_negatives(
                        state_text,
                        set(pos_names),
                        accessible,
                        k=hp["hard_negatives_per_state"],
                        corpus=all_premise_names,
                    )
                    items.append((state_text, pos_names, neg_names))

                batch = _prepare_batch(
                    items, tokenizer, dataset.premise_corpus, hp["max_seq_length"]
                )
                if batch is None:
                    continue

                try:
                    s_ids = batch["state_input_ids"].to(device)
                    s_mask = batch["state_attention_mask"].to(device)
                    p_ids = batch["premise_input_ids"].to(device)
                    p_mask = batch["premise_attention_mask"].to(device)

                    with autocast_ctx():
                        state_embs = model(s_ids, s_mask)

                        # Encode premises without gradient tracking.
                        # A single training pair can reference thousands
                        # of premises; storing backward activations for
                        # all of them would OOM.  The shared-weight
                        # encoder learns from state-side gradients.
                        _P_CHUNK = 64
                        with torch.no_grad():
                            if p_ids.size(0) <= _P_CHUNK:
                                premise_embs = model(p_ids, p_mask)
                            else:
                                chunks = []
                                for ps in range(0, p_ids.size(0), _P_CHUNK):
                                    pe = min(ps + _P_CHUNK, p_ids.size(0))
                                    chunks.append(model(p_ids[ps:pe], p_mask[ps:pe]))
                                premise_embs = torch.cat(chunks, dim=0)
                        loss = (
                            masked_contrastive_loss(
                                state_embs,
                                premise_embs,
                                batch["positive_indices"],
                                hp["temperature"],
                            )
                            / accumulation_steps
                        )

                    if scaler:
                        scaler.scale(loss).backward()
                    else:
                        loss.backward()

                    epoch_loss += loss.item() * accumulation_steps
                    n_micro += 1
                    accum_count += 1

                    if accum_count >= accumulation_steps:
                        if scaler:
                            scaler.step(optimizer)
                            scaler.update()
                        else:
                            optimizer.step()
                        optimizer.zero_grad()
                        accum_count = 0

                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        raise TrainingResourceError(
                            f"GPU out of memory with batch_size={hp['batch_size']}. "
                            f"Try reducing batch_size."
                        ) from e
                    raise

            # Flush remaining accumulated gradients
            if accum_count > 0:
                if scaler:
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    optimizer.step()
                optimizer.zero_grad()

            # Validation
            avg_loss = epoch_loss / max(n_micro, 1)

            val_recall = 0.0
            if dataset.val:
                val_recall = _compute_recall_at_k(
                    model,
                    tokenizer,
                    dataset.val,
                    dataset.premise_corpus,
                    hp["max_seq_length"],
                    device,
                    k=32,
                )

            print(f"Epoch {epoch}: loss={avg_loss:.4f}, val_R@32={val_recall:.4f}")

            # Epoch callback (used by HPO tuner for pruning)
            if epoch_callback is not None:
                epoch_callback(epoch, val_recall)

            # Save best checkpoint
            if val_recall > best_recall:
                best_recall = val_recall
                save_checkpoint(
                    {
                        "model_state_dict": {
                            k: v.cpu() for k, v in model.state_dict().items()
                        },
                        "optimizer_state_dict": optimizer.state_dict(),
                        "epoch": epoch,
                        "best_recall_32": val_recall,
                        "hyperparams": hp,
                        "vocabulary_path": str(vocabulary_path) if vocabulary_path else None,
                    },
                    output_path,
                )

            if tracker.should_stop(val_recall):
                break

        # Save final checkpoint alongside best
        final_path = output_path.parent / (
            output_path.stem + ".final" + output_path.suffix
        )
        save_checkpoint(
            {
                "model_state_dict": {
                    k: v.cpu() for k, v in model.state_dict().items()
                },
                "optimizer_state_dict": optimizer.state_dict(),
                "epoch": final_epoch,
                "best_recall_32": best_recall,
                "hyperparams": hp,
                "vocabulary_path": str(vocabulary_path) if vocabulary_path else None,
            },
            final_path,
        )


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------


def save_checkpoint(data: dict, path: Path) -> None:
    """Save checkpoint dict. Uses torch.save when available, pickle otherwise."""
    path = Path(path)
    try:
        import torch

        torch.save(data, path)
    except ImportError:
        with open(path, "wb") as f:
            pickle.dump(data, f)


def load_checkpoint(path: Path) -> dict:
    """Load checkpoint dict. Tries torch.load first, falls back to pickle."""
    path = Path(path)
    try:
        import torch

        return torch.load(path, map_location="cpu", weights_only=False)
    except ImportError:
        with open(path, "rb") as f:
            return pickle.load(f)


def get_fine_tune_hyperparams(overrides: dict | None = None) -> dict:
    """Return hyperparameters for fine-tuning (lower LR, fewer epochs)."""
    params = dict(DEFAULT_HYPERPARAMS)
    params.update(FINE_TUNE_OVERRIDES)
    if overrides:
        params.update(overrides)
    return params
