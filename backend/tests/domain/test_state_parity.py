"""The domain states have to mean the same thing in three places.

Spec 001 §6: "Every `domain_state` value in `DESIGN_SYSTEM.md` exists in the
enum." That criterion is about one specific failure — a state the UI can
paint that the database cannot store, or the reverse — and it is worth
holding because the three descriptions live in three files that are edited by
different people at different times:

  docs/DESIGN_SYSTEM.md               the lifecycle-colour table
  spydra/domain/enums.py              DomainState
  spydra/adapters/postgres/tables.py  the `crawl.domain_state` SQL enum

**Finding F13, filed and not fixed here.** `DESIGN_SYSTEM.md` lists
`pending`; the enum has `awaiting_approval`. The documentation's own meaning
column reads "Awaiting your approval", so the likely reading is that
`pending` is a display label rather than a seventh state — but
`DESIGN_SYSTEM.md` is not the state authority (ADR-0025 gave that to
`UI_STATES.md`) and correcting it is outside this slice's declared file set.
So the mapping is written down here, explicitly, where it is visible in a
diff and where a genuinely new row still fails. See
`.tasks/feat-1.1-1.2-schema-and-domain.md` § Open questions.
"""

import re
from pathlib import Path

import pytest

from spydra.adapters.postgres.tables import domain_state as sql_domain_state
from spydra.adapters.postgres.tables import run_state as sql_run_state
from spydra.domain import DomainState, RunState

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# `.:/repo` in compose, so the repository root is there inside the api
# container; the backend's parent is the root for a checkout run directly.
_DOCS_CANDIDATES = (BACKEND_ROOT.parent / "docs", Path("/repo/docs"))

# F13. The one documented label that is not an enum value, and what it means.
# A row that is neither an enum value nor a key here fails the test.
DISPLAY_LABELS = {"pending": DomainState.AWAITING_APPROVAL}


def _docs_dir() -> Path:
    for candidate in _DOCS_CANDIDATES:
        if (candidate / "DESIGN_SYSTEM.md").is_file():
            return candidate
    pytest.fail(
        "DESIGN_SYSTEM.md not found. Spec 001 §6 asserts against it, so this is a "
        f"failure and not a skip. Looked in {[str(c) for c in _DOCS_CANDIDATES]}; "
        "inside the api container the repository root arrives via compose's "
        "`.:/repo` mount."
    )


def documented_states() -> list[str]:
    """The first column of the lifecycle-colour table in DESIGN_SYSTEM.md.

    Matched on the table's shape — a row of backticked cells whose second and
    third are hex colours — rather than on a heading, so renaming the section
    does not quietly empty this list and turn the test green.
    """
    text = (_docs_dir() / "DESIGN_SYSTEM.md").read_text()
    rows = re.findall(
        r"^\|\s*`(\w+)`\s*\|\s*`#[0-9A-Fa-f]{6}`\s*\|\s*`#[0-9A-Fa-f]{6}`\s*\|",
        text,
        re.MULTILINE,
    )
    assert rows, "found no lifecycle-colour rows in DESIGN_SYSTEM.md — has the table moved?"
    return rows


def test_every_documented_state_resolves_to_one_enum_member() -> None:
    values = {s.value for s in DomainState}
    unresolved = [
        row for row in documented_states() if row not in values and row not in DISPLAY_LABELS
    ]
    assert not unresolved, (
        f"DESIGN_SYSTEM.md paints state(s) the database cannot store: {unresolved}. "
        "Either add them to DomainState and the SQL enum, or — if they are display "
        "labels — record them in DISPLAY_LABELS with the state they render."
    )


def test_the_display_label_mapping_has_not_gone_stale() -> None:
    """If F13 is resolved by correcting the docs, this fails and the mapping
    should be deleted rather than left behind as decoration."""
    documented = set(documented_states())
    stale = [label for label in DISPLAY_LABELS if label not in documented]
    assert not stale, (
        f"DISPLAY_LABELS maps {stale}, which DESIGN_SYSTEM.md no longer lists. "
        "F13 looks resolved — delete the mapping."
    )


def test_every_enum_member_is_documented() -> None:
    """The other direction, which §6 does not ask for and which matters just
    as much: a state the crawler can enter and the UI has no colour for is a
    domain the operator cannot see is stuck."""
    painted = set(documented_states()) | {s.value for s in DISPLAY_LABELS.values()}
    missing = sorted(s.value for s in DomainState if s.value not in painted)
    assert not missing, f"DomainState member(s) with no row in DESIGN_SYSTEM.md: {missing}"


def test_domain_state_matches_the_sql_enum() -> None:
    """The schema and the domain cannot disagree: a value the entity can hold
    and the column cannot is an INSERT that fails at 3 a.m. mid-run."""
    assert {s.value for s in DomainState} == set(sql_domain_state.enums)


def test_run_state_matches_the_sql_enum() -> None:
    assert {s.value for s in RunState} == set(sql_run_state.enums)
