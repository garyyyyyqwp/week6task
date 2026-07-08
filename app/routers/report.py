"""Report Router — SSE streaming report generation + refine + export."""

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from sse_starlette.sse import EventSourceResponse

from app.schemas.report import (
    ReportGenerateRequest,
    ReportRefineRequest,
    ReportRefineResponse,
)
from app.services.report_generator import generate_report_stream
from app.services.llm import get_client, get_model

logger = logging.getLogger(__name__)

router = APIRouter(tags=["report"])

# In-memory report store (in production, use DB)
_reports: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# POST /api/v1/report/generate — 分章节 SSE 流式生成研报
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_report(request: ReportGenerateRequest):
    """Generate a research report with section-by-section SSE streaming.

    SSE Events:
        status: Progress message
        outline: Full chapter outline
        section_start: Start of a section
        section_chunk: Token-by-token content streaming
        section_end: Complete section with full content
        abstract: Generated abstract
        references: Citation list
        report_complete: Full report JSON + Markdown
        done: Generation complete
    """
    async def event_generator():
        async for event in generate_report_stream(
            topic=request.topic,
            num_sections=request.num_sections,
            include_references=request.include_references,
            language=request.language,
        ):
            yield event

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# POST /api/v1/report/refine — 划词优化
# ---------------------------------------------------------------------------

@router.post("/refine", response_model=ReportRefineResponse)
async def refine_text(request: ReportRefineRequest):
    """Refine a selected text passage with LLM assistance.

    Receives the selected text along with surrounding context, applies the
    user's instruction (e.g., "make this more rigorous"), and returns the
    refined text for the frontend to replace.
    """
    client = get_client()
    model = get_model()

    prompt = f"""你是一个学术文字润色助手。用户选中了一段报告中的文字，请你按照要求优化。

## 上下文（供参考，不需要修改）
前文: {request.context_before or "(无)"}

后文: {request.context_after or "(无)"}

## 需要优化的文字
{request.selected_text}

## 用户要求
{request.instruction}

## 要求
1. 只返回优化后的文字内容
2. 不要添加任何解释、说明或前缀
3. 保持原意，只优化表达方式
4. 使用与上下文一致的风格和术语"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的学术文字润色助手。只返回润色后的文字，不加任何解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            stream=False,
        )

        refined = (response.choices[0].message.content or "").strip()

        # If LLM prepended explanation, strip it
        if refined.startswith("优化"):
            lines = refined.split("\n")
            # Find the first non-empty line that might be the start of content
            refined = "\n".join(lines[1:]).strip()
            if not refined:
                refined = lines[0]

        return ReportRefineResponse(
            refined_text=refined,
            original_text=request.selected_text,
            changes_summary=f"根据「{request.instruction}」进行了优化",
        )

    except Exception as e:
        logger.error("Refine error: %s", e)
        raise HTTPException(status_code=502, detail=f"润色服务暂时不可用: {str(e)}")


# ---------------------------------------------------------------------------
# GET /api/v1/report/{report_id}/export — 文档导出
# ---------------------------------------------------------------------------

@router.get("/{report_id}/export")
async def export_report(
    report_id: str,
    format: str = Query("md", description="Export format: md or pdf"),
):
    """Export a generated report as Markdown or PDF."""
    report_data = _reports.get(report_id)
    if not report_data:
        raise HTTPException(
            status_code=404,
            detail=f"报告不存在: {report_id}。请先生成报告。"
        )

    if format == "md":
        md_content = report_data.get("markdown", "")
        if not md_content:
            # Generate markdown from report JSON
            from app.schemas.report import ResearchReport
            report = ResearchReport(**report_data["report"])
            md_content = report.to_markdown()

        return Response(
            content=md_content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=report_{report_id}.md",
            },
        )

    elif format == "pdf":
        # Use weasyprint for PDF generation
        try:
            md_content = report_data.get("markdown", "")
            html = _md_to_html(md_content, report_data.get("report", {}).get("title", "Report"))

            from weasyprint import HTML
            import io

            pdf_bytes = io.BytesIO()
            HTML(string=html).write_pdf(pdf_bytes)
            pdf_bytes.seek(0)

            return Response(
                content=pdf_bytes.getvalue(),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=report_{report_id}.pdf",
                },
            )
        except Exception as e:
            logger.error("PDF export error: %s", e)
            raise HTTPException(
                status_code=500,
                detail=f"PDF导出失败: {str(e)}。请尝试 Markdown 格式导出。"
            )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的导出格式: {format}。支持: md, pdf"
        )


def _md_to_html(md_content: str, title: str = "Research Report") -> str:
    """Convert Markdown to styled HTML for PDF rendering."""
    import markdown

    html_body = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "codehilite"],
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  @page {{
    size: A4;
    margin: 2cm;
    @top-center {{
      content: "{title}";
      font-size: 10pt;
      color: #666;
    }}
  }}
  body {{
    font-family: "SimSun", "Noto Sans CJK SC", "Source Han Sans CN", serif;
    font-size: 12pt;
    line-height: 1.8;
    color: #222;
  }}
  h1 {{ font-size: 20pt; text-align: center; margin-bottom: 1em; }}
  h2 {{ font-size: 16pt; border-bottom: 2px solid #333; padding-bottom: 4px; margin-top: 1.5em; }}
  h3 {{ font-size: 14pt; margin-top: 1em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background-color: #f0f0f0; }}
  code {{ background: #f5f5f5; padding: 1px 4px; font-size: 10pt; }}
  pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; }}
  blockquote {{ border-left: 4px solid #ccc; padding-left: 1em; color: #555; }}
  img {{ max-width: 100%; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
