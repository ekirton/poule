(*
 * Contract test fixture for Hammer Automation tests.
 *
 * Imports CoqHammer so that sauto/qauto/hammer tactics are available.
 * Provides a simple lemma (hammer_test) that sauto can solve quickly.
 *)

From Hammer Require Import Hammer.
From Coq Require Import PeanoNat.

Lemma hammer_test : forall n : nat, n + 0 = n.
Proof.
  intros n.
  apply Nat.add_0_r.
Qed.
