"""Phase-0: run the failure corpus at scale and publish the violation-rate number.

`belay.phase0.ledger` is the data model (`Disposition`, `InstanceRecord`, `RunLedger`).
`belay.phase0.report` renders it into the published violation-rate number, with its honesty
guards. `belay.phase0.runner` is the driver that fills a `RunLedger` by verifying traces —
`run_batch`. No CLI lives here yet.
"""

from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger
from belay.phase0.runner import run_batch

__all__ = ["Disposition", "InstanceRecord", "RunLedger", "run_batch"]
