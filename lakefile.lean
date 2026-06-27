import Lake
open Lake DSL

package «sparse-ir-lean» where
  version := v!"0.1.0"

@[default_target]
lean_lib SparseIRLean

@[default_target]
lean_exe «sparse-ir-lean» where
  root := `SparseIRLean.Main

@[test_driver]
lean_exe «sparse-ir-lean-tests» where
  root := `Tests
