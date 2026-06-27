import Lean.Data.Json
import SparseIRLean.Zebra

open Lean

namespace SparseIRLean

/-- The frozen canonical envelope and problem schema version. -/
def schemaVersion : String := "0.2"

structure ProblemSource where
  dataset : String
  split : String
  externalId : String
  grid : String
  deriving Repr, BEq

/-- `expect` is retained exactly as JSON and is not interpreted by the parser. -/
structure Envelope where
  schemaVersion : String
  domain : String
  id : String
  source : ProblemSource
  expect : Option Json
  deriving BEq

structure ParsedProblem where
  envelope : Envelope
  puzzle : Zebra.RawPuzzle
  deriving BEq

/-- Stable Stage 1 parse-error vocabulary. -/
inductive ParseErrorCode where
  | invalidJson
  | expectedObject
  | missingField
  | unknownField
  | invalidFieldType
  | invalidValue
  | unsupportedSchemaVersion
  | invalidDomain
  | invalidHouse
  | unknownClueType
  deriving Repr, BEq

def ParseErrorCode.toString : ParseErrorCode → String
  | .invalidJson => "invalid_json"
  | .expectedObject => "expected_object"
  | .missingField => "missing_field"
  | .unknownField => "unknown_field"
  | .invalidFieldType => "invalid_field_type"
  | .invalidValue => "invalid_value"
  | .unsupportedSchemaVersion => "unsupported_schema_version"
  | .invalidDomain => "invalid_domain"
  | .invalidHouse => "invalid_house"
  | .unknownClueType => "unknown_clue_type"

structure ParseError where
  code : ParseErrorCode
  path : String
  message : String
  deriving Repr, BEq

private abbrev ParseM := Except ParseError
private abbrev JObject := Std.TreeMap.Raw String Json compare

private def fail (code : ParseErrorCode) (path message : String) : ParseM α :=
  .error { code, path, message }

private def childPath (path field : String) : String :=
  if path == "$" then s!"$.{field}" else s!"{path}.{field}"

private def asObject (path : String) (value : Json) : ParseM JObject :=
  match value with
  | .obj fields => pure fields
  | _ => fail .expectedObject path "expected an object"

private def checkFields (path : String) (allowed : List String) (object : JObject) : ParseM Unit := do
  for (field, _) in object.toList do
    unless allowed.contains field do
      fail .unknownField (childPath path field) s!"unknown field '{field}'"

private def required (path field : String) (object : JObject) : ParseM Json :=
  match object.get? field with
  | some value => pure value
  | none => fail .missingField (childPath path field) s!"missing required field '{field}'"

private def optional (field : String) (object : JObject) : Option Json := object.get? field

private def asString (path : String) (value : Json) : ParseM String :=
  match value with
  | .str result => pure result
  | _ => fail .invalidFieldType path "expected a string"

private def asNonemptyString (path : String) (value : Json) : ParseM String := do
  let result ← asString path value
  if result.isEmpty then
    fail .invalidValue path "expected a non-empty string"
  else
    pure result

private def asArray (path : String) (value : Json) : ParseM (Array Json) :=
  match value with
  | .arr values => pure values
  | _ => fail .invalidFieldType path "expected an array"

private def asPositiveNat (path : String) (value : Json) : ParseM Nat :=
  match value.getNat? with
  | .ok 0 => fail .invalidValue path "expected a positive integer"
  | .ok result => pure result
  | .error _ => fail .invalidFieldType path "expected a positive integer"

private def parseHouse (path : String) (value : Json) : ParseM Zebra.House :=
  match value.getNat? with
  | .ok 0 => fail .invalidHouse path "house numbers are one-based"
  | .ok house => pure { value := house }
  | .error _ => fail .invalidHouse path "expected a positive integer house number"

private def validGrid (grid : String) : Bool :=
  match grid.splitOn "x" with
  | [rows, columns] =>
      match rows.toNat?, columns.toNat? with
      | some r, some c => r > 0 && c > 0 && rows == toString r && columns == toString c
      | _, _ => false
  | _ => false

private def parseSource (value : Json) : ParseM ProblemSource := do
  let path := "$.source"
  let object ← asObject path value
  checkFields path ["dataset", "split", "external_id", "grid"] object
  let dataset ← asNonemptyString (childPath path "dataset") (← required path "dataset" object)
  unless dataset == "zebralogic" do
    fail .invalidValue (childPath path "dataset") "dataset must be 'zebralogic'"
  let split ← asNonemptyString (childPath path "split") (← required path "split" object)
  let externalId ← asNonemptyString (childPath path "external_id")
    (← required path "external_id" object)
  let grid ← asNonemptyString (childPath path "grid") (← required path "grid" object)
  unless validGrid grid do
    fail .invalidValue (childPath path "grid")
      "grid must have the form NxM with positive integers"
  pure { dataset, split, externalId, grid }

private def parseSize (value : Json) : ParseM Zebra.PuzzleSize := do
  let path := "$.size"
  let object ← asObject path value
  checkFields path ["houses", "categories"] object
  let houses ← asPositiveNat (childPath path "houses") (← required path "houses" object)
  let categories ← asPositiveNat (childPath path "categories")
    (← required path "categories" object)
  pure { houses, categories }

private def parseCategories (value : Json) : ParseM (Array Zebra.Category) := do
  let path := "$.categories"
  let object ← asObject path value
  if object.toList.isEmpty then
    fail .invalidValue path "expected at least one category"
  else
    let mut categories := #[]
    for (name, rawValues) in object.toList do
      let categoryPath := childPath path name
      if name.isEmpty then
        fail .invalidValue categoryPath "category names must be non-empty"
      let values ← asArray categoryPath rawValues
      if values.isEmpty then
        fail .invalidValue categoryPath "expected at least one category value"
      let mut parsedValues := #[]
      for i in *...values.size do
        let value ← asNonemptyString s!"{categoryPath}[{i}]" values[i]!
        parsedValues := parsedValues.push { value := value }
      categories := categories.push { name := { value := name }, values := parsedValues }
    pure categories

private def parseAttribute (path : String) (value : Json) : ParseM Zebra.Attribute := do
  let object ← asObject path value
  checkFields path ["cat", "val"] object
  let category ← asNonemptyString (childPath path "cat") (← required path "cat" object)
  let attributeValue ← asNonemptyString (childPath path "val") (← required path "val" object)
  pure { category := { value := category }, value := { value := attributeValue } }

private def parseUnaryAttribute (path : String) (object : JObject) : ParseM Zebra.Attribute := do
  let category ← asNonemptyString (childPath path "cat") (← required path "cat" object)
  let value ← asNonemptyString (childPath path "val") (← required path "val" object)
  pure { category := { value := category }, value := { value := value } }

private def parseClue (index : Nat) (value : Json) : ParseM Zebra.Clue := do
  let path := s!"$.clues[{index}]"
  let object ← asObject path value
  let id ← asNonemptyString (childPath path "id") (← required path "id" object)
  let clueType ← asNonemptyString (childPath path "type") (← required path "type" object)
  match clueType with
  | "found_at" =>
      checkFields path ["id", "type", "cat", "val", "house"] object
      let item ← parseUnaryAttribute path object
      let house ← parseHouse (childPath path "house") (← required path "house" object)
      pure <| .foundAt id item house
  | "not_at" =>
      checkFields path ["id", "type", "cat", "val", "house"] object
      let item ← parseUnaryAttribute path object
      let house ← parseHouse (childPath path "house") (← required path "house" object)
      pure <| .notAt id item house
  | binaryType =>
      let constructor : Option (String → Zebra.Attribute → Zebra.Attribute → Zebra.Clue) :=
        match binaryType with
        | "same_house" => some .sameHouse
        | "direct_left" => some .directLeft
        | "direct_right" => some .directRight
        | "side_by_side" => some .sideBySide
        | "left_of" => some .leftOf
        | "right_of" => some .rightOf
        | "one_between" => some .oneBetween
        | "two_between" => some .twoBetween
        | _ => none
      match constructor with
      | none =>
          fail .unknownClueType (childPath path "type") s!"unknown clue type '{binaryType}'"
      | some makeClue =>
          checkFields path ["id", "type", "a", "b"] object
          let a ← parseAttribute (childPath path "a") (← required path "a" object)
          let b ← parseAttribute (childPath path "b") (← required path "b" object)
          pure <| makeClue id a b

private def parseClues (value : Json) : ParseM (Array Zebra.Clue) := do
  let values ← asArray "$.clues" value
  let mut clues := #[]
  for i in *...values.size do
    clues := clues.push (← parseClue i values[i]!)
  pure clues

def parseProblemJson (value : Json) : Except ParseError ParsedProblem := do
  let object ← asObject "$" value
  checkFields "$" ["schema_version", "domain", "id", "source", "size", "categories",
    "clues", "expect"] object
  let version ← asNonemptyString "$.schema_version" (← required "$" "schema_version" object)
  unless version == schemaVersion do
    fail .unsupportedSchemaVersion "$.schema_version"
      s!"expected schema version {schemaVersion}"
  let domain ← asNonemptyString "$.domain" (← required "$" "domain" object)
  unless domain == Zebra.domainId do
    fail .invalidDomain "$.domain" "domain must be 'zebra'"
  let id ← asNonemptyString "$.id" (← required "$" "id" object)
  let source ← parseSource (← required "$" "source" object)
  let size ← parseSize (← required "$" "size" object)
  let categories ← parseCategories (← required "$" "categories" object)
  let clues ← parseClues (← required "$" "clues" object)
  let envelope : Envelope := {
    schemaVersion := version
    domain := domain
    id := id
    source := source
    expect := optional "expect" object
  }
  pure { envelope, puzzle := { size, categories, clues } }

def parseProblem (input : String) : Except ParseError ParsedProblem :=
  match Json.parse input with
  | .ok value => parseProblemJson value
  | .error message => .error { code := .invalidJson, path := "$", message }

def problemParserAvailable : Bool := true

end SparseIRLean
