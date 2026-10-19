"""Guards on the Makefile itself.

Every defect this file checks for has already happened, and each one cost a
round trip because it made a target **report success while doing nothing**.
That is the expensive failure mode in a repository whose contract between one
agent and the next is `make check` (ADR-0022 §3): a gate that cannot fail is
worse than no gate, because it is believed.

A pytest rather than a lint or a shell script, for the same reason task 0.8
chose one for the domain import contract: it blocks CI where a lint only
warns, and it needs nothing but the standard library.
"""

import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# `.:/repo` in compose, so the repository root is there inside the api
# container; the backend's parent is the root for a checkout run directly.
_ROOT_CANDIDATES = (BACKEND_ROOT.parent, Path("/repo"))

# Guarded paths that do not exist yet because their task has not landed.
# This list only shrinks. A guard whose path is neither on disk nor named
# here is a typo, and a typo in a guard means that target skips silently for
# ever while `make check` stays green.
PENDING_PATHS = {
    "backend/spydra/seed_dev.py": "BUILD_PLAN 5.1 — offline fixture domains",
    "frontend/playwright.config.ts": "BUILD_PLAN phase 3 — the e2e journey",
}


def _repo_root() -> Path:
    for candidate in _ROOT_CANDIDATES:
        if (candidate / "Makefile").is_file():
            return candidate
    pytest.fail(
        "Makefile not found. This is a failure and not a skip — the whole point is "
        f"that it is checked. Looked in {[str(c) for c in _ROOT_CANDIDATES]}; inside "
        "the api container the repository root arrives via compose's `.:/repo` mount."
    )


@pytest.fixture(scope="module")
def makefile() -> str:
    return (_repo_root() / "Makefile").read_text()


def _recipe_lines(makefile: str) -> list[tuple[int, str]]:
    """Tab-indented **logical** lines — continuations joined.

    Physical lines are the wrong unit and quietly defeat these checks. A
    shell function definition wraps, so `psql` lands on one line and the
    connection URL on the next; a rule matching both on one physical line
    passed this Makefile while the flag it looks for was absent. Found by
    mutating the Makefile and re-running these tests, which is the only way
    to know a guard is a guard rather than decoration.

    The line number returned is where the logical line starts.
    """
    joined: list[tuple[int, str]] = []
    buffer: list[str] = []
    start = 0
    for n, line in enumerate(makefile.splitlines(), start=1):
        if not line.startswith("\t") and not buffer:
            continue
        if not buffer:
            start = n
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buffer.append(stripped[:-1])
            continue
        buffer.append(stripped)
        joined.append((start, " ".join(part.strip() for part in buffer)))
        buffer = []
    if buffer:
        joined.append((start, " ".join(part.strip() for part in buffer)))
    return joined


def test_every_guarded_path_exists_or_is_declared_pending(makefile: str) -> None:
    """A guard pointing at a path that will never exist disables its target.

    `skip_if_missing` prints a message and exits 0, so the target succeeds
    having done nothing. Mistype the path and `make test-api` is green for
    ever — which is the shape of the defect that cost three rounds getting
    `make test-api` to run at all.
    """
    root = _repo_root()
    guarded = set(re.findall(r"skip_if_missing,([^)]+)\)", makefile))
    assert guarded, "found no skip_if_missing guards — has the macro been renamed?"

    unexplained = sorted(
        path for path in guarded if not (root / path).exists() and path not in PENDING_PATHS
    )
    assert not unexplained, (
        "Makefile guards point at paths that do not exist and are not declared "
        f"pending: {unexplained}. Each one silently disables its target. Either "
        "fix the path, or add it to PENDING_PATHS with the task that creates it."
    )


def test_pending_paths_are_pruned_once_they_land(makefile: str) -> None:
    """The allowlist above only shrinks.

    A path left on it after its task lands is a guard that now never fires,
    which the Makefile's own header calls a defect.
    """
    root = _repo_root()
    landed = sorted(p for p in PENDING_PATHS if (root / p).exists())
    assert not landed, (
        f"PENDING_PATHS still lists {landed}, which now exist. Remove the guard "
        "from the Makefile and the entry from this list — the Makefile header: "
        '"a guard firing after its task is ticked is a defect".'
    )


def test_no_guard_sits_alone_on_its_recipe_line(makefile: str) -> None:
    """A guard must be joined to its command, or it guards nothing.

    `skip_if_missing` ends in `exit 0`, which exits **that line's** shell.
    Make then runs the next recipe line regardless. The Makefile header says
    the guard is joined with `&&` for exactly this reason; on its own line it
    is decoration. (Introduced and caught while rewriting `verify-grants`.)
    """
    offenders = [
        f"line {n}: {line.strip()}"
        for n, line in enumerate(makefile.splitlines(), start=1)
        if line.startswith("\t")
        and "skip_if_missing" in line
        and not line.rstrip().endswith(("&&", "\\"))
        and "&&" not in line.split("skip_if_missing", 1)[1]
    ]
    assert not offenders, (
        "a skip_if_missing guard is not joined to the command it guards, so the "
        "target runs anyway when the guard trips:\n  " + "\n  ".join(offenders)
    )


def _commands(makefile: str) -> list[tuple[int, str]]:
    """Individual shell commands: logical lines split on `;`.

    The unit matters. A whole recipe is one logical line here, so a rule
    applied to the line cannot tell F14's swallowed `docker volume rm` from a
    legitimate best-effort cleanup several commands away in the same recipe.
    """
    return [
        (n, segment.strip())
        for n, line in _recipe_lines(makefile)
        for segment in line.split(";")
        if segment.strip()
    ]


def test_docker_results_are_never_swallowed(makefile: str) -> None:
    """`|| true` on a docker command hides whether it did anything.

    This is finding F14 exactly: `make reset-deps` was
    `compose stop && docker volume rm ... || true`. A stopped container still
    references its volumes, so the removal failed every time, `|| true` ate
    the failure, and the target exited 0 having done nothing — for long
    enough that a stale venv survived a lockfile change, an image rebuild and
    three runs of the target whose only job is to drop it.

    Best-effort cleanup is still allowed; it just may not be spelled by
    swallowing a docker invocation's result on the same line.
    """
    offenders = [
        f"line {n}: {command}"
        for n, command in _commands(makefile)
        if ("|| true" in command or "||:" in command or "|| :" in command)
        and ("docker " in command or "$(COMPOSE)" in command)
    ]
    assert not offenders, (
        "a docker command's result is swallowed, so the target cannot tell you it "
        "failed (finding F14):\n  " + "\n  ".join(offenders)
    )


def test_volume_removal_removes_the_containers_first(makefile: str) -> None:
    """`docker volume rm` after `compose stop` can never work.

    The other half of F14, and the half that actually did the damage. A
    STOPPED container still holds a reference to its volumes, so the removal
    fails with "volume is in use" every time. `compose down` removes the
    containers and keeps the named volumes, which is exactly what a target
    that drops three volumes by name needs.
    """
    offenders = [
        f"line {n}: {line}"
        for n, line in _recipe_lines(makefile)
        if "docker volume rm" in line and "stop" in line
    ]
    assert not offenders, (
        "a target removes volumes after only STOPPING the containers, which cannot "
        "succeed — use `compose down` (finding F14):\n  " + "\n  ".join(offenders)
    )


def test_every_psql_assertion_stops_on_error(makefile: str) -> None:
    """psql exits 0 on a failed statement unless told otherwise.

    Finding F15: `make verify-grants` — the proof that the BFF role cannot
    write `crawl`, which spec 010 §6 and BUILD_PLAN 0.7 both rest on — ran
    every statement without `ON_ERROR_STOP`. Its CREATE silently failed, its
    assertions could not fail, and it printed "✓ grants hold" having proved
    nothing.

    `make psql` is exempt: it is an interactive shell for a human, not an
    assertion.
    """
    # Keyed on the connection URL, not on `-c`. The statements are run
    # through shell functions, so `-c` and `psql` land on different lines —
    # a rule that wanted both on one line passed this file while the flag
    # was missing (found by mutating the Makefile and re-running this test).
    # `make psql` connects with `-U spydra` and no URL, so it is exempt
    # without needing to be named: it is an interactive shell, not an
    # assertion.
    offenders = [
        f"line {n}: {command}"
        for n, command in _commands(makefile)
        if "psql" in command and "postgres://" in command and "ON_ERROR_STOP" not in command
    ]
    assert not offenders, (
        "psql runs a statement without -v ON_ERROR_STOP=1, so a SQL error exits 0 "
        "and the assertion around it cannot fail (finding F15):\n  " + "\n  ".join(offenders)
    )


def test_verify_grants_never_touches_a_real_table(makefile: str) -> None:
    """The grant probe must not name a table the schema actually has.

    Finding F15: the probe table was `crawl.runs`. Harmless until BUILD_PLAN
    1.1 made `crawl.runs` the run history — at which point the target's last
    act was `DROP TABLE crawl.runs`. It survives today only because
    page_observations, crawl_queue and asset_queue hold foreign keys into it,
    which is luck rather than design.
    """
    from spydra.adapters.postgres.tables import metadata

    real = {t.name for t in metadata.sorted_tables}
    section = makefile[makefile.index("verify-grants:") :]
    section = section[: section.index("\n# ---")]

    # Both the probe variable and any hardcoded name. Scanning only for
    # `CREATE TABLE <literal>` misses the whole point once the name lives in
    # a shell variable, which is how the first version of this test passed a
    # Makefile whose probe was `crawl.runs` (found by mutation).
    names = set(re.findall(r"PROBE=([\w.]+)", section))
    names |= set(re.findall(r"(?:CREATE|DROP) TABLE (?:IF EXISTS )?([A-Za-z_][\w.]*)", section))
    touched = {n.split(".", 1)[-1] for n in names}

    collisions = sorted(touched & real)
    assert not collisions, (
        f"verify-grants creates or drops {collisions}, which the migration also "
        "creates — so its cleanup DROP is aimed at real data. Use a probe name "
        "that cannot collide."
    )
