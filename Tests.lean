import SparseIRLean

open Lean SparseIRLean

def assertTrue (message : String) (condition : Bool) : IO Unit :=
  unless condition do
    throw <| IO.userError message

def expectParsed (label input : String) : IO ParsedProblem :=
  match parseProblem input with
  | .ok problem => pure problem
  | .error error =>
      throw <| IO.userError s!"{label}: unexpected {error.code.toString} at {error.path}"

def expectError (label : String) (code : ParseErrorCode) (result : Except ParseError α) : IO Unit :=
  match result with
  | .ok _ => throw <| IO.userError s!"{label}: unexpectedly parsed"
  | .error error => do
      assertTrue s!"{label}: got {error.code.toString}, expected {code.toString}" (error.code == code)
      assertTrue s!"{label}: error path is empty" (!error.path.isEmpty)

def loadFixture (name : String) : IO String :=
  IO.FS.readFile ("tests" / "problems" / name)

def eraseField (value : Json) (field : String) : Json :=
  match value with
  | .obj fields => .obj (fields.erase field)
  | other => other

def updateClue (problem : Json) (index : Nat) (update : Json → Json) : Json :=
  match problem.getObjVal? "clues" with
  | .ok (.arr clues) => problem.setObjVal! "clues" (.arr (clues.modify index update))
  | _ => problem

def clueKinds (clues : Array Zebra.Clue) : List String :=
  clues.toList.map fun clue => match clue with
    | .foundAt .. => "found_at"
    | .notAt .. => "not_at"
    | .sameHouse .. => "same_house"
    | .directLeft .. => "direct_left"
    | .directRight .. => "direct_right"
    | .sideBySide .. => "side_by_side"
    | .leftOf .. => "left_of"
    | .rightOf .. => "right_of"
    | .oneBetween .. => "one_between"
    | .twoBetween .. => "two_between"

def main : IO UInt32 := do
  assertTrue "canonical schema version changed" (schemaVersion == "0.2")
  assertTrue "v0 domain changed" (Zebra.domainId == "zebra")
  assertTrue "Stage 1 parser is unavailable" problemParserAvailable
  assertTrue "Stage 1 Zebra AST is unavailable" Zebra.astAvailable
  assertTrue "checker leaked into Stage 1" (!CheckerCore.available)
  assertTrue "audit renderer leaked into Stage 1" (!Pretty.available)
  let errorCodes := [
    ParseErrorCode.invalidJson,
    .expectedObject,
    .missingField,
    .unknownField,
    .invalidFieldType,
    .invalidValue,
    .unsupportedSchemaVersion,
    .invalidDomain,
    .invalidHouse,
    .unknownClueType
  ]
  assertTrue "parse error vocabulary changed" (errorCodes.map ParseErrorCode.toString == [
    "invalid_json", "expected_object", "missing_field", "unknown_field",
    "invalid_field_type", "invalid_value", "unsupported_schema_version",
    "invalid_domain", "invalid_house", "unknown_clue_type"
  ])

  let names := [
    "lgp-test-2x2-33.problem.json",
    "lgp-test-4x4-27.problem.json",
    "lgp-test-6x6-5.problem.json"
  ]
  let mut allKinds : List String := []
  for name in names do
    let problem ← expectParsed name (← loadFixture name)
    assertTrue s!"{name}: source id missing" (!problem.envelope.source.externalId.isEmpty)
    allKinds := clueKinds problem.puzzle.clues ++ allKinds
  for kind in ["found_at", "not_at", "same_house", "direct_left", "direct_right",
      "side_by_side", "left_of", "right_of", "one_between", "two_between"] do
    assertTrue s!"clue constructor not covered: {kind}" (allKinds.contains kind)

  let source ← loadFixture "lgp-test-4x4-27.problem.json"
  let parsed ← expectParsed "opaque expect" source
  let expected := Json.mkObj [("opaque_marker", Json.arr #[1, true, Json.null,
    Json.mkObj [("keep", "exactly")]])]
  assertTrue "expect was not preserved opaquely" (parsed.envelope.expect == some expected)

  expectError "invalid JSON" .invalidJson (parseProblem "{")
  expectError "root is not an object" .expectedObject (parseProblem "[]")
  let json ← match Json.parse source with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  expectError "missing domain" .missingField (parseProblemJson (eraseField json "domain"))
  expectError "wrong domain" .invalidDomain
    (parseProblemJson (json.setObjVal! "domain" "horn"))
  expectError "wrong schema version" .unsupportedSchemaVersion
    (parseProblemJson (json.setObjVal! "schema_version" "9"))
  expectError "empty id" .invalidValue
    (parseProblemJson (json.setObjVal! "id" ""))
  expectError "wrong field type" .invalidFieldType <| parseProblemJson <|
    json.setObjVal! "size" (Json.mkObj [("houses", "four"), ("categories", 4)])
  expectError "unknown top-level field" .unknownField
    (parseProblemJson (json.setObjVal! "surprise" true))
  expectError "unknown clue type" .unknownClueType <| parseProblemJson <|
    updateClue json 0 fun clue => clue.setObjVal! "type" "near"
  expectError "missing clue field" .missingField <| parseProblemJson <|
    updateClue json 0 fun clue => eraseField clue "a"
  expectError "house zero" .invalidHouse <| parseProblemJson <|
    updateClue json 1 fun clue => clue.setObjVal! "house" 0
  expectError "house wrong type" .invalidHouse <| parseProblemJson <|
    updateClue json 1 fun clue => clue.setObjVal! "house" "2"

  -- These are raw-AST concerns only. Stage 2 owns cross-reference, cardinality,
  -- uniqueness, and puzzle-relative house-bound validation.
  let semanticMutations := [
    json.setObjVal! "size" (Json.mkObj [("houses", 99), ("categories", 1)]),
    updateClue json 0 fun clue => clue.setObjVal! "a"
      (Json.mkObj [("cat", "Undeclared"), ("val", "missing")]),
    updateClue json 1 fun clue => clue.setObjVal! "house" 99,
    updateClue json 1 fun clue => clue.setObjVal! "id" "c1"
  ]
  for mutation in semanticMutations do
    match parseProblemJson mutation with
    | .ok _ => pure ()
    | .error error =>
        throw <| IO.userError
          (s!"Stage 2 validation leaked into parser: {error.code.toString} at {error.path}")

  IO.println "Stage 1 Lean parser checks passed"
  pure 0
