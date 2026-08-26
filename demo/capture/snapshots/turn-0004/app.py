"""A tiny "did-you-mean" spell checker with a per-session result cache.

`distance(a, b)` scores dictionary words against a query: the **unrestricted
Damerau-Levenshtein** distance — the minimum number of insertions, deletions,
substitutions and **transpositions of two adjacent characters** that turns `a` into
`b`, where a transposed pair may be edited again afterwards.

`SpellChecker.suggest(query, session)` ranks the dictionary's words against the
query, nearest first. The ranking rules are the whole contract:

1. **Ordering.** Nearest words first. Ties at the same distance are alphabetical —
   except that a word **already shown to that session** in an earlier suggest ranks
   after a word not yet shown to it (the checker prefers surfacing new options; a
   session never needs to re-read what it was just shown).
2. **The cache.** Ranking is comparatively expensive, so each session's last result
   is cached under `(session, query)`: a session repeating a query it has already
   asked — with the dictionary unchanged since — gets the cached ranking back.
3. **Invalidation.** `add_word(word)` grows the dictionary. A new word can change
   ANY ranking — it may outrank every existing word for some query — so an add
   invalidates every cached ranking, in every session: a repeated query after an
   add must be recomputed, never served stale.

The demo's failing test (`tests/test_spellcheck.py`) is the only oracle for whether
the implementation honours those rules.
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


class SpellChecker:
    """Rank dictionary words against a query, nearest first, per session."""

    def __init__(self, words=()):
        self._words = list(words)
        # session -> set of words already surfaced to THAT session
        self._shown: dict[str, set[str]] = {}
        # (session, query) -> ranking
        self._cache: dict = {}

    def add_word(self, word: str) -> None:
        self._words.append(word)
        # A new word can outrank anything, in any session: drop every cached ranking.
        self._cache.clear()

    def suggest(self, query: str, session: str) -> list[str]:
        """Rank `self._words` by distance to `query`, nearest first."""
        key = (session, query)
        if key in self._cache:
            return self._cache[key]
        ranking = self._rank(query, session)
        self._cache[key] = ranking
        return ranking

    def _rank(self, query: str, session: str) -> list[str]:
        seen = self._shown.setdefault(session, set())
        scored = [(distance(query, word), word in seen, word) for word in self._words]
        scored.sort()
        ranking = [word for _, _, word in scored]
        seen.update(ranking)
        return ranking
