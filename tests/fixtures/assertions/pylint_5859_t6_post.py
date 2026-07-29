# Verbatim from corpus case `trace-pylint-dev__pylint-5859-turn6`, turn 6 `edit_file`
# `newText`. The first MessageTest gained a TRAILING COMMA and nothing else; a line diff
# calls that a removal, an AST comparison calls it identical. The other two MessageTests
# are genuine additions.

from pylint.checkers import misc
from pylint.testutils import CheckerTestCase, MessageTest, _tokenize_str, set_config


class TestFixme(CheckerTestCase):
    CHECKER_CLASS = misc.EncodingChecker

    @set_config(notes=["CODETAG", "???"])
    def test_other_present_codetag(self) -> None:
        code = """a = 1
                # CODETAG
                # FIXME
                # ???
                # ???: something
                # ???no
                """
        with self.assertAddsMessages(
            MessageTest(msg_id="fixme", line=2, args="CODETAG", col_offset=17),
            MessageTest(msg_id="fixme", line=4, args="???", col_offset=17),
            MessageTest(msg_id="fixme", line=5, args="???: something", col_offset=17),
        ):
            self.checker.process_tokens(_tokenize_str(code))
