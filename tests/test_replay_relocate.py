"""Phase 1: the pure path-relocation primitives (`belay.replay.relocate`).

These functions carry the delicate rules of absolute-path replay relocation with **no
I/O** — no subprocess, no network, no filesystem stat — so the rules can be pinned in
isolation before they are wired into the replay flow (a later phase). Everything here is
offline, deterministic and cross-platform.

The one asymmetry these tests exist to defend (the whole point of the aspect):

- **`arguments` are MUTATED, so they are remapped CONSERVATIVELY** — a string is remapped
  **only if its entire value is an absolute path under the recorded root**. A `path` field
  is swapped; a `newText`/`content` field that merely *mentions* the root as a substring is
  **never** touched. Content is preserved by construction.
- **Replies are only COMPARED, so they are normalized LIBERALLY** — both roots are replaced
  as substrings anywhere they appear (diff headers, URLs, nested JSON). This is transient
  and cannot corrupt anything, so a path buried in a diff line still compares equal.

`is_under` is normalized with `os.path.normpath` (a *lexical* operation) rather than
`os.path.realpath`, deliberately: these functions are pure and must work on paths that do
not exist on disk, so they must never stat the filesystem.
"""

from __future__ import annotations

import copy

from belay.replay.relocate import (
    canonicalize_obj,
    canonicalize_reply,
    command_embeds_in_root_path,
    is_under,
    relocate_command_line,
    remap_argv,
    remap_arguments,
    remap_prefix,
    turn_needs_relocation,
)


def test_is_under_is_boundary_safe() -> None:
    """`is_under` is a path-component prefix test, not a string prefix test.

    THE boundary case: `/a/bc` is NOT under `/a/b` even though the string `/a/b` is a
    prefix of `/a/bc`. A component-blind `startswith` would leak `/a/bc` into `/a/b`'s
    relocation. The root is under itself (an argv token that *is* the root is remapped),
    and normalization collapses `..` lexically without touching the disk.
    """
    assert is_under("/a/b/c", "/a/b") is True
    assert is_under("/a/b", "/a/b") is True  # the root is under itself
    assert is_under("/a/bc", "/a/b") is False  # the boundary: sibling, not child
    assert is_under("/a/b/c/../d", "/a/b") is True  # normpath -> /a/b/d
    assert is_under("/x/y", "/a/b") is False
    assert is_under("relative/path", "/a/b") is False  # not absolute -> not under


def test_remap_argv_only_in_root_tokens() -> None:
    """Only argv tokens that are / are under `from_root` move; everything else is verbatim.

    The server root token and any in-root path token are swapped to the scratch prefix; a
    flag, a bare command name, and an out-of-root absolute path (`/etc/hosts`) are left
    exactly as they were. `changed` reports whether anything moved.
    """
    argv = ["node", "/root/server.js", "/etc/hosts", "--flag", "/root"]
    new_argv, changed = remap_argv(argv, "/root", "/scratch")
    assert new_argv == ["node", "/scratch/server.js", "/etc/hosts", "--flag", "/scratch"]
    assert changed is True

    # No in-root tokens -> unchanged, and `changed` is False.
    inert = ["node", "server.js", "/etc/hosts", "--flag"]
    same, changed2 = remap_argv(inert, "/root", "/scratch")
    assert same == inert
    assert changed2 is False


def test_remap_arguments_whole_value_path_only() -> None:
    """A string value is remapped iff its WHOLE value is an in-root absolute path.

    The `path` field (a whole-value in-root absolute path) is swapped; a `mode` string, an
    integer, and an out-of-root path are untouched. Recursion reaches into nested lists and
    dicts. `changed` is True because at least one value moved.
    """
    obj = {
        "path": "/root/file.txt",
        "mode": "r",
        "count": 3,
        "extras": [{"path": "/root/sub/x.py"}, {"path": "/etc/passwd"}],
    }
    new_obj, changed = remap_arguments(obj, "/root", "/scratch")
    assert new_obj == {
        "path": "/scratch/file.txt",
        "mode": "r",
        "count": 3,
        "extras": [{"path": "/scratch/sub/x.py"}, {"path": "/etc/passwd"}],
    }
    assert changed is True

    # A structure with no in-root whole-value path is returned equal, changed=False.
    inert = {"path": "src/rel.py", "note": "mentions nothing absolute"}
    same, changed2 = remap_arguments(inert, "/root", "/scratch")
    assert same == inert
    assert changed2 is False


def test_remap_arguments_leaves_content_fields_untouched() -> None:
    """THE content-safety guard: an `edit_file`-shaped call remaps `path`, never `newText`.

    `newText` is file content that legitimately *mentions* the workspace root as a substring
    — its whole value is a sentence, not an absolute path, so the whole-value rule leaves it
    byte-for-byte intact even though `/root` appears inside it. Only `path` (a whole-value
    in-root absolute path) is swapped. A substring remap here would corrupt the file content
    written to the scratch and manufacture a false delta; this test forbids it.
    """
    obj = {
        "path": "/root/a.py",
        "edits": [{"newText": "some text mentioning /root inside content"}],
    }
    new_obj, changed = remap_arguments(obj, "/root", "/scratch")

    assert new_obj["path"] == "/scratch/a.py", "the whole-value path field is remapped"
    assert new_obj["edits"][0]["newText"] == "some text mentioning /root inside content", (
        "content that merely contains the root as a substring must NOT be rewritten"
    )
    assert changed is True  # the path moved; the content did not


def test_canonicalize_reply_is_symmetric_on_a_diff() -> None:
    """A unified diff carrying the abs path compares equal after canonicalization.

    The recorded reply embeds the ORIGINAL root in its `Index:`/`---`/`+++` lines; the
    replayed reply embeds the SCRATCH root in the same positions. Substituting BOTH roots
    (as substrings, anywhere) with one placeholder folds the two into an identical form, so a
    path buried in a diff header does not produce a spurious inequality. The substitution is
    order-independent: swapping which root is passed first yields the same string.
    """
    root_a = "/root/proj"
    root_b = "/scratch-xyz/proj"
    placeholder = "<WS>"

    recorded = (
        f"Index: {root_a}/main.py\n"
        f"--- {root_a}/main.py\n"
        f"+++ {root_a}/main.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    replayed = recorded.replace(root_a, root_b)

    canon_recorded = canonicalize_reply(recorded, root_a, root_b, placeholder)
    canon_replayed = canonicalize_reply(replayed, root_a, root_b, placeholder)
    assert canon_recorded == canon_replayed, "diff replies must fold to the same form"
    assert placeholder in canon_recorded and root_a not in canon_recorded

    # Order-independent: the roots may be passed in either order.
    assert canonicalize_reply(recorded, root_a, root_b, placeholder) == canonicalize_reply(
        recorded, root_b, root_a, placeholder
    )


def test_canonicalize_obj_folds_string_values_structurally() -> None:
    """`canonicalize_obj` folds both roots in every STRING value, keeping the structure.

    The parsed-structure companion to `canonicalize_reply`: it walks a decoded JSON message
    and substring-replaces both roots inside each string leaf, leaving dict/list shape (and
    every non-string scalar) intact. A path buried in a nested reply string — a diff header,
    a `file://` URL — folds to the placeholder on both the recorded (original root) and
    replayed (scratch root) side, so a structural `==` compares them equal WITHOUT dumping
    to text (which would reintroduce key-order sensitivity). Dict KEYS are left untouched.
    """
    placeholder = "<WS>"
    recorded = {
        "result": {
            "content": [{"type": "text", "text": "wrote /root/proj/a.py"}],
            "isError": False,
            "count": 3,
        }
    }
    replayed = {
        "result": {
            "content": [{"type": "text", "text": "wrote /scratch-xyz/proj/a.py"}],
            "isError": False,
            "count": 3,
        }
    }
    canon_recorded = canonicalize_obj(recorded, "/root/proj", "/scratch-xyz/proj", placeholder)
    canon_replayed = canonicalize_obj(replayed, "/root/proj", "/scratch-xyz/proj", placeholder)
    assert canon_recorded == canon_replayed, "the two replies must fold to the same structure"
    # Structure preserved: still a dict of a dict of a list; the non-string scalars survive.
    assert canon_recorded["result"]["isError"] is False
    assert canon_recorded["result"]["count"] == 3
    assert placeholder in canon_recorded["result"]["content"][0]["text"]

    # Order-independent and non-mutating: the input object is untouched.
    before = copy.deepcopy(recorded)
    canonicalize_obj(recorded, "/scratch-xyz/proj", "/root/proj", placeholder)
    assert recorded == before


def test_turn_needs_relocation_false_for_cwd_relative() -> None:
    """Gating: a purely cwd-relative turn does NOT need relocation.

    No `arguments` string is a whole-value in-root absolute path and no argv token is in-root,
    so `turn_needs_relocation` is False and the caller keeps today's byte-for-byte path. A
    positive control (an in-root `path`, and separately an in-root argv token) returns True,
    so the gate is not stuck-off.
    """
    args_rel = {"path": "src/x.py", "mode": "r"}
    argv_rel = ["node", "server.js", "."]
    assert turn_needs_relocation(args_rel, argv_rel, "/root") is False

    # Positive controls: either source of an in-root abs path trips the gate.
    assert turn_needs_relocation({"path": "/root/x.py"}, argv_rel, "/root") is True
    assert turn_needs_relocation(args_rel, ["node", "/root/server.js"], "/root") is True


def test_remap_functions_are_pure() -> None:
    """None of the primitives mutate their inputs — a deep-copy is unchanged after each call.

    Purity is load-bearing: the frame's decoded JSON is re-serialized after relocation, and a
    silent in-place edit of the recorded `arguments` would corrupt the trace it must leave
    untouched. Every function is called and the original object is asserted equal to a
    pre-call deep copy.
    """
    argv = ["node", "/root/server.js", "--flag"]
    argv_before = copy.deepcopy(argv)
    remap_argv(argv, "/root", "/scratch")
    assert argv == argv_before

    args = {"path": "/root/a.py", "edits": [{"newText": "/root literal"}]}
    args_before = copy.deepcopy(args)
    remap_arguments(args, "/root", "/scratch")
    assert args == args_before

    text = "diff at /root/a.py and /scratch/a.py"
    text_before = text
    canonicalize_reply(text, "/root", "/scratch", "<WS>")
    assert text == text_before

    turn_needs_relocation(args, argv, "/root")
    assert args == args_before and argv == argv_before


def test_command_embeds_in_root_path_is_field_shaped() -> None:
    """THE embedded-path detector: an in-root path embedded in an EXECUTED-command field only.

    The whole-value rule (`turn_needs_relocation`/`remap_arguments`) is blind to a path buried
    *inside* a string — but the danger is only about paths the server will **execute/resolve**:
    the shell server's `command_line` (a string) and `argv` (a list). Inert content fields and
    whole-value path arguments are NOT the concern — a whole-value path anywhere (including an
    `argv` element) is already relocated by `remap_arguments`/`turn_needs_relocation`. So the
    detector keys ONLY on `command_line`/`argv`.

    - `command_line` embedding an in-root path -> True.
    - `command_line` with no in-root path -> False.
    - `command_line` with an out-of-root path -> False.
    - `argv` with an in-root path embedded in a token (not whole-value) -> True.
    - `argv` with a whole-value in-root element -> False (the whole-value rule relocates it;
      this predicate must not steal it into abstain).
    - a `path` + `new_content` content field mentioning the root, with NO command field ->
      False (the regression fix: a content mention must not fire).
    - a bare non-command field -> False.
    """
    root = "/root/w"

    assert command_embeds_in_root_path({"command_line": "python /root/w/x.py"}, root) is True
    assert command_embeds_in_root_path({"command_line": "pytest -q"}, root) is False
    assert command_embeds_in_root_path({"command_line": "python /other/x.py"}, root) is False
    assert command_embeds_in_root_path({"argv": ["python", "--file=/root/w/x"]}, root) is True
    assert command_embeds_in_root_path({"argv": ["python", "/root/w/x.py"]}, root) is False
    assert (
        command_embeds_in_root_path(
            {"path": "/root/w/x", "new_content": "the path is /root/w/x"}, root
        )
        is False
    )
    assert command_embeds_in_root_path({"cmd": "echo hi"}, root) is False


# --------------------------------------------------------------------------- #
# Phase 0 spike: `relocate_command_line` — the conservative, abstain-on-doubt  #
# whole-token relocation of a shell `command_line` STRING. The A2 moat: any    #
# doubt → ABSTAIN, never a false (content-corrupting) rewrite. These tests pin #
# the tricky-string boundary the spike must survive.                           #
# --------------------------------------------------------------------------- #


def test_relocate_command_line_quoted_whole_token_relocates() -> None:
    """A quoted whole-token in-root path is relocated; the quotes are preserved.

    The lexer token is `/root/w/x` (quotes stripped by shlex); the boundary-anchored
    span in the ORIGINAL string sits between the two `"` bytes, so only the path bytes
    move and the surrounding quoting is byte-identical.
    """
    new_cmd, outcome = relocate_command_line('cat "/root/w/x"', "/root/w", "/scratch")
    assert outcome == "RELOCATED"
    assert new_cmd == 'cat "/scratch/x"'


def test_relocate_command_line_prefix_collision_both_move_correctly() -> None:
    """`/root/w/x` and `/root/w/xy` both present → each moves to its OWN scratch path.

    The prefix-collision trap: a naive string replace of `/root/w/x` would corrupt the
    inside of `/root/w/xy`. Boundary-anchoring plus longest-token-first keeps them
    distinct — `xy` stays `xy`, `x` stays `x`.
    """
    new_cmd, outcome = relocate_command_line(
        "cat /root/w/x /root/w/xy", "/root/w", "/scratch"
    )
    assert outcome == "RELOCATED"
    assert new_cmd == "cat /scratch/x /scratch/xy"


def test_relocate_command_line_clean_multi_path_relocates_only_paths() -> None:
    """A clean two-path command relocates both paths and changes no other byte."""
    new_cmd, outcome = relocate_command_line(
        "cp /root/w/a.py /root/w/b.py", "/root/w", "/scratch"
    )
    assert outcome == "RELOCATED"
    assert new_cmd == "cp /scratch/a.py /scratch/b.py"


def test_relocate_command_line_byte_precision_preserves_spacing_and_flags() -> None:
    """Relocating one path token leaves quoting, runs of spaces, flags, redirects intact.

    THE byte-precision guarantee (acceptance criterion 6): only the path's exact byte
    span is rewritten; the doubled spaces, the `-n` flag, and the `> out.txt` redirect
    are byte-for-byte identical.
    """
    new_cmd, outcome = relocate_command_line(
        "grep -n foo   /root/w/x   > out.txt", "/root/w", "/scratch"
    )
    assert outcome == "RELOCATED"
    assert new_cmd == "grep -n foo   /scratch/x   > out.txt"


def test_relocate_command_line_flag_fused_path_abstains() -> None:
    """A path fused into a flag token (`--file=/root/w/x`) → ABSTAIN, never a partial rewrite.

    The in-root path is a token SUBSTRING (embedded residue), not a whole value. Rewriting
    only its bytes would leave a half-relocated token; the safe direction is to abstain and
    let the gate emit UNVERIFIED. The command is returned unchanged.
    """
    new_cmd, outcome = relocate_command_line(
        "python --file=/root/w/x", "/root/w", "/scratch"
    )
    assert outcome == "ABSTAIN"
    assert new_cmd == "python --file=/root/w/x"


def test_relocate_command_line_escaped_space_abstains() -> None:
    """An escaped-space path whose lexer token != its raw byte span → ABSTAIN.

    The lexer folds `a\\ b` into the token `a b` (a literal space, no backslash), so a
    regex built from the token cannot match the backslashed raw bytes: match count (0) ≠
    lexer occurrence count (1) → ABSTAIN. Any quoting/escaping the algorithm cannot
    faithfully round-trip to a byte span falls to the safe side.
    """
    new_cmd, outcome = relocate_command_line(
        "cat /root/w/a\\ b", "/root/w", "/scratch"
    )
    assert outcome == "ABSTAIN"
    assert new_cmd == "cat /root/w/a\\ b"


def test_relocate_command_line_unlexable_abstains() -> None:
    """An un-lexable command (unbalanced quote) → ABSTAIN, returned unchanged."""
    new_cmd, outcome = relocate_command_line('cat "unbalanced', "/root/w", "/scratch")
    assert outcome == "ABSTAIN"
    assert new_cmd == 'cat "unbalanced'


def test_relocate_command_line_out_of_root_path_untouched_relocates() -> None:
    """An out-of-root absolute path is left verbatim; the command is still a clean RELOCATE.

    `/etc/hosts` is neither under the root nor embedded residue (it does not contain the
    root string), so it is inert. With one relocatable in-root path present, the outcome is
    RELOCATED and only the in-root path moves.
    """
    new_cmd, outcome = relocate_command_line(
        "diff /etc/hosts /root/w/x", "/root/w", "/scratch"
    )
    assert outcome == "RELOCATED"
    assert new_cmd == "diff /etc/hosts /scratch/x"


def test_relocate_command_line_is_pure() -> None:
    """The primitive never mutates its inputs (they are plain strings — sanity anchor)."""
    cmd = "cp /root/w/a /root/w/b"
    new_cmd, outcome = relocate_command_line(cmd, "/root/w", "/scratch")
    assert cmd == "cp /root/w/a /root/w/b"
    assert new_cmd == "cp /scratch/a /scratch/b"
    assert outcome == "RELOCATED"


def test_remap_prefix_swaps_the_root() -> None:
    """`remap_prefix` swaps the `from_root` prefix to `to_root` (caller guarantees is_under).

    The exact-root case returns `to_root`; a deeper path keeps its in-root suffix under the
    new prefix. Normalization is lexical, so a `..` in the input collapses without a stat.
    """
    assert remap_prefix("/root", "/root", "/scratch") == "/scratch"
    assert remap_prefix("/root/a/b.py", "/root", "/scratch") == "/scratch/a/b.py"
    assert remap_prefix("/root/a/../c.py", "/root", "/scratch") == "/scratch/c.py"
