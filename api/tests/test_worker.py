"""The arq worker runs the periodic jobs on the same schedule as the inline queue."""

from app import worker
from app.core.config import get_settings


def test_intervals_map_onto_cron_fields():
    assert worker.every(30, at_second=0) == {"second": {0, 30}}
    assert worker.every(60, at_second=30) == {"minute": set(range(60)), "second": {30}}
    assert worker.every(300, at_second=10) == {"minute": set(range(0, 60, 5)), "second": {10}}
    assert worker.every(7200, at_second=0) == {"minute": {0}, "second": {0}}


def test_the_schedule_follows_the_settings(env):
    env.setenv("OPSCEND_POLL_INTERVAL_SECONDS", "120")
    env.setenv("OPSCEND_HEALTH_INTERVAL_SECONDS", "30")
    get_settings.cache_clear()
    jobs = {job.name.removeprefix("cron:"): job for job in worker.build_cron_jobs()}
    assert jobs["reconcile"].minute == set(range(0, 60, 2))
    assert jobs["health_checks"].second == {0, 30}
    assert "refresh_demo" not in jobs

    env.setenv("OPSCEND_PUBLIC_DEMO", "1")
    get_settings.cache_clear()
    jobs = {job.name.removeprefix("cron:"): job for job in worker.build_cron_jobs()}
    assert jobs["refresh_demo"].minute == set(range(0, 60, 5))
