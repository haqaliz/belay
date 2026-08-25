"""Edit distance for the fuzzy-search index.

`distance(a, b)` is documented — and depended on — as the **unrestricted
Damerau-Levenshtein** distance: the minimum number of insertions, deletions,
substitutions and **transpositions of two adjacent characters** that turns `a` into `b`,
where a transposed pair may be edited again afterwards.

That last clause is the whole contract. The cheaper, better-known variant — *optimal string
alignment* — forbids a substring from being edited more than once, so it cannot see that
`"ca"` reaches `"abc"` in two edits (transpose to `"ac"`, insert `"b"`) and reports three.

The implementation below is that cheaper variant, which is why
`tests/test_distance.py::test_transposed_pairs_may_be_edited_again` fails: the recurrence
only ever looks one row and one column back, so it has no way to charge for the characters
between a transposed pair.
"""


def distance(a: str, b: str) -> int:
    """Return the edit distance between `a` and `b`."""
    n, m = len(a), len(b)
    grid = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        grid[i][0] = i
    for j in range(m + 1):
        grid[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            grid[i][j] = min(
                grid[i - 1][j] + 1,      # delete
                grid[i][j - 1] + 1,      # insert
                grid[i - 1][j - 1] + cost,  # substitute
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                grid[i][j] = min(grid[i][j], grid[i - 2][j - 2] + cost)  # transpose
    return grid[n][m]
