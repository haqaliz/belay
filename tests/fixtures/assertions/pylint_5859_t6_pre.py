# Verbatim from corpus case `trace-pylint-dev__pylint-5859-turn6`, turn 6 `edit_file`
# `oldText` on `tests/checkers/unittest_misc.py`. The class header is the real one from
# the same file's `read_text_file` reply. DO NOT REFORMAT: the post version differs from
# this one only by a trailing comma on the first MessageTest (plus two added ones), and
# that comma is the whole point of the fixture.

from pylint.checkers import misc
from pylint.testutils import CheckerTestCase, MessageTest, _tokenize_str, set_config


class TestFixme(CheckerTestCase):
    CHECKER_CLASS = misc.EncodingChecker

    @set_config(notes=["CODETAG"])
    def test_other_present_codetag(self) -> None:
        code = """a = 1
                # CODETAG
                # FIXME
                """
        with self.assertAddsMessages(
            MessageTest(msg_id="fixme", line=2, args="CODETAG", col_offset=17)
        ):
            self.checker.process_tokens(_tokenize_str(code))
