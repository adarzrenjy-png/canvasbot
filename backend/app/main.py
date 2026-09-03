import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from .api import router
from .config import settings
from .database import create_db_and_tables, engine
from .seed import seed_demo
from .services import recompute_schedule
from .canvas.worker import run_pending_job_once


async def job_loop() -> None:
    while True:
        with Session(engine) as session:
            run_pending_job_once(session, demo_mode=settings.demo_mode)
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    if settings.demo_mode:
        with Session(engine) as session:
            seed_demo(session)
            recompute_schedule(session, "demo startup")
    worker = asyncio.create_task(job_loop())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title=settings.app_name, version="0.2.0", description="Local-first academic planning API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")
