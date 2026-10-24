"""`python -m spydra.load_seeds <file.csv>`: onboard many seed URLs fast
(BUILD_PLAN 2.9, spec 004 §6).

**Scaffolding with the same end date as the YAML loader**: `3.2` deletes
`spydra.load` and deletes this module with it. A file carries domains and
seeds but never templates — those still come from YAML today, so every
domain lands template-less: the structured rung still extracts (1.10),
every 200 is an `unknown_pages` row saying `no_template`, and the crawl
runs exactly the file's seeds and drains.

Unlike the YAML loader, a bad **row** costs only that row: the valid rows
are applied and the rejected ones are reported to stderr with their file
line numbers. A domain in a state a file cannot approve (`paused`,
`broken`, `archived`) is refused the same way — **alone**: its rows are
skipped, the rest of the file imports, and the run covers what imported
(`apply(skip_refused=True)`; the YAML loader keeps the whole-file refusal,
because a YAML file is one coherent template set and a CSV is independent
facts). The database transaction is still all-or-nothing for everything it
writes.

Exit codes are the only channel `make` has, and "imported with rejections"
is not "success": `0` only when every data row imported (silent dedupes do
not count against it), `1` when any row was rejected, any domain was
refused, or the file was refused.
"""

import asyncio
import os
import sys
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import create_async_engine

from spydra.adapters.postgres.configuration import DomainRefusal, PostgresConfiguration
from spydra.domain.errors import RefusedConfiguration
from spydra.domain.ids import RunId
from spydra.seed_csv import SeedFile, parse

__all__ = ["ImportResult", "load", "parse"]


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What one file did. `run_id is None` means no run was started — an
    empty file, every row rejected, or every domain refused."""

    run_id: RunId | None
    seed_file: SeedFile
    refusals: tuple[DomainRefusal, ...] = ()


async def load(configuration: PostgresConfiguration, text: str) -> ImportResult:
    """Parse, then apply every domain that parsed in one transaction.

    A domain already paused/broken/archived is refused alone — its rows are
    skipped, the rest of the file imports — so parse-level rejects and
    world-level refusals never reach the transaction together.
    """
    seed_file = parse(text)
    if not seed_file.domains:
        # Header-only or every row rejected: an empty `apply` would start a
        # run over nothing, which is a write the operator never approved.
        return ImportResult(run_id=None, seed_file=seed_file)
    outcome = await configuration.apply(seed_file.domains, skip_refused=True)
    return ImportResult(run_id=outcome.run_id, seed_file=seed_file, refusals=outcome.refusals)


async def main(path: str) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        with open(path, encoding="utf-8") as f:
            result = await load(PostgresConfiguration(engine), f.read())
    finally:
        await engine.dispose()

    for reject in result.seed_file.rejects:
        print(f"line {reject.line}: {reject.token} — {reject.detail}", file=sys.stderr)
    # Per host, not per line: the refusal is a fact about the domain's row
    # in `crawl.domains`, and every row naming the host shares it.
    for refusal in result.refusals:
        print(f"refused: {refusal.message} Its rows were skipped.", file=sys.stderr)

    if result.run_id is None:
        if result.refusals:
            sys.exit("refused: every domain in the file was refused; nothing was written")
        if result.seed_file.rejects:
            sys.exit("refused: every row was rejected; nothing was written")
        sys.exit("refused: no data rows after the header; nothing was written")

    refused_hosts = {refusal.host for refusal in result.refusals}
    imported = [d for d in result.seed_file.domains if d.host not in refused_hosts]
    seeds = sum(len(d.seeds) for d in imported)
    domain_s = "" if len(imported) == 1 else "s"
    seed_s = "" if seeds == 1 else "s"
    print(f"{len(imported)} domain{domain_s}, {seeds} seed{seed_s} imported")
    print(f"run {int(result.run_id)} started from {path}")
    if result.seed_file.rejects or result.refusals:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m spydra.load_seeds <file.csv>")
    try:
        asyncio.run(main(sys.argv[1]))
    except (RefusedConfiguration, ValueError) as refused:
        sys.exit(f"refused: {refused}")
