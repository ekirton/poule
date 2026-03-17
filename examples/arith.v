From Stdlib Require Import PeanoNat.

Lemma add_comm : forall n m : nat, n + m = m + n.
Proof.
  intros n m.
  apply Nat.add_comm.
Qed.
