import SparseIRLean

open SparseIRLean

def assertTrue (message : String) (condition : Bool) : IO Unit :=
  unless condition do
    throw <| IO.userError message

def main : IO UInt32 := do
  assertTrue "canonical schema version changed" (schemaVersion == "0.2")
  assertTrue "v0 domain changed" (Zebra.domainId == "zebra")
  assertTrue "Stage 1 parser leaked into Stage 0" (!problemParserAvailable)
  assertTrue "Stage 1 Zebra AST leaked into Stage 0" (!Zebra.astAvailable)
  assertTrue "checker leaked into Stage 0" (!CheckerCore.available)
  assertTrue "audit renderer leaked into Stage 0" (!Pretty.available)
  IO.println "Stage 0 Lean boundary checks passed"
  pure 0
