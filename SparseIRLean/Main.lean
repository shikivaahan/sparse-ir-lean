import Lean
import SparseIRLean

open Lean

namespace SparseIRLean.Cli

def protocolVersion : String := "0.1.0"
def backendVersion : String := "0.1.0"

private def jsonString (value : String) : Json := Json.str value

private def errorResponse (requestId : Json) (code message : String) : Json :=
  Json.mkObj [
    ("protocol_version", jsonString protocolVersion),
    ("request_id", requestId),
    ("result", Json.mkObj [
      ("kind", jsonString "STATIC_ERROR"),
      ("error_code", jsonString code),
      ("message", jsonString message)
    ])
  ]

private def infoResponse (requestId : Json) : Json :=
  Json.mkObj [
    ("protocol_version", jsonString protocolVersion),
    ("request_id", requestId),
    ("result", Json.mkObj [
      ("kind", jsonString "INFO"),
      ("backend_id", jsonString "SparseIRLeanVerifier"),
      ("backend_version", jsonString backendVersion),
      ("domain", jsonString Zebra.domainId),
      ("schema_version", jsonString schemaVersion),
      ("trust", jsonString "trusted_for_results"),
      ("capabilities", Json.mkObj [
        ("modes", Json.arr #[]),
        ("stepwise", Json.bool false),
        ("tactics", Json.bool false),
        ("audit_view", Json.bool false)
      ])
    ])
  ]

private def requestId (request : Json) : Json :=
  match request.getObjVal? "request_id" with
  | .ok value => value
  | .error _ => Json.null

private def dispatchCommand (request : Json) : Json :=
  let id := requestId request
  match request.getObjVal? "command" with
  | .ok (Json.str "info") => infoResponse id
  | .ok (Json.str _) => errorResponse id "not_implemented_stage_0"
      "Only the info command is implemented during Stage 0"
  | .ok _ => errorResponse id "invalid_request" "command must be a string"
  | .error _ => errorResponse id "invalid_request" "missing command"

private def dispatch (request : Json) : Json :=
  let id := requestId request
  match request.getObjVal? "protocol_version" with
  | .ok (Json.str version) =>
      if version == protocolVersion then
        dispatchCommand request
      else
        errorResponse id "unsupported_protocol_version"
          s!"Expected protocol version {protocolVersion}"
  | .ok _ => errorResponse id "invalid_request" "protocol_version must be a string"
  | .error _ => errorResponse id "invalid_request" "missing protocol_version"

def run : IO UInt32 := do
  let stdin ← IO.getStdin
  let input ← stdin.readToEnd
  let response := match Json.parse input with
    | .ok request => dispatch request
    | .error message => errorResponse Json.null "invalid_json" message
  IO.println response.compress
  pure 0

end SparseIRLean.Cli

def main : IO UInt32 := SparseIRLean.Cli.run
