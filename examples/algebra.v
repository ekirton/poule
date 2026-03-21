(*
 * Example: algebraic properties with multiple proof approaches.
 *
 * Provides scenarios for:
 * - Checking a lemma with implicit arguments (tests 2.2, 2.7)
 * - Comparing axiom profiles of alternative proofs (test 2.9)
 * - Profiling proof performance (tests 8.1, 8.3, 8.4)
 *)

From Coq Require Import PeanoNat ZArith Lia.

(** --- A lemma with implicit arguments for inspection --- *)

Lemma my_lemma : forall (A : Type) (f : A -> A) (x : A),
  f x = f x.
Proof.
  intros A f x. reflexivity.
Qed.

(** --- Three alternative proofs of the same fact ---
    Each has a different axiom profile. *)

(** Proof 1: direct computation, no axioms *)
Lemma add_0_r_v1 : forall n : nat, n + 0 = n.
Proof.
  induction n as [| n' IH].
  - reflexivity.
  - simpl. rewrite IH. reflexivity.
Qed.

(** Proof 2: using stdlib, no axioms *)
Lemma add_0_r_v2 : forall n : nat, n + 0 = n.
Proof.
  intro n. apply Nat.add_0_r.
Qed.

(** Proof 3: using lia (omega), may depend on different lemma chains *)
Lemma add_0_r_v3 : forall n : nat, n + 0 = n.
Proof.
  intro n. lia.
Qed.

(** --- Ring-like properties for profiling --- *)

Lemma ring_morph : forall a b c : nat,
  a * (b + c) = a * b + a * c.
Proof.
  intros a b c.
  induction a as [| a' IH].
  - reflexivity.
  - simpl. rewrite IH. lia.
Qed.

Lemma ring_assoc : forall a b c : nat,
  a * (b * c) = (a * b) * c.
Proof.
  intros a b c.
  induction a as [| a' IH].
  - reflexivity.
  - simpl. rewrite IH. lia.
Qed.

Lemma ring_comm : forall a b : nat,
  a * b = b * a.
Proof.
  intros a b.
  induction a as [| a' IH].
  - simpl. lia.
  - simpl. rewrite IH. lia.
Qed.

(** Z arithmetic — additional profiling targets *)
Open Scope Z_scope.

Lemma zadd_shuffle : forall a b c d : Z,
  (a + b) + (c + d) = (a + c) + (b + d).
Proof.
  intros. lia.
Qed.

Lemma zmul_expand : forall a b : Z,
  (a + b) * (a + b) = a * a + 2 * a * b + b * b.
Proof.
  intros. lia.
Qed.
