"""`make eval`: run the investigator on every case of the evaluation set and score it.

Each case gets fresh sample data, has its failure pushed through the real ingest
pipeline (as the Chaos lab does), and is then investigated by the configured model with
the real tools, limits and evidence check. Everything happens in a throwaway SQLite
database: the install's own data is never read or changed, and no email is sent.

    make eval                                  every case, once
    make eval ARGS="--case timeout --runs 3"   one case, three times
    make eval ARGS="--min-accuracy 0.8"        exit 1 below 80% (for CI)
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core import db
from app.core.config import get_settings
from app.core.queue import InlineQueue, get_queue, init_queue
from app.demo.breaker import break_demo
from app.demo.seed import rebuild_demo
from app.investigator.llm import LLMClient, build_llm
from app.investigator.orchestrator import run_investigation
from app.jobs import JOBS
from app.models import Deployment, Incident, Investigation

from .cases import CASES, CASES_BY_ID, Case
from .scoring import OUTCOMES, Outcome, score


@dataclass
class Result:
    case: str
    run: int
    outcome: Outcome
    problems: list[str] = field(default_factory=list)
    confidence: str | None = None
    summary: str | None = None
    seconds: float = 0.0
    tokens: int = 0
    tool_calls: int = 0
    #: The stored report, kept so a miss can be read without running the case again.
    report: dict[str, Any] | None = None


@asynccontextmanager
async def isolated_database() -> AsyncIterator[None]:
    """Point the app at an empty, migrated SQLite file for the duration of the run."""
    overrides = {
        "REDIS_URL": "",
        "OPSCEND_DEMO": "1",
        "OPSCEND_PUBLIC_DEMO": "0",
        "OPSCEND_AUTO_INVESTIGATE": "0",
        "OPSCEND_BACKGROUND_JOBS": "0",
        "OPSCEND_SMTP_HOST": "",
    }
    before = {key: os.environ.get(key) for key in (*overrides, "DATABASE_URL")}
    with tempfile.TemporaryDirectory(prefix="opscend-eval-") as folder:
        os.environ.update(overrides, DATABASE_URL=f"sqlite+aiosqlite:///{folder}/eval.db")
        get_settings.cache_clear()
        db.reset_caches()
        # Ingest enqueues jobs (remember_incidents), so start the same inline queue the
        # API uses. No periodic jobs: OPSCEND_BACKGROUND_JOBS is off above.
        queue = init_queue(JOBS, {})
        try:
            await db.run_migrations()
            yield
        finally:
            await queue.stop()
            await db.dispose_all()
            for key, value in before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()
            db.reset_caches()


async def _stage(case: Case) -> tuple[str, str | None, str | None]:
    """Fresh sample data with this case's failed deploy in it.

    Returns (deployment_id, incident_id, commit sha of the failed deploy).
    """
    async with db.session_scope() as session:
        await rebuild_demo(session)
        if case.seeded:
            deployment = await session.scalar(
                select(Deployment)
                .where(
                    Deployment.commit_message == case.scenario.commit_message,
                    Deployment.status == "failed",
                )
                .order_by(Deployment.started_at.desc())
                .limit(1)
            )
            if deployment is None:
                raise RuntimeError(f"the sample data has no failed deploy for {case.id}")
            incident_id = await session.scalar(
                select(Incident.id).where(Incident.deployment_id == deployment.id).limit(1)
            )
            return deployment.id, incident_id, deployment.commit_sha
        deployment_id, incident_id = await break_demo(session, case.scenario)
        sha = await session.scalar(
            select(Deployment.commit_sha).where(Deployment.id == deployment_id)
        )
        return deployment_id, incident_id, sha


async def run_case(case: Case, llm: LLMClient, run: int = 1) -> Result:
    deployment_id, incident_id, sha = await _stage(case)
    # Let the jobs ingest started finish first, as they usually have by the time a
    # real investigation runs, so every case starts from the same state.
    queue = get_queue()
    if isinstance(queue, InlineQueue):
        await queue.drain()
    async with db.session_scope() as session:
        investigation = Investigation(
            deployment_id=deployment_id,
            incident_id=incident_id,
            service_name=case.scenario.service,
            model=llm.model,
        )
        session.add(investigation)
        await session.commit()
        investigation_id = investigation.id

    started = time.perf_counter()
    await run_investigation(investigation_id, llm)
    seconds = time.perf_counter() - started

    async with db.session_scope() as session:
        investigation = await session.get(Investigation, investigation_id)
        report: dict[str, Any] | None = investigation.report
        verdict = score(case, report, sha)
        problems = list(verdict.problems)
        if report is None and investigation.error:
            problems = [investigation.error]
        return Result(
            case=case.id,
            run=run,
            outcome=verdict.outcome,
            problems=problems,
            confidence=report.get("confidence") if report else None,
            summary=report.get("summary") if report else None,
            seconds=round(seconds, 1),
            tokens=investigation.tokens_used,
            tool_calls=sum(1 for step in investigation.steps if step.type == "tool"),
            report=report,
        )


async def run_eval(
    cases: Sequence[Case],
    llm: LLMClient,
    *,
    runs: int = 1,
    on_result: Any = None,
) -> list[Result]:
    """Run every case `runs` times, one after another. Needs a database to work in."""
    results = []
    for case in cases:
        for run in range(1, runs + 1):
            try:
                result = await run_case(case, llm, run)
            except Exception as exc:  # one broken case must not lose the rest of the run
                result = Result(case.id, run, "error", [f"{type(exc).__name__}: {exc}"])
            results.append(result)
            if on_result:
                on_result(result)
    return results


def summarize(results: Sequence[Result]) -> dict[str, Any]:
    counts = Counter(result.outcome for result in results)
    total = len(results)
    return {
        "total": total,
        "accuracy": round(counts["correct"] / total, 3) if total else 0.0,
        **{outcome.replace(" ", "_"): counts[outcome] for outcome in OUTCOMES},
        "seconds": round(sum(result.seconds for result in results), 1),
        "tokens": sum(result.tokens for result in results),
    }


def _line(result: Result, case: Case, runs: int) -> str:
    name = result.case if runs == 1 else f"{result.case} #{result.run}"
    expect = "cause" if case.has_cause else "inconclusive"
    return (
        f"{name:<32} {expect:<13} {result.outcome:<18} {result.confidence or '-':<7}"
        f"{result.seconds:>6.0f}s {result.tokens:>7} tok"
    )


def _print_summary(results: Sequence[Result]) -> dict[str, Any]:
    stats = summarize(results)
    failed = [result for result in results if result.outcome != "correct"]
    if failed:
        print("\nNot correct:")
        for result in failed:
            print(f"  {result.case} #{result.run}: {result.outcome}")
            for problem in result.problems:
                print(f"    - {problem}")
            if result.summary:
                print(f"    it said: {result.summary}")
    print(
        f"\naccuracy {stats['correct']}/{stats['total']} ({stats['accuracy']:.0%})"
        f"   confidently wrong {stats['confidently_wrong']}   wrong {stats['wrong']}"
        f"   abstained {stats['abstained']}   errors {stats['error']}"
    )
    print(f"{stats['seconds']:.0f}s, {stats['tokens']} tokens")
    return stats


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make eval", description=__doc__.splitlines()[0])
    parser.add_argument("--case", action="append", help="run only this case (repeatable)")
    parser.add_argument("--runs", type=int, default=1, help="times to run each case (default 1)")
    parser.add_argument("--json", type=Path, help="also write the results to this file")
    parser.add_argument("--min-accuracy", type=float, help="exit 1 below this share, e.g. 0.8")
    parser.add_argument("--list", action="store_true", help="list the cases and exit")
    args = parser.parse_args(argv)

    if args.list:
        for case in CASES:
            expect = "cause" if case.has_cause else "inconclusive"
            print(f"{case.id:<32} {expect:<13} {case.scenario.description}")
        return 0
    unknown = [name for name in args.case or [] if name not in CASES_BY_ID]
    if unknown:
        print(f"unknown case: {', '.join(unknown)} (see --list)")
        return 2
    cases = [CASES_BY_ID[name] for name in args.case] if args.case else list(CASES)

    settings = get_settings()
    if settings.ai_simulated:
        print("The model is simulated (OPSCEND_AI_SIMULATED): there is nothing to measure.")
        return 2
    if settings.ai_missing:
        print(f"No model is configured. {settings.ai_missing}.")
        return 2
    kind = "self-hosted" if settings.ai_self_hosted else "hosted"
    print(f"model  {settings.ai_model} ({settings.ai_provider}, {kind})")
    print(f"cases  {len(cases)} x {args.runs} run(s)\n")
    print(f"{'case':<32} {'expected':<13} {'result':<18} {'conf':<7}{'time':>7} {'tokens':>11}")

    async with isolated_database():
        results = await run_eval(
            cases,
            build_llm(),
            runs=args.runs,
            on_result=lambda r: print(_line(r, CASES_BY_ID[r.case], args.runs), flush=True),
        )
    stats = _print_summary(results)

    if args.json:
        payload = {
            "model": settings.ai_model,
            "provider": settings.ai_provider,
            "summary": stats,
            "results": [asdict(result) for result in results],
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"results written to {args.json}")
    if args.min_accuracy is not None and stats["accuracy"] < args.min_accuracy:
        print(f"FAIL  accuracy is below {args.min_accuracy:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
