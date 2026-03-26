"""Known-axiom registry for axiom classification.

Module-level constants loaded at import time.
"""

from __future__ import annotations

from Poule.auditing.types import AxiomCategory

# Static registry mapping fully qualified axiom names to (category, explanation).
KNOWN_AXIOMS: dict[str, tuple[AxiomCategory, str]] = {
    # Classical
    "Stdlib.Logic.Classical_Prop.classic": (
        AxiomCategory("classical"),
        "Law of excluded middle: for any proposition P, either P or its negation holds.",
    ),
    "Stdlib.Logic.Classical_Prop.NNPP": (
        AxiomCategory("classical"),
        "Double-negation elimination: if not-not-P then P.",
    ),
    "Stdlib.Logic.ClassicalEpsilon.excluded_middle_informative": (
        AxiomCategory("classical"),
        "Informative excluded middle: decidability of all propositions with computational content.",
    ),
    "Stdlib.Logic.Decidable.dec_not_not": (
        AxiomCategory("classical"),
        "Decidable double negation: double-negation elimination for decidable propositions.",
    ),
    # Extensionality
    "Stdlib.Logic.FunctionalExtensionality.functional_extensionality_dep": (
        AxiomCategory("extensionality"),
        "Dependent functional extensionality: pointwise-equal functions are equal.",
    ),
    "Stdlib.Logic.PropExtensionality.propositional_extensionality": (
        AxiomCategory("extensionality"),
        "Propositional extensionality: logically equivalent propositions are equal.",
    ),
    # Choice
    "Stdlib.Logic.IndefiniteDescription.constructive_indefinite_description": (
        AxiomCategory("choice"),
        "Indefinite description: extract a witness from an existential proof.",
    ),
    "Stdlib.Logic.ClassicalChoice.choice": (
        AxiomCategory("choice"),
        "Classical axiom of choice: every total relation contains a function.",
    ),
    "Stdlib.Logic.Epsilon.epsilon": (
        AxiomCategory("choice"),
        "Hilbert's epsilon operator: select an element satisfying a predicate.",
    ),
    # Proof irrelevance
    "Stdlib.Logic.ProofIrrelevance.proof_irrelevance": (
        AxiomCategory("proof_irrelevance"),
        "Proof irrelevance: all proofs of a Prop are equal.",
    ),
    "Stdlib.Logic.JMeq.JMeq_eq": (
        AxiomCategory("proof_irrelevance"),
        "Heterogeneous equality collapse: JMeq implies eq when types match.",
    ),
}

# Module-prefix mappings for Stage 2 classification.
# Ordered list of (prefix, category) tuples, checked in order.
MODULE_PREFIXES: list[tuple[str, AxiomCategory]] = [
    ("Stdlib.Logic.Classical_Prop", AxiomCategory("classical")),
    ("Stdlib.Logic.ClassicalEpsilon", AxiomCategory("classical")),
    ("Stdlib.Logic.FunctionalExtensionality", AxiomCategory("extensionality")),
    ("Stdlib.Logic.PropExtensionality", AxiomCategory("extensionality")),
    ("Stdlib.Logic.ChoiceFacts", AxiomCategory("choice")),
    ("Stdlib.Logic.IndefiniteDescription", AxiomCategory("choice")),
    ("Stdlib.Logic.ClassicalChoice", AxiomCategory("choice")),
    ("Stdlib.Logic.Epsilon", AxiomCategory("choice")),
    ("Stdlib.Logic.ProofIrrelevance", AxiomCategory("proof_irrelevance")),
    ("Stdlib.Logic.ProofIrrelevanceFacts", AxiomCategory("proof_irrelevance")),
]
