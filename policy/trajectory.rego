# Real Rego, evaluated by a real `opa eval` subprocess (gateway/policy.py), not a Python
# mirror of this logic. The input this policy ever sees is built in gateway/policy.py from
# registry metadata alone: input.current is the tool about to be called (its name and its
# registry annotations), input.history is the ordered list of tools already called in this
# session (same shape). Neither ever carries a call's actual argument values, a prompt, or
# any document content, which is the "never prompt or document content" half of the claim;
# the other half, "tool identity, argument authority ... and prior call trajectory", is
# exactly input.current.tool, input.current.annotations (argument authority is encoded
# upstream, in which annotation a tool carries, not re-derived here), and input.history.
package gateway.trajectory

import rego.v1

default allow := false

# A call is denied if it is tagged external_send and any earlier call in this session's
# trajectory was tagged private_read, regardless of how many ordinary calls sit between
# them. This is deliberately a trajectory-wide check, not a check against only the
# immediately preceding call, because an agent trying to exfiltrate data would have every
# reason to interleave an innocuous call in between.
deny contains reason if {
	"external_send" in input.current.annotations
	some entry in input.history
	"private_read" in entry.annotations
	reason := sprintf("external_send (%s) follows a private_read call (%s) in this session's trajectory", [input.current.tool, entry.tool])
}

allow if {
	count(deny) == 0
}
