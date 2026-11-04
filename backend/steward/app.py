import difflib
import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .domain import PlanRequest, StartRequest
from .providers import OSV, Gemini, GitHub, ProviderError, Registry
from .service import Steward
from .store import Conflict, FirestoreStore, SQLStore


def create_app(settings=None, service=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.require_ready()
        async with httpx.AsyncClient(timeout=35) as client:
            store = (
                FirestoreStore(settings.firestore_project, settings.firestore_collection)
                if settings.firestore_project
                else SQLStore(settings.database_url)
            )
            app.state.service = service or Steward(
                settings,
                store,
                GitHub(settings.github_token, settings.github_repo, client),
                Registry(client),
                OSV(client),
                Gemini(settings.gemini_api_key, settings.gemini_model, client),
            )
            yield

    app = FastAPI(title="Dependency Steward", lifespan=lifespan, docs_url=None, redoc_url=None)

    def operator(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not secrets.compare_digest(
            authorization, f"Bearer {settings.operator_token}"
        ):
            raise HTTPException(status_code=401, detail="Sign in with the operator token")

    def worker(x_worker_token: Annotated[str | None, Header()] = None):
        if settings.app_role == "worker" and os.environ.get("K_SERVICE"):
            # This deployment is private: Cloud Run's IAM proxy verifies the Scheduler OIDC token.
            return
        if not x_worker_token or not secrets.compare_digest(x_worker_token, settings.worker_token):
            raise HTTPException(status_code=401, detail="Worker authentication required")

    def get_service(request: Request):
        svc = request.app.state.service
        svc.github.requests = 0
        return svc

    Service = Annotated[Steward, Depends(get_service)]

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)[:600]})

    @app.exception_handler(Conflict)
    async def conflict(_, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def provider(_, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc)[:600]})

    @app.exception_handler(httpx.HTTPError)
    async def network_error(_, exc):
        return JSONResponse(
            status_code=502, content={"detail": "A provider request failed. Please retry shortly."}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/dashboard", dependencies=[Depends(operator)])
    def dashboard(svc: Service):
        return svc.dashboard()

    @app.post("/api/scan", dependencies=[Depends(operator)])
    async def scan(svc: Service):
        return await svc.scan()

    @app.post("/api/plans", dependencies=[Depends(operator)])
    async def plan(body: PlanRequest, svc: Service):
        return await svc.plan(body)

    @app.post("/api/jobs", dependencies=[Depends(operator)])
    async def start(body: StartRequest, svc: Service):
        return await svc.start(body)

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(operator)])
    def job(job_id: str, svc: Service):
        _, data = svc.store.get(f"job-{job_id}")
        if not data:
            raise HTTPException(404, "Unknown job")
        if data.get("result"):
            plan = data["plan"]
            originals = {
                "package.json": plan["manifest"],
                "package-lock.json": plan["lock"],
                **plan["sources"],
            }
            data["result"]["diffs"] = {
                path: "".join(
                    difflib.unified_diff(
                        originals.get(path, "").splitlines(keepends=True),
                        text.splitlines(keepends=True),
                        fromfile=f"a/{path}",
                        tofile=f"b/{path}",
                    )
                )
                for path, text in data["result"].get("changes", {}).items()
            }
        return data

    @app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(operator)])
    def cancel(job_id: str, svc: Service):
        return svc.cancel(job_id)

    class Action(BaseModel):
        days: int = Field(ge=0, le=30)

    @app.post("/api/candidates/{candidate_id}/action", dependencies=[Depends(operator)])
    def action(candidate_id: str, body: Action, svc: Service):
        return svc.action(candidate_id, body.days)

    @app.post("/internal/tick", dependencies=[Depends(worker)])
    async def tick(svc: Service):
        return await svc.tick()

    @app.middleware("http")
    async def security_headers(request, call_next):
        if settings.app_role == "web" and request.url.path.startswith("/internal/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        if settings.app_role == "worker" and not request.url.path.startswith(("/internal/", "/health")):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    if settings.app_role != "worker" and settings.frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(settings.frontend_dist / "index.html")

    return app


app = create_app()
