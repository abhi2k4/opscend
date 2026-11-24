"""Score one investigation report against the expected answer of its case.

No model judges the answer: every check is a string or id comparison, so the same
report always gets the same score.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from .cases import Case

Outcome = Literal["correct", "wrong", "confidently wrong", "abstained", "error"]

#: "abstained" is a cause that was there but not found; "confidently wrong" is a wrong
#: answer given with medium or high confidence, the outcome that costs a reader's trust.
OUTCOMES: tuple[Outcome, ...] = ("correct", "abstained", "wrong", "confidently wrong", "error")


@dataclass
class Score:
    outcome: Outcome
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome == "correct"


def score(case: Case, report: dict[str, Any] | None, commit_sha: str | None) -> Score:
    """`report` is the stored `InvestigationReport` (None when the run failed)."""
    if report is None:
        return Score("error", ["the run did not produce a report"])

    inconclusive = bool(report.get("inconclusive"))
    confident = report.get("confidence") in ("medium", "high")
    culprit = report.get("culprit_commit_sha")

    if not case.has_cause:
        if inconclusive:
            return Score("correct")
        problems = ["named a cause the data does not support (expected: inconclusive)"]
        return Score("confidently wrong" if confident else "wrong", problems)

    if inconclusive:
        return Score("abstained", ["reported inconclusive, but the logs show the cause"])

    problems = []
    stated = f"{report.get('summary', '')}\n{report.get('likely_cause', '')}".lower()
    for group in case.mentions:
        if not any(term.lower() in stated for term in group):
            problems.append("the cause does not mention " + " / ".join(group))

    if case.culprit == "commit" and culprit != commit_sha:
        problems.append(
            "blamed a different commit" if culprit else "did not name the culprit commit"
        )
    if case.culprit == "none" and culprit:
        problems.append("blamed a commit that did not cause it")

    if case.evidence:
        quotes = [
            str(item.get("quote", "")).lower()
            for item in report.get("evidence", [])
            if item.get("type") == "log"
        ]
        if not any(fragment.lower() in quote for fragment in case.evidence for quote in quotes):
            problems.append("no cited log line shows the failure")

    if not problems:
        return Score("correct")
    return Score("confidently wrong" if confident else "wrong", problems)
