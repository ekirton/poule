(*
 * Example: proof style issues for /proof-lint.
 *
 * This file intentionally contains lint-worthy patterns:
 * - Unnecessary tactics (simpl before reflexivity)
 * - Overly verbose tactic chains
 * - Deprecated names (app_length → length_app)
 * - Mixed bullet styles across different proofs
 * - Deep nesting where semicolons would be cleaner
 *)

From Coq Require Import PeanoNat List Lia.
Import ListNotations.

(** Unnecessary simpl before reflexivity *)
Lemma obvious_refl : forall n : nat, n = n.
Proof.
  intros n.
  simpl.
  trivial.
Qed.

(** Overly verbose: manual steps where auto suffices *)
Lemma verbose_and : forall P Q : Prop, P -> Q -> P /\ Q.
Proof.
  intros P Q Hp Hq.
  split.
  - exact Hp.
  - exact Hq.
Qed.

(** Uses deprecated name app_length (renamed to length_app in 8.20) *)
Lemma len_append : forall (A : Type) (l1 l2 : list A),
  length (l1 ++ l2) = length l1 + length l2.
Proof.
  intros A l1 l2.
  apply app_length.
Qed.

(** Unnecessarily complex: rewrite then simpl then trivial where
    a single tactic (apply or lia) suffices *)
Lemma overcomplicated : forall n m : nat,
  n + m = m + n.
Proof.
  intros n m.
  rewrite Nat.add_comm.
  simpl.
  trivial.
Qed.

(** Deep nesting instead of semicolons *)
Lemma deep_nesting : forall n : nat,
  n + 0 = n /\ 0 + n = n /\ n * 1 = n.
Proof.
  intro n. split.
  - apply Nat.add_0_r.
  - split.
    + apply Nat.add_0_l.
    + apply Nat.mul_1_r.
Qed.

(** Uses star bullets in one proof, dashes in another — inconsistent
    across the file (lint should flag cross-proof inconsistency) *)
Lemma star_bullets : forall n : nat, n + 0 = n /\ 0 + n = n.
Proof.
  intro n. split.
  * apply Nat.add_0_r.
  * apply Nat.add_0_l.
Qed.

(** Unnecessary unfold + fold pattern *)
Lemma unfold_fold : forall n : nat, S n = n + 1.
Proof.
  intros n.
  unfold Nat.add.
  fold Nat.add.
  lia.
Qed.
