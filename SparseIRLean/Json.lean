namespace SparseIRLean

/-- The frozen canonical envelope schema version for SparseIR v0. -/
def schemaVersion : String := "0.2"

/-- Stage 0 freezes the transport contract but does not parse problem payloads. -/
def problemParserAvailable : Bool := false

end SparseIRLean
