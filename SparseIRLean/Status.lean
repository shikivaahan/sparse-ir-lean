namespace SparseIRLean

/-- Domain-agnostic result vocabulary frozen for the verifier subprocess seam. -/
inductive ResultKind where
  | staticError
  | acceptStep
  | acceptSolved
  | incomplete
  | reject
  deriving Repr, BEq

end SparseIRLean
