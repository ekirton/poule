(*
 * Example: automation tactics, hint databases, and custom Ltac.
 *
 * Provides scenarios for:
 * - auto vs eauto differences (test 7.1)
 * - Hint database inspection (tests 7.4, 7.8)
 * - auto using wrong lemma / competing hints (test 7.6)
 * - Custom Ltac tactic profiling (test 8.7)
 *)

From Coq Require Import PeanoNat List Lia.
Import ListNotations.

(** --- auto vs eauto ---
    auto cannot solve existential goals; eauto can. *)

Lemma eauto_needed : forall n : nat, exists m, m = n + 1.
Proof.
  intros n.
  (* auto would fail here — it doesn't instantiate existentials *)
  eauto.
Qed.

(** --- Hint databases --- *)

Definition double (n : nat) : nat := n + n.

Lemma double_0 : double 0 = 0.
Proof. reflexivity. Qed.

Lemma double_S : forall n, double (S n) = S (S (double n)).
Proof. intros n. unfold double. lia. Qed.

Create HintDb my_hints.
#[export] Hint Resolve double_0 : my_hints.
#[export] Hint Resolve double_S : my_hints.

(** A goal solvable with the custom hint database *)
Lemma double_2 : double 1 = 2.
Proof. auto with my_hints. Qed.

(** --- Competing hints ---
    When multiple hints match, auto picks the first that succeeds. *)

Lemma add_comm_alt : forall n m, n + m = m + n.
Proof. intros. lia. Qed.

#[export] Hint Resolve Nat.add_comm : my_hints.
#[export] Hint Resolve add_comm_alt : my_hints.

(** auto will use whichever hint it finds first *)
Lemma add_comm_test : 3 + 5 = 5 + 3.
Proof. auto with my_hints. Qed.

(** --- Custom Ltac --- *)

(** A custom tactic that tries multiple strategies *)
Ltac my_crush :=
  intros;
  try reflexivity;
  try lia;
  try (simpl; auto with my_hints);
  try (unfold double in *; lia).

Lemma crush_test_1 : forall n : nat, n = n.
Proof. my_crush. Qed.

Lemma crush_test_2 : forall n, n + 0 = n.
Proof. my_crush. Qed.

Lemma crush_test_3 : forall n, double n = n + n.
Proof. my_crush. Qed.

(** A slightly more complex custom tactic with sub-tactics *)
Ltac destruct_and :=
  match goal with
  | [ H : _ /\ _ |- _ ] => destruct H; destruct_and
  | _ => idtac
  end.

Ltac my_solver :=
  intros;
  destruct_and;
  auto.

Lemma solver_test : forall P Q R : Prop,
  P /\ Q /\ R -> R /\ P.
Proof. my_solver. Qed.
