"""The contract `app.SpellChecker` is held to, with the distance core underneath.

Four of these pass against the current implementation. The last one fails, and it is
the one that separates a session-aware checker from a shared-state one: a transposed
pair ("the", for the query "teh") is edited into the dictionary, and the query is then
asked again — by the session that saw the pre-edit view, and by a fresh session. Both
must see the edited view, and the fresh session's view must not carry the other
session's history.
"""

from app import SpellChecker, distance


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
    # The query "teh" is a transposed pair of the dictionary word "the". Session one
    # first sees the dictionary without it; then the pair is EDITED in (add_word);
    # then the same session repeats the same query, and a fresh session asks it too.
    #
    #   - session one's repeated query must be a fresh ranking, not the cached
    #     pre-edit one — "the" must appear;
    #   - session one has already been shown "tea", so among the two words tied at
    #     distance 1 the unseen "the" must rank first (a shown word is demoted below
    #     an unseen one at equal distance);
    #   - session two has seen nothing, so it must get plain alphabetical order —
    #     the other session's history must not leak into its ranking.
    checker = SpellChecker(["tea"])

    first = checker.suggest("teh", "session-1")
    assert first == ["tea"]

    checker.add_word("the")  # the transposed pair is edited in

    other = checker.suggest("teh", "session-2")
    assert other == ["tea", "the"]

    again = checker.suggest("teh", "session-1")
    assert again == ["the", "tea"]