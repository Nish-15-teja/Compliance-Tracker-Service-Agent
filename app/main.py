from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import init_db, SessionLocal
from app.core.vector_store import vector_store
from app.routers import regulations, evidence, obligations, review

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Synchronize all uploaded evidence documents into vector store at startup
    db = SessionLocal()
    try:
        vector_store.sync_from_db(db)
    except Exception as e:
        print(f"[Startup] Vector store sync warning: {e}")
    finally:
        db.close()
    yield

app = FastAPI(
    title="Compliance Tracker — Service Agent",
    description="Autonomous regulatory compliance, change impact tracking, and human-in-the-loop remediation platform.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(regulations.router)
app.include_router(evidence.router)
app.include_router(obligations.router)
app.include_router(review.router)

@app.get("/")
def root():
    return {
        "service": "Compliance Tracker — Service Agent",
        "status": "online",
        "version": "1.0.0"
    }
