"""The CSV parser's own semantics (BUILD_PLAN 2.9, spec 004 §6), no database.

Holds, from the slice contract:

- **Purity, proven twice.** An AST allowlist over `seed_csv.py`'s imports —
  input-unbounded, so a future `httpx` cannot drift in — and a runtime
  test that parses real-looking hosts with `socket.socket` and
  `getaddrinfo` made to raise. Host validation is syntax-only.
- **The reject vocabulary.** Every token on a crafted row, each reported
  with the FILE line number (`csv.reader.line_num`: the header is line 1,
  the first data row line 2), so a reject after blank lines and earlier
  rejects still names the line the operator's editor shows.
- **The header is the column contract.** Three spellings accepted, fields
  stripped; a wrong order, wrong name, invented column or missing header
  refuses the whole file before any row is read.
- **Defaults, dedupe and conflict.** Optional columns absent → `static`/
  `2000`/`respect_robots` true, asserted on the `DomainConfig` the loader
  feeds to `apply`; a declared-but-empty optional cell is a reject, not
  the default; byte-identical rows dedupe silently; a same-host setting
  change is a `conflict` reject naming the earlier line.
- **The committed one-bad-row file** (`fixtures/phase2/seeds.csv`) parses
  to one Halden domain, two seeds and one line-4 `host_mismatch` — the
  fixture IS the done-when, so an edit that drifts it fails here.
"""

import ast
import socket
from pathlib import Path

import pytest

import spydra.seed_csv
from spydra.domain.enums import RenderMode
from spydra.seed_csv import parse

PHASE2 = Path(__file__).resolve().parent / "fixtures" / "phase2"

# ---------------------------------------------------------------------------
# Purity: nothing in the parser can make a network call
# ---------------------------------------------------------------------------

# The contract's allowlist, and nothing else. An allowlist, not a denylist:
# a module nobody has imagined yet is refused by default.
_ALLOWED_IMPORTS = (
    "csv",
    "dataclasses",
    "typing",
    "urllib.parse",
    "spydra.domain.enums",
    "spydra.load",
)


def test_the_parser_imports_only_what_the_contract_pins() -> None:
    source = Path(spydra.seed_csv.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative imports must be recorded, not skipped: `from . import
                # x` carries module=None and was invisible to the old
                # `and node.module` guard, against refused-by-default.
                imported.append("." * node.level + (node.module or ""))
            else:
                assert node.module is not None  # a level-0 import always names one
                imported.append(node.module)

    assert imported, "the walk read no imports; the test proves nothing"
    offending = [
        module
        for module in imported
        if not any(
            module == allowed or module.startswith(allowed + ".") for allowed in _ALLOWED_IMPORTS
        )
    ]
    assert offending == []


def test_parsing_survives_a_world_where_sockets_are_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    """The execution, not just the imports: real-looking hosts (a name, a
    host with a port, an IP) parse while any dial raises."""

    def _dialed(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"the parser made a network call: {args} {kwargs}")

    monkeypatch.setattr(socket, "socket", _dialed)
    monkeypatch.setattr(socket, "getaddrinfo", _dialed)

    result = parse(
        "host,seed_url\n"
        "example.com,https://example.com/catalog\n"
        "halden.fixtures:8099,http://halden.fixtures:8099/shop/cutting/\n"
        "192.0.2.7,http://192.0.2.7/items\n"
    )

    assert result.rejects == ()
    assert [domain.host for domain in result.domains] == [
        "example.com",
        "halden.fixtures:8099",
        "192.0.2.7",
    ]


# ---------------------------------------------------------------------------
# The header: the column contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "row"),
    [
        ("host,seed_url", "example.com,https://example.com/a"),
        ("host,seed_url,render_mode", "example.com,https://example.com/a,static"),
        (
            "host,seed_url,render_mode,crawl_delay_ms",
            "example.com,https://example.com/a,static,2000",
        ),
    ],
    ids=["two-column", "three-column", "four-column"],
)
def test_every_accepted_header_spelling_parses(header: str, row: str) -> None:
    result = parse(f"{header}\n{row}\n")

    assert result.rejects == ()
    (domain,) = result.domains
    assert domain.host == "example.com"
    assert domain.seeds == ("https://example.com/a",)


@pytest.mark.parametrize(
    "header",
    [
        "seed_url,host",
        "hostname,seed_url",
        "host,seed_url,respect_robots",
        "host,seed_url,render_mode,crawl_delay_ms,extra",
        "Host,Seed_Url",
        # No header: row 1 is data, so every later reject would be
        # unnameable — the reason the header is refused, not inferred.
        "example.com,https://example.com/a",
    ],
    ids=["wrong-order", "wrong-name", "invented-column", "extra-column", "uppercase", "missing"],
)
def test_a_header_that_is_not_one_of_the_three_spellings_refuses_the_file(header: str) -> None:
    with pytest.raises(ValueError, match="header must be") as refused:
        parse(f"{header}\nexample.com,https://example.com/a\n")

    assert "got:" in str(refused.value)


def test_an_empty_file_is_a_header_refusal() -> None:
    with pytest.raises(ValueError, match=r"got: \(nothing\)"):
        parse("")


def test_header_fields_are_stripped_like_row_fields() -> None:
    """The one hand-edited forgiveness, applied to the header as fields."""
    result = parse(" host , seed_url \nexample.com, https://example.com/a\n")

    assert result.rejects == ()
    (domain,) = result.domains
    assert domain.host == "example.com"
    assert domain.seeds == ("https://example.com/a",)


# ---------------------------------------------------------------------------
# Defaults: the optional columns
# ---------------------------------------------------------------------------


def test_absent_optional_columns_default_to_the_yaml_loaders_values() -> None:
    (domain,) = parse("host,seed_url\nexample.com,https://example.com/a\n").domains

    assert domain.render_mode is RenderMode.STATIC
    assert domain.crawl_delay_ms == 2000
    assert domain.respect_robots is True
    assert domain.templates == ()


def test_present_optional_columns_override_the_defaults() -> None:
    (domain,) = parse(
        "host,seed_url,render_mode,crawl_delay_ms\n"
        "example.com,https://example.com/a,rendered,7000\n"
    ).domains

    assert domain.render_mode is RenderMode.RENDERED
    assert domain.crawl_delay_ms == 7000


@pytest.mark.parametrize(
    ("header", "row", "token"),
    [
        ("host,seed_url,render_mode", "example.com,https://example.com/a,", "bad_render_mode"),
        (
            "host,seed_url,render_mode,crawl_delay_ms",
            "example.com,https://example.com/a,static,",
            "bad_delay",
        ),
    ],
    ids=["empty-render-mode", "empty-delay"],
)
def test_an_empty_cell_in_a_declared_optional_column_is_a_reject_not_its_default(
    header: str, row: str, token: str
) -> None:
    """Defaults belong to absent columns, which only the header can make
    absent; a declared column with an empty cell is the operator's typo."""
    result = parse(f"{header}\n{row}\n")

    (reject,) = result.rejects
    assert reject.token == token


# ---------------------------------------------------------------------------
# The reject vocabulary, each on a crafted row
# ---------------------------------------------------------------------------


def test_rejects_carry_file_line_numbers_not_row_indices() -> None:
    """The line the operator's editor shows: blank lines count, earlier
    rejects count, and a valid row after a reject still imports."""
    result = parse(
        "host,seed_url\n"  # line 1 — the header
        "\n"  # line 2 — blank, skipped silently
        "example.com,https://example.com/a\n"  # line 3 — valid
        "example.com,https://elsewhere.test/b\n"  # line 4 — the bad row
        "example.com,https://example.com/c\n"  # line 5 — imports after it
    )

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (4, "host_mismatch")
    (domain,) = result.domains
    assert domain.seeds == ("https://example.com/a", "https://example.com/c")


def test_a_spaces_only_line_is_blank_after_stripping_and_skipped() -> None:
    """`csv.reader` yields `['   ']` for it — one field of padding, not a
    row (a `column_count` reject for it was a review finding). The line
    still counts: file numbering is what the editor shows."""
    result = parse(
        "host,seed_url\n"
        "   \n"  # line 2 — spaces only: blank after stripping
        "example.com,https://elsewhere.test/a\n"  # line 3 — still line 3
    )

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (3, "host_mismatch")
    assert result.domains == ()


_TWO_COLUMN = "host,seed_url"
_FOUR_COLUMN = "host,seed_url,render_mode,crawl_delay_ms"


@pytest.mark.parametrize(
    ("header", "row", "token"),
    [
        # Seed-level rules, under the two-column header.
        (_TWO_COLUMN, ",https://example.com/a", "empty_host"),
        (_TWO_COLUMN, "example.com,", "empty_seed"),
        (_TWO_COLUMN, "example.com,/catalog/abrasives", "bad_url"),
        # Protocol-relative: a scheme the browser would guess, the operator
        # did not write — the full URL is required, not inferred.
        (_TWO_COLUMN, "example.com,//example.com/a", "bad_url"),
        # `mailto:` has a scheme and no netloc: scheme is checked first so
        # the token says which rule was broken (this slice's own smoke find).
        (_TWO_COLUMN, "example.com,mailto:support@example.com", "off_scheme"),
        (_TWO_COLUMN, "example.com,javascript:void(0)", "off_scheme"),
        (_TWO_COLUMN, "example.com,ftp://example.com/file.zip", "off_scheme"),
        (_TWO_COLUMN, "example.com,https://elsewhere.test/a", "host_mismatch"),
        # Optional-column rules, under the four-column header.
        (_FOUR_COLUMN, "example.com,https://EXAMPLE.com/a,dynamic,2000", "bad_render_mode"),
        # Case-pinned: `Rendered` is not one of the three.
        (_FOUR_COLUMN, "example.com,https://EXAMPLE.com/a,Rendered,2000", "bad_render_mode"),
        (_FOUR_COLUMN, "example.com,https://EXAMPLE.com/a,static,slow", "bad_delay"),
        (_FOUR_COLUMN, "example.com,https://EXAMPLE.com/a,static,-5", "bad_delay"),
        (_FOUR_COLUMN, "example.com,https://EXAMPLE.com/a,static,2.5", "bad_delay"),
        (_FOUR_COLUMN, "example.com,https://EXAMPLE.com/a,static,+5", "bad_delay"),
    ],
)
def test_each_reject_token_names_the_rule_and_the_line_it_broke(
    header: str, row: str, token: str
) -> None:
    result = parse(f"{header}\n{row}\n")

    (reject,) = result.rejects
    assert reject.token == token
    assert reject.line == 2
    assert result.domains == ()


def test_a_bad_render_mode_names_the_three_accepted() -> None:
    result = parse("host,seed_url,render_mode\nexample.com,https://example.com/a,dynamic\n")

    (reject,) = result.rejects
    assert reject.token == "bad_render_mode"
    for spelling in ("static", "rendered", "auto"):
        assert spelling in reject.detail


def test_a_delay_with_an_underscore_is_rejected_not_parsed_by_int() -> None:
    """`int("5_000")` is 50: a politeness floor the operator did not write
    is the one mistake this loader refuses to make silently."""
    result = parse(
        "host,seed_url,render_mode,crawl_delay_ms\nexample.com,https://example.com/a,static,5_000\n"
    )

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (2, "bad_delay")
    assert "5_000" in reject.detail


@pytest.mark.parametrize(
    ("row", "got"),
    [
        ("example.com", "got 1"),
        ("example.com,https://example.com/a,static", "got 3"),
        ("example.com,https://example.com/a,static,2000,extra", "got 5"),
    ],
    ids=["one-field", "three-fields", "five-fields"],
)
def test_a_row_with_the_wrong_field_count_is_rejected_naming_both_counts(
    row: str, got: str
) -> None:
    result = parse(f"host,seed_url,render_mode,crawl_delay_ms\n{row}\n")

    (reject,) = result.rejects
    assert reject.token == "column_count"
    assert "expected 4" in reject.detail
    assert got in reject.detail


# ---------------------------------------------------------------------------
# The host cross-check: case-insensitive netloc, port included
# ---------------------------------------------------------------------------


def test_the_host_compare_ignores_case_on_both_sides() -> None:
    result = parse(
        "host,seed_url\n"
        "EXAMPLE.com,https://example.com/a\n"
        "halden.fixtures:8099,http://HALDEN.FIXTURES:8099/shop/cutting/\n"
    )

    assert result.rejects == ()
    assert [domain.host for domain in result.domains] == [
        "EXAMPLE.com",
        "halden.fixtures:8099",
    ]


@pytest.mark.parametrize(
    ("host", "seed"),
    [
        ("example.com", "https://example.com:8099/a"),
        ("example.com:8099", "https://example.com/a"),
        ("example.com", "https://sub.example.com/a"),
    ],
    ids=["seed-adds-a-port", "seed-drops-the-port", "subdomain-is-another-host"],
)
def test_a_netloc_that_is_not_the_host_is_a_mismatch(host: str, seed: str) -> None:
    """The same comparison `_seed` makes: the worker reads the seed's
    domain row for robots, delay and pause state."""
    result = parse(f"host,seed_url\n{host},{seed}\n")

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (2, "host_mismatch")
    assert "robots.txt" in reject.detail


# ---------------------------------------------------------------------------
# Dedupe and conflict: one domain, one setting
# ---------------------------------------------------------------------------


def test_an_exact_duplicate_row_imports_once_silently() -> None:
    """`ON CONFLICT (run_id, url_hash) DO NOTHING` makes the two outcomes
    byte-identical in the database: reporting one reports a non-failure."""
    row = "halden.test,https://halden.test/a,static,1000"
    result = parse(f"host,seed_url,render_mode,crawl_delay_ms\n{row}\n{row}\n")

    assert result.rejects == ()
    (domain,) = result.domains
    assert domain.seeds == ("https://halden.test/a",)


def test_a_second_row_changing_the_delay_conflicts_and_names_the_earlier_line() -> None:
    result = parse(
        "host,seed_url,render_mode,crawl_delay_ms\n"
        "halden.test,https://halden.test/a,static,1000\n"  # line 2 — accepted
        "halden.test,https://halden.test/b,static,2000\n"  # line 3 — the conflict
    )

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (3, "conflict")
    assert "line 2" in reject.detail
    assert "1000" in reject.detail and "2000" in reject.detail


def test_a_render_mode_change_conflicts_even_at_the_same_delay() -> None:
    result = parse(
        "host,seed_url,render_mode,crawl_delay_ms\n"
        "halden.test,https://halden.test/a,static,1000\n"
        "halden.test,https://halden.test/b,rendered,1000\n"
    )

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (3, "conflict")


def test_the_same_setting_on_new_seeds_is_not_a_conflict() -> None:
    result = parse(
        "host,seed_url,render_mode\n"
        "halden.test,https://halden.test/a,static\n"
        "halden.test,https://halden.test/b,static\n"
    )

    assert result.rejects == ()
    (domain,) = result.domains
    assert domain.seeds == ("https://halden.test/a", "https://halden.test/b")


# ---------------------------------------------------------------------------
# What a whole file parses to
# ---------------------------------------------------------------------------


def test_domains_keep_first_accepted_order_and_seeds_keep_file_order() -> None:
    result = parse(
        "host,seed_url\nb.test,https://b.test/1\na.test,https://a.test/1\nb.test,https://b.test/2\n"
    )

    assert [domain.host for domain in result.domains] == ["b.test", "a.test"]
    assert [domain.seeds for domain in result.domains] == [
        ("https://b.test/1", "https://b.test/2"),
        ("https://a.test/1",),
    ]


def test_a_file_where_every_row_is_rejected_parses_to_no_domains() -> None:
    """The loader's refusal input: the rejects must survive to be printed."""
    # The first row carries a seed: a `,`-only row is blank after stripping
    # now, and empty_host needs a row with content in it.
    result = parse("host,seed_url\n,https://nowhere.test/a\nexample.com,https://elsewhere.test/x\n")

    assert result.domains == ()
    assert [reject.token for reject in result.rejects] == ["empty_host", "host_mismatch"]


def test_a_header_only_file_has_no_domains_and_no_rejects() -> None:
    result = parse("host,seed_url\n")

    assert result.domains == ()
    assert result.rejects == ()


def test_the_committed_seeds_file_imports_its_valid_rows_and_names_line_4() -> None:
    """`fixtures/phase2/seeds.csv` is the done-when committed: one bad row
    (line 4, a seed on another host) among Halden rows, for
    `make load-seeds` against the `phase1-exit` fixture site."""
    result = parse((PHASE2 / "seeds.csv").read_text(encoding="utf-8"))

    (reject,) = result.rejects
    assert (reject.line, reject.token) == (4, "host_mismatch")
    (domain,) = result.domains
    assert domain.host == "halden.fixtures:8099"
    assert domain.render_mode is RenderMode.STATIC
    assert domain.crawl_delay_ms == 500
    assert domain.seeds == (
        "http://halden.fixtures:8099/shop/cutting/",
        "http://halden.fixtures:8099/shop/cutting/blades/",
    )
