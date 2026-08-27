"""Put this repo's root on `sys.path` so `tests/test_auth.py` can `import app`.

Explicit rather than relying on pytest's rootdir insertion, because the suite is also
run by `demo/server.py`'s `run_tests` tool, which is not pytest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
