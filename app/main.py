import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from app.db import init_db, SessionLocal
from app.core.vector_store import vector_store
from app.core.evidence_monitor import check_evidence_expiry
from app.routers import regulations, evidence, obligations, review

scheduler = BackgroundScheduler()

def scheduled_expiry_check():
    db = SessionLocal()
    try:
        check_evidence_expiry(db)
    except Exception as e:
        print(f"[Scheduler] Expiry check error: {e}")
    finally:
        db.close()

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

    # Start automatic background scheduler if not running tests
    if os.getenv("TESTING") != "1":
        try:
            scheduler.add_job(scheduled_expiry_check, "interval", hours=24, id="evidence_expiry_check")
            scheduler.start()
            print("[Scheduler] Automatic 24h evidence expiry monitor started.")
        except Exception as e:
            print(f"[Scheduler] Warning: could not start scheduler: {e}")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)

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
