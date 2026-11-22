"""Report feedback, and the "what changed since the last good deploy" comparison."""

from datetime import timedelta

import respx
from sqlalchemy import select

from app import schemas
from app.core.db import session_scope
from app.core.time import utcnow
from app.models import Commit, CommitDiff, Investigation
from app.services.changes import NO_BASELINE, SAME_COMMIT, get_changes
from tests.conftest import drain_jobs, make_deployment, make_service
from tests.test_api import ai_client  # noqa: F401  (fixture)

GOOD = "a" * 40
BAD = "b" * 40

# ───────────────────────────── feedback


async def test_a_finished_report_can_be_rated_changed_and_cleared(ai_client):  # noqa: F811
    client = ai_client
    [failed] = (
        await client.get("/api/deployments", params={"status": "failed", "provider": "railway"})
    ).json()
    started = (await client.post(f"/api/deployments/{failed['id']}/investigate")).json()
    url = f"/api/investigations/{started['id']}/feedback"

    # Not while it is still running.
    assert (await client.put(url, json={"rating": "up"})).status_code == 409
    await drain_jobs()
    assert (await client.get(f"/api/investigations/{started['id']}")).json()["feedback"] is None

    rated = await client.put(url, json={"rating": "down", "note": "  wrong commit  "})
    assert rated.status_code == 200, rated.text
    feedback = schemas.Investigation.model_validate(rated.json()).feedback
    assert (feedback.rating, feedback.note) == ("down", "wrong commit")

    stats = schemas.InvestigationStats.model_validate(
        (await client.get("/api/investigations/stats")).json()
    )
    assert (stats.rated, stats.helpful, stats.not_helpful) == (1, 0, 1)
    assert stats.completed >= 1

    changed = (await client.put(url, json={"rating": "up"})).json()["feedback"]
    assert (changed["rating"], changed["note"]) == ("up", None)

    assert (await client.put(url, json={"rating": None})).json()["feedback"] is None
    assert (await client.get("/api/investigations/stats")).json()["rated"] == 0

    assert (await client.put(url, json={"rating": "meh"})).status_code == 422
    assert (await client.put(url, json={"rating": "up", "note": "x" * 501})).status_code == 422
    missing = await client.put("/api/investigations/nope/feedback", json={"rating": "up"})
    assert missing.status_code == 404


async def test_feedback_requires_sign_in(anon_client):
    response = await anon_client.put("/api/investigations/x/feedback", json={"rating": "up"})
    assert response.status_code == 401


# ───────────────────────────── what changed


async def test_no_earlier_good_deploy_means_nothing_to_compare(database):
    async with session_scope() as session:
        service = await make_service(session)
        failed = await make_deployment(session, service, status="failed", sha=BAD)
        changes = await get_changes(session, failed)
        assert changes.baseline is None and changes.source == "none"
        assert changes.note == NO_BASELINE


async def test_same_commit_points_away_from_the_code(database):
    async with session_scope() as session:
        service = await make_service(session)
        good = await make_deployment(session, service, status="ready", minutes_ago=60, sha=GOOD)
        await make_deployment(session, service, status="failed", minutes_ago=30, sha=BAD)
        failed = await make_deployment(session, service, status="failed", minutes_ago=5, sha=GOOD)
        changes = await get_changes(session, failed)
        assert changes.baseline.id == good.id
        assert changes.same_commit is True and changes.note == SAME_COMMIT
        assert changes.failed_between == 1
        assert changes.commits == [] and changes.compare_url is None
        assert changes.duration_delta_ms == 0


@respx.mock
async def test_github_compare_gives_the_exact_commits_and_files(database):
    route = respx.get(
        f"https://api.github.com/repos/acme/storefront/compare/{GOOD}...{BAD}"
    ).respond(
        json={
            "total_commits": 2,
            "commits": [
                {
                    "sha": "c" * 40,
                    "html_url": "https://github.com/acme/storefront/commit/ccc",
                    "commit": {
                        "message": "chore: bump deps",
                        "author": {"name": "Dana", "date": "2026-11-20T09:00:00Z"},
                    },
                },
                {
                    "sha": BAD,
                    "commit": {
                        "message": "refactor: read stripe secret from env",
                        "author": {"name": "Priya", "date": "2026-11-20T10:00:00Z"},
                    },
                },
            ],
            "files": [
                {"filename": "app/config.py", "status": "modified", "additions": 1, "deletions": 1},
                {"filename": "uv.lock", "status": "modified", "additions": 40, "deletions": 12},
            ],
        }
    )
    async with session_scope() as session:
        service = await make_service(session)
        await make_service(session, provider="github", name="repo", external_id="acme/storefront")
        await make_deployment(session, service, status="ready", minutes_ago=60, sha=GOOD)
        failed = await make_deployment(session, service, status="failed", minutes_ago=5, sha=BAD)
        changes = await get_changes(session, failed)

    assert route.called
    assert changes.source == "compare" and changes.note is None and not changes.truncated
    assert [c.sha for c in changes.commits] == [BAD, "c" * 40]  # newest first
    assert [(f.filename, f.additions) for f in changes.files] == [
        ("app/config.py", 1),
        ("uv.lock", 40),
    ]
    assert changes.compare_url == f"https://github.com/acme/storefront/compare/{GOOD}...{BAD}"


@respx.mock
async def test_without_a_readable_repo_stored_history_is_used(database):
    respx.get(f"https://api.github.com/repos/acme/storefront/compare/{GOOD}...{BAD}").respond(404)
    async with session_scope() as session:
        service = await make_service(session)
        await make_service(session, provider="github", name="repo", external_id="acme/storefront")
        await make_deployment(session, service, status="ready", minutes_ago=60, sha=GOOD)
        failed = await make_deployment(session, service, status="failed", minutes_ago=5, sha=BAD)
        now = utcnow()
        for sha, minutes, message in ((GOOD, 70, "old"), ("d" * 40, 20, "mid"), (BAD, 10, "bad")):
            session.add(
                Commit(
                    repo="acme/storefront",
                    sha=sha,
                    message=message,
                    author="Priya",
                    committed_at=now.replace(microsecond=0) - timedelta(minutes=minutes),
                )
            )
        files = [
            {"filename": "app/config.py", "status": "modified", "additions": 2, "deletions": 1}
        ]
        session.add(CommitDiff(repo="acme/storefront", sha=BAD, files=files))
        session.add(CommitDiff(repo="acme/storefront", sha="d" * 40, files=files))
        await session.commit()
        changes = await get_changes(session, failed)

    assert changes.source == "history"
    assert [c.message for c in changes.commits] == ["bad", "mid"]
    assert [(f.filename, f.additions, f.deletions) for f in changes.files] == [
        ("app/config.py", 4, 2)
    ]
    assert "unavailable" in changes.note


async def test_demo_failed_deploy_has_a_changes_view(demo_client):
    [failed] = (
        await demo_client.get(
            "/api/deployments", params={"status": "failed", "provider": "railway"}
        )
    ).json()
    response = await demo_client.get(f"/api/deployments/{failed['id']}/changes")
    assert response.status_code == 200, response.text
    changes = schemas.DeploymentChanges.model_validate(response.json())
    assert changes.baseline is not None and changes.baseline.status == "ready"
    assert changes.note is None  # demo data never asks GitHub, and says nothing about it
    async with session_scope() as session:
        assert await session.scalar(select(Investigation.id).limit(1)) is not None
