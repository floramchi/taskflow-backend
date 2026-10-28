from fastapi import FastAPI

from app.api.routes import auth


def create_app() -> FastAPI:
    app = FastAPI(title="TaskFlow")
    app.include_router(auth.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
