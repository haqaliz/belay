"""The verification layer: verdicts and the reduction they combine through.

C4 is the first grounded verdict in Belay. This package owns the `Verdict` type and the
worst-status-wins `reduce`, which A1 (C5) and A3 (C8) reuse unchanged. Pure data and logic
— no model, no network, no re-execution lives here.
"""
