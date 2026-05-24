"""FastAPI 入口。

挂载 search / snapshot / log 三个 router，启动时建 ES + Mongo client。

启动命令：
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import INDEX_NAME, get_es, lifespan
from api.routers import auth, feedback, log, search, snapshot, suggest

app = FastAPI(
    title="ISR Search API",
    description="面向小说同人创作的角色背景垂直检索引擎",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(snapshot.router)
app.include_router(log.router)
app.include_router(auth.router)
app.include_router(feedback.router)
app.include_router(suggest.router)


@app.get("/health")
def health() -> dict[str, object]:
    es = get_es()
    try:
        ok = es.ping()
        count = es.count(index=INDEX_NAME).get("count", 0)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": ok, "index": INDEX_NAME, "doc_count": count}
