from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.security.policy import RateLimitMiddleware, RequestLimitMiddleware, SecurityHeadersMiddleware

configure_logging()
settings = get_settings()

app = FastAPI(title="Archway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.include_router(router)


@app.exception_handler(Exception)
async def safe_exception_handler(_request, exc: Exception):
    if settings.env == "development":
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(status_code=500, content={"detail": "Archway hit an internal error. Diagnostics were recorded."})

