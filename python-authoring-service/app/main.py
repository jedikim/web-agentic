from fastapi import FastAPI
from app.api import compile_intent, plan_patch, optimize_profile, profiles

app = FastAPI(title="Web-Agentic Authoring Service", version="0.1.0")

app.include_router(compile_intent.router, prefix="/compile-intent", tags=["compile"])
app.include_router(plan_patch.router, prefix="/plan-patch", tags=["patch"])
app.include_router(optimize_profile.router, prefix="/optimize-profile", tags=["optimize"])
app.include_router(profiles.router, prefix="/profiles", tags=["profiles"])


@app.get("/health")
async def health():
    return {"status": "ok"}
