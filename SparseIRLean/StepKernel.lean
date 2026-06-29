import SparseIRLean.CheckerCore

open Lean

namespace SparseIRLean

inductive StepErrorCode where
  | malformedStep
  | unknownCategory
  | unknownValue
  | houseOutOfRange
  | unknownClueRef
  | ruleClueMismatch
  | contradictsState
  | placementConflict
  | notForced
  | unsupportedRule
  | invalidConclusion
  | incompleteFinal
  | clueViolationFinal
  | maxStepsExceeded
  deriving Repr, BEq

def StepErrorCode.toString : StepErrorCode → String
  | .malformedStep => "malformed_step"
  | .unknownCategory => "unknown_category"
  | .unknownValue => "unknown_value"
  | .houseOutOfRange => "house_out_of_range"
  | .unknownClueRef => "unknown_clue_ref"
  | .ruleClueMismatch => "rule_clue_mismatch"
  | .contradictsState => "contradicts_state"
  | .placementConflict => "placement_conflict"
  | .notForced => "not_forced"
  | .unsupportedRule => "unsupported_rule"
  | .invalidConclusion => "invalid_conclusion"
  | .incompleteFinal => "incomplete_final"
  | .clueViolationFinal => "clue_violation_final"
  | .maxStepsExceeded => "max_steps_exceeded"

structure StepError where
  code : StepErrorCode
  path : String
  message : String
  deriving Repr, BEq

structure StepCell where
  category : Zebra.CategoryName
  house : Nat
  possible : List Zebra.ValueName
  placed : Bool
  deriving Repr, BEq

structure StepState where
  stepCount : Nat
  cells : List StepCell
  deriving Repr, BEq

structure StepJustification where
  rule : String
  clueId : Option String
  deriving Repr, BEq

inductive SingleStep where
  | place (item : Zebra.Attribute) (house : Nat) (justify : StepJustification)
  | eliminate (item : Zebra.Attribute) (house : Nat) (justify : StepJustification)
  | conclude (status : String) (solution : Option CandidateAssignment)
  deriving Repr, BEq

inductive StepCheckResult where
  | accepted (state : StepState)
  | solved
  | rejected (error : StepError)
  deriving Repr, BEq

namespace StepKernel

def maxSteps : Nat := 10000

def supportedRules : List String := [
  "given_found_at_place",
  "given_not_at_eliminate",
  "bijection_place_eliminates_same_value_other_houses",
  "bijection_place_eliminates_other_values_same_house",
  "bijection_cell_singleton_forces_place",
  "bijection_value_singleton_forces_place",
  "same_house_place_from_placed",
  "same_house_eliminate_no_possible_match",
  "direct_left_place_from_fixed",
  "direct_left_eliminate_no_possible_partner",
  "direct_right_place_from_fixed",
  "direct_right_eliminate_no_possible_partner",
  "side_by_side_place_from_single_neighbor",
  "side_by_side_eliminate_no_possible_neighbor",
  "left_of_eliminate_impossible_order",
  "right_of_eliminate_impossible_order",
  "one_between_place_from_fixed",
  "one_between_eliminate_no_possible_partner",
  "two_between_place_from_fixed",
  "two_between_eliminate_no_possible_partner",
  "solved_conclusion",
  "contradiction_detection"
]

private def fail (code : StepErrorCode) (path message : String) : Except StepError α :=
  .error { code, path, message }

private def reject (code : StepErrorCode) (path message : String) : StepCheckResult :=
  .rejected { code, path, message }

private def category? (puzzle : CompiledPuzzle)
    (name : Zebra.CategoryName) : Option CompiledCategory :=
  puzzle.categories.find? fun category => category.name == name

private def valueDeclared (category : CompiledCategory) (value : Zebra.ValueName) : Bool :=
  category.values.any fun declared => declared == value

private def houses (puzzle : CompiledPuzzle) : List Nat :=
  (List.range puzzle.houses).map (· + 1)

def initState (puzzle : CompiledPuzzle) : StepState :=
  let cells := puzzle.categories.flatMap fun category =>
    (houses puzzle).map fun house => {
      category := category.name,
      house := house,
      possible := category.values,
      placed := false
    }
  { stepCount := 0, cells := cells }

private def cell? (state : StepState) (category : Zebra.CategoryName)
    (house : Nat) : Option StepCell :=
  state.cells.find? fun cell => cell.category == category && cell.house == house

private def attributePossible (state : StepState) (item : Zebra.Attribute) (house : Nat) : Bool :=
  match cell? state item.category house with
  | some cell => cell.possible.any fun value => value == item.value
  | none => false

private def attributePlaced (state : StepState) (item : Zebra.Attribute) (house : Nat) : Bool :=
  match cell? state item.category house with
  | some cell => cell.placed && cell.possible == [item.value]
  | none => false

private def possibleHouses (puzzle : CompiledPuzzle) (state : StepState)
    (item : Zebra.Attribute) : List Nat :=
  (houses puzzle).filter fun house => attributePossible state item house

private def placedHouse? (puzzle : CompiledPuzzle) (state : StepState)
    (item : Zebra.Attribute) : Option Nat :=
  (houses puzzle).find? fun house => attributePlaced state item house

private def clueId : Zebra.Clue → String
  | .foundAt id .. | .notAt id .. | .sameHouse id .. | .directLeft id ..
  | .directRight id .. | .sideBySide id .. | .leftOf id .. | .rightOf id ..
  | .oneBetween id .. | .twoBetween id .. => id

private def clue? (puzzle : CompiledPuzzle) (id : String) : Option Zebra.Clue :=
  puzzle.clues.find? fun clue => clueId clue == id

private def stateContradiction (puzzle : CompiledPuzzle) (state : StepState) : Bool :=
  state.cells.any (fun cell => cell.possible.isEmpty || (cell.placed && cell.possible.length != 1)) ||
  puzzle.categories.any (fun category =>
    category.values.any fun value =>
      let item : Zebra.Attribute := { category := category.name, value := value }
      (possibleHouses puzzle state item).isEmpty ||
      ((houses puzzle).filter (attributePlaced state item)).length > 1)

private def updateCell (state : StepState) (category : Zebra.CategoryName)
    (house : Nat) (update : StepCell → StepCell) : StepState :=
  { state with cells := state.cells.map fun cell =>
      if cell.category == category && cell.house == house then update cell else cell }

private def placeValue (puzzle : CompiledPuzzle) (state : StepState)
    (item : Zebra.Attribute) (house : Nat) : Except StepError StepState := do
  let some target := cell? state item.category house
    | fail .unknownCategory "$.step.cat" "candidate cell does not exist"
  if target.placed then
    if target.possible == [item.value] then
      fail .contradictsState "$.step" "value is already placed in this cell"
    else
      fail .placementConflict "$.step" "cell already contains a different placed value"
  unless target.possible.any (· == item.value) do
    fail .contradictsState "$.step.val" "value has already been eliminated from this cell"
  for otherHouse in houses puzzle do
    if otherHouse != house && attributePlaced state item otherHouse then
      fail .placementConflict "$.step" "value is already placed in another house"
  let cells := state.cells.map fun cell =>
    if cell.category != item.category then cell
    else if cell.house == house then { cell with possible := [item.value], placed := true }
    else { cell with possible := cell.possible.filter (· != item.value) }
  let next := { stepCount := state.stepCount + 1, cells := cells }
  if stateContradiction puzzle next then
    fail .contradictsState "$.state" "placement creates an empty candidate set"
  pure next

private def eliminateValue (puzzle : CompiledPuzzle) (state : StepState)
    (item : Zebra.Attribute) (house : Nat) (allowNoop : Bool) : Except StepError StepState := do
  let some target := cell? state item.category house
    | fail .unknownCategory "$.step.cat" "candidate cell does not exist"
  unless target.possible.any (· == item.value) do
    if allowNoop then
      return { state with stepCount := state.stepCount + 1 }
    fail .contradictsState "$.step.val" "value is already absent from this cell"
  if target.placed || target.possible.length == 1 then
    fail .contradictsState "$.step" "elimination would empty a fixed cell"
  let next := updateCell state item.category house fun cell =>
    { cell with possible := cell.possible.filter (· != item.value) }
  let next := { next with stepCount := state.stepCount + 1 }
  if stateContradiction puzzle next then
    fail .contradictsState "$.state" "elimination creates a contradiction"
  pure next

private def clueRule (rule : String) : Bool :=
  rule.startsWith "given_" || rule.startsWith "same_house_" ||
  rule.startsWith "direct_left_" || rule.startsWith "direct_right_" ||
  rule.startsWith "side_by_side_" || rule.startsWith "left_of_" ||
  rule.startsWith "right_of_" || rule.startsWith "one_between_" ||
  rule.startsWith "two_between_"

private def clueMatchesRule (rule : String) : Zebra.Clue → Bool
  | .foundAt .. => rule == "given_found_at_place"
  | .notAt .. => rule == "given_not_at_eliminate"
  | .sameHouse .. => rule.startsWith "same_house_"
  | .directLeft .. => rule.startsWith "direct_left_"
  | .directRight .. => rule.startsWith "direct_right_"
  | .sideBySide .. => rule.startsWith "side_by_side_"
  | .leftOf .. => rule.startsWith "left_of_"
  | .rightOf .. => rule.startsWith "right_of_"
  | .oneBetween .. => rule.startsWith "one_between_"
  | .twoBetween .. => rule.startsWith "two_between_"

private def referencedClue (puzzle : CompiledPuzzle)
    (justify : StepJustification) : Except StepError (Option Zebra.Clue) := do
  if !clueRule justify.rule then return none
  let some id := justify.clueId
    | fail .unknownClueRef "$.step.justify.clue_id" "this rule requires a clue id"
  let some clue := clue? puzzle id
    | fail .unknownClueRef "$.step.justify.clue_id" s!"unknown clue id {id}"
  unless clueMatchesRule justify.rule clue do
    fail .ruleClueMismatch "$.step.justify.rule" "rule does not match the cited clue type"
  pure (some clue)

private def singletonNeighbor (puzzle : CompiledPuzzle) (state : StepState)
    (item : Zebra.Attribute) (fixedHouse distance : Nat) : Option Nat :=
  let candidates := (houses puzzle).filter fun house =>
    attributePossible state item house &&
      (house + distance == fixedHouse || fixedHouse + distance == house)
  match candidates with
  | [house] => some house
  | _ => none

private def noPartnerAtDistance (puzzle : CompiledPuzzle) (state : StepState)
    (item : Zebra.Attribute) (house distance : Nat) : Bool :=
  !(houses puzzle).any fun other =>
    attributePossible state item other &&
      (house + distance == other || other + distance == house)

private def ruleAllows (puzzle : CompiledPuzzle) (state : StepState)
    (step : SingleStep) : Except StepError Bool := do
  let justification := match step with
    | .place _ _ justify | .eliminate _ _ justify => some justify
    | .conclude .. => none
  let some justify := justification
    | return false
  unless supportedRules.contains justify.rule do
    fail .unsupportedRule "$.step.justify.rule" s!"unsupported rule {justify.rule}"
  let clue ← referencedClue puzzle justify
  match step with
  | .place item house _ =>
      match justify.rule, clue with
      | "given_found_at_place", some (.foundAt _ given givenHouse) =>
          pure (item == given && house == givenHouse.value)
      | "bijection_cell_singleton_forces_place", none =>
          pure <| match cell? state item.category house with
            | some cell => !cell.placed && cell.possible == [item.value]
            | none => false
      | "bijection_value_singleton_forces_place", none =>
          pure (!attributePlaced state item house && possibleHouses puzzle state item == [house])
      | "same_house_place_from_placed", some (.sameHouse _ a b) =>
          pure <| if item == a then attributePlaced state b house
            else if item == b then attributePlaced state a house else false
      | "direct_left_place_from_fixed", some (.directLeft _ a b) =>
          pure <| if item == a then placedHouse? puzzle state b == some (house + 1)
            else if item == b then house > 1 && placedHouse? puzzle state a == some (house - 1)
            else false
      | "direct_right_place_from_fixed", some (.directRight _ a b) =>
          pure <| if item == a then house > 1 && placedHouse? puzzle state b == some (house - 1)
            else if item == b then placedHouse? puzzle state a == some (house + 1)
            else false
      | "side_by_side_place_from_single_neighbor", some (.sideBySide _ a b) =>
          if item == a then
            pure <| match placedHouse? puzzle state b with
              | some fixed => singletonNeighbor puzzle state a fixed 1 == some house
              | none => false
          else if item == b then
            pure <| match placedHouse? puzzle state a with
              | some fixed => singletonNeighbor puzzle state b fixed 1 == some house
              | none => false
          else pure false
      | "one_between_place_from_fixed", some (.oneBetween _ a b) =>
          if item == a then
            pure <| match placedHouse? puzzle state b with
              | some fixed => singletonNeighbor puzzle state a fixed 2 == some house
              | none => false
          else if item == b then
            pure <| match placedHouse? puzzle state a with
              | some fixed => singletonNeighbor puzzle state b fixed 2 == some house
              | none => false
          else pure false
      | "two_between_place_from_fixed", some (.twoBetween _ a b) =>
          if item == a then
            pure <| match placedHouse? puzzle state b with
              | some fixed => singletonNeighbor puzzle state a fixed 3 == some house
              | none => false
          else if item == b then
            pure <| match placedHouse? puzzle state a with
              | some fixed => singletonNeighbor puzzle state b fixed 3 == some house
              | none => false
          else pure false
      | _, _ => pure false
  | .eliminate item house _ =>
      match justify.rule, clue with
      | "given_not_at_eliminate", some (.notAt _ given givenHouse) =>
          pure (item == given && house == givenHouse.value)
      | "bijection_place_eliminates_same_value_other_houses", none =>
          pure <| (houses puzzle).any fun other =>
            other != house && attributePlaced state item other
      | "bijection_place_eliminates_other_values_same_house", none =>
          pure <| match cell? state item.category house with
            | some cell => cell.placed && cell.possible.length == 1 && cell.possible != [item.value]
            | none => false
      | "same_house_eliminate_no_possible_match", some (.sameHouse _ a b) =>
          pure <| if item == a then !attributePossible state b house
            else if item == b then !attributePossible state a house else false
      | "direct_left_eliminate_no_possible_partner", some (.directLeft _ a b) =>
          pure <| if item == a then !attributePossible state b (house + 1)
            else if item == b then house == 1 || !attributePossible state a (house - 1)
            else false
      | "direct_right_eliminate_no_possible_partner", some (.directRight _ a b) =>
          pure <| if item == a then house == 1 || !attributePossible state b (house - 1)
            else if item == b then !attributePossible state a (house + 1)
            else false
      | "side_by_side_eliminate_no_possible_neighbor", some (.sideBySide _ a b) =>
          pure <| if item == a then noPartnerAtDistance puzzle state b house 1
            else if item == b then noPartnerAtDistance puzzle state a house 1 else false
      | "left_of_eliminate_impossible_order", some (.leftOf _ a b) =>
          pure <| if item == a then !(possibleHouses puzzle state b).any (· > house)
            else if item == b then !(possibleHouses puzzle state a).any (· < house)
            else false
      | "right_of_eliminate_impossible_order", some (.rightOf _ a b) =>
          pure <| if item == a then !(possibleHouses puzzle state b).any (· < house)
            else if item == b then !(possibleHouses puzzle state a).any (· > house)
            else false
      | "one_between_eliminate_no_possible_partner", some (.oneBetween _ a b) =>
          pure <| if item == a then noPartnerAtDistance puzzle state b house 2
            else if item == b then noPartnerAtDistance puzzle state a house 2 else false
      | "two_between_eliminate_no_possible_partner", some (.twoBetween _ a b) =>
          pure <| if item == a then noPartnerAtDistance puzzle state b house 3
            else if item == b then noPartnerAtDistance puzzle state a house 3 else false
      | _, _ => pure false
  | .conclude .. => pure false

private def candidateFromState (puzzle : CompiledPuzzle)
    (state : StepState) : Option CandidateAssignment := do
  let mut solution : List CandidateCategory := []
  for category in puzzle.categories do
    let mut assignments : List (Nat × Zebra.ValueName) := []
    for house in houses puzzle do
      let cell ← cell? state category.name house
      let [value] := cell.possible | none
      assignments := assignments ++ [(house, value)]
    solution := solution ++ [{ name := category.name, assignments := assignments }]
  pure { schemaVersion := schemaVersion, problemId := puzzle.envelope.id, solution := solution }

private def conclude (puzzle : CompiledPuzzle) (state : StepState)
    (status : String) (supplied : Option CandidateAssignment) : StepCheckResult :=
  if status != "solved" then
    reject .invalidConclusion "$.step.status" "Stage 3C only accepts a solved conclusion"
  else if stateContradiction puzzle state then
    reject .invalidConclusion "$.state" "contradictory state cannot be concluded"
  else match candidateFromState puzzle state with
    | none => reject .incompleteFinal "$.state" "candidate state is not complete"
    | some candidate =>
        if supplied.isSome && supplied != some candidate then
          reject .invalidConclusion "$.step.solution"
            "supplied solution does not match the candidate state"
        else match CheckerCore.checkCandidate puzzle candidate with
          | .solved => .solved
          | .clueViolation index id =>
              reject .clueViolationFinal s!"$.clues[{index}]" s!"candidate violates clue {id}"
          | _ => reject .invalidConclusion "$.state" "candidate state is invalid"

def checkStep (puzzle : CompiledPuzzle) (state : StepState) (step : SingleStep) : StepCheckResult :=
  if state.stepCount >= maxSteps then
    reject .maxStepsExceeded "$.state.step_count" s!"maximum of {maxSteps} steps exceeded"
  else match step with
    | .conclude status solution => conclude puzzle state status solution
    | .place item house _justify =>
        if stateContradiction puzzle state then
          reject .contradictsState "$.state" "candidate state already contains a contradiction"
        else match ruleAllows puzzle state step with
          | .error error => .rejected error
          | .ok false => reject .notForced "$.step"
              "the cited local rule does not force this placement"
          | .ok true => match placeValue puzzle state item house with
              | .ok next => .accepted next
              | .error error => .rejected error
    | .eliminate item house justify =>
        if stateContradiction puzzle state then
          reject .contradictsState "$.state" "candidate state already contains a contradiction"
        else match ruleAllows puzzle state step with
          | .error error => .rejected error
          | .ok false => reject .notForced "$.step"
              "the cited local rule does not force this elimination"
          | .ok true =>
              let propagation := justify.rule ==
                "bijection_place_eliminates_same_value_other_houses" || justify.rule ==
                "bijection_place_eliminates_other_values_same_house"
              match eliminateValue puzzle state item house propagation with
              | .ok next => .accepted next
              | .error error => .rejected error

private abbrev JObject := Std.TreeMap.Raw String Json compare

private def asObject (path : String) (value : Json) : Except StepError JObject :=
  match value with
  | .obj fields => pure fields
  | _ => fail .malformedStep path "expected an object"

private def required (path field : String) (object : JObject) : Except StepError Json :=
  match object.get? field with
  | some value => pure value
  | none => fail .malformedStep s!"{path}.{field}" s!"missing field {field}"

private def asString (path : String) (value : Json) : Except StepError String :=
  match value with
  | .str result => if result.isEmpty then fail .malformedStep path "string must be non-empty"
      else pure result
  | _ => fail .malformedStep path "expected a string"

private def divideDecimal (mantissa : Nat) : Nat → Option Nat
  | 0 => some mantissa
  | exponent + 1 =>
      if mantissa % 10 == 0 then divideDecimal (mantissa / 10) exponent else none

private def asNat (path : String) (value : Json) : Except StepError Nat :=
  match value with
  | .num number =>
      if number.mantissa < 0 then fail .malformedStep path "expected a natural number"
      else match divideDecimal number.mantissa.natAbs number.exponent with
        | some result => pure result
        | none => fail .malformedStep path "expected an integer"
  | _ => fail .malformedStep path "expected an integer"

private def parseTarget (puzzle : CompiledPuzzle) (object : JObject) : Except StepError
    (Zebra.Attribute × Nat) := do
  let categoryName ← asString "$.step.cat" (← required "$.step" "cat" object)
  let category : Zebra.CategoryName := { value := categoryName }
  let some declared := category? puzzle category
    | fail .unknownCategory "$.step.cat" s!"unknown category {categoryName}"
  let valueName ← asString "$.step.val" (← required "$.step" "val" object)
  let value : Zebra.ValueName := { value := valueName }
  unless valueDeclared declared value do
    fail .unknownValue "$.step.val" s!"unknown value {valueName}"
  let house ← asNat "$.step.house" (← required "$.step" "house" object)
  unless 1 ≤ house && house ≤ puzzle.houses do
    fail .houseOutOfRange "$.step.house" s!"house {house} is outside 1..{puzzle.houses}"
  pure ({ category := category, value := value }, house)

private def parseJustification (object : JObject) : Except StepError StepJustification := do
  let raw ← required "$.step" "justify" object
  let justify ← asObject "$.step.justify" raw
  let rule ← asString "$.step.justify.rule" (← required "$.step.justify" "rule" justify)
  let clueId ← match justify.get? "clue_id" with
    | none => pure none
    | some value => pure (some (← asString "$.step.justify.clue_id" value))
  pure { rule := rule, clueId := clueId }

def parseStepJson (puzzle : CompiledPuzzle) (value : Json) : Except StepError SingleStep := do
  let object ← asObject "$.step" value
  let op ← asString "$.step.op" (← required "$.step" "op" object)
  if op == "place" || op == "eliminate" then
    let (item, house) ← parseTarget puzzle object
    let justify ← parseJustification object
    if op == "place" then pure (.place item house justify)
    else pure (.eliminate item house justify)
  else if op == "conclude" then
    let status ← asString "$.step.status" (← required "$.step" "status" object)
    let solution ← match object.get? "solution" with
      | none => pure none
      | some raw => match Candidate.parseJson raw with
          | .ok candidate => pure (some candidate)
          | .error error => fail .malformedStep error.path error.message
    pure (.conclude status solution)
  else
    fail .malformedStep "$.step.op" s!"unknown operation {op}"

def parseStep (puzzle : CompiledPuzzle) (input : String) : Except StepError SingleStep :=
  match Json.parse input with
  | .ok value => parseStepJson puzzle value
  | .error message => .error { code := .malformedStep, path := "$.step", message := message }

def stateToJson (state : StepState) : Json :=
  Json.mkObj [
    ("step_count", toJson state.stepCount),
    ("cells", Json.arr <| state.cells.toArray.map fun cell => Json.mkObj [
      ("cat", Json.str cell.category.value),
      ("house", toJson cell.house),
      ("possible", Json.arr <| cell.possible.toArray.map fun value => Json.str value.value),
      ("placed", Json.bool cell.placed)
    ])
  ]

def parseStateJson (puzzle : CompiledPuzzle) (value : Json) : Except StepError StepState := do
  let object ← asObject "$.state" value
  let stepCount ← asNat "$.state.step_count" (← required "$.state" "step_count" object)
  let rawCells ← required "$.state" "cells" object
  let cellsArray ← match rawCells with
    | .arr cells => pure cells
    | _ => fail .malformedStep "$.state.cells" "expected an array"
  let mut cells : List StepCell := []
  for rawCell in cellsArray do
    let cellObject ← asObject "$.state.cells[]" rawCell
    let categoryName ← asString "$.state.cells[].cat"
      (← required "$.state.cells[]" "cat" cellObject)
    let category : Zebra.CategoryName := { value := categoryName }
    let some declared := category? puzzle category
      | fail .unknownCategory "$.state.cells[].cat" s!"unknown category {categoryName}"
    let house ← asNat "$.state.cells[].house" (← required "$.state.cells[]" "house" cellObject)
    unless 1 ≤ house && house ≤ puzzle.houses do
      fail .houseOutOfRange "$.state.cells[].house" "state house is out of range"
    if cells.any fun cell => cell.category == category && cell.house == house then
      fail .malformedStep "$.state.cells" "duplicate candidate cell"
    let rawPossible ← required "$.state.cells[]" "possible" cellObject
    let possibleArray ← match rawPossible with
      | .arr values => pure values
      | _ => fail .malformedStep "$.state.cells[].possible" "expected an array"
    let mut possible : List Zebra.ValueName := []
    for rawValue in possibleArray do
      let valueName ← asString "$.state.cells[].possible[]" rawValue
      let value : Zebra.ValueName := { value := valueName }
      unless valueDeclared declared value do
        fail .unknownValue "$.state.cells[].possible[]" s!"unknown value {valueName}"
      if possible.any (· == value) then
        fail .malformedStep "$.state.cells[].possible" "duplicate possible value"
      possible := possible ++ [value]
    let placed ← match ← required "$.state.cells[]" "placed" cellObject with
      | .bool value => pure value
      | _ => fail .malformedStep "$.state.cells[].placed" "expected a boolean"
    cells := cells ++ [{ category := category, house := house, possible := possible, placed := placed }]
  unless cells.length == puzzle.categories.length * puzzle.houses do
    fail .malformedStep "$.state.cells" "state does not contain every category/house cell"
  pure { stepCount := stepCount, cells := cells }

def parseState (puzzle : CompiledPuzzle) (input : String) : Except StepError StepState :=
  match Json.parse input with
  | .ok value => parseStateJson puzzle value
  | .error message => .error { code := .malformedStep, path := "$.state", message := message }

end StepKernel
end SparseIRLean
