"""Parse a CSV of seed URLs into template-less `DomainConfig`s (BUILD_PLAN
2.9, spec 004 §6).

**Scaffolding with the same end date as the YAML loader**: `3.2` deletes
`spydra.load` and deletes this module with it, so there is deliberately no
schema and no format anyone could grow attached to. It exists so an operator
can onboard many seed URLs fast while templates still come from YAML.

The file is row-oriented bulk onboarding, so validation is per-row: a bad
row is reported as a `Reject` naming the file line (what the operator's
editor shows; the header is line 1) and the rest of the file still parses.
The one exception is the header — the column contract. A wrong or missing
header refuses the whole file, because inferring it would turn row 1's data
into column names and make every later reject message unnameable.

**Nothing here can make a network call.** Host validation is syntax-only —
no `getaddrinfo`, no DNS — and the import allowlist below (csv, dataclasses,
typing, urllib.parse, the `RenderMode` enum and the `DomainConfig` carrier
both loaders feed to `apply`) is enforced by test, so a future `httpx`
cannot drift in.
"""

import csv
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from spydra.domain.enums import RenderMode
from spydra.load import DomainConfig

__all__ = ["Reject", "SeedFile", "parse"]

# The three accepted headers, exact and ordered. Optional columns exist only
# when their header names them: a row cannot carry a column the header did
# not declare, and a cell left empty in a declared column is a row reject,
# not the column's default.
_HEADERS: Final[tuple[tuple[str, ...], ...]] = (
    ("host", "seed_url"),
    ("host", "seed_url", "render_mode"),
    ("host", "seed_url", "render_mode", "crawl_delay_ms"),
)

_RENDER_MODES: Final = ("static", "rendered", "auto")


@dataclass(frozen=True, slots=True)
class Reject:
    """One rejected row: the file line it came from and why it was refused."""

    line: int
    token: str
    detail: str


@dataclass(frozen=True, slots=True)
class SeedFile:
    """A parsed file: the domains that parsed and the rows that did not.

    An all-or-nothing file never reaches this shape — a bad header raises,
    and a file with no importable row returns empty `domains`, which the
    loader refuses before anything is written.
    """

    domains: tuple[DomainConfig, ...]
    rejects: tuple[Reject, ...]


def parse(text: str) -> SeedFile:
    """Parse CSV text. Raises `ValueError` when the header is not one of the
    three accepted spellings — the one file-level fact known before any row."""
    reader = csv.reader(text.splitlines())
    header = next(reader, None)
    if header is None or tuple(field.strip() for field in header) not in _HEADERS:
        got = ",".join(header) if header is not None else "(nothing)"
        raise ValueError(
            f"header must be host,seed_url[,render_mode[,crawl_delay_ms]] — got: {got}"
        )

    rejects: list[Reject] = []

    def reject(line: int, token: str, detail: str) -> None:
        rejects.append(Reject(line=line, token=token, detail=detail))

    # host -> (render_mode, crawl_delay_ms, first accepted line); a domain has
    # one setting, so a later row with a different one is a conflict, not a
    # silent pick. `respect_robots` is fixed true — the `load.py` default —
    # and is deliberately not a column.
    accepted: dict[str, tuple[RenderMode, int, int]] = {}
    seeds: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()

    for row in reader:
        row = [field.strip() for field in row]
        if not any(row):
            # Blank, or blank after stripping (csv yields ['   '] for a
            # spaces-only line — padding, not a row): skipped silently, per
            # spec 004 §6. A "," line is blank the same way — every field
            # strips to empty; a row with any content in it still rejects.
            continue
        line = reader.line_num

        if len(row) != len(header):
            reject(
                line,
                "column_count",
                f"expected {len(header)} fields, got {len(row)} — the header declares the columns",
            )
            continue
        host, seed = row[0], row[1]

        if not host:
            reject(line, "empty_host", "host is empty — every seed needs the domain it belongs to")
            continue
        if not seed:
            reject(line, "empty_seed", "seed_url is empty — a row without a seed onboards nothing")
            continue
        try:
            parts = urlsplit(seed)
        except ValueError:
            parts = None
        not_absolute = (
            f"{seed!r} is not an absolute URL — write the full URL including its "
            "scheme; a path alone is not resolved against the host as it is in YAML"
        )
        # Scheme before netloc: `mailto:` has a scheme and no netloc, and the
        # vocabulary pins it `off_scheme`, not `bad_url` — the token says which
        # rule the operator broke, and "no netloc" is true of every URL whose
        # scheme takes no authority.
        if parts is None or not parts.scheme:
            reject(line, "bad_url", not_absolute)
            continue
        if parts.scheme not in ("http", "https"):
            reject(
                line,
                "off_scheme",
                f"{parts.scheme} is not http or https — mailto:, tel: and javascript: "
                "are not crawlable (spec 004 §1 rule 2)",
            )
            continue
        if not parts.netloc:
            reject(line, "bad_url", not_absolute)
            continue
        if parts.netloc.lower() != host.lower():
            reject(
                line,
                "host_mismatch",
                f"seed {seed} is not on {host}. Each seed is crawled under its domain's "
                "robots.txt and politeness, so it belongs under the domain it is on.",
            )
            continue

        mode_text = row[2] if len(row) > 2 else RenderMode.STATIC.value
        delay_text = row[3] if len(row) > 3 else "2000"
        if mode_text not in _RENDER_MODES:
            reject(
                line,
                "bad_render_mode",
                f"{mode_text!r} is not one of static, rendered, auto",
            )
            continue
        # ASCII digits only: int() would take "5_000" as 50 and "+5" as 5,
        # and a crawl delay an operator did not mean is the one mistake this
        # loader cannot make silently.
        if not (delay_text.isascii() and delay_text.isdigit()):
            reject(
                line,
                "bad_delay",
                f"{delay_text!r} is not a whole number of milliseconds ≥ 0 — the "
                "configured delay is the domain's politeness floor (spec 002 §4)",
            )
            continue

        mode = RenderMode(mode_text)
        delay = int(delay_text)
        known = accepted.get(host)
        if known is not None and (known[0], known[1]) != (mode, delay):
            reject(
                line,
                "conflict",
                f"{host} is {known[0].value}/{known[1]} from line {known[2]}, this row "
                f"says {mode.value}/{delay} — a domain has one setting; keep one of "
                "the two rows",
            )
            continue
        if (host, seed) in seen:
            continue  # an exact duplicate enqueues nothing the first row did not
        seen.add((host, seed))
        if known is None:
            accepted[host] = (mode, delay, line)
        seeds.setdefault(host, []).append(seed)

    domains = tuple(
        DomainConfig(
            host=host,
            render_mode=mode,
            crawl_delay_ms=delay,
            respect_robots=True,
            templates=(),
            seeds=tuple(seeds[host]),
        )
        for host, (mode, delay, _) in accepted.items()
    )
    return SeedFile(domains=domains, rejects=tuple(rejects))
