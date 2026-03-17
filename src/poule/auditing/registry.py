"""Known-axiom registry for axiom classification.

Module-level constants loaded at import time.
"""

from __future__ import annotations

from poule.auditing.types import AxiomCategory

# Static registry mapping fully qualified axiom names to (category, explanation).
KNOWN_AXIOMS: dict[str, tuple[AxiomCategory, str]] = {
    # Classical
    "Coq.Logic.Classical_Prop.classic": (
        AxiomCategory("classical"),
        "Law of excluded middle: for any proposition P, either P or its negation holds.",
    ),
    "Coq.Logic.Classical_Prop.NNPP": (
        AxiomCategory("classical"),
        "Double-negation elimination: if not-not-P then P.",
    ),
    "Coq.Logic.ClassicalEpsilon.excluded_middle_informative": (
        AxiomCategory("classical"),
        "Informative excluded middle: decidability of all propositions with computational content.",
    ),
    "Coq.Logic.Decidable.dec_not_not": (
        AxiomCategory("classical"),
        "Decidable double negation: double-negation elimination for decidable propositions.",
    ),
    # Extensionality
    "Coq.Logic.FunctionalExtensionality.functional_extensionality_dep": (
        AxiomCategory("extensionality"),
        "Dependent functional extensionality: pointwise-equal functions are equal.",
    ),
    "Coq.Logic.PropExtensionality.propositional_extensionality": (
        AxiomCategory("extensionality"),
        "Propositional extensionality: logically equivalent propositions are equal.",
    ),
    # Choice
    "Coq.Logic.IndefiniteDescription.constructive_indefinite_description": (
        AxiomCategory("choice"),
        "Indefinite description: extract a witness from an existential proof.",
    ),
    "Coq.Logic.ClassicalChoice.choice": (
        AxiomCategory("choice"),
        "Classical axiom of choice: every total relation contains a function.",
    ),
    "Coq.Logic.Epsilon.epsilon": (
        AxiomCategory("choice"),
        "Hilbert's epsilon operator: select an element satisfying a predicate.",
    ),
    # Proof irrelevance
    "Coq.Logic.ProofIrrelevance.proof_irrelevance": (
        AxiomCategory("proof_irrelevance"),
        "Proof irrelevance: all proofs of a Prop are equal.",
    ),
    "Coq.Logic.JMeq.JMeq_eq": (
        AxiomCategory("proof_irrelevance"),
        "Heterogeneous equality collapse: JMeq implies eq when types match.",
    ),
}

# Module-prefix mappings for Stage 2 classification.
# Ordered list of (prefix, category) tuples, checked in order.
MODULE_PREFIXES: list[tuple[str, AxiomCategory]] = [
    ("Coq.Logic.Classical_Prop", AxiomCategory("classical")),
    ("Coq.Logic.ClassicalEpsilon", AxiomCategory("classical")),
    ("Coq.Logic.FunctionalExtensionality", AxiomCategory("extensionality")),
    ("Coq.Logic.PropExtensionality", AxiomCategory("extensionality")),
    ("Coq.Logic.ChoiceFacts", AxiomCategory("choice")),
    ("Coq.Logic.IndefiniteDescription", AxiomCategory("choice")),
    ("Coq.Logic.ClassicalChoice", AxiomCategory("choice")),
    ("Coq.Logic.Epsilon", AxiomCategory("choice")),
    ("Coq.Logic.ProofIrrelevance", AxiomCategory("proof_irrelevance")),
    ("Coq.Logic.ProofIrrelevanceFacts", AxiomCategory("proof_irrelevance")),
]
