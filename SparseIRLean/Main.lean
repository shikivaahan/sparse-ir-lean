import Lean
import SparseIRLean

open Lean

namespace SparseIRLean.Cli

def protocolVersion : String := "0.1.0"
def backendVersion : String := "0.1.0"

private def jsonString (value : String) : Json := Json.str value

private def errorResponseWithPath (requestId : Json) (code message : String)
    (path : Option String) : Json :=
  let errorFields := [
    ("kind", jsonString "STATIC_ERROR"),
    ("error_code", jsonString code),
    ("message", jsonString message)
  ] ++ match path with
    | some value => [("error_path", jsonString value)]
    | none => []
  Json.mkObj [
    ("protocol_version", jsonString protocolVersion),
    ("request_id", requestId),
    ("result", Json.mkObj errorFields)
  ]

private def errorResponse (requestId : Json) (code message : String) : Json :=
  errorResponseWithPath requestId code message none

private def errorResponseAt (requestId : Json) (code path message : String) : Json :=
  errorResponseWithPath requestId code message (some path)

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
        ("stepwise", Json.bool true),
        ("tactics", Json.bool false),
        ("audit_view", Json.bool false)
      ])
    ])
  ]

private def compiledResponse (requestId id : Json) : Json :=
  Json.mkObj [
    ("protocol_version", jsonString protocolVersion),
    ("request_id", requestId),
    ("result", Json.mkObj [
      ("kind", jsonString "COMPILED"),
      ("compiled", Json.mkObj [
        ("problem_id", id)
      ])
    ])
  ]

private def resultResponse (requestId result : Json) : Json :=
  Json.mkObj [
    ("protocol_version", jsonString protocolVersion),
    ("request_id", requestId),
    ("result", result)
  ]

private def solvedResponse (requestId : Json) (problemId : String) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "ACCEPT_SOLVED"),
    ("artifact", Json.mkObj [
      ("problem_id", jsonString problemId),
      ("status", jsonString "solved"),
      ("claim", jsonString "assignment satisfies all clues of the puzzle")
    ])
  ]

private def failureView (status : String) (failure : CandidateIssue)
    (extra : List (String × Json) := []) : Json :=
  Json.mkObj <| [
    ("status", jsonString status),
    ("failure_code", jsonString failure.code),
    ("path", jsonString failure.path),
    ("message", jsonString failure.message)
  ] ++ extra

private def invalidCandidateResponse (requestId : Json) (failure : CandidateIssue) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "REJECT"),
    ("failure", failureView "invalid_candidate" failure)
  ]

private def malformedCandidateResponse (requestId : Json)
    (failure : CandidateParseError) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "REJECT"),
    ("failure", failureView "malformed_candidate" {
      code := failure.code.toString, path := failure.path, message := failure.message
    })
  ]

private def incompleteResponse (requestId : Json) (problemId : String)
    (failure : CandidateIssue) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "INCOMPLETE"),
    ("state", Json.mkObj [
      ("problem_id", jsonString problemId),
      ("status", jsonString "incomplete"),
      ("failure_code", jsonString failure.code),
      ("path", jsonString failure.path),
      ("message", jsonString failure.message)
    ])
  ]

private def clueViolationResponse (requestId : Json) (index : Nat) (clueId : String) : Json :=
  let failure : CandidateIssue := {
    code := "clue_violation",
    path := s!"$.clues[{index}]",
    message := s!"candidate violates clue {clueId}"
  }
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "REJECT"),
    ("failure", failureView "clue_violation" failure [("clue_id", jsonString clueId)])
  ]

private def initializedStateResponse (requestId : Json) (state : StepState) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "STATE_INITIALIZED"),
    ("state", StepKernel.stateToJson state)
  ]

private def acceptedStepResponse (requestId : Json) (state : StepState) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "ACCEPT_STEP"),
    ("state", StepKernel.stateToJson state)
  ]

private def rejectedStepResponse (requestId : Json) (failure : StepError) : Json :=
  resultResponse requestId <| Json.mkObj [
    ("kind", jsonString "REJECT"),
    ("failure", Json.mkObj [
      ("status", jsonString "step_rejected"),
      ("failure_code", jsonString failure.code.toString),
      ("path", jsonString failure.path),
      ("message", jsonString failure.message)
    ])
  ]

private def attributeView (item : Zebra.Attribute) : Json :=
  Json.mkObj [
    ("cat", jsonString item.category.value),
    ("val", jsonString item.value.value)
  ]

private def binaryClueView (id clueType : String) (a b : Zebra.Attribute) : Json :=
  Json.mkObj [
    ("id", jsonString id),
    ("type", jsonString clueType),
    ("a", attributeView a),
    ("b", attributeView b)
  ]

private def clueView : Zebra.Clue → Json
  | .foundAt id item house => Json.mkObj [
      ("id", jsonString id),
      ("type", jsonString "found_at"),
      ("cat", jsonString item.category.value),
      ("val", jsonString item.value.value),
      ("house", toJson house.value)
    ]
  | .notAt id item house => Json.mkObj [
      ("id", jsonString id),
      ("type", jsonString "not_at"),
      ("cat", jsonString item.category.value),
      ("val", jsonString item.value.value),
      ("house", toJson house.value)
    ]
  | .sameHouse id a b => binaryClueView id "same_house" a b
  | .directLeft id a b => binaryClueView id "direct_left" a b
  | .directRight id a b => binaryClueView id "direct_right" a b
  | .sideBySide id a b => binaryClueView id "side_by_side" a b
  | .leftOf id a b => binaryClueView id "left_of" a b
  | .rightOf id a b => binaryClueView id "right_of" a b
  | .oneBetween id a b => binaryClueView id "one_between" a b
  | .twoBetween id a b => binaryClueView id "two_between" a b

private def compiledViewResponse (requestId : Json) (compiled : CompiledPuzzle) : Json :=
  let categories := compiled.categories.toArray.map fun category => Json.mkObj [
    ("name", jsonString category.name.value),
    ("values", Json.arr <| category.values.toArray.map fun value => jsonString value.value)
  ]
  Json.mkObj [
    ("protocol_version", jsonString protocolVersion),
    ("request_id", requestId),
    ("result", Json.mkObj [
      ("kind", jsonString "COMPILED"),
      ("compiled", Json.mkObj [
        ("problem_id", jsonString compiled.envelope.id),
        ("houses", toJson compiled.houses),
        ("categories", toJson compiled.categories.length),
        ("compiled_categories", Json.arr categories),
        ("compiled_clues", Json.arr <| compiled.clues.map clueView)
      ])
    ])
  ]

private def requestId (request : Json) : Json :=
  match request.getObjVal? "request_id" with
  | .ok value => value
  | .error _ => Json.null

private def allowedRequestField (field : String) : Bool :=
  field == "protocol_version" || field == "request_id" ||
    field == "command" || field == "payload"

private def allowedCommand (command : String) : Bool :=
  command == "info" || command == "compile" || command == "compile_view" ||
    command == "init_state" || command == "check_step" || command == "apply_step" ||
    command == "step" || command == "check_candidate" || command == "classify" ||
    command == "render_audit" || command == "emit_artifact"

private def validateRequestShape (request : Json) : Except String Unit := do
  let object ← request.getObj?.mapError fun _ => "request must be an object"
  for (field, _) in object.toList do
    if !allowedRequestField field then
      throw s!"unknown request field: {field}"
  match request.getObjVal? "payload" with
  | .ok (.obj _) => pure ()
  | .ok _ => throw "payload must be an object"
  | .error _ => pure ()

private def payloadProblemText (request : Json) : Except String String := do
  match request.getObjVal? "payload" with
  | .ok payload =>
      match payload.getObjVal? "problem" with
      | .ok (Json.str text) => pure text
      | .ok _ => throw "payload.problem must be a string"
      | .error _ => throw "payload.problem is required"
  | .error _ => throw "payload is required"

private def payloadCandidateText (request : Json) : Except String String := do
  match request.getObjVal? "payload" with
  | .ok payload =>
      match payload.getObjVal? "candidate" with
      | .ok (Json.str text) => pure text
      | .ok _ => throw "payload.candidate must be a string"
      | .error _ => throw "payload.candidate is required"
  | .error _ => throw "payload is required"

private def payloadText (request : Json) (field : String) : Except String String := do
  match request.getObjVal? "payload" with
  | .ok payload =>
      match payload.getObjVal? field with
      | .ok (Json.str text) => pure text
      | .ok _ => throw s!"payload.{field} must be a string"
      | .error _ => throw s!"payload.{field} is required"
  | .error _ => throw "payload is required"

private def compileProblem (request : Json) (includeView : Bool) : Json :=
  let id := requestId request
  match payloadProblemText request with
  | .error message => errorResponse id "invalid_request" message
  | .ok text =>
      match parseProblem text with
      | .error parseError =>
          let kind := match parseError.code with
            | .invalidJson => "invalid_json"
            | _ => "invalid_schema"
          errorResponseAt id kind parseError.path parseError.message
      | .ok parsed =>
          match Compiler.compile parsed with
          | .error staticError =>
              errorResponseAt id staticError.code.toString staticError.path staticError.message
          | .ok compiled =>
              if includeView then
                compiledViewResponse id compiled
              else
                compiledResponse id (Json.str compiled.envelope.id)

private def compileCommand (request : Json) : Json := compileProblem request false

private def compileViewCommand (request : Json) : Json := compileProblem request true

private def checkCandidateCommand (request : Json) : Json :=
  let id := requestId request
  match payloadProblemText request, payloadCandidateText request with
  | .error message, _ | _, .error message => errorResponse id "invalid_request" message
  | .ok problemText, .ok candidateText =>
      match parseProblem problemText with
      | .error parseError =>
          let kind := match parseError.code with
            | .invalidJson => "invalid_json"
            | _ => "invalid_schema"
          errorResponseAt id kind parseError.path parseError.message
      | .ok parsed =>
          match Compiler.compile parsed with
          | .error staticError =>
              errorResponseAt id staticError.code.toString staticError.path staticError.message
          | .ok compiled =>
              match Candidate.parse candidateText with
              | .error parseError => malformedCandidateResponse id parseError
              | .ok candidate =>
                  match CheckerCore.checkCandidate compiled candidate with
                  | .solved => solvedResponse id compiled.envelope.id
                  | .clueViolation index clueId => clueViolationResponse id index clueId
                  | .incomplete failure => incompleteResponse id compiled.envelope.id failure
                  | .invalid failure => invalidCandidateResponse id failure

private def initStateCommand (request : Json) : Json :=
  let id := requestId request
  match payloadProblemText request with
  | .error message => errorResponse id "invalid_request" message
  | .ok problemText =>
      match parseProblem problemText with
      | .error parseError =>
          let kind := match parseError.code with
            | .invalidJson => "invalid_json"
            | _ => "invalid_schema"
          errorResponseAt id kind parseError.path parseError.message
      | .ok parsed =>
          match Compiler.compile parsed with
          | .error staticError =>
              errorResponseAt id staticError.code.toString staticError.path staticError.message
          | .ok compiled => initializedStateResponse id (StepKernel.initState compiled)

private def stepCommand (request : Json) (apply : Bool) : Json :=
  let id := requestId request
  match payloadProblemText request, payloadText request "state", payloadText request "step" with
  | .error message, _, _ | _, .error message, _ | _, _, .error message =>
      errorResponse id "invalid_request" message
  | .ok problemText, .ok stateText, .ok stepText =>
      match parseProblem problemText with
      | .error parseError =>
          let kind := match parseError.code with
            | .invalidJson => "invalid_json"
            | _ => "invalid_schema"
          errorResponseAt id kind parseError.path parseError.message
      | .ok parsed =>
          match Compiler.compile parsed with
          | .error staticError =>
              errorResponseAt id staticError.code.toString staticError.path staticError.message
          | .ok compiled =>
              match StepKernel.parseState compiled stateText with
              | .error stepError => rejectedStepResponse id stepError
              | .ok state =>
                  match StepKernel.parseStep compiled stepText with
                  | .error stepError => rejectedStepResponse id stepError
                  | .ok step =>
                      match StepKernel.checkStep compiled state step with
                      | .rejected failure => rejectedStepResponse id failure
                      | .solved => solvedResponse id compiled.envelope.id
                      | .accepted next =>
                          acceptedStepResponse id (if apply then next else state)

private def dispatchCommand (request : Json) : Json :=
  let id := requestId request
  match request.getObjVal? "command" with
  | .ok (Json.str "info") => infoResponse id
  | .ok (Json.str "compile") => compileCommand request
  | .ok (Json.str "compile_view") => compileViewCommand request
  | .ok (Json.str "check_candidate") => checkCandidateCommand request
  | .ok (Json.str "init_state") => initStateCommand request
  | .ok (Json.str "check_step") => stepCommand request false
  | .ok (Json.str "apply_step") => stepCommand request true
  | .ok (Json.str command) =>
      if allowedCommand command then
        errorResponse id "not_implemented_stage_0"
          "This command is not implemented through Stage 3A"
      else
        errorResponse id "invalid_request" "unsupported command"
  | .ok _ => errorResponse id "invalid_request" "command must be a string"
  | .error _ => errorResponse id "invalid_request" "missing command"

private def dispatch (request : Json) : Json :=
  let id := requestId request
  match validateRequestShape request with
  | .error message => errorResponse id "invalid_request" message
  | .ok () =>
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
