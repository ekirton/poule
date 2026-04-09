# Proposal: Leave-One-Library-Out Cross-Validation with Cap=1000

## Status

Future proposal — diagnostic experiment to determine whether library-level data leakage is the bottleneck for tactic prediction generalization.

## Problem

The tactic prediction model's current file-level split (`position % 10`) scatters files from the same library across train/val/test. Libraries share tactic conventions — MathComp uses SSReflect idioms (`move`, `congr`, `suff`, `wlog`), stdlib favors `destruct`/`induction`, stdpp has its own automation patterns. The model may learn library identity rather than generalizable proof-state-to-tactic mappings.

Evidence of leakage:
- 35pp val-test gap before undersampling (val_acc@5=80.2%, test_acc@5=45.2%)
- 6pp val-test gap after undersampling — but val and test both contain files from the same libraries as training, so this gap measures within-library generalization, not cross-library transfer
- 44 of 65 tactic families remain dead (zero recall on test set)
- SSReflect-specific tactics (`congr`, `wlog`, `suff`) are dead in all models

The core question: **is library-level leakage the bottleneck, or are the dead families simply too rare regardless of split strategy?**

## Proposed Experiment

### Design

**Leave-one-library-out cross-validation (LOOCV)** across the 5 vanilla-Coq libraries: stdlib, stdpp, flocq, coquelicot, coqinterval. MathComp is excluded: 71% of its steps use SSReflect-dialect tactics (`by` alone is 42.5%), making it a different tactic language rather than a transferable signal.

For each fold:
1. Hold out one library entirely as the test set
2. Split remaining libraries' files 90/10 (file-level, seeded shuffle) for train/val
3. Apply head-class undersampling with cap=1000 per family (down from 2,000)
4. Train with the best HPO hyperparams from the undersampled experiment (6 layers, lr=1.07e-5, batch_size=64, alpha=0.065, label_smoothing=0.190, sam_rho=0.180, lambda_within=1.93, embedding_dim=128)
5. Evaluate on the held-out library

**Why cap=1000**: Holding out an entire library shrinks the training set. The previous cap=2000 was tuned for 40K training samples; with one library removed, training could be 25-35K. A lower cap keeps head-class ratios in check with the smaller pool and further forces the model to learn minority families.

**Validation strategy**: Val comes from training-distribution libraries (not the held-out library) so early stopping gets a proper signal. The test set is a completely unseen library — true generalization.

### Expected libraries and approximate sizes

| Library | Est. steps | Vanilla % | Notes |
|---------|-----------|-----------|-------|
| stdlib | ~44K | 99% | Largest; core Coq tactics |
| flocq | ~24K | 99% | Floating-point arithmetic |
| coquelicot | ~23K | 78% | Real analysis; moderate SSReflect usage |
| stdpp | ~9K | 86% | Iris-style automation |
| coqinterval | ~8K | 88% | Interval arithmetic |
| ~~mathcomp~~ | ~~~33K~~ | ~~29%~~ | **Excluded** — 71% SSReflect dialect |

Holding out stdlib is the easiest test (most training data remains). Holding out a small library like coqinterval is the hardest test (model must generalize from very different libraries to a specialized domain).

### Interpretation guide

| Outcome | Meaning | Next step |
|---------|---------|-----------|
| Mean test_acc@5 ≈ 57% (current baseline) | Library leakage is not the bottleneck; dead families are a class-imbalance/data-scarcity problem | Focus on data augmentation, focal loss, or more training data for rare families |
| Mean test_acc@5 drops to 30-40% | Library conventions dominate; model learns library style, not proof structure | Adopt a library-aware split (Option D hybrid) for the production model; consider library-adversarial training |
| High variance across folds (e.g., 60% on stdlib-held-out, 30% on coqinterval-held-out) | Some libraries transfer well, others don't | Investigate which libraries are "hard" and why; may need library-specific heads or adapters |
| Dead families decrease when their library is in training | Confirms the dead families are library-specific, not universally rare | Library-balanced training data is the fix |

## Implementation

### New code

**`src/Poule/neural/training/data.py`** — add `TrainingDataLoader.load_by_library()`:

```python
@staticmethod
def load_by_library(
    library_paths: dict[str, list[Path]],
    held_out_library: str,
    val_fraction: float = 0.1,
    seed: int = 42,
) -> TacticDataset:
```

- Reads all JSONL files, tagging each step with its library (from the dict key)
- Held-out library → test_pairs
- Remaining libraries' files → 90/10 train/val via seeded file-level shuffle
- Same taxonomy lookup, category indexing, and label map construction as `load()`

**`src/Poule/neural/training/loocv.py`** (new) — orchestration:

```python
@dataclass
class FoldResult:
    held_out_library: str
    train_samples: int
    val_samples: int
    test_samples: int
    accuracy_at_1: float
    accuracy_at_5: float
    category_accuracy_at_1: float
    dead_families: int
    total_families: int
    per_family_recall: dict[str, float]
    training_time_s: float

@dataclass
class LOOCVReport:
    folds: list[FoldResult]
    undersample_cap: int
    mean_test_acc_at_5: float
    std_test_acc_at_5: float
    mean_dead_families: float
    per_library_acc_at_5: dict[str, float]

class LibraryLOOCV:
    @staticmethod
    def run(
        library_paths: dict[str, list[Path]],
        vocabulary_path: Path,
        output_dir: Path,
        undersample_cap: int = 1000,
        hyperparams: dict | None = None,
        backend: str = "mlx",
    ) -> LOOCVReport:
```

For each library: load with held-out split → undersample at cap → train → evaluate → collect FoldResult → delete checkpoint. Aggregate at end.

**`src/Poule/cli/commands.py`** — add `loocv` command:

```python
@cli.command("loocv")
@click.argument("data", nargs=-1, required=True)
@click.option("--output-dir", required=True, type=click.Path())
@click.option("--vocabulary", required=True, type=click.Path(exists=True))
@click.option("--undersample-cap", default=1000, type=int)
@click.option("--backend", default="mlx", type=click.Choice(["mlx", "pytorch"]))
```

Library name inferred from JSONL filename stem (e.g., `stdlib.jsonl` → `"stdlib"`).

### Spec and doc updates

- **`specification/neural-training.md`**: Add section documenting the `load_by_library()` split contract
- **`doc/neural-network-tactic-prediction.md`**: Add LOOCV results section after undersampled results (filled in after running)

## Verification

1. **Unit test** (`test/unit/test_loocv.py`): 3 mock libraries, 10 files each. Verify held-out library appears only in test, val comes from non-held-out libraries, undersampling applied.
2. **Dry run**: `poule loocv stdlib.jsonl mathcomp.jsonl ... --output-dir tmp --vocabulary coq-vocabulary.json --undersample-cap 1000` with `max_epochs=1` to verify pipeline correctness.
3. **Full run**: All 6 folds, `max_epochs=20, patience=3`. Estimated wall time: ~9 hours (6 folds x ~1.5h each, smaller training sets than the 1.85h cap=2000 run).
4. **Analysis**: Compare mean test_acc@5 and dead-family counts to the 57.0% / 44-dead baseline. Record per-fold breakdown.

## Files modified

| File | Change |
|------|--------|
| `src/Poule/neural/training/data.py` | Add `load_by_library()` method |
| `src/Poule/neural/training/loocv.py` | New: `LibraryLOOCV`, `FoldResult`, `LOOCVReport` |
| `src/Poule/cli/commands.py` | Add `loocv` command |
| `specification/neural-training.md` | Add library-level split spec |
| `doc/neural-network-tactic-prediction.md` | Add LOOCV results section |
| `test/unit/test_loocv.py` | New: unit tests for library-level splitting |
