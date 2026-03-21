(*
 * Example: typeclasses, Proper instances, and setoid rewriting.
 *
 * Provides scenarios for:
 * - Typeclass resolution tracing (tests 2.5, 7.9)
 * - Comparing rewrite vs setoid_rewrite (test 4.4)
 * - Generating Proper instances (test 4.21)
 *)

From Coq Require Import Setoid Morphisms RelationClasses.
From Coq Require Import PeanoNat List Lia.
Import ListNotations.

(** An equivalence relation on lists: same length *)
Definition list_equiv {A : Type} (l1 l2 : list A) : Prop :=
  length l1 = length l2.

#[export] Instance list_equiv_Equivalence (A : Type) :
  Equivalence (@list_equiv A).
Proof.
  constructor.
  - intro x. reflexivity.
  - intros x y H. symmetry. exact H.
  - intros x y z H1 H2. unfold list_equiv in *.
    rewrite H1. exact H2.
Qed.

(** A union function that respects list_equiv *)
Definition list_union {A : Type} (l1 l2 : list A) : list A := l1 ++ l2.

#[export] Instance list_union_Proper (A : Type) :
  Proper (@list_equiv A ==> @list_equiv A ==> @list_equiv A) (@list_union A).
Proof.
  intros l1 l1' H1 l2 l2' H2.
  unfold list_equiv, list_union in *.
  rewrite !length_app. lia.
Qed.

(** A lemma provable with setoid_rewrite but not plain rewrite *)
Lemma union_equiv_compat :
  forall (A : Type) (l1 l1' l2 l2' : list A),
    list_equiv l1 l1' ->
    list_equiv l2 l2' ->
    list_equiv (list_union l1 l2) (list_union l1' l2').
Proof.
  intros A l1 l1' l2 l2' H1 H2.
  rewrite H1. rewrite H2. reflexivity.
Qed.

(** A simple typeclass for demonstration *)
Class Measurable (A : Type) := {
  measure : A -> nat;
  measure_nonneg : forall x, 0 <= measure x;
}.

#[export] Instance nat_Measurable : Measurable nat := {
  measure := fun n => n;
  measure_nonneg := fun _ => Nat.le_0_l _;
}.

#[export] Instance list_Measurable (A : Type) : Measurable (list A) := {
  measure := @length A;
  measure_nonneg := fun _ => Nat.le_0_l _;
}.

(** A goal requiring typeclass resolution *)
Lemma measure_app_length :
  forall (A : Type) (l1 l2 : list A),
    measure (l1 ++ l2) = measure l1 + measure l2.
Proof.
  intros A l1 l2.
  simpl. apply length_app.
Qed.
