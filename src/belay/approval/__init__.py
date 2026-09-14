"""Belay approval gate — hold risky tool calls pending human approval.

Package marker. Modules are imported directly (`belay.approval.gate`,
`belay.approval.channel`, `belay.approval.reader`); the composition helper
`compose` is added by the proxy-deny aspect.
"""