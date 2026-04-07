(*
 * Test fixture for Hammer Automation e2e tests.
 *
 * Provides a range of goal types:
 * - Trivial goals that sauto/qauto solve instantly
 * - First-order goals that benefit from hints
 * - A goal too hard for hammer within a short timeout
 * - A multi-goal proof to test focused-goal targeting
 *
 * All lemmas are left with Admitted so proof sessions start
 * at the first goal.  The e2e tests submit hammer tactics
 * to complete them.
 *)

From Hammer Require Import Hammer.
From Coq Require Import PeanoNat.
From Coq Require Import List.
Import ListNotations.

(* --- Trivial: sauto / qauto should solve instantly --- *)

Lemma hammer_trivial_eq : forall (n : nat), n = n.
Proof.
  intro n.
Admitted.

Lemma hammer_and_comm : forall (P Q : Prop), P /\ Q -> Q /\ P.
Proof.
  intros P Q H.
Admitted.

(* --- First-order with hints --- *)

Lemma hammer_add_0_r : forall n : nat, n + 0 = n.
Proof.
  intro n.
Admitted.

Lemma hammer_add_comm : forall n m : nat, n + m = m + n.
Proof.
  intros n m.
Admitted.

(* --- List reasoning --- *)

Lemma hammer_app_nil_r : forall (A : Type) (l : list A), l ++ [] = l.
Proof.
  intros A l.
Admitted.

(* --- Hard goal: unlikely to solve in 2 seconds --- *)

Lemma hammer_hard : forall (f : nat -> nat),
  (forall x y, f (x + y) = f x + f y) ->
  (forall x, f (x * 2) = f x * 2).
Proof.
  intros f Hadd x.
Admitted.

(* --- Multi-subgoal: hammer targets focused goal only --- *)

Lemma hammer_multi_goal : forall (n m : nat),
  n + 0 = n /\ m + 0 = m.
Proof.
  intros n m.
  split.
  (* First subgoal: n + 0 = n — hammer should close this *)
Admitted.
