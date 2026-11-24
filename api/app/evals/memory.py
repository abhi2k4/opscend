"""`make eval-memory`: how well incident memory recognises a failure it has seen.

No model and no database: the past incidents are the demo's failures, and each query
is one of them changed the way a real repeat changes (other ids, timestamps and
durations, extra lines, a provider's timestamp prefix) or a different value of the
same kind of error. Novel errors that match nothing measure false "seen before"s,
which cost more than a miss: a reader follows a wrong hint.

    make eval-memory               the table
    make eval-memory ARGS=--list   every query and what it matched
"""

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from app.demo.scenarios import SCENARIOS, STRIPE_ENV, Scenario
from app.incidents import fingerprint, memory
from app.models import Incident

Lines = list[tuple[str, str]]


def _lines(scenario: Scenario) -> Lines:
    return [
        (level, message) for _, level, message in (*scenario.build_logs, *scenario.runtime_logs)
    ]


# The memory: one past incident per demo failure.
PAST: dict[str, Lines] = {"stripe-env": _lines(STRIPE_ENV)} | {s.id: _lines(s) for s in SCENARIOS}


# ───────────────────────────── how a repeat differs from the first time


def _renumber(lines: Lines) -> Lines:
    """Other ids, ports, durations, line numbers and versions."""
    return [
        (level, re.sub(r"\d+", lambda m: str(int(m.group()) * 7 + 3), msg)) for level, msg in lines
    ]


def _noisy(lines: Lines) -> Lines:
    """More output around the same failure."""
    noise = [("info", "npm warn deprecated inflight@1.0.6: not supported"), ("warn", "Using cache")]
    return [*noise, *lines, ("info", "Waiting for the next attempt")]


def _prefixed(lines: Lines) -> Lines:
    """A platform that puts its own timestamp and level in the message text."""
    return [
        (level, f"2026-11-24T10:00:0{n % 10}.123Z {level.upper()} {msg}")
        for n, (level, msg) in enumerate(lines)
    ]


def _swap(old: str, new: str):  # noqa: ANN202
    def change(lines: Lines) -> Lines:
        return [(level, msg.replace(old, new)) for level, msg in lines]

    return change


@dataclass(frozen=True)
class Query:
    name: str
    lines: Lines
    # The past incidents that count as the right first match (equally good ties), or
    # nothing for a novel error.
    expected: tuple[str, ...]
    kind: str | None = None  # the match kind it should get


VARIANTS = {"renumbered": _renumber, "noisy": _noisy, "prefixed": _prefixed}
# The same kind of error with a different value: a family match.
FAMILY = [
    ("stripe-env", _swap("STRIPE_WEBHOOK_SECRET", "SENTRY_DSN")),
    ("bad-env-var", _swap("CACHE_URL", "DATABASE_URL")),
    ("failing-migration", _swap('"customer_id"', '"tenant_id"')),
]
# Both missing-variable incidents are one family: either is a right first match.
FAMILY_OF = {
    "stripe-env": ("stripe-env", "bad-env-var"),
    "bad-env-var": ("stripe-env", "bad-env-var"),
    "failing-migration": ("failing-migration",),
}
# Errors the demo never had. None of them should be "seen before".
NOVEL = [
    "Error: listen EADDRINUSE: address already in use :::3000",
    'FATAL: password authentication failed for user "app"',
    "Container killed: OOMKilled (memory limit 512Mi exceeded)",
    "ModuleNotFoundError: No module named 'requests'",
    "SyntaxError: Unexpected token '<', \"<!DOCTYPE \"... is not valid JSON",
    "panic: runtime error: invalid memory address or nil pointer dereference",
    "Error: Cannot find module 'express'",
    "npm ERR! code ERESOLVE",
    "TypeError: Cannot read properties of undefined (reading 'map')",
    "Error: connect ECONNREFUSED 10.0.0.12:5432",
    "Error: Missing required argument --port",
    "Healthcheck failed: HTTP 404 on /health",
    # Near misses: they share words with a past error but are a different failure.
    'error: relation "orders" does not exist',
    "TypeError: Cannot read properties of null (reading 'QueueScheduler')",
    "Error: Missing required header x-request-id",
    "Error: Request timed out after 300s calling the reviews API",
]


def queries() -> list[Query]:
    out = [
        Query(f"{name}/{variant}", change(lines), (name,), "signature")
        for name, lines in PAST.items()
        for variant, change in VARIANTS.items()
    ]
    out += [
        Query(f"{name}/other-value", change(PAST[name]), FAMILY_OF[name], "family")
        for name, change in FAMILY
    ]
    out += [Query(f"novel/{n}", [("error", text)], ()) for n, text in enumerate(NOVEL, 1)]
    return out


# ───────────────────────────── scoring


def _incident(name: str, lines: Lines) -> Incident:
    found = fingerprint.from_logs(lines)
    assert found is not None, name
    return Incident(
        id=name,
        service_id="svc",
        signature=found.signature,
        family=found.family,
        error_text=found.error_text,
    )


def rank(query: Query) -> list[tuple[str, str]]:
    """Past incidents that match, best first, as (name, match kind): memory.similar's rule."""
    new = _incident(query.name, query.lines)
    scored = []
    for name, lines in PAST.items():
        result = memory._score(new, _incident(name, lines))  # noqa: SLF001
        if result is not None:
            scored.append((result[1], name, result[0]))
    return [(name, kind) for _, name, kind in sorted(scored, key=lambda row: -row[0])]


@dataclass
class Report:
    hit_at_1: float
    hit_at_3: float
    mrr: float
    right_kind: float  # of the first hits, the share with the expected match kind
    false_seen_before: float  # novel errors that matched something
    rows: list[tuple[str, str, list[tuple[str, str]]]]


def evaluate() -> Report:
    positives, negatives, rows = [], [], []
    for query in queries():
        ranked = rank(query)
        names = [name for name, _ in ranked]
        if not query.expected:
            negatives.append(bool(ranked))
            verdict = "FALSE MATCH" if ranked else "ok"
        else:
            hits = [n for n, name in enumerate(names, 1) if name in query.expected]
            position = hits[0] if hits else None
            kind_ok = bool(ranked) and ranked[0][0] in query.expected and ranked[0][1] == query.kind
            positives.append((position, kind_ok))
            verdict = "ok" if position == 1 and kind_ok else f"rank {position}"
        rows.append((query.name, verdict, ranked[:3]))
    count = len(positives)
    return Report(
        hit_at_1=sum(p == 1 for p, _ in positives) / count,
        hit_at_3=sum(p is not None and p <= 3 for p, _ in positives) / count,
        mrr=sum(1 / p for p, _ in positives if p) / count,
        right_kind=sum(kind for _, kind in positives) / count,
        false_seen_before=sum(negatives) / len(negatives),
        rows=rows,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make eval-memory", description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="show every query")
    args = parser.parse_args(argv)
    report = evaluate()
    if args.list:
        for name, verdict, ranked in report.rows:
            print(f"{verdict:12} {name:32} {ranked}")
        print()
    positives = sum(1 for _, _, _ in report.rows) - len(NOVEL)
    print(f"{positives} repeats, {len(NOVEL)} novel errors, {len(PAST)} past incidents")
    print(f"hit@1               {report.hit_at_1:.2f}")
    print(f"hit@3               {report.hit_at_3:.2f}")
    print(f"MRR                 {report.mrr:.2f}")
    print(f"right match kind    {report.right_kind:.2f}")
    print(f"false seen-before   {report.false_seen_before:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
