(*
 * Example: dependent types and the convoy pattern.
 *
 * Provides scenarios for:
 * - Reverting hypotheses before destruct (test 4.17)
 * - Convoy pattern generation (test 4.18)
 *)

From Coq Require Import PeanoNat.

(** A length-indexed vector type *)
Inductive vec (A : Type) : nat -> Type :=
  | vnil  : vec A 0
  | vcons : forall n, A -> vec A n -> vec A (S n).

Arguments vnil {A}.
Arguments vcons {A n}.

(** Head of a non-empty vector — uses dependent match with convoy pattern *)
Definition vhead {A : Type} {n : nat} (v : vec A (S n)) : A :=
  match v in vec _ m return match m with O => unit | S _ => A end with
  | vnil     => tt
  | vcons h _ => h
  end.

(** Tail of a non-empty vector *)
Definition vtail {A : Type} {n : nat} (v : vec A (S n)) : vec A n :=
  match v in vec _ m return match m with O => unit | S k => vec A k end with
  | vnil      => tt
  | vcons _ t => t
  end.

(** A lemma requiring revert before destruct on the length index.
    Without reverting v, destructing n loses the connection between
    n and the vector's length. *)
Lemma vhead_vcons : forall (A : Type) (n : nat) (x : A) (xs : vec A n),
  vhead (vcons x xs) = x.
Proof.
  intros A n x xs.
  reflexivity.
Qed.

(** Map over a vector — exercises the convoy pattern *)
Fixpoint vmap {A B : Type} {n : nat} (f : A -> B) (v : vec A n) : vec B n :=
  match v in vec _ m return vec B m with
  | vnil      => vnil
  | vcons h t => vcons (f h) (vmap f t)
  end.

(** Composing vmap — requires careful dependent reasoning *)
Lemma vmap_vmap : forall (A B C : Type) (n : nat) (f : A -> B) (g : B -> C) (v : vec A n),
  vmap g (vmap f v) = vmap (fun x => g (f x)) v.
Proof.
  intros A B C n f g v.
  induction v as [| m x xs IH].
  - reflexivity.
  - simpl. rewrite IH. reflexivity.
Qed.
