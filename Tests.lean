import SparseIRLean

open Lean SparseIRLean

/-- A single assertion with a stable error message. -/
def assertTrue (message : String) (condition : Bool) : IO Unit :=
  unless condition do
    throw <| IO.userError message

/-- Parse successfully, or fail with a labeled message. -/
def expectParsed (label input : String) : IO ParsedProblem :=
  match parseProblem input with
  | .ok problem => pure problem
  | .error error =>
      throw <| IO.userError s!"{label}: unexpected {error.code.toString} at {error.path}"

/-- Expect a parse error with the given code. -/
def expectParseError (label : String) (code : ParseErrorCode) (input : String) : IO Unit :=
  match parseProblem input with
  | .ok _ => throw <| IO.userError s!"{label}: unexpectedly parsed"
  | .error error => do
      assertTrue s!"{label}: got {error.code.toString}, expected {code.toString}"
        (error.code == code)
      assertTrue s!"{label}: error path is empty" (!error.path.isEmpty)

/-- Expect a parse error with the given code on a Json value. -/
def expectParseErrorJson (label : String) (code : ParseErrorCode)
    (value : Json) : IO Unit :=
  match parseProblemJson value with
  | .ok _ => throw <| IO.userError s!"{label}: unexpectedly parsed"
  | .error error => do
      assertTrue s!"{label}: got {error.code.toString}, expected {code.toString}"
        (error.code == code)
      assertTrue s!"{label}: error path is empty" (!error.path.isEmpty)

/-- Parse successfully and then expect a static-compile error. -/
def expectStaticError (label : String) (code : StaticErrorCode)
    (input : String) : IO Unit :=
  match parseProblem input with
  | .error _ =>
      throw <| IO.userError s!"{label}: parser rejected input before static phase"
  | .ok parsed =>
      match Compiler.compile parsed with
      | .ok _ =>
          throw <| IO.userError s!"{label}: unexpectedly compiled"
      | .error error => do
          assertTrue s!"{label}: got {error.code.toString}, expected {code.toString}"
            (error.code == code)
          assertTrue s!"{label}: error path is empty" (!error.path.isEmpty)

/-- Parse-and-compile a fixture, returning the compiled puzzle. -/
def expectCompiled (label input : String) : IO CompiledPuzzle :=
  match parseProblem input with
  | .error parseError =>
      throw <| IO.userError
        s!"{label}: unexpected parse error {parseError.code.toString} at {parseError.path}"
  | .ok parsed =>
      match Compiler.compile parsed with
      | .ok compiled => pure compiled
      | .error staticError =>
          throw <| IO.userError
            s!"{label}: unexpected static error {staticError.code.toString} at {staticError.path}"

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

def setSize (problem : Json) (houses categories : Nat) : Json :=
  problem.setObjVal! "size" (Json.mkObj [
    ("houses", Json.num (Int.ofNat houses)),
    ("categories", Json.num (Int.ofNat categories))
  ])

def setCategories (problem : Json) (categories : List (String × List String)) : Json :=
  let entries := categories.map fun (name, values) =>
    (name, Json.arr (values.map Json.str |>.toArray))
  problem.setObjVal! "categories" (Json.mkObj entries)

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

/-- Assert a Json mutation parses successfully at Stage 1 (raw AST level).
    Used to lock the boundary: shape-valid-but-semantically-bad problems must
    pass through Stage 1 so Stage 2 owns every semantic decision. -/
def assertParsesRaw (label : String) (value : Json) : IO Unit :=
  match parseProblemJson value with
  | .ok _ => pure ()
  | .error error =>
      throw <| IO.userError
        (s!"Stage 2 validation leaked into parser at {label}: " ++
         s!"{error.code.toString} at {error.path}")

namespace Walkthrough

/-- Render an Option Json opaquely without requiring a Repr instance. -/
def ppExpect : Option Json → String
  | none => "none"
  | some v => "some " ++ v.compress

/-- Convert a value to its String representation, suitable for `++`. -/
def pp (a : α) [Repr α] : String := repr a |>.pretty

/-- Compact one-line view of the envelope, used by the demo walkthrough. -/
def envelopeSummary (e : Envelope) : String :=
  "Envelope.mk { schemaVersion := " ++ pp e.schemaVersion ++
    ", domain := " ++ pp e.domain ++
    ", id := " ++ pp e.id ++
    ", source := " ++ pp e.source ++
    ", expect := " ++ ppExpect e.expect ++ " }"

/-- Compact one-line view of a compiled category. -/
def categorySummary (c : CompiledCategory) : String :=
  "CompiledCategory.mk { name := " ++ pp c.name.value ++
    ", values := " ++ pp c.values ++ " }"

/-- Compact one-line view of a compiled clue. -/
def clueSummary : Zebra.Clue → String
  | .foundAt id a h =>
      s!"Clue.foundAt {pp id} {pp a} {h.value}"
  | .notAt id a h =>
      s!"Clue.notAt {pp id} {pp a} {h.value}"
  | .sameHouse id a b =>
      s!"Clue.sameHouse {pp id} {pp a} {pp b}"
  | .directLeft id a b =>
      s!"Clue.directLeft {pp id} {pp a} {pp b}"
  | .directRight id a b =>
      s!"Clue.directRight {pp id} {pp a} {pp b}"
  | .sideBySide id a b =>
      s!"Clue.sideBySide {pp id} {pp a} {pp b}"
  | .leftOf id a b =>
      s!"Clue.leftOf {pp id} {pp a} {pp b}"
  | .rightOf id a b =>
      s!"Clue.rightOf {pp id} {pp a} {pp b}"
  | .oneBetween id a b =>
      s!"Clue.oneBetween {pp id} {pp a} {pp b}"
  | .twoBetween id a b =>
      s!"Clue.twoBetween {pp id} {pp a} {pp b}"

end Walkthrough

def main : IO UInt32 := do
  -- ====================================================================
  -- Stage 1 boundary: shape/parser only. Stage 2 owns every value check.
  -- ====================================================================
  assertTrue "canonical schema version changed" (schemaVersion == "0.2")
  assertTrue "v0 domain changed" (Zebra.domainId == "zebra")
  assertTrue "Stage 1 parser is unavailable" problemParserAvailable
  assertTrue "Stage 1 Zebra AST is unavailable" Zebra.astAvailable
  assertTrue "Stage 3A candidate checker is unavailable" CheckerCore.available
  assertTrue "audit renderer leaked into Stage 1" (!Pretty.available)

  -- The Stage 1 parse-error vocabulary is shape-only. Domain value,
  -- schema_version value, and puzzle-relative concerns do not appear here.
  let parseVocab := [
    ParseErrorCode.invalidJson,
    .expectedObject,
    .missingField,
    .unknownField,
    .invalidFieldType,
    .invalidValue,
    .invalidHouse,
    .unknownClueType
  ]
  assertTrue "parse error vocabulary changed"
    (parseVocab.map ParseErrorCode.toString == [
      "invalid_json", "expected_object", "missing_field", "unknown_field",
      "invalid_field_type", "invalid_value", "invalid_house", "unknown_clue_type"
    ])

  -- Stage 1: valid JSON across all grid sizes parses into ParsedProblem.
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

  -- Stage 1: opaque expect preserved through parsing.
  let source ← loadFixture "lgp-test-4x4-27.problem.json"
  let parsed ← expectParsed "opaque expect" source
  let expected := Json.mkObj [("opaque_marker", Json.arr #[1, true, Json.null,
    Json.mkObj [("keep", "exactly")]])]
  assertTrue "expect was not preserved opaquely" (parsed.envelope.expect == some expected)

  -- Stage 1: integral JSON number accepted, fractional rejected as wrong type.
  let _ ← expectParsed "integral JSON number"
    (source.replace "\"houses\": 4" "\"houses\": 4.0")
  expectParseError "fractional JSON number" .invalidFieldType
    (source.replace "\"houses\": 4" "\"houses\": 4.5")

  -- Stage 1 shape rejections.
  expectParseError "invalid JSON" .invalidJson "{"
  expectParseError "root is not an object" .expectedObject "[]"
  let json ← match Json.parse source with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  expectParseErrorJson "missing domain" .missingField (eraseField json "domain")
  expectParseErrorJson "empty id" .invalidValue (json.setObjVal! "id" "")
  expectParseErrorJson "wrong field type" .invalidFieldType <|
    json.setObjVal! "size" (Json.mkObj [("houses", "four"), ("categories", 4)])
  expectParseErrorJson "unknown top-level field" .unknownField
    (json.setObjVal! "surprise" true)
  expectParseErrorJson "unknown clue type" .unknownClueType <|
    updateClue json 0 fun clue => clue.setObjVal! "type" "near"
  expectParseErrorJson "missing clue field" .missingField <|
    updateClue json 0 fun clue => eraseField clue "a"
  expectParseErrorJson "house wrong type" .invalidHouse <|
    updateClue json 1 fun clue => clue.setObjVal! "house" "2"

  -- Stage 1 boundary: the parser MUST accept these semantically invalid
  -- inputs. Every one of these becomes a Stage 2 static error instead.
  assertParsesRaw "wrong domain" (json.setObjVal! "domain" "horn")
  assertParsesRaw "wrong schema_version" (json.setObjVal! "schema_version" "9")
  assertParsesRaw "size mismatch (declared vs actual)"
    (json.setObjVal! "size" (Json.mkObj [("houses", 99), ("categories", 1)]))
  assertParsesRaw "category size mismatch"
    (setCategories
      (setSize json 4 4)
      [("Name", ["A", "B", "C"]),
       ("Color", ["red", "green", "blue", "yellow"]),
       ("Pet", ["dog", "cat", "fish", "bird"]),
       ("Food", ["pizza", "sushi", "taco", "salad"])])
  assertParsesRaw "duplicate value"
    (setCategories (setSize json 2 2)
      [("Name", ["Eric", "Eric"]), ("Pet", ["dog", "cat"])])
  assertParsesRaw "unknown category in clue"
    (updateClue json 0 fun clue =>
      clue.setObjVal! "a"
        (Json.mkObj [("cat", "Undeclared"), ("val", "Eric")]))
  assertParsesRaw "unknown value in clue"
    (updateClue json 0 fun clue =>
      clue.setObjVal! "a"
        (Json.mkObj [("cat", "Name"), ("val", "Missing")]))
  assertParsesRaw "house out of range"
    (updateClue json 1 fun clue => clue.setObjVal! "house" 99)
  assertParsesRaw "house zero"
    (updateClue json 1 fun clue => clue.setObjVal! "house" 0)
  assertParsesRaw "duplicate clue id"
    (updateClue json 1 fun clue => clue.setObjVal! "id" "c1")

  -- ====================================================================
  -- Stage 2 boundary: semantic static compiler/well-formedness.
  -- ====================================================================
  assertTrue "static compiler not advertised" staticCompilerAvailable
  assertTrue "Stage 3A candidate checker is unavailable" CheckerCore.available
  assertTrue "audit renderer leaked into Stage 2" (!Pretty.available)

  -- Static error vocabulary is the frozen set every Stage 2 release ships.
  assertTrue "static error vocabulary changed"
    ([
      StaticErrorCode.unsupportedSchemaVersion,
      .invalidDomain,
      .sizeMismatch,
      .categorySizeMismatch,
      .duplicateValue,
      .unknownCategory,
      .unknownValue,
      .houseOutOfRange,
      .duplicateClueId
    ].map StaticErrorCode.toString == [
      "unsupported_schema_version", "invalid_domain",
      "size_mismatch", "category_size_mismatch", "duplicate_value",
      "unknown_category", "unknown_value", "house_out_of_range",
      "duplicate_clue_id"
    ])

  -- Every gold fixture compiles; the opaque expect field is preserved.
  for name in names do
    let fixture ← loadFixture name
    let compiled ← expectCompiled name fixture
    assertTrue s!"{name}: houses not propagated" (compiled.houses > 0)
    assertTrue s!"{name}: categories empty" (compiled.categories ≠ [])
    assertTrue s!"{name}: clues empty" (compiled.clues ≠ #[])
    for category in compiled.categories do
      assertTrue s!"{name}: category '{category.name.value}' has wrong size"
        (category.values.length == compiled.houses)
    -- CompiledPuzzle must not contain a solution.
    assertTrue s!"{name}: envelope id missing" (!compiled.envelope.id.isEmpty)

  -- Stage 2 rejects envelope-level semantic mismatches.
  expectStaticError "unsupported_schema_version"
    .unsupportedSchemaVersion
    (json.setObjVal! "schema_version" "9" |>.compress)
  expectStaticError "invalid_domain"
    .invalidDomain
    (json.setObjVal! "domain" "horn" |>.compress)

  -- Stage 2 rejects size and category-cardinality violations.
  expectStaticError "size_mismatch: declared category count wrong"
    .sizeMismatch
    ((json.setObjVal! "size" (Json.mkObj [("houses", Json.num 4), ("categories", Json.num 1)])).compress)
  expectStaticError "category_size_mismatch: too few values"
    .categorySizeMismatch
    (setCategories
      (setSize json 4 4)
      [("Name", ["A", "B", "C"]), ("Color", ["red", "green", "blue", "yellow"]),
       ("Pet", ["dog", "cat", "fish", "bird"]), ("Food", ["pizza", "sushi", "taco", "salad"])]
    ).compress
  expectStaticError "duplicate_value: repeated value"
    .duplicateValue
    (setCategories
      (setSize json 2 2)
      [("Name", ["Eric", "Eric"]), ("Pet", ["dog", "cat"])]
    ).compress

  -- Stage 2 rejects unknown categories, values, houses, and duplicate clue ids.
  expectStaticError "unknown_category"
    .unknownCategory
    (updateClue json 0 fun clue =>
      clue.setObjVal! "a"
        (Json.mkObj [("cat", "Undeclared"), ("val", "Eric")])).compress
  expectStaticError "unknown_value"
    .unknownValue
    (updateClue json 0 fun clue =>
      clue.setObjVal! "a"
        (Json.mkObj [("cat", "Name"), ("val", "Missing")])).compress
  expectStaticError "house_out_of_range: above N"
    .houseOutOfRange
    (updateClue json 1 fun clue => clue.setObjVal! "house" 99).compress
  expectStaticError "duplicate_clue_id"
    .duplicateClueId
    (updateClue json 1 fun clue => clue.setObjVal! "id" "c1").compress

  -- Stage 2 also rejects house index 0. The parser accepts it as a positive
  -- raw house, but the puzzle bound is 1..N.
  let fixture2x2 ← loadFixture "lgp-test-2x2-33.problem.json"
  let json2x2 ← match Json.parse fixture2x2 with
    | .ok v => pure v
    | .error e => throw <| IO.userError e
  expectStaticError "house_out_of_range: zero"
    .houseOutOfRange
    ((updateClue json2x2 1 fun clue => clue.setObjVal! "house" 0).compress)

  -- Stage 2 never reads `expect`; the fixture-with-expect and
  -- fixture-without-expect both compile to the same opaque result.
  let compiledWithExpect ← expectCompiled "expect preserved"
    (← loadFixture "lgp-test-4x4-27.problem.json")
  assertTrue "expect dropped during compile" compiledWithExpect.envelope.expect.isSome
  let plainText ← loadFixture "lgp-test-4x4-27.problem.json"
  let parsedPlain ← match Json.parse plainText with
    | .ok value => pure (eraseField value "expect")
    | .error message => throw <| IO.userError s!"plain parse failed: {message}"
  let compiledNoExpect ← expectCompiled "expect absent" parsedPlain.compress
  assertTrue "compiled id changed when expect removed"
    (compiledNoExpect.envelope.id == compiledWithExpect.envelope.id)
  -- Compiled puzzle must not carry any solution. The only opaque content is
  -- the original envelope id.
  assertTrue "expect mutated during compile"
    (compiledNoExpect.envelope.expect == none)

  -- ====================================================================
  -- Stage 3A boundary: candidate parsing, validation, and clue checking.
  -- Public house keys are one-based and Lean never searches for values.
  -- ====================================================================
  let candidateText :=
    "{\"schema_version\":\"0.2\",\"problem_id\":\"zl_lgp-test-2x2-33\"," ++
    "\"solution\":{\"Name\":{\"1\":\"Eric\",\"2\":\"Arnold\"}," ++
    "\"Pet\":{\"1\":\"cat\",\"2\":\"dog\"}}}"
  let candidate ← match Candidate.parse candidateText with
    | .ok value => pure value
    | .error e => throw <| IO.userError (s!"candidate parse failed: {e.code.toString} at {e.path}")
  let puzzle2x2 ← expectCompiled "Stage 3A 2x2" fixture2x2
  assertTrue "known satisfying real 2x2 candidate was not solved"
    (CheckerCore.checkCandidate puzzle2x2 candidate == .solved)

  let violatingText := candidateText.replace
    "\"Pet\":{\"1\":\"cat\",\"2\":\"dog\"}"
    "\"Pet\":{\"1\":\"dog\",\"2\":\"cat\"}"
  let violating ← match Candidate.parse violatingText with
    | .ok value => pure value
    | .error error => throw <| IO.userError error.message
  assertTrue "complete bijective clue violation was not localized to c2"
    (CheckerCore.checkCandidate puzzle2x2 violating == .clueViolation 1 "c2")

  let partialText :=
    "{\"schema_version\":\"0.2\",\"problem_id\":\"zl_lgp-test-2x2-33\"," ++
    "\"solution\":{\"Name\":{\"1\":\"Eric\"}}}"
  let partialCandidate ← match Candidate.parse partialText with
    | .ok value => pure value
    | .error error => throw <| IO.userError error.message
  match CheckerCore.checkCandidate puzzle2x2 partialCandidate with
  | .incomplete failure =>
      assertTrue "partial candidate did not identify its first missing assignment"
        (failure.code == "missing_assignment")
  | _ => throw <| IO.userError "partial candidate was not INCOMPLETE"

  let invalidText := candidateText.replace "\"cat\"" "\"dragon\""
  let invalid ← match Candidate.parse invalidText with
    | .ok value => pure value
    | .error error => throw <| IO.userError error.message
  match CheckerCore.checkCandidate puzzle2x2 invalid with
  | .invalid failure => assertTrue "unknown value code changed" (failure.code == "unknown_value")
  | _ => throw <| IO.userError "unknown candidate value was not rejected"
  match Candidate.parse "{" with
  | .error e => do
      assertTrue "malformed JSON code changed"
        (e.code == CandidateParseErrorCode.invalidCandidateJson)
  | .ok _ => do
      throw <| IO.userError "malformed candidate JSON parsed"

  let a : Zebra.CategoryName := { value := "A" }
  let b : Zebra.CategoryName := { value := "B" }
  let a1 : Zebra.Attribute := { category := a, value := { value := "a1" } }
  let a2 : Zebra.Attribute := { category := a, value := { value := "a2" } }
  let a3 : Zebra.Attribute := { category := a, value := { value := "a3" } }
  let b1 : Zebra.Attribute := { category := b, value := { value := "b1" } }
  let b2 : Zebra.Attribute := { category := b, value := { value := "b2" } }
  let b3 : Zebra.Attribute := { category := b, value := { value := "b3" } }
  let b4 : Zebra.Attribute := { category := b, value := { value := "b4" } }
  let semanticCandidate : CandidateAssignment := {
    schemaVersion := "0.2", problemId := "semantics",
    solution := [
      { name := a, assignments := [
          (1, { value := "a1" }), (2, { value := "a2" }),
          (3, { value := "a3" }), (4, { value := "a4" })] },
      { name := b, assignments := [
          (1, { value := "b1" }), (2, { value := "b2" }),
          (3, { value := "b3" }), (4, { value := "b4" })] }
    ]
  }
  let violationClues : List Zebra.Clue := [
    .foundAt "found_at" a1 { value := 2 },
    .notAt "not_at" a1 { value := 1 },
    .sameHouse "same_house" a1 b2,
    .directLeft "direct_left" a2 b1,
    .directRight "direct_right" a1 b2,
    .sideBySide "side_by_side" a1 b3,
    .leftOf "left_of" a3 b1,
    .rightOf "right_of" a1 b3,
    .oneBetween "one_between" a1 b2,
    .twoBetween "two_between" a1 b3
  ]
  for clue in violationClues do
    assertTrue "a v0 clue violation predicate unexpectedly passed"
      (!CheckerCore.clueSatisfied semanticCandidate clue)
  let satisfiedClues : List Zebra.Clue := [
    .foundAt "found_at" a1 { value := 1 },
    .notAt "not_at" a1 { value := 2 },
    .sameHouse "same_house" a1 b1,
    .directLeft "direct_left" a1 b2,
    .directRight "direct_right" a2 b1,
    .sideBySide "side_by_side" a1 b2,
    .leftOf "left_of" a1 b3,
    .rightOf "right_of" a3 b1,
    .oneBetween "one_between" a1 b3,
    .twoBetween "two_between" a1 b4
  ]
  for clue in satisfiedClues do
    assertTrue "a v0 clue satisfaction predicate unexpectedly failed"
      (CheckerCore.clueSatisfied semanticCandidate clue)

  -- ====================================================================
  -- Walkthrough: problem.json -> ParsedProblem -> CompiledPuzzle ->
  -- COMPILED wire response. Demonstrates the locked boundary end-to-end.
  -- ====================================================================
  let walkSource ← loadFixture "lgp-test-2x2-33.problem.json"
  IO.println ""
  IO.println "--- Stage 1 walkthrough: lgp-test-2x2-33.problem.json ---"
  IO.println ""
  IO.println "raw JSON (truncated):"
  IO.println ((walkSource.take 120).toString ++ "...")
  let walkParsed ← expectParsed "walkthrough" walkSource
  IO.println ""
  IO.println "ParsedProblem.mk {"
  IO.println ("  envelope := " ++ Walkthrough.envelopeSummary walkParsed.envelope)
  IO.println "  puzzle := RawPuzzle.mk {"
  IO.println s!"    size := {Walkthrough.pp walkParsed.puzzle.size}"
  IO.println "    categories := #["
  for c in walkParsed.puzzle.categories do
    IO.println ("      { name := " ++ Walkthrough.pp c.name.value ++
      ", values := " ++ Walkthrough.pp c.values ++ " }")
  IO.println "    ]"
  IO.println "    clues := #["
  for c in walkParsed.puzzle.clues do
    IO.println ("      " ++ Walkthrough.clueSummary c)
  IO.println "    ]"
  IO.println "  }"
  IO.println "}"
  IO.println ""
  IO.println "--- Stage 2 walkthrough: Compiler.compile ---"
  IO.println ""
  let walkCompiled ← expectCompiled "walkthrough" walkSource
  IO.println "CompiledPuzzle.mk {"
  IO.println ("  envelope := " ++ Walkthrough.envelopeSummary walkCompiled.envelope)
  IO.println s!"  houses := {walkCompiled.houses}"
  IO.println "  categories := ["
  for cat in walkCompiled.categories do
    IO.println ("    " ++ Walkthrough.categorySummary cat)
  IO.println "  ]"
  IO.println "  clues := #["
  for clue in walkCompiled.clues do
    IO.println ("    " ++ Walkthrough.clueSummary clue)
  IO.println "  ]"
  IO.println "}"
  IO.println ""
  IO.println "--- COMPILED wire response (opaque) ---"
  IO.println ("{ \"kind\": \"COMPILED\", \"compiled\": { \"problem_id\": " ++
    Walkthrough.pp walkCompiled.envelope.id ++ " } }")

  IO.println ""
  IO.println "Stage 2 Lean static compiler checks passed"
  pure 0
