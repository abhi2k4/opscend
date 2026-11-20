"""The investigation loop.

model turn → tool calls → model turn → … → submit_report. Each model turn and each
tool call is one `investigation_step`, committed when it starts and again when it
ends, so the UI can poll the trace while it runs. The loop is bounded by a tool-call
cap and a token budget; once either is hit the model is forced to report.
"""

import json
import logging
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.time import utcnow
from app.models import Deployment, Incident, Investigation, InvestigationStep, Service
from app.notifications import service as notifications
from app.schemas import InvestigationReport

from .llm import LLMClient, LLMError, build_llm
from .prompts import SYSTEM_PROMPT, task_prompt
from .report import REPORT_TOOL, REPORT_TOOL_NAME, ReportDraft, finalize_report
from .tools import TOOL_SPECS, EvidenceLedger, InvestigatorTools

log = logging.getLogger(__name__)

MAX_TURNS = 14
SUMMARY_CHARS = 600
FORCE_REPORT = {"type": "function", "function": {"name": REPORT_TOOL_NAME}}


class InvestigationFailed(Exception):
    """The run could not produce a valid report."""


async def run_investigation(investigation_id: str, llm: LLMClient | None = None) -> None:
    """Job: run one queued investigation to completion (or to a recorded failure)."""
    async with session_scope() as session:
        investigation = await session.get(Investigation, investigation_id)
        if investigation is None or investigation.status != "queued":
            return
        investigation.status = "running"
        await session.commit()

        report: InvestigationReport | None = None
        error: str | None = None
        try:
            run = _Run(session, investigation, llm or build_llm())
            report = await run.execute()
        except (InvestigationFailed, LLMError) as exc:
            error = str(exc)
        except Exception as exc:
            log.exception("investigation %s crashed", investigation_id)
            error = f"internal error: {type(exc).__name__}"

        await session.rollback()
        await session.execute(
            update(InvestigationStep)
            .where(
                InvestigationStep.investigation_id == investigation_id,
                InvestigationStep.status == "running",
            )
            .values(status="error", output_summary="interrupted")
        )
        investigation = await session.get(Investigation, investigation_id)
        investigation.status = "completed" if report else "failed"
        investigation.report = report.model_dump(mode="json") if report else None
        investigation.error = error
        investigation.finished_at = utcnow()
        notifications.investigation_finished(session, investigation)
        await session.commit()


class _Run:
    def __init__(self, session: AsyncSession, investigation: Investigation, llm: LLMClient) -> None:
        self.session = session
        self.investigation = investigation
        self.llm = llm
        self.ledger = EvidenceLedger()
        self.tools = InvestigatorTools(session, self.ledger)
        self.settings = get_settings()
        self.next_index = len(investigation.steps)
        self.tool_calls = 0

    async def _start_step(self, type_: str, name: str, input_: dict[str, Any] | None):
        step = InvestigationStep(
            investigation_id=self.investigation.id,
            index=self.next_index,
            type=type_,
            name=name,
            input=input_,
        )
        self.next_index += 1
        self.session.add(step)
        await self.session.commit()
        return step, time.perf_counter()

    async def _finish_step(
        self,
        step: InvestigationStep,
        started: float,
        *,
        ok: bool,
        summary: str,
        tokens: int | None = None,
    ) -> None:
        step.status = "ok" if ok else "error"
        step.duration_ms = int((time.perf_counter() - started) * 1000)
        step.output_summary = summary[:SUMMARY_CHARS]
        step.tokens = tokens
        if tokens:
            self.investigation.tokens_used += tokens
        await self.session.commit()

    async def _context(self) -> list[dict[str, Any]]:
        inv = self.investigation
        incident = await self.session.get(Incident, inv.incident_id) if inv.incident_id else None
        deployment = (
            await self.session.get(Deployment, inv.deployment_id) if inv.deployment_id else None
        )
        service: Service | None = None
        if deployment is not None:
            service = deployment.service
            self.ledger.add_deployment(deployment)
        elif incident is not None:
            service = incident.service
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt(deployment, incident, service)},
        ]

    def _must_report(self, turn: int, nudged: bool) -> bool:
        return (
            nudged
            or turn == MAX_TURNS - 1
            or self.tool_calls >= self.settings.ai_max_tool_calls
            or self.investigation.tokens_used >= self.settings.ai_token_budget
        )

    async def execute(self) -> InvestigationReport:
        messages = await self._context()
        nudged = retried_llm = retried_report = False

        for turn in range(MAX_TURNS):
            forced = self._must_report(turn, nudged)
            step, started = await self._start_step(
                "llm", self.llm.model, {"turn": turn + 1, "forced_report": forced}
            )
            try:
                response = await self.llm.complete(
                    messages,
                    [REPORT_TOOL] if forced else [*TOOL_SPECS, REPORT_TOOL],
                    FORCE_REPORT if forced else "auto",
                )
            except LLMError as exc:
                await self._finish_step(step, started, ok=False, summary=str(exc))
                if exc.retryable and not retried_llm:
                    retried_llm = True
                    continue
                raise
            names = ", ".join(call.name for call in response.tool_calls)
            await self._finish_step(
                step,
                started,
                ok=True,
                summary=response.content or f"→ {names or 'no tool call'}",
                tokens=response.tokens,
            )
            messages.append(response.message)

            if not response.tool_calls:
                if forced:
                    raise InvestigationFailed("the model did not submit a report")
                nudged = True
                messages.append({"role": "user", "content": "Call submit_report now."})
                continue

            report_call = next(
                (call for call in response.tool_calls if call.name == REPORT_TOOL_NAME), None
            )
            if report_call is not None:
                report, problem = await self._report_step(report_call.arguments)
                if report is not None:
                    return report
                if retried_report:
                    raise InvestigationFailed(f"the model submitted an invalid report: {problem}")
                retried_report = nudged = True
            for call in response.tool_calls:
                if call is report_call:
                    content = f"Invalid report, fix it and call submit_report again: {problem}"
                elif report_call is not None:
                    content = "Skipped: a report was submitted in the same turn."
                elif self.tool_calls >= self.settings.ai_max_tool_calls:
                    content = "Tool budget exhausted. Call submit_report now."
                else:
                    content = await self._tool_step(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

        raise InvestigationFailed("the investigation ran out of turns")

    async def _tool_step(self, name: str, arguments: dict[str, Any]) -> str:
        self.tool_calls += 1
        step, started = await self._start_step("tool", name, arguments)
        output = await self.tools.call(name, arguments)
        await self._finish_step(
            step, started, ok=not output.startswith("error:"), summary=_summarize(output)
        )
        return output

    async def _report_step(
        self, arguments: dict[str, Any]
    ) -> tuple[InvestigationReport | None, str]:
        step, started = await self._start_step("report", REPORT_TOOL_NAME, arguments)
        try:
            draft = ReportDraft.model_validate(arguments)
        except ValidationError as exc:
            problem = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()[:5]
            )
            await self._finish_step(step, started, ok=False, summary=f"invalid report: {problem}")
            return None, problem
        report, notes = finalize_report(draft, self.ledger)
        verdict = "inconclusive" if report.inconclusive else f"{report.confidence} confidence"
        summary = f"{verdict}, {len(report.evidence)} verified evidence ref(s): {report.summary}"
        if notes:
            summary += f" [{'; '.join(notes)}]"
        await self._finish_step(step, started, ok=True, summary=summary)
        return report, ""


def _summarize(output: str) -> str:
    """A one-line digest of a tool result for the trace view (the model gets the full text)."""
    if output.startswith("["):
        try:
            return f"{len(json.loads(output))} deployment(s) in the last 2 hours"
        except ValueError:
            pass
    return " ".join(output.split())
