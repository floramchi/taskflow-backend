from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routes import auth, projects, tasks
from app.services.task_service import AssigneeNotFoundError


def create_app() -> FastAPI:
    app = FastAPI(title="TaskFlow")
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)

    @app.exception_handler(AssigneeNotFoundError)
    def assignee_not_found(request: Request, exc: AssigneeNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Assignee does not exist"},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
