# Class Imbalance in Neural Network Training: State of the Art (April 2026)

A survey of techniques for training neural networks on class-imbalanced data, with emphasis on classification tasks where a small number of classes dominate the training distribution and a long tail of classes have few examples. Synthesized from survey literature, NeurIPS/CVPR/ICLR publications, and recent empirical studies.

Cross-references:
- [neural-retrieval.md](neural-retrieval.md) — Neural architectures for formal math
- [neural-encoder-architectures-premise-selection.md](neural-encoder-architectures-premise-selection.md) — Encoder training strategies

---

## 1. Problem Characterization

Class imbalance occurs when training data has substantially unequal representation across classes. In the extreme case — *long-tailed distributions* — a few head classes contain most examples while thousands of tail classes have single-digit counts. Standard cross-entropy training on such distributions is biased toward head classes: the model learns to minimize loss by predicting the majority class, achieving high average accuracy while performing poorly on the tail.

The problem is quantified by the *imbalance ratio* (IR): the count of the largest class divided by the count of the smallest. Benchmarks in the literature range from IR = 10 (mild) to IR = 200 (severe). Real-world datasets commonly exceed IR = 100.

**Key observations from the literature:**

1. Standard empirical risk minimization (ERM) degrades sharply as IR increases. On CIFAR-100 with IR = 100, ERM achieves 47.7% accuracy vs. 78% on the balanced version (Shwartz-Ziv et al., 2023).
2. Tail-class performance drops disproportionately. In long-tailed ImageNet (Liu et al., 2019), head-class accuracy is ~65% while tail-class accuracy is ~10%.
3. Neural networks learn high-quality representations even from imbalanced data — the classifier layer, not the feature extractor, is the primary source of bias (Kang et al., 2020).

---

## 2. Taxonomy of Approaches

The literature organizes imbalance-handling techniques into four categories (Zhang et al., 2025):

| Category | Mechanism | Representative Methods |
|----------|-----------|----------------------|
| **Data re-balancing** | Modify the training distribution | SMOTE, Mixup, GAN-based generation, undersampling |
| **Loss re-weighting** | Assign differential costs per class or sample | Focal loss, class-balanced loss, LDAM, balanced softmax |
| **Training strategy** | Adjust the learning procedure | Decoupled training, curriculum learning, posterior re-calibration |
| **Ensemble methods** | Combine multiple models | Bagging, boosting, knowledge distillation |

---

## 3. Data-Level Methods

### 3.1 Oversampling

**Random oversampling** duplicates minority examples. Simple and effective at small scale, but causes overfitting when tail classes have very few examples — the model memorizes the duplicated samples.

**SMOTE** (Chawla et al., 2002) generates synthetic minority samples by interpolating between a sample and its k-nearest neighbors in feature space. Widely used for tabular data; less effective for high-dimensional inputs (images, sequences) where interpolation in input space produces unrealistic examples.

| Method | Strengths | Weaknesses |
|--------|-----------|------------|
| Random oversampling | Zero-cost, no hyperparameters | Overfitting on tail classes |
| SMOTE | Generates diverse samples, well-studied | Poor in high-dimensional spaces, computationally expensive at scale |
| Mixup / CutMix | Works in embedding space, regularizes | Requires careful tuning of interpolation ratio |
| GAN / diffusion generation | High-fidelity synthetic data | Expensive to train, mode collapse risk |

### 3.2 Undersampling

Removes majority-class examples to balance the distribution. Tomek Links and NearMiss are the standard approaches. The fundamental trade-off: undersampling discards potentially valuable data. Effective when the majority class has high redundancy; harmful when it does not.

### 3.3 Hybrid Sampling

Combines oversampling of the minority with undersampling of the majority (e.g., SMOTE + Tomek Links). Generally outperforms either in isolation but introduces two sets of hyperparameters.

---

## 4. Loss Function Methods

### 4.1 Inverse-Frequency Weighting

The simplest re-weighting: scale each class's loss contribution by the inverse of its frequency. For a class with $n_c$ examples out of $N$ total, the weight is $N / n_c$. Effective for moderate imbalance but unstable at extreme ratios — rare classes receive enormous gradients that destabilize training.

### 4.2 Class-Balanced Loss (Cui et al., 2019)

Introduces the *effective number of samples*: as class size grows, each additional sample provides diminishing marginal information due to data overlap. The effective number is $(1 - \beta^{n_c}) / (1 - \beta)$, where $\beta \in [0, 1)$ is a hyperparameter. The class-balanced loss weights each class inversely by its effective number rather than raw count.

| Dataset | CE Baseline | CB-Focal (best β) | Improvement |
|---------|------------|-------------------|-------------|
| CIFAR-100 (IR=100) | 61.7% | 57.9% error | +3.8pp |
| iNaturalist 2018 | 42.0% | 38.2% error | +3.8pp |

The effective number framework provides a principled alternative to raw inverse-frequency weighting and is compatible with any base loss function (softmax cross-entropy, focal loss, etc.).

### 4.3 Focal Loss (Lin et al., 2017)

Originally designed for object detection, focal loss down-weights *easy* (well-classified) examples regardless of class, focusing training on hard examples:

$$\text{FL}(p_t) = -\alpha_t (1 - p_t)^\gamma \log(p_t)$$

The focusing parameter $\gamma$ controls the rate at which easy examples are down-weighted. With $\gamma = 2$ (the standard setting), an example classified with $p_t = 0.9$ receives 100× less loss than one with $p_t = 0.5$.

Focal loss is sample-level, not class-level — it does not directly address class frequency. It is most effective when combined with class-level weighting ($\alpha_t$ set by inverse frequency or effective number).

### 4.4 Label-Distribution-Aware Margin Loss (Cao et al., 2019)

LDAM encourages larger decision margins for minority classes by adding a class-dependent offset to the logits:

$$\Delta_c = C / n_c^{1/4}$$

where $C$ is a constant and $n_c$ is the class count. Combined with deferred re-balancing (DRW) — training with standard sampling initially, then switching to class-balanced sampling — LDAM-DRW is a strong baseline across benchmarks.

### 4.5 Balanced Softmax (Ren et al., 2020)

Adjusts the softmax function to account for class priors by subtracting $\log(\pi_c)$ from logits, where $\pi_c$ is the class frequency. This corrects for the bias that the standard softmax inherits from the training distribution. Conceptually simple and adds no hyperparameters beyond the known class frequencies.

---

## 5. Training Strategy Methods

### 5.1 Decoupled Training (Kang et al., 2020)

A landmark finding: representation learning and classifier learning can be separated.

**Stage 1 — Representation learning.** Train the full network (backbone + classifier) with standard instance-balanced sampling. The backbone learns high-quality features even from imbalanced data.

**Stage 2 — Classifier re-training.** Freeze the backbone. Re-initialize and retrain only the classifier layer with class-balanced sampling (cRT) or learnable scaling (τ-norm, LWS).

| Method | ImageNet-LT (top-1) | Places-LT | iNaturalist 2018 |
|--------|---------------------|-----------|-------------------|
| Instance-balanced ERM | 44.4% | 30.2% | 63.1% |
| cRT (re-trained classifier) | 49.6% | 36.7% | 68.2% |
| τ-normalized | 49.4% | 37.9% | 69.3% |
| Learnable weight scaling (LWS) | 49.9% | 37.6% | 69.5% |

**Key insight:** Data imbalance does not harm representation learning — it harms the classifier. This finding simplifies the practitioner's task: train representations normally, then fix the classifier.

### 5.2 Deferred Re-Balancing (DRW)

A two-phase schedule: train with standard (instance-balanced) sampling for most of training, then switch to class-balanced sampling for the final epochs. Used successfully with LDAM and other loss functions. DRW avoids the early-training instability of full re-weighting while correcting classifier bias in the final phase.

### 5.3 Curriculum Learning

Present examples in an order that progressively increases difficulty. For imbalanced data, this typically means training on head classes first (abundant, easy examples) before introducing tail classes. Effective but sensitive to the curriculum schedule.

---

## 6. Simplifying Training Under Imbalance (Shwartz-Ziv et al., 2023)

This NeurIPS 2023 paper challenges the necessity of specialized imbalance methods. The authors demonstrate that tuning six standard training components achieves state-of-the-art performance on imbalanced benchmarks *without* specialized loss functions or samplers.

### 6.1 Components and Findings

| Component | Finding |
|-----------|---------|
| **Batch size** | Smaller batches significantly outperform larger ones under severe imbalance, even though minority samples appear less frequently per batch. This contradicts the intuition that larger batches ensure minority representation. |
| **Data augmentation** | Effects are "greatly amplified on imbalanced data, especially for minority classes." AutoAugment outperforms TrivialAugment on imbalanced data — the optimal augmentation policy depends on imbalance severity. |
| **Architecture size** | Larger networks that perform well on balanced data *overfit* on imbalanced data. Correlation between balanced and imbalanced performance across architectures is only 0.14. |
| **Label smoothing** | Class-conditional smoothing (higher smoothing for minority classes) prevents overfitting on underrepresented groups. |
| **Optimizer** | Sharpness-Aware Minimization (SAM) with asymmetric perturbation radius improves tail-class generalization. |
| **Self-supervised pre-training** | Joint self-supervised + supervised training (Joint-SSL) improves representations for imbalanced data without requiring a separate pre-training phase. |

### 6.2 Performance Comparison

| Method | CIFAR-100 (IR=100) | CIFAR-10 (IR=100) |
|--------|--------------------|--------------------|
| ERM baseline | 47.7% | 84.9% |
| Focal Loss | 47.1% | — |
| LDAM-DRW | 47.2% | — |
| Class-balanced loss | — | — |
| M2m (oversampling) | — | 84.5% |
| **Tuned standard pipeline** | **48.9%** | **86.0%** |

### 6.3 Practical Implications

The paper's most actionable finding: well-tuned standard training routines can match or exceed specialized imbalance methods. This does not mean specialized methods are useless, but it establishes a strong baseline that should be attempted first. The authors also found that CIFAR-based imbalanced benchmarks correlate poorly (r = 0.03–0.19) with real-world imbalanced datasets, suggesting that benchmark-specific tuning does not transfer.

---

## 7. Regularization and Imbalance

### 7.1 Label Smoothing

Standard label smoothing replaces hard targets $y = 1$ with $y = 1 - \epsilon + \epsilon / K$, where $K$ is the number of classes and $\epsilon$ is the smoothing parameter. This prevents overconfident predictions and acts as a regularizer.

For imbalanced data, *class-conditional* label smoothing applies higher smoothing to minority classes. The intuition: minority classes are more prone to overfitting due to limited examples, so they benefit more from the regularization effect. Shwartz-Ziv et al. (2023) confirm this empirically.

An ICLR 2025 study (Li et al., 2025) provides theoretical grounding for why label smoothing works: it implicitly calibrates the model's confidence toward the true posterior, which is especially beneficial when some classes have few training examples.

### 7.2 Data Augmentation as Regularization

Data augmentation is a stronger regularizer for minority classes than for majority classes, because each augmented variant of a rare example provides proportionally more new information. Learned augmentation policies (AutoAugment) outperform hand-designed augmentation on imbalanced data.

---

## 8. Long-Tailed Learning: Emerging Directions

### 8.1 Supervised Contrastive Learning

Contrastive objectives (SupCon, PaCo, BCL) learn embeddings where same-class examples cluster tightly while different-class examples separate. These methods show stable performance even as imbalance severity increases, because the contrastive loss operates on pairs rather than individual examples — a minority-class example can form informative pairs with every other example.

### 8.2 Prototype Learning

Class prototype methods maintain a representative centroid for each class and classify based on distance to prototypes. This naturally equalizes representation across classes — each class has exactly one prototype regardless of sample count. Effective for extreme imbalance with minimal computational overhead.

### 8.3 Diffusion-Based Data Generation

Recent work uses diffusion models (rather than GANs) to generate synthetic minority examples. Diffusion models avoid mode collapse and produce more diverse samples than GANs, though at higher computational cost. This is an active research direction as of 2025–2026.

---

## 9. Applicability to Sequence Classification

Most class-imbalance research targets image classification. Sequence classification (NLP, formal language processing) shares the same fundamental problem but with important differences:

| Aspect | Image Classification | Sequence Classification |
|--------|---------------------|------------------------|
| SMOTE viability | Poor (pixel interpolation unrealistic) | Poor (token interpolation meaningless) |
| Mixup viability | Effective in embedding space | Effective in embedding space |
| Loss re-weighting | Standard approach | Standard approach, equally effective |
| Data augmentation | Strong gains (crop, flip, color) | Domain-dependent (back-translation, masking, paraphrase) |
| Decoupled training | Well-validated | Under-explored but architecturally applicable |
| Pre-training | Strong gains (ImageNet, self-supervised) | Strong gains (language model pre-training) |

For sequence classification on formal languages (such as proof state → tactic family prediction), the most directly applicable techniques are:

1. **Loss re-weighting** (focal loss, class-balanced loss, or inverse-frequency) — universally applicable
2. **Label smoothing** (class-conditional) — acts as regularization for rare classes
3. **Decoupled training** — train the encoder on all data, retrain the classifier head with balanced sampling
4. **Excluding or grouping rare classes** — collapsing the extreme tail into an "other" category reduces effective class count and improves tail coverage
5. **Standard pipeline tuning** (Shwartz-Ziv et al.) — smaller batch size, appropriate augmentation, smaller architecture

---

## 10. Key Findings

1. **Classifier bias, not representation bias.** Imbalanced training harms the linear classifier more than the feature extractor. Decoupled training (Kang et al., 2020) exploits this by training representations with natural sampling and re-balancing only the classifier.

2. **Standard tuning is a strong baseline.** Shwartz-Ziv et al. (2023) show that tuning batch size, augmentation, architecture size, label smoothing, optimizer, and self-supervised pre-training matches specialized imbalance methods on standard benchmarks.

3. **Class-conditional smoothing outperforms uniform smoothing.** Applying higher label smoothing to minority classes acts as targeted regularization against overfitting.

4. **Focal loss addresses sample hardness, not class frequency.** It is most effective when combined with class-level weighting. On its own, it does not address the class prior.

5. **Benchmarks may not predict real-world performance.** CIFAR-based imbalanced benchmarks show near-zero correlation with real-world deployment datasets (Shwartz-Ziv et al., 2023), suggesting that method selection should be validated on the target distribution.

6. **Oversampling in input space is fragile for non-tabular data.** SMOTE and variants produce unrealistic examples in high-dimensional or structured spaces. Embedding-space augmentation (Mixup) is more robust.

7. **Tail-class grouping is pragmatic.** When the tail contains hundreds of classes with single-digit examples, collapsing them into a catch-all category improves overall accuracy without complex engineering.

---

## References

- Cao, K., Wei, C., Gaidon, A., Arechiga, N., & Ma, T. (2019). Learning Imbalanced Datasets with Label-Distribution-Aware Margin Loss. *NeurIPS 2019*.
- Chawla, N. V., Bowyer, K. W., Hall, L. O., & Kegelmeyer, W. P. (2002). SMOTE: Synthetic Minority Over-sampling Technique. *JAIR*, 16, 321–357.
- Cui, Y., Jia, M., Lin, T.-Y., Song, Y., & Belongie, S. (2019). Class-Balanced Loss Based on Effective Number of Samples. *CVPR 2019*.
- Kang, B., Xie, S., Rohrbach, M., Yan, Z., Gordo, A., Feng, J., & Kalantidis, Y. (2020). Decoupling Representation and Classifier for Long-Tailed Recognition. *ICLR 2020*.
- Li, Y., et al. (2025). Towards Understanding Why Label Smoothing Degrades Selective Classification and How to Fix It. *ICLR 2025*.
- Lin, T.-Y., Goyal, P., Girshick, R., He, K., & Dollár, P. (2017). Focal Loss for Dense Object Detection. *ICCV 2017*.
- Liu, Z., Miao, Z., Zhan, X., Wang, J., Gong, B., & Yu, S. X. (2019). Large-Scale Long-Tailed Recognition in an Open World. *CVPR 2019*.
- Ren, J., Yu, C., Ma, X., Zhao, H., Yi, S., & Li, H. (2020). Balanced Meta-Softmax for Long-Tailed Visual Recognition. *NeurIPS 2020*.
- Shwartz-Ziv, R., Goldblum, M., Li, Y., Bruss, C. B., & Wilson, A. G. (2023). Simplifying Neural Network Training Under Class Imbalance. *NeurIPS 2023*.
- Zhang, Y., et al. (2025). A Comprehensive Survey on Imbalanced Data Learning. *arXiv:2502.08960*.
- Zheng, Z., et al. (2021). Deep Long-Tailed Learning: A Survey. *IEEE TPAMI*, 2024.
