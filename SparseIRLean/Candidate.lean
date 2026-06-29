import Lean.Data.Json
import SparseIRLean.Compiler

open Lean

namespace SparseIRLean

/-- A public candidate uses one-based house numbers. Internally they remain
    one-based `Nat`s so diagnostics can quote the public JSON path exactly. -/
structure CandidateCategory where
  name : Zebra.CategoryName
  assignments : List (Nat × Zebra.ValueName)
  deriving Repr, BEq

structure CandidateAssignment where
  schemaVersion : String
  problemId : String
  solution : List CandidateCategory
  deriving Repr, BEq

inductive CandidateParseErrorCode where
  | invalidCandidateJson
  | expectedObject
  | missingField
  | unknownField
  | invalidFieldType
  | invalidValue
  | invalidHouseKey
  | unsupportedSchemaVersion
  deriving Repr, BEq

def CandidateParseErrorCode.toString : CandidateParseErrorCode → String
  | .invalidCandidateJson => "invalid_candidate_json"
  | .expectedObject => "expected_object"
  | .missingField => "missing_field"
  | .unknownField => "unknown_field"
  | .invalidFieldType => "invalid_field_type"
  | .invalidValue => "invalid_value"
  | .invalidHouseKey => "invalid_house_key"
  | .unsupportedSchemaVersion => "unsupported_schema_version"

structure CandidateParseError where
  code : CandidateParseErrorCode
  path : String
  message : String
  deriving Repr, BEq

namespace Candidate

private abbrev ParseM := Except CandidateParseError
private abbrev JObject := Std.TreeMap.Raw String Json compare

private def fail (code : CandidateParseErrorCode) (path message : String) : ParseM α :=
  .error { code, path, message }

private def childPath (path field : String) : String :=
  if path == "$" then s!"$.{field}" else s!"{path}.{field}"

private def asObject (path : String) (value : Json) : ParseM JObject :=
  match value with
  | .obj fields => pure fields
  | _ => fail .expectedObject path "expected an object"

private def required (path field : String) (object : JObject) : ParseM Json :=
  match object.get? field with
  | some value => pure value
  | none => fail .missingField (childPath path field) s!"missing required field '{field}'"

private def asNonemptyString (path : String) (value : Json) : ParseM String :=
  match value with
  | .str result =>
      if result.isEmpty then fail .invalidValue path "expected a non-empty string" else pure result
  | _ => fail .invalidFieldType path "expected a string"

private def checkFields (path : String) (allowed : List String) (object : JObject) : ParseM Unit := do
  for (field, _) in object.toList do
    unless allowed.contains field do
      fail .unknownField (childPath path field) s!"unknown field '{field}'"

def parseJson (value : Json) : Except CandidateParseError CandidateAssignment := do
  let object ← asObject "$" value
  checkFields "$" ["schema_version", "problem_id", "solution"] object
  let version ← asNonemptyString "$.schema_version" (← required "$" "schema_version" object)
  unless version == schemaVersion do
    fail .unsupportedSchemaVersion "$.schema_version"
      s!"expected candidate schema version {schemaVersion}"
  let problemId ← asNonemptyString "$.problem_id" (← required "$" "problem_id" object)
  let solutionObject ← asObject "$.solution" (← required "$" "solution" object)
  let mut solution : List CandidateCategory := []
  for (categoryName, rawAssignments) in solutionObject.toList do
    if categoryName.isEmpty then
      fail .invalidValue "$.solution" "category names must be non-empty"
    let categoryPath := childPath "$.solution" categoryName
    let assignmentObject ← asObject categoryPath rawAssignments
    let mut assignments : List (Nat × Zebra.ValueName) := []
    for (houseKey, rawValue) in assignmentObject.toList do
      let housePath := childPath categoryPath houseKey
      let house ← match houseKey.toNat? with
        | some value =>
            if toString value == houseKey then pure value
            else fail .invalidHouseKey housePath "house keys must be canonical decimal integers"
        | none => fail .invalidHouseKey housePath "house keys must be decimal integers"
      let value ← asNonemptyString housePath rawValue
      assignments := assignments ++ [(house, { value := value })]
    solution := solution ++ [{ name := { value := categoryName }, assignments := assignments }]
  pure { schemaVersion := version, problemId := problemId, solution := solution }

def parse (input : String) : Except CandidateParseError CandidateAssignment :=
  match Json.parse input with
  | .ok value => parseJson value
  | .error message =>
      .error { code := .invalidCandidateJson, path := "$", message := message }

end Candidate
end SparseIRLean
