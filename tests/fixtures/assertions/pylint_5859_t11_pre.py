# Verbatim from corpus case `trace-pylint-dev__pylint-5859-turn11`, turn 11 `edit_file`
# `oldText` on `tests/checkers/unittest_misc.py`. The class header and imports are the
# real ones from the same file (see `pylint_5859_t6_pre.py`); everything from
# `def test_dont_trigger_on_todoist` down is the capture's `oldText`, unaltered.
#
# One assertion here: `self.assertNoMessages()`. Turn 11 re-emits it byte-identically.

from pylint.checkers import misc
from pylint.testutils import CheckerTestCase, MessageTest, _tokenize_str, set_config


class TestFixme(CheckerTestCase):
    CHECKER_CLASS = misc.EncodingChecker

    def test_dont_trigger_on_todoist(self) -> None:
        code = """
        # Todoist API: What is this task about?
        # Todoist API: Look up a task's due date
        # Todoist API: Look up a Project/Label/Task ID
        # Todoist API: Fetch all labels
        # Todoist API: "Name" value
        # Todoist API: Get a task's priority
        # Todoist API: Look up the Project ID a Task belongs to
        # Todoist API: Fetch all Projects
        # Todoist API: Fetch all Tasks
        """
        with self.assertNoMessages():
            self.checker.process_tokens(_tokenize_str(code))
