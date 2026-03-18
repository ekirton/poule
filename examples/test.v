(*
 * Minimal fixture for contract tests.
 *
 * Provides a proof named test_proof that exercises standard library
 * constructs (nat, list, Prop) so that contract tests can open a
 * session against this file and issue introspection commands
 * (Print Universes, Check, About, Print Assumptions, etc.).
 *)

From Stdlib Require Import PeanoNat.
From Stdlib Require Import List.
Import ListNotations.

Lemma test_proof : forall n m : nat, n + m = m + n.
Proof.
  intros n m.
  apply Nat.add_comm.
Qed.
