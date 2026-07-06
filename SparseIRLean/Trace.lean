import Lean.Data.Json
import SparseIRLean.Candidate

open Lean

namespace SparseIRLean

structure TraceCell where
  category : Zebra.CategoryName
  house : Nat
  value : Zebra.ValueName
  deriving Repr, BEq

/-- Public justification for a `place`/`eliminate` step.

This is the *Stage 4* honest AST: it admits only what the spec allows a model
to emit on the public trace surface.

* `clue clueId fromCells?` — a step justified by a single clue id (an optional
  `from` list is allowed and provides referenced cells).
* `bijection fromCells?` — a step justified by the structural bijection rule.
  The 22 private `StepKernel.supportedRules` names are intentionally NOT
  exposed here; mapping a public structural `bijection` to the right private
  consequence-schema is the Stage 5 bridge work.

The 22 private kernel rule names stay forbidden and are not encoded as
constructors. The Stage 5 bridge that infers the private rule from
`(op, publicJustification, currentState)` is out of scope here. -/
inductive TraceJustification where
  | clue (clueId : String) (fromCells : List TraceCell)
  | bijection (fromCells : List TraceCell)
  deriving Repr, BEq

/-- The ONLY legal public structural-rule name. The JSON wire form is
`{"rule": "bijection", "from": ...?}`. -/
def structuralRuleBijection : String := "bijection"

inductive TraceOp where
  | assignAll (solution : List CandidateCategory)
  | place (cell : TraceCell) (justify : TraceJustification)
  | eliminate (cell : TraceCell) (justify : TraceJustification)
  | conclude (status : String) (solution : Option (List CandidateCategory))
  deriving Repr, BEq

inductive TraceStyle where
  | fullCandidate
  | stepwise
  deriving Repr, BEq

def TraceStyle.toString : TraceStyle → String
  | .fullCandidate => "full_candidate"
  | .stepwise => "stepwise"

structure Trace where
  schemaVersion : String
  problemId : String
  ops : List TraceOp
  deriving Repr, BEq

def Trace.style (trace : Trace) : TraceStyle :=
  if trace.ops.any fun op => match op with
    | .assignAll _ => true
    | _ => false
  then .fullCandidate
  else .stepwise

inductive TraceParseErrorCode where
  | invalidJson
  | missingSchemaVersion
  | unsupportedSchemaVersion
  | missingProblemId
  | malformedProblemId
  | missingOps
  | opsNotArray
  | emptyOps
  | malformedOp
  | unknownOp
  | assignAllMissingSolution
  | assignAllMalformedSolution
  | placeMissingCat
  | placeMissingHouse
  | placeMissingVal
  | eliminateMissingCat
  | eliminateMissingHouse
  | eliminateMissingVal
  | missingJustify
  | malformedJustify
  | unknownJustifyRule
  | malformedFromCell
  | concludeMissingStatus
  | concludeBadStatus
  | concludeMalformedSolution
  | unexpectedField
  deriving Repr, BEq

def TraceParseErrorCode.toString : TraceParseErrorCode → String
  | .invalidJson => "invalid_json"
  | .missingSchemaVersion => "missing_schema_version"
  | .unsupportedSchemaVersion => "unsupported_schema_version"
  | .missingProblemId => "missing_problem_id"
  | .malformedProblemId => "malformed_problem_id"
  | .missingOps => "missing_ops"
  | .opsNotArray => "ops_not_array"
  | .emptyOps => "empty_ops"
  | .malformedOp => "malformed_op"
  | .unknownOp => "unknown_op"
  | .assignAllMissingSolution => "assign_all_missing_solution"
  | .assignAllMalformedSolution => "assign_all_malformed_solution"
  | .placeMissingCat => "place_missing_cat"
  | .placeMissingHouse => "place_missing_house"
  | .placeMissingVal => "place_missing_val"
  | .eliminateMissingCat => "eliminate_missing_cat"
  | .eliminateMissingHouse => "eliminate_missing_house"
  | .eliminateMissingVal => "eliminate_missing_val"
  | .missingJustify => "missing_justify"
  | .malformedJustify => "malformed_justify"
  | .unknownJustifyRule => "unknown_justify_rule"
  | .malformedFromCell => "malformed_from_cell"
  | .concludeMissingStatus => "conclude_missing_status"
  | .concludeBadStatus => "conclude_bad_status"
  | .concludeMalformedSolution => "conclude_malformed_solution"
  | .unexpectedField => "unexpected_field"

structure TraceParseError where
  code : TraceParseErrorCode
  path : String
  message : String
  deriving Repr, BEq

namespace TraceParser

private abbrev ParseM := Except TraceParseError
private abbrev JObject := Std.TreeMap.Raw String Json compare

private def fail (code : TraceParseErrorCode) (path message : String) : ParseM α :=
  .error { code, path, message }

private def childPath (path field : String) : String := s!"{path}.{field}"

private def indexPath (path : String) (index : Nat) : String := s!"{path}[{index}]"

private def asObject (code : TraceParseErrorCode) (path : String) (value : Json) : ParseM JObject :=
  match value with
  | .obj fields => pure fields
  | _ => fail code path "expected an object"

private def checkFields (path : String) (allowed : List String) (object : JObject) : ParseM Unit := do
  for (field, _) in object.toList do
    unless allowed.contains field do
      fail .unexpectedField (childPath path field) s!"unexpected field '{field}'"

private def required (code : TraceParseErrorCode) (path field : String)
    (object : JObject) : ParseM Json :=
  match object.get? field with
  | some value => pure value
  | none => fail code (childPath path field) s!"missing required field '{field}'"

private def asString (code : TraceParseErrorCode) (path : String) (value : Json) : ParseM String :=
  match value with
  | .str result =>
      if result.isEmpty then fail code path "expected a non-empty string" else pure result
  | _ => fail code path "expected a string"

private def divideDecimal (mantissa : Nat) : Nat → Option Nat
  | 0 => some mantissa
  | exponent + 1 =>
      if mantissa % 10 == 0 then divideDecimal (mantissa / 10) exponent else none

private def asNat (code : TraceParseErrorCode) (path : String) (value : Json) : ParseM Nat :=
  match value with
  | .num number =>
      if number.mantissa <= 0 then fail code path "expected a natural number"
      else match divideDecimal number.mantissa.natAbs number.exponent with
        | some result =>
            if result == 0 then fail code path "expected a natural number" else pure result
        | none => fail code path "expected an integer"
  | _ => fail code path "expected an integer"

private def parseSolution (code : TraceParseErrorCode) (path : String)
    (value : Json) : ParseM (List CandidateCategory) := do
  let object ← asObject code path value
  if object.isEmpty then
    fail code path "solution must declare at least one category"
  let mut solution : List CandidateCategory := []
  for (categoryName, rawAssignments) in object.toList do
    if categoryName.isEmpty then
      fail code path "category names must be non-empty"
    let categoryPath := childPath path categoryName
    let assignmentsObject ← asObject code categoryPath rawAssignments
    if assignmentsObject.isEmpty then
      fail code categoryPath "category must declare at least one assignment"
    let mut assignments : List (Nat × Zebra.ValueName) := []
    for (houseKey, rawValue) in assignmentsObject.toList do
      let housePath := childPath categoryPath houseKey
      let house ← match houseKey.toNat? with
        | some parsed =>
            if parsed == 0 then fail code housePath "house keys must be positive integers"
            else if toString parsed == houseKey then pure parsed
            else fail code housePath "house keys must be canonical decimal integers"
        | none => fail code housePath "house keys must be decimal integers"
      let valueName ← asString code housePath rawValue
      assignments := assignments ++ [(house, { value := valueName })]
    solution := solution ++ [{ name := { value := categoryName }, assignments := assignments }]
  pure solution

private def parseCell (codeCat codeHouse codeVal : TraceParseErrorCode)
    (path : String) (object : JObject) : ParseM TraceCell := do
  let category ← asString codeCat (childPath path "cat") (← required codeCat path "cat" object)
  let house ← asNat codeHouse (childPath path "house") (← required codeHouse path "house" object)
  let value ← asString codeVal (childPath path "val") (← required codeVal path "val" object)
  pure { category := { value := category }, house, value := { value := value } }

private def parseFromCell (path : String) (value : Json) : ParseM TraceCell := do
  let object ← asObject .malformedFromCell path value
  checkFields path ["cat", "house", "val"] object
  parseCell .malformedFromCell .malformedFromCell .malformedFromCell path object

/-- Parse the optional `from` array of a justify object. The list may be absent
or empty (an empty `from` is documented to be allowed). -/
private def parseFromArray (justifyPath : String) (value : Json) : ParseM (List TraceCell) := do
  match value with
  | .arr cells =>
      let mut parsed : List TraceCell := []
      for index in [0:cells.size] do
        parsed := parsed ++
          [← parseFromCell (indexPath (childPath justifyPath "from") index) cells[index]!]
      pure parsed
  | _ => fail .malformedFromCell (childPath justifyPath "from") "expected an array"

private def parseJustification (opPath : String) (object : JObject) : ParseM TraceJustification := do
  let justifyPath := childPath opPath "justify"
  let raw ← required .missingJustify opPath "justify" object
  let justify ← asObject .malformedJustify justifyPath raw
  -- A justify object must declare exactly one of:
  --   * `clue` (and optional `from`)  → clue-based justification
  --   * `rule` (and optional `from`)  → structural rule (currently only `bijection`)
  -- Combining `clue` and `rule` is forbidden. The 22 private kernel rule
  -- names stay forbidden and are rejected via `unknown_justify_rule`.
  let hasClue := justify.contains "clue"
  let hasRule := justify.contains "rule"
  if hasClue && hasRule then
    fail .malformedJustify justifyPath
      "justify must not declare both 'clue' and 'rule'"
  if !hasClue && !hasRule then
    fail .malformedJustify justifyPath
      "justify must declare either 'clue' or 'rule'"
  if hasRule then
    checkFields justifyPath ["rule", "from"] justify
    let rawRule ← required .unknownJustifyRule justifyPath "rule" justify
    let ruleName ← asString .unknownJustifyRule (childPath justifyPath "rule") rawRule
    unless ruleName == structuralRuleBijection do
      fail .unknownJustifyRule (childPath justifyPath "rule")
        s!"unknown structural rule '{ruleName}'; only 'bijection' is public"
    let fromCells ← match justify.get? "from" with
      | none => pure []
      | some raw => parseFromArray justifyPath raw
    pure (.bijection fromCells)
  else
    checkFields justifyPath ["clue", "from"] justify
    let rawClue ← required .malformedJustify justifyPath "clue" justify
    let clue ← asString .malformedJustify (childPath justifyPath "clue") rawClue
    let fromCells ← match justify.get? "from" with
      | none => pure []
      | some raw => parseFromArray justifyPath raw
    pure (.clue clue fromCells)

private def parseOp (index : Nat) (value : Json) : ParseM TraceOp := do
  let path := indexPath "$.ops" index
  let object ← asObject .malformedOp path value
  let op ← match object.get? "op" with
    | some raw => asString .unknownOp (childPath path "op") raw
    | none => fail .unknownOp (childPath path "op") "missing required field 'op'"
  if op == "assign_all" then
    checkFields path ["op", "solution"] object
    let solution ← parseSolution .assignAllMalformedSolution (childPath path "solution")
      (← required .assignAllMissingSolution path "solution" object)
    pure (.assignAll solution)
  else if op == "place" then
    checkFields path ["op", "cat", "house", "val", "justify"] object
    let cell ← parseCell .placeMissingCat .placeMissingHouse .placeMissingVal path object
    pure (.place cell (← parseJustification path object))
  else if op == "eliminate" then
    checkFields path ["op", "cat", "house", "val", "justify"] object
    let cell ← parseCell .eliminateMissingCat .eliminateMissingHouse .eliminateMissingVal path object
    pure (.eliminate cell (← parseJustification path object))
  else if op == "conclude" then
    checkFields path ["op", "status", "solution"] object
    let status ← asString .concludeBadStatus (childPath path "status")
      (← required .concludeMissingStatus path "status" object)
    unless status == "solved" do
      fail .concludeBadStatus (childPath path "status") "expected status 'solved'"
    let solution ← match object.get? "solution" with
      | none => pure none
      | some raw => pure (some (← parseSolution .concludeMalformedSolution
          (childPath path "solution") raw))
    pure (.conclude status solution)
  else
    fail .unknownOp (childPath path "op") s!"unknown operation '{op}'"

def parseJson (value : Json) : Except TraceParseError Trace := do
  let object ← asObject .invalidJson "$" value
  checkFields "$" ["schema_version", "problem_id", "ops"] object
  let version ← asString .unsupportedSchemaVersion "$.schema_version"
    (← required .missingSchemaVersion "$" "schema_version" object)
  unless version == schemaVersion do
    fail .unsupportedSchemaVersion "$.schema_version" s!"expected trace schema version {schemaVersion}"
  let problemId ← asString .malformedProblemId "$.problem_id"
    (← required .missingProblemId "$" "problem_id" object)
  let rawOps ← required .missingOps "$" "ops" object
  let opsArray ← match rawOps with
    | .arr values => pure values
    | _ => fail .opsNotArray "$.ops" "expected an array"
  if opsArray.isEmpty then
    fail .emptyOps "$.ops" "at least one operation is required"
  let mut ops : List TraceOp := []
  for index in [0:opsArray.size] do
    ops := ops ++ [← parseOp index opsArray[index]!]
  pure { schemaVersion := version, problemId, ops }

def parse (input : String) : Except TraceParseError Trace :=
  match Json.parse input with
  | .ok value => parseJson value
  | .error message => .error { code := .invalidJson, path := "$", message }

end TraceParser
end SparseIRLean
