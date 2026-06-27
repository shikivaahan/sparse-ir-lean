import Lean.Data.Json

namespace SparseIRLean.Zebra

/-- The only domain admitted by the v0 repository. -/
def domainId : String := "zebra"

structure CategoryName where
  value : String
  deriving Repr, BEq

structure ValueName where
  value : String
  deriving Repr, BEq

/-- A one-based house encoding. Bounds against a puzzle are checked by Stage 2. -/
structure House where
  value : Nat
  deriving Repr, BEq

structure Attribute where
  category : CategoryName
  value : ValueName
  deriving Repr, BEq

/-- Raw clue syntax. Reference and bound checks deliberately belong to Stage 2. -/
inductive Clue where
  | foundAt (id : String) (item : Attribute) (house : House)
  | notAt (id : String) (item : Attribute) (house : House)
  | sameHouse (id : String) (a b : Attribute)
  | directLeft (id : String) (a b : Attribute)
  | directRight (id : String) (a b : Attribute)
  | sideBySide (id : String) (a b : Attribute)
  | leftOf (id : String) (a b : Attribute)
  | rightOf (id : String) (a b : Attribute)
  | oneBetween (id : String) (a b : Attribute)
  | twoBetween (id : String) (a b : Attribute)
  deriving Repr, BEq

structure PuzzleSize where
  houses : Nat
  categories : Nat
  deriving Repr, BEq

structure Category where
  name : CategoryName
  values : Array ValueName
  deriving Repr, BEq

structure RawPuzzle where
  size : PuzzleSize
  categories : Array Category
  clues : Array Clue
  deriving Repr, BEq

def astAvailable : Bool := true

end SparseIRLean.Zebra
