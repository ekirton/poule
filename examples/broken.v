(*
 * Example: proofs broken by Coq version upgrade.
 *
 * This file intentionally does NOT compile under Coq 9.1.
 * It simulates a project that worked under Coq 8.13 but broke
 * after upgrading. Use with /proof-repair to test automated
 * repair of version-incompatible proofs.
 *
 * NOT included in _CoqProject — add it to test /proof-repair:
 *   echo "broken.v" >> _CoqProject
 *
 * Errors this file produces:
 * 1. Omega module removed (use Lia instead)
 * 2. omega tactic removed (use lia instead)
 * 3. fourier tactic removed (use lra instead)
 *)

(* Error 1: Omega was removed in Coq 8.14+ *)
From Coq Require Import Omega.
From Coq Require Import PeanoNat.

(* Error 2: omega tactic no longer exists *)
Lemma add_0_r_broken : forall n : nat, n + 0 = n.
Proof.
  intros n. omega.
Qed.

Lemma add_comm_broken : forall n m : nat, n + m = m + n.
Proof.
  intros n m. omega.
Qed.

(* Error 3: fourier was removed — use lra *)
From Coq Require Import Reals.
Open Scope R_scope.

Lemma r_add_comm_broken : forall x y : R, x + y = y + x.
Proof.
  intros x y. fourier.
Qed.
