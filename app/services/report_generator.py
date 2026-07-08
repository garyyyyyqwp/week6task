"""Report Generator — 分章节 SSE 流式研报生成。

Pipeline:
  1. LLM generates outline (section titles)
  2. For each section: LLM generates content with streaming
  3. Collect citations from agent tools
  4. Yield SSE events: outline → section_start → section_chunk → section_end → references → done
"""

import json
import logging
from typing import AsyncIterator

from app.services.llm import get_client, get_model
from app.services.citation_manager import CitationManager

logger = logging.getLogger(__name__)

OUTLINE_PROMPT = """你是一个研究报告撰写专家。用户指定了一个研究主题，请为这个主题设计一个章节大纲。

要求:
1. 输出 JSON 格式的章节列表，每个章节包含 title（标题）和 description（简短描述这节要写什么）
2. 章节数: {num_sections} 个
3. 语言: {language}
4. 章节标题要具体、有层次、适合研究报告

只返回 JSON 数组，不要任何其他文字:
[
  {{"title": "第一章标题", "description": "本节要点"}},
  ...
]"""

SECTION_PROMPT = """你是一个研究报告撰写专家。你正在撰写一份关于「{topic}」的研究报告。

## 报告大纲
{outline_summary}

## 当前任务
撰写以下章节: **{section_title}**

## 写作要求
1. 使用学术化、严谨的语言（语言: {language}）
2. 内容要充实，包含具体数据、案例或引用
3. 使用 Markdown 格式，适当使用 **粗体**、列表、表格等
4. 引用来源时使用方括号编号 [1]、[2] 等
5. 字数: 300-800 字
6. 直接写正文，不要重复章节标题

## 可用引用来源
{references}

现在开始撰写「{section_title}」的正文："""


async def generate_outline(
    topic: str,
    num_sections: int = 5,
    language: str = "zh-CN",
) -> list[dict]:
    """Generate a chapter outline for the report.

    Args:
        topic: Research topic.
        num_sections: Number of sections to generate.
        language: Report language.

    Returns:
        List of {title, description} dicts.
    """
    client = get_client()
    model = get_model()

    prompt = OUTLINE_PROMPT.format(
        num_sections=num_sections,
        language=language,
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的报告大纲设计助手。只输出 JSON。"},
                {"role": "user", "content": f"研究主题: {topic}\n\n{prompt}"},
            ],
            temperature=0.5,
            stream=False,
        )

        content = response.choices[0].message.content or "[]"

        # Extract JSON from response (handle markdown code fences)
        import re
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        sections = json.loads(content)
        if not isinstance(sections, list):
            logger.warning("Outline parse failed, using default structure")
            return _default_outline(topic, num_sections)

        return sections

    except Exception as e:
        logger.error("Outline generation failed: %s", e)
        return _default_outline(topic, num_sections)


def _default_outline(topic: str, num_sections: int) -> list[dict]:
    """Fallback outline structure."""
    defaults = [
        {"title": "引言与研究背景", "description": "介绍研究主题的背景和意义"},
        {"title": "核心概念与理论基础", "description": "梳理关键概念和理论框架"},
        {"title": "当前研究现状分析", "description": "综述最新研究成果和进展"},
        {"title": "关键问题与挑战", "description": "分析面临的主要问题和挑战"},
        {"title": "发展趋势与展望", "description": "展望未来研究方向和应用前景"},
    ]
    return defaults[:num_sections]


async def generate_report_stream(
    topic: str,
    num_sections: int = 5,
    include_references: bool = True,
    language: str = "zh-CN",
) -> AsyncIterator[dict]:
    """Generate a full research report with SSE streaming.

    SSE Events:
      outline → section_start → section_chunk (×N) → section_end
      → (next section_start...) → references → done

    Args:
        topic: Research topic.
        num_sections: Number of sections.
        include_references: Whether to include citation references.
        language: Report language.

    Yields:
        SSE event dicts.
    """
    client = get_client()
    model = get_model()

    # Step 1: Generate outline
    yield {
        "event": "status",
        "data": json.dumps({"status": "outline", "message": "正在生成报告大纲..."}, ensure_ascii=False),
    }

    outline = await generate_outline(topic, num_sections, language)

    yield {
        "event": "outline",
        "data": json.dumps({
            "topic": topic,
            "sections": outline,
            "count": len(outline),
        }, ensure_ascii=False),
    }

    # Build outline summary for section prompt
    outline_summary = "\n".join(
        f"{i+1}. **{s['title']}**: {s.get('description', '')}"
        for i, s in enumerate(outline)
    )

    # Step 2: Generate each section with streaming
    all_sections_content = []
    cm = CitationManager()

    # Mock references for demo (in production, these come from agent tool calls)
    references_text = "(本节暂无引用来源)" if not include_references else ""

    for i, section_info in enumerate(outline):
        section_title = section_info["title"]

        yield {
            "event": "section_start",
            "data": json.dumps({
                "index": i,
                "title": section_title,
                "total": len(outline),
            }, ensure_ascii=False),
        }

        # Build section prompt with accumulated context
        previous_sections = ""
        if all_sections_content:
            prev_summary = "\n".join(
                f"### {s['title']}\n{s['content'][:200]}..."
                for s in all_sections_content
            )
            previous_sections = f"\n## 已完成的章节\n{prev_summary}\n"

        prompt = SECTION_PROMPT.format(
            topic=topic,
            outline_summary=outline_summary + previous_sections,
            section_title=section_title,
            language=language,
            references=references_text,
        )

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个专业的学术研究报告撰写助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                stream=True,
            )

            collected = ""
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    collected += delta.content
                    yield {
                        "event": "section_chunk",
                        "data": json.dumps({
                            "index": i,
                            "chunk": delta.content,
                        }, ensure_ascii=False),
                    }

        except Exception as e:
            logger.error("Section generation failed: %s", e)
            collected = f"*(本节生成失败: {str(e)})*"
            yield {
                "event": "section_chunk",
                "data": json.dumps({
                    "index": i,
                    "chunk": collected,
                }, ensure_ascii=False),
            }

        all_sections_content.append({
            "title": section_title,
            "content": collected,
        })

        yield {
            "event": "section_end",
            "data": json.dumps({
                "index": i,
                "title": section_title,
                "content": collected,
                "citations": [],
            }, ensure_ascii=False),
        }

    # Step 3: Generate abstract
    yield {
        "event": "status",
        "data": json.dumps({"status": "abstract", "message": "正在生成摘要..."}, ensure_ascii=False),
    }

    abstract = await _generate_abstract(topic, outline, language)

    yield {
        "event": "abstract",
        "data": json.dumps({"abstract": abstract}, ensure_ascii=False),
    }

    # Step 4: Collect references
    if include_references and cm.count > 0:
        yield {
            "event": "references",
            "data": json.dumps({
                "references": cm.format_references(),
                "citations_json": cm.to_dict(),
            }, ensure_ascii=False),
        }

    # Step 5: Build final report
    from app.schemas.report import ResearchReport, ReportSection, Citation

    report = ResearchReport(
        title=topic,
        abstract=abstract,
        sections=[
            ReportSection(
                title=s["title"],
                content=s["content"],
                citations=[],
            )
            for s in all_sections_content
        ],
        references=[],
    )

    yield {
        "event": "report_complete",
        "data": json.dumps({
            "report": report.model_dump(),
            "markdown": report.to_markdown(),
        }, ensure_ascii=False),
    }

    yield {
        "event": "done",
        "data": json.dumps({
            "topic": topic,
            "sections_count": len(all_sections_content),
        }, ensure_ascii=False),
    }


async def _generate_abstract(
    topic: str,
    outline: list[dict],
    language: str = "zh-CN",
) -> str:
    """Generate an abstract for the report."""
    client = get_client()
    model = get_model()

    sections_str = "\n".join(f"- {s['title']}" for s in outline)

    prompt = f"""为以下研究报告写一段摘要（200-300字）:

研究主题: {topic}

报告结构:
{sections_str}

要求:
- 语言: {language}
- 概括报告的核心内容和结论
- 直接写摘要正文，不要标题
- 控制在200-300字"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的学术摘要撰写助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            stream=False,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("Abstract generation failed: %s", e)
        return f"本报告系统研究了「{topic}」相关领域的发展现状、关键问题与未来趋势。"
