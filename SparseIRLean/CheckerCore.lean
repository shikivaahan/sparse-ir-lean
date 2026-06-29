import SparseIRLean.Candidate

namespace SparseIRLean

structure CandidateIssue where
  code : String
  path : String
  message : String
  deriving Repr, BEq

inductive CandidateCheckResult where
  | solved
  | clueViolation (clueIndex : Nat) (clueId : String)
  | incomplete (issue : CandidateIssue)
  | invalid (issue : CandidateIssue)
  deriving Repr, BEq

namespace CheckerCore

def available : Bool := true

private def issue (code path message : String) : CandidateIssue := { code, path, message }

private def compiledCategory? (puzzle : CompiledPuzzle)
    (name : Zebra.CategoryName) : Option CompiledCategory :=
  puzzle.categories.find? fun category => category.name == name

private def candidateCategory? (candidate : CandidateAssignment)
    (name : Zebra.CategoryName) : Option CandidateCategory :=
  candidate.solution.find? fun category => category.name == name

private def valueDeclared (category : CompiledCategory) (value : Zebra.ValueName) : Bool :=
  category.values.any fun declared => declared == value

private def houseOf (candidate : CandidateAssignment) (item : Zebra.Attribute) : Option Nat := do
  let category ← candidateCategory? candidate item.category
  let assignment ← category.assignments.find? fun pair => pair.2 == item.value
  pure assignment.1

private def atHouses (candidate : CandidateAssignment) (a b : Zebra.Attribute)
    (predicate : Nat → Nat → Bool) : Bool :=
  match houseOf candidate a, houseOf candidate b with
  | some ah, some bh => predicate ah bh
  | _, _ => false

/-- Evaluate one clue against a supplied complete assignment. This only looks up
    candidate-provided locations and applies the fixed predicate; it never fills
    cells or searches over alternatives. -/
def clueSatisfied (candidate : CandidateAssignment) : Zebra.Clue → Bool
  | .foundAt _ item house => houseOf candidate item == some house.value
  | .notAt _ item house =>
      match houseOf candidate item with
      | some actual => actual != house.value
      | none => false
  | .sameHouse _ a b => atHouses candidate a b (· == ·)
  | .directLeft _ a b => atHouses candidate a b fun ah bh => ah + 1 == bh
  | .directRight _ a b => atHouses candidate a b fun ah bh => ah == bh + 1
  | .sideBySide _ a b => atHouses candidate a b fun ah bh => ah + 1 == bh || bh + 1 == ah
  | .leftOf _ a b => atHouses candidate a b (· < ·)
  | .rightOf _ a b => atHouses candidate a b (· > ·)
  | .oneBetween _ a b => atHouses candidate a b fun ah bh => ah + 2 == bh || bh + 2 == ah
  | .twoBetween _ a b => atHouses candidate a b fun ah bh => ah + 3 == bh || bh + 3 == ah

private def clueId : Zebra.Clue → String
  | .foundAt id .. | .notAt id .. | .sameHouse id .. | .directLeft id ..
  | .directRight id .. | .sideBySide id .. | .leftOf id .. | .rightOf id ..
  | .oneBetween id .. | .twoBetween id .. => id

/-- Validate and classify one full or partial candidate. Missing categories or
    houses are `INCOMPLETE`; malformed, extra, unknown, or non-bijective content
    is invalid. Partial candidates are not support-checked in Stage 3A. -/
def checkCandidate (puzzle : CompiledPuzzle)
    (candidate : CandidateAssignment) : CandidateCheckResult := Id.run do
  if candidate.problemId != puzzle.envelope.id then
    return .invalid <| issue "problem_id_mismatch" "$.problem_id"
      s!"candidate problem_id '{candidate.problemId}' does not match '{puzzle.envelope.id}'"

  for supplied in candidate.solution do
    let categoryPath := s!"$.solution.{supplied.name.value}"
    let some declared := compiledCategory? puzzle supplied.name
      | return .invalid <| issue "unknown_category" categoryPath
          s!"unknown category {supplied.name.value}"
    let mut seenHouses : List Nat := []
    let mut seenValues : List Zebra.ValueName := []
    for (house, value) in supplied.assignments do
      let path := s!"{categoryPath}.{house}"
      if house < 1 || house > puzzle.houses then
        return .invalid <| issue "extra_house" path
          s!"house {house} is outside 1..{puzzle.houses}"
      if seenHouses.contains house then
        return .invalid <| issue "duplicate_house" path s!"house {house} is assigned twice"
      unless valueDeclared declared value do
        return .invalid <| issue "unknown_value" path
          s!"unknown value {value.value} for category {declared.name.value}"
      if seenValues.any fun existing => existing == value then
        return .invalid <| issue "duplicate_value" path
          s!"value {value.value} is assigned more than once in category {declared.name.value}"
      seenHouses := house :: seenHouses
      seenValues := value :: seenValues

  for declared in puzzle.categories do
    let some supplied := candidateCategory? candidate declared.name
      | return .incomplete <| issue "missing_category" s!"$.solution.{declared.name.value}"
          s!"missing category {declared.name.value}"
    for house in [1:puzzle.houses + 1] do
      unless supplied.assignments.any fun pair => pair.1 == house do
        return .incomplete <| issue "missing_assignment"
          s!"$.solution.{declared.name.value}.{house}" "missing assignment"
    for value in declared.values do
      unless supplied.assignments.any fun pair => pair.2 == value do
        return .invalid <| issue "category_not_bijective" s!"$.solution.{declared.name.value}"
          s!"category {declared.name.value} does not use value {value.value} exactly once"

  for clue in puzzle.clues, index in [:puzzle.clues.size] do
    unless clueSatisfied candidate clue do
      return .clueViolation index (clueId clue)
  return .solved

end CheckerCore
end SparseIRLean
