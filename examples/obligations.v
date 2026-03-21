(*
 * Example: incomplete proofs and axiom declarations.
 *
 * Provides scenarios for:
 * - Scanning for proof obligations (/proof-obligations)
 * - Auditing axiom dependencies (test 2.8)
 *
 * This file intentionally contains Admitted proofs, admit tactics,
 * and Axiom declarations as test targets.
 *)

From Coq Require Import PeanoNat List.
Import ListNotations.

(** An axiom — classical logic not provable in Coq *)
Axiom classic : forall P : Prop, P \/ ~ P.

(** An axiom used as a placeholder for an unproven assumption *)
Axiom list_length_nonneg : forall (A : Type) (l : list A), 0 <= length l.

(** An Admitted proof — work in progress *)
Lemma mul_comm_todo : forall n m : nat, n * m = m * n.
Proof.
  intros n m.
  induction n as [| n' IH].
  - simpl.
    (* TODO: finish this case *)
    admit.
  - simpl.
    admit.
Admitted.

(** Another Admitted proof with no progress *)
Lemma app_assoc_todo : forall (A : Type) (l1 l2 l3 : list A),
  l1 ++ (l2 ++ l3) = (l1 ++ l2) ++ l3.
Proof.
Admitted.

(** A completed proof that depends on the classic axiom *)
Lemma not_not_elim : forall P : Prop, ~ ~ P -> P.
Proof.
  intros P Hnn.
  destruct (classic P) as [Hp | Hnp].
  - exact Hp.
  - exfalso. apply Hnn. exact Hnp.
Qed.
