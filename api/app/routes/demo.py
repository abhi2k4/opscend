"""Demo mode: scripted failures and reset."""

from fastapi import APIRouter, Depends, HTTPException

from app import schemas
from app.core.config import get_settings
from app.core.public_demo import paced
from app.demo.breaker import DemoUnavailable, break_demo
from app.demo.scenarios import SCENARIOS, SCENARIOS_BY_ID
from app.demo.seed import rebuild_demo

from .deps import SessionDep

router = APIRouter(prefix="/demo", tags=["demo"])


def _require_demo() -> None:
    if not get_settings().demo:
        raise HTTPException(409, "Demo mode is off. Set OPSCEND_DEMO=1 and restart the API.")


@router.get("/scenarios")
async def scenarios() -> list[schemas.DemoScenario]:
    return [schemas.DemoScenario.model_validate(scenario) for scenario in SCENARIOS]


@router.post("/break", dependencies=[Depends(paced("break", 4))])
async def break_something(
    body: schemas.DemoBreakRequest, session: SessionDep
) -> schemas.DemoBreakResult:
    _require_demo()
    scenario = SCENARIOS_BY_ID.get(body.scenario_id)
    if scenario is None:
        raise HTTPException(404, f"Unknown scenario '{body.scenario_id}'")
    try:
        deployment_id, incident_id = await break_demo(session, scenario)
    except DemoUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    return schemas.DemoBreakResult(deployment_id=deployment_id, incident_id=incident_id)


@router.post("/reset", dependencies=[Depends(paced("reset", 60, shared=True))])
async def reset(session: SessionDep) -> schemas.Ok:
    _require_demo()
    await rebuild_demo(session)
    return schemas.Ok()
