# chore: pre-push refuses to vouch for a tree it is not pushing

**Owner:** spydra-ops · **Files:** `.githooks/pre-push`,
`scripts/audit-phase0.sh`, `docs/WORKFLOW.md`, `docs/DEVELOPMENT.md`

## Why

#13 (1.9) and #14 (1.10) reached CI with a stale
`bff/src/db/schema/crawl.generated.ts`. Migration `2071b5ff83e1` added
`consecutive_403s`, but the regenerated mirror was committed in 1.11's
`e7535c3`, so the 1.9 commit never had it. Pre-push ran `make check` against
the working tree, not against the commit being pushed. That leaves two gaps:

- pushing a ref other than `HEAD` (a stacked branch pushed from another
  checkout) runs the gate on the wrong commit;
- uncommitted or untracked files (a regenerated mirror, a new migration) make
  the gate pass on a tree the commit does not contain.

Fixed in the branches on `24bcf03` / `414599f`. This slice closes the gate.

## Contract

Pre-push exits non-zero, before `make check`, when:

1. any pushed ref's sha is neither `HEAD` nor a deletion, or
2. `git status --porcelain --untracked-files=normal` is non-empty.

The protected-branch refusal (`develop`, `main`) is unchanged and still runs
first.

## Acceptance

- [x] Scratch-repo matrix: clean `HEAD` push passes; non-`HEAD` push, modified
      file, untracked file, dirty manual run all refused; branch deletion
      passes; `HEAD:develop` still refused. 4 of these 7 cases passed
      wrongly under the old hook.
- [x] `scripts/audit-phase0.sh gate` gains 3c (non-`HEAD`) and 3d
      (untracked). Both OK with the new hook; both FAIL and 0.3 reads BROKEN
      with the old one (2 chosen mutations, both red).
- [ ] `make check`. Not run: no Docker daemon in the authoring container.
      The diff touches no code `make check` covers.

## Handoff log

- ops (cloud session): diagnosis, hook, audit gates, docs.

## Open questions — for the human

- Untracked files count as dirty, so a throwaway mutation runner left in
  `.tasks/` blocks a push until it is deleted or stashed. That is the intended
  behaviour (the runner is meant to be deleted before committing anyway), but
  it is stricter than before.
- `--no-verify` still bypasses all of this; CI is the only backstop, and it
  caught this case.
