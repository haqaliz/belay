"""Invariant authoring: a model writes A1 policy, execution calibrates it.

The Phase-2 authoring experiment (R3's third mitigation). This package owns the
out-of-process BYOK author protocol and the `belay invariant infer` orchestration;
the artifact's schema, loader and trust rules live in `belay.verify.invariants`,
because the provenance guard over policy producers must see them.

Nothing in this package is in the verdict path. The author proposes policy; the
control replay calibrates it; the shipped A1 machinery decides. Stdlib only.
"""
