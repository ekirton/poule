(*
 * Example: Flocq floating-point arithmetic.
 *
 * Provides scenarios for:
 * - Debugging why simpl doesn't reduce bpow (test 2.10)
 *)

From Flocq Require Import Zaux Raux Defs BinarySingleNaN.
From Coq Require Import Reals Lra.
Open Scope R_scope.

(** bpow is opaque to simpl because Flocq defines it via a fixpoint
    on Z that doesn't reduce on symbolic arguments. *)

Lemma bpow_example : bpow radix2 3 = 8%R.
Proof.
  unfold bpow. simpl. lra.
Qed.

(** A goal where simpl can't reduce bpow on a variable exponent *)
Lemma bpow_nonneg_example : forall e : Z, (0 <= bpow radix2 e)%R.
Proof.
  intro e.
  (* simpl does nothing here — bpow won't reduce on variable e *)
  apply bpow_ge_0.
Qed.
