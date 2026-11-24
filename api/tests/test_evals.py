"""The accuracy evaluation set: the scorer, the case data, and the harness end to end.

No model is called. The harness is driven by the scripted stand-in from the public demo,
which knows the six demo failures and reports anything else as inconclusive.
"""

from typing import Any

import pytest

from app.demo.simulated import SimulatedLLM
from app.evals.cases import CASES, CASES_BY_ID
from app.evals.runner import run_eval, summarize
from app.evals.scoring import score

SHA = "bb083918c9be1579a96112ac2a5779ee95256c89"
ENV_CASE = CASES_BY_ID["bad-env-var"]
OUTAGE_CASE = CASES_BY_ID["registry-outage"]
NO_LOGS_CASE = CASES_BY_ID["no-runtime-logs"]


def report(**overrides: Any) -> dict[str, Any]:
    body = {
        "inconclusive": False,
        "likely_cause": "The commit renamed REDIS_URL to CACHE_URL, which is not set.",
        "confidence": "high",
        "summary": "storefront-api crashes at boot",
        "culprit_commit_sha": SHA,
        "evidence": [
            {
                "type": "log",
                "ref": "log_1",
                "quote": "Error: Missing required environment variable CACHE_URL",
            }
        ],
    }
    return {**body, **overrides}


def test_a_right_answer_is_correct():
    assert score(ENV_CASE, report(), SHA).outcome == "correct"


def test_a_wrong_cause_stated_with_confidence_is_confidently_wrong():
    verdict = score(ENV_CASE, report(likely_cause="Postgres ran out of connections."), SHA)
    assert verdict.outcome == "confidently wrong"
    assert verdict.problems == ["the cause does not mention CACHE_URL"]


def test_a_wrong_cause_at_low_confidence_is_only_wrong():
    verdict = score(ENV_CASE, report(likely_cause="Unclear.", confidence="low"), SHA)
    assert verdict.outcome == "wrong"


def test_the_culprit_commit_has_to_be_the_failing_one():
    assert "did not name the culprit commit" in (
        score(ENV_CASE, report(culprit_commit_sha=None), SHA).problems
    )
    assert "blamed a different commit" in (
        score(ENV_CASE, report(culprit_commit_sha="a" * 40), SHA).problems
    )


def test_the_cited_log_line_has_to_show_the_failure():
    cited = [{"type": "log", "ref": "log_9", "quote": "Starting Container"}]
    verdict = score(ENV_CASE, report(evidence=cited), SHA)
    assert verdict.problems == ["no cited log line shows the failure"]


def test_giving_up_when_the_cause_is_in_the_logs_is_abstaining():
    assert score(ENV_CASE, report(inconclusive=True, confidence="low"), SHA).outcome == "abstained"


def test_blaming_an_innocent_commit_is_wrong():
    answer = report(
        likely_cause="The npm registry answered 503 during install.",
        evidence=[{"type": "log", "ref": "log_2", "quote": "ERR_PNPM_FETCH_503"}],
    )
    assert score(OUTAGE_CASE, answer, SHA).problems == ["blamed a commit that did not cause it"]
    assert score(OUTAGE_CASE, {**answer, "culprit_commit_sha": None}, SHA).outcome == "correct"


def test_a_case_with_nothing_to_go_on_expects_inconclusive():
    assert score(NO_LOGS_CASE, report(inconclusive=True, confidence="low"), SHA).passed
    assert score(NO_LOGS_CASE, report(), SHA).outcome == "confidently wrong"


def test_a_run_without_a_report_is_an_error():
    assert score(ENV_CASE, None, SHA).outcome == "error"


def test_case_ids_are_unique_and_expectations_are_complete():
    assert len(CASES_BY_ID) == len(CASES)
    for case in CASES:
        if case.has_cause:
            assert case.mentions and case.evidence, case.id
        else:
            assert case.culprit == "none", case.id


@pytest.mark.parametrize("case", [c for c in CASES if c.evidence], ids=lambda c: c.id)
def test_the_expected_evidence_is_in_the_logs_of_the_case(case):
    """An expectation nothing can meet would count every answer as wrong."""
    logs = [
        message.lower()
        for _, _, message in (*case.scenario.build_logs, *case.scenario.runtime_logs)
    ]
    assert any(fragment.lower() in line for fragment in case.evidence for line in logs)


async def test_the_harness_scores_real_runs_through_the_pipeline(database):
    cases = [
        ENV_CASE,
        CASES_BY_ID["seeded-stripe-secret"],
        CASES_BY_ID["syntax-error"],
        OUTAGE_CASE,
        NO_LOGS_CASE,
    ]
    results = await run_eval(cases, SimulatedLLM(delay=0))

    outcomes = {result.case: result.outcome for result in results}
    assert outcomes == {
        "bad-env-var": "correct",
        "seeded-stripe-secret": "correct",
        "syntax-error": "correct",
        "registry-outage": "abstained",  # the stand-in does not know this failure
        "no-runtime-logs": "correct",
    }
    assert all(result.tool_calls >= 3 for result in results)
    stats = summarize(results)
    assert (stats["total"], stats["correct"], stats["abstained"]) == (5, 4, 1)
    assert stats["accuracy"] == 0.8


async def test_a_case_that_crashes_does_not_stop_the_run(database):
    class Broken:
        model = "broken"

        async def complete(self, messages, tools, tool_choice):
            raise RuntimeError("boom")

    results = await run_eval([ENV_CASE, NO_LOGS_CASE], Broken())

    assert [result.outcome for result in results] == ["error", "error"]
    assert results[0].problems == ["internal error: RuntimeError"]
