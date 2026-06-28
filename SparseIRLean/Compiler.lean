import Lean.Data.Json
import SparseIRLean.Json
import SparseIRLean.Zebra

namespace SparseIRLean

/-- Stage 2 static-error vocabulary. Frozen by the Stage 2 quality gate.
    All semantic well-formedness checks for Zebra puzzles live here; the
    parser (`SparseIRLean.Json`) never inspects any of these values. -/
inductive StaticErrorCode where
  | unsupportedSchemaVersion
  | invalidDomain
  | sizeMismatch
  | categorySizeMismatch
  | duplicateValue
  | unknownCategory
  | unknownValue
  | houseOutOfRange
  | duplicateClueId
  deriving BEq

def StaticErrorCode.toString : StaticErrorCode → String
  | .unsupportedSchemaVersion => "unsupported_schema_version"
  | .invalidDomain => "invalid_domain"
  | .sizeMismatch => "size_mismatch"
  | .categorySizeMismatch => "category_size_mismatch"
  | .duplicateValue => "duplicate_value"
  | .unknownCategory => "unknown_category"
  | .unknownValue => "unknown_value"
  | .houseOutOfRange => "house_out_of_range"
  | .duplicateClueId => "duplicate_clue_id"

structure StaticError where
  code : StaticErrorCode
  path : String
  message : String
  deriving BEq

/-- The frozen Stage 2 representation of a Zebra puzzle. The list-based view is
    what the Stage 3 checker core consumes; the raw AST from the parser is not
    reused at later stages. -/
structure CompiledCategory where
  name : Zebra.CategoryName
  values : List Zebra.ValueName
  deriving BEq, Inhabited

structure CompiledPuzzle where
  envelope : Envelope
  houses : Nat
  categories : List CompiledCategory
  clues : Array Zebra.Clue
  deriving BEq

def staticCompilerAvailable : Bool := true

namespace Compiler

private abbrev CompileM := Except StaticError

private def fail (code : StaticErrorCode) (path message : String) : CompileM α :=
  .error { code, path, message }

private def categoryPath (index : Nat) : String := s!"$.categories[{index}]"

private def cluePath (index : Nat) : String := s!"$.clues[{index}]"

private def attrPath (parent : String) (side field : String) : String :=
  s!"{parent}.{side}.{field}"

private def categoryIndex (categories : List CompiledCategory)
    (name : Zebra.CategoryName) : Option Nat :=
  categories.findIdx? (fun cat => cat.name == name)

private def valueDeclared (category : CompiledCategory) (value : Zebra.ValueName) : Bool :=
  category.values.any (fun v => v == value)

/-- The Stage 2 compile step. Never inspects `expect`, never solves, and never
    touches the puzzle solution; it only enforces the envelope acceptance, size,
    declaration, and uniqueness invariants specified in Section 7.1 of the spec.
    `expect` is preserved opaquely on the resulting `CompiledPuzzle.envelope`
    but is never used for any correctness decision. -/
def compile (problem : ParsedProblem) : CompileM CompiledPuzzle := do
  let envelope := problem.envelope
  unless envelope.schemaVersion == schemaVersion do
    fail .unsupportedSchemaVersion "$.schema_version"
      s!"expected schema version {schemaVersion}"
  unless envelope.domain == Zebra.domainId do
    fail .invalidDomain "$.domain" s!"domain must be '{Zebra.domainId}'"
  let raw := problem.puzzle
  let houses := raw.size.houses
  let declaredCategoryCount := raw.size.categories
  let rawCategories := raw.categories.toList
  if rawCategories.length != declaredCategoryCount then
    fail .sizeMismatch "$.size.categories"
      s!"declared {declaredCategoryCount} categories but provided {rawCategories.length}"
  let mut compiled : List CompiledCategory := []
  for cat in rawCategories do
    let values := cat.values.toList
    if values.length != houses then
      fail .categorySizeMismatch s!"$.categories.{cat.name.value}"
        s!"category '{cat.name.value}' has {values.length} values; expected {houses}"
    let mut seen : List Zebra.ValueName := []
    let mut vidx : Nat := 0
    for value in values do
      if seen.any (fun v => v == value) then
        fail .duplicateValue s!"$.categories.{cat.name.value}[{vidx}]"
          s!"category '{cat.name.value}' lists value '{value.value}' more than once"
      seen := value :: seen
      vidx := vidx + 1
    compiled := { name := cat.name, values := values } :: compiled
  let categories := compiled.reverse
  let mut seenIds : List String := []
  let mut clues := #[]
  for clue in raw.clues, index in [:raw.clues.size] do
    let id := match clue with
      | .foundAt id .. => id
      | .notAt id .. => id
      | .sameHouse id .. => id
      | .directLeft id .. => id
      | .directRight id .. => id
      | .sideBySide id .. => id
      | .leftOf id .. => id
      | .rightOf id .. => id
      | .oneBetween id .. => id
      | .twoBetween id .. => id
    if seenIds.contains id then
      fail .duplicateClueId s!"{cluePath index}.id"
        s!"clue id '{id}' is used by more than one clue"
    seenIds := id :: seenIds
    let clueRoot := cluePath index
    let checkBinaryAttr (side : String) (attr : Zebra.Attribute) : CompileM Unit := do
      match categoryIndex categories attr.category with
      | none =>
          fail .unknownCategory (attrPath clueRoot side "cat")
            s!"clue references unknown category '{attr.category.value}'"
      | some catIdx =>
          let category := categories[catIdx]!
          unless valueDeclared category attr.value do
            fail .unknownValue (attrPath clueRoot side "val")
              s!"value '{attr.value.value}' is not declared in category '{category.name.value}'"
    let checkUnaryAttr (attr : Zebra.Attribute) : CompileM Unit := do
      match categoryIndex categories attr.category with
      | none =>
          fail .unknownCategory s!"{clueRoot}.cat"
            s!"clue references unknown category '{attr.category.value}'"
      | some catIdx =>
          let category := categories[catIdx]!
          unless valueDeclared category attr.value do
            fail .unknownValue s!"{clueRoot}.val"
              s!"value '{attr.value.value}' is not declared in category '{category.name.value}'"
    let checkHouse (house : Zebra.House) : CompileM Unit := do
      unless 1 ≤ house.value ∧ house.value ≤ houses do
        fail .houseOutOfRange s!"{clueRoot}.house"
          s!"house {house.value} is outside 1..{houses}"
    match clue with
    | .foundAt _ attr house =>
        checkUnaryAttr attr
        checkHouse house
    | .notAt _ attr house =>
        checkUnaryAttr attr
        checkHouse house
    | .sameHouse _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .directLeft _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .directRight _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .sideBySide _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .leftOf _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .rightOf _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .oneBetween _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    | .twoBetween _ a b => checkBinaryAttr "a" a; checkBinaryAttr "b" b
    clues := clues.push clue
  pure {
    envelope := envelope,
    houses := houses,
    categories := categories,
    clues := clues
  }

end Compiler

end SparseIRLean
