"""Week 6: 研报平台技术预研 — FastAPI 入口

五个核心模块 Demo：
  POST /api/v1/search/web       — 真实联网搜索 (Tavily)
  POST /api/v1/search/fetch     — 网页正文提取 (Jina Reader)
  POST /api/v1/search/site      — 定向站点抓取 (SiteRegistry)
  POST /api/v1/agent/chat       — ReAct Agent (并行 tool_calls + 引用追踪)
  POST /api/v1/report/generate  — 研报分章节 SSE 流式生成
  POST /api/v1/report/refine    — 划词优化
  GET  /api/v1/report/{id}/export — 文档导出
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.routers import search, agent, report

app = FastAPI(
    title="研报平台技术预研",
    description="Week 6 — 五个核心模块技术验证",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router, prefix="/api/v1/search")
app.include_router(agent.router, prefix="/api/v1/agent")
app.include_router(report.router, prefix="/api/v1/report")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    """Serve the demo frontend."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
