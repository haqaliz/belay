"""The contract `app.distance` is held to: unrestricted Damerau-Levenshtein.

Four of these pass against the current implementation. The last one fails, and it is the
one that separates the real distance from optimal string alignment: a transposed pair that
is edited again afterwards.
"""

from app import distance


def test_identical_and_empty_strings():
    assert distance("", "") == 0
    assert distance("abc", "abc") == 0
    assert distance("abc", "") == 3
    assert distance("", "abc") == 3


def test_insertions_substitutions_and_deletions():
    assert distance("kitten", "sitting") == 3
    assert distance("an act", "a cat") == 2
    assert distance("abcdef", "abcfad") == 3


def test_one_adjacent_transposition_costs_one():
    assert distance("ab", "ba") == 1
    assert distance("teh", "the") == 1
    assert distance("hackathon", "hackthon") == 1


def test_the_distance_is_symmetric():
    assert distance("kitten", "sitting") == distance("sitting", "kitten")
    assert distance("abc", "cab") == distance("cab", "abc")


def test_transposed_pairs_may_be_edited_again():
    # "ca" -> "ac" (transpose) -> "abc" (insert "b"): two edits, not three. Optimal
    # string alignment forbids touching the transposed substring again and says three.
    assert distance("ca", "abc") == 2
    assert distance("CA", "ABC") == 2
    # "abcd" -> "bacd" -> "badc" -> "bdac": three edits under the real distance.
    assert distance("abcd", "bdac") == 3
