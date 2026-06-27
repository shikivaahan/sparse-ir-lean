namespace SparseIRLean

/-- Domain-agnostic result vocabulary frozen for the verifier subprocess seam. -/
inductive ResultKind where
  | info
  | staticError
  | compiled
  | stateInitialized
  | acceptStep
  | acceptSolved
  | incomplete
  | reject
  | auditRendered
  | artifactEmitted
  deriving Repr, BEq

end SparseIRLean
