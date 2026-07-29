# Verbatim from corpus case `trace-pylint-dev__pylint-5859-turn11`, turn 11 `edit_file`
# `newText`. A TRUE APPEND: `test_dont_trigger_on_todoist` is reproduced character for
# character and a whole new `test_punctuation_notes` follows it, carrying one
# `assertAddsMessages` and three `MessageTest` expectations. Every one of those is an
# addition; nothing that existed changed.

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

    @set_config(notes=["YES", "???"])
    def test_punctuation_notes(self) -> None:
        code = """
        # YES: yes
        # ???: no
        # ???
        """
        with self.assertAddsMessages(
            MessageTest(msg_id="fixme", line=2, args="YES: yes", col_offset=9),
            MessageTest(msg_id="fixme", line=3, args="???: no", col_offset=9),
            MessageTest(msg_id="fixme", line=4, args="???", col_offset=9),
        ):
            self.checker.process_tokens(_tokenize_str(code))
