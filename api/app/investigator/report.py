"""The `submit_report` tool and the evidence check that keeps reports honest."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas import (
    CommitEvidence,
    Confidence,
    DeployEvidence,
    EvidenceRef,
    HealthEvidence,
    InvestigationReport,
    LogEvidence,
)

from .tools import EvidenceLedger

REPORT_TOOL_NAME = "submit_report"
MAX_QUOTE_CHARS = 300


class EvidenceDraft(BaseModel):
    type: Literal["log", "commit", "deploy", "health"]
    ref: str
    quote: str = ""


class ReportDraft(BaseModel):
    """What the model submits, before its evidence has been verified."""

    inconclusive: bool
    likely_cause: str = Field(min_length=1)
    confidence: Confidence
    summary: str = Field(min_length=1)
    culprit_commit_sha: str | None = None
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    suggested_fix: str | None = None
    missing: str | None = None

    @field_validator("culprit_commit_sha", "suggested_fix", "missing", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Models often send "" or "null" for an optional string; treat those as absent."""
        if isinstance(value, str) and value.strip().lower() in ("", "null", "none", "n/a"):
            return None
        return value


REPORT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REPORT_TOOL_NAME,
        "description": "Submit the final investigation report. This ends the investigation.",
        "parameters": {
            "type": "object",
            "properties": {
                "inconclusive": {
                    "type": "boolean",
                    "description": "true when the data does not support a cause",
                },
                "likely_cause": {"type": "string", "description": "2-4 sentences"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "summary": {"type": "string", "description": "One-line headline"},
                "culprit_commit_sha": {
                    "type": "string",
                    "description": "Full sha of the commit that caused it; omit if not identified",
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["log", "commit", "deploy", "health"],
                            },
                            "ref": {
                                "type": "string",
                                "description": "log: the log line id (log_...). commit: the sha. "
                                "deploy: the deployment_id. health: the service_id.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The exact text that supports the cause",
                            },
                        },
                        "required": ["type", "ref", "quote"],
                    },
                },
                "suggested_fix": {"type": "string", "description": "Concrete next step"},
                "missing": {
                    "type": "string",
                    "description": "Only when inconclusive: what data was missing",
                },
            },
            "required": ["inconclusive", "likely_cause", "confidence", "summary", "evidence"],
        },
    },
}


def _verify(item: EvidenceDraft, ledger: EvidenceLedger) -> EvidenceRef | None:
    ref, quote = item.ref.strip().strip("[]"), item.quote.strip()[:MAX_QUOTE_CHARS]
    if item.type == "log":
        if ref not in ledger.logs:
            return None
        deployment_id, text = ledger.logs[ref]
        # Quote the stored line itself, so a paraphrased or invented quote cannot slip through.
        return LogEvidence(ref=ref, deployment_id=deployment_id, quote=text[:MAX_QUOTE_CHARS])
    if item.type == "commit":
        sha = ledger.resolve_commit(ref)
        return CommitEvidence(ref=sha, quote=quote) if sha else None
    if item.type == "deploy":
        deployment_id = ledger.deploys.get(ref)
        return DeployEvidence(ref=deployment_id, quote=quote) if deployment_id else None
    return HealthEvidence(ref=ref, quote=quote) if ref in ledger.services else None


def finalize_report(
    draft: ReportDraft, ledger: EvidenceLedger
) -> tuple[InvestigationReport, list[str]]:
    """Check every evidence ref against what the tools really returned.

    Unverifiable refs are dropped. Losing evidence caps confidence at medium. A
    conclusion that cites no log line or health check is a reading of the diff, not
    of the failure, so it is capped at low; one left with no evidence at all is
    reported as inconclusive. Returns the report and notes about what was changed.
    """
    notes: list[str] = []
    evidence: list[EvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for item in draft.evidence:
        verified = _verify(item, ledger)
        if verified is None:
            dropped += 1
        elif (verified.type, verified.ref) not in seen:
            seen.add((verified.type, verified.ref))
            evidence.append(verified)

    confidence: Confidence = draft.confidence
    if dropped:
        notes.append(f"dropped {dropped} evidence ref(s) that no tool output contained")
        if confidence == "high":
            confidence = "medium"

    culprit = None
    if draft.culprit_commit_sha:
        culprit = ledger.resolve_commit(draft.culprit_commit_sha)
        if culprit is None:
            notes.append("removed a culprit commit that no tool output contained")

    missing = draft.missing
    inconclusive = draft.inconclusive
    if inconclusive:
        confidence = "low"
        missing = missing or "The available logs and diffs did not point to a single cause."
    elif not evidence:
        inconclusive, confidence, culprit = True, "low", None
        missing = missing or "No log line, commit or deploy that the tools returned backs this up."
        notes.append("no verifiable evidence: reported as inconclusive")
    elif not any(item.type in ("log", "health") for item in evidence):
        if confidence != "low":
            notes.append("no log or health evidence of the failure itself: confidence set to low")
        confidence = "low"

    report = InvestigationReport(
        inconclusive=inconclusive,
        likely_cause=draft.likely_cause.strip(),
        confidence=confidence,
        summary=draft.summary.strip(),
        culprit_commit_sha=culprit,
        evidence=evidence,
        suggested_fix=draft.suggested_fix,
        missing=missing,
    )
    return report, notes
