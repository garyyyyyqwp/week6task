"""Report Schemas — Pydantic models for research reports.

Defines the structured document model:
  ResearchReport
    ├── title
    ├── abstract
    ├── sections[]
    │   ├── title
    │   ├── content (Markdown)
    │   └── citations (ref indices)
    ├── references[]
    └── generated_at
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """A single citation / reference entry."""
    index: int = Field(..., description="引用编号 [n]")
    url: str = Field(..., description="来源 URL")
    title: str = Field(..., description="文章/页面标题")
    snippet: str = Field(default="", description="摘要或摘要")
    source_type: str = Field(default="web", description="web, academic, official, code")
    site_name: str = Field(default="", description="来源站点名")


class ReportSection(BaseModel):
    """A single section in the report."""
    title: str = Field(..., description="章节标题")
    content: str = Field(default="", description="Markdown 格式正文")
    citations: list[int] = Field(default_factory=list, description="本节引用的引用编号")


class ResearchReport(BaseModel):
    """Complete structured research report."""
    title: str = Field(..., description="报告标题")
    abstract: str = Field(default="", description="摘要")
    sections: list[ReportSection] = Field(default_factory=list, description="章节列表")
    references: list[Citation] = Field(default_factory=list, description="参考文献列表")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="生成时间 (ISO 8601)",
    )

    def to_markdown(self) -> str:
        """Export the report as Markdown."""
        lines = [
            f"# {self.title}",
            "",
            f"> 生成时间: {self.generated_at}",
            "",
        ]

        if self.abstract:
            lines.append("## 摘要")
            lines.append("")
            lines.append(self.abstract)
            lines.append("")

        # Table of Contents
        if self.sections:
            lines.append("## 目录")
            lines.append("")
            for i, sec in enumerate(self.sections, 1):
                lines.append(f"{i}. [{sec.title}](#{self._anchor(sec.title)})")
            lines.append("")

        # Sections
        for sec in self.sections:
            lines.append(f"## {sec.title}")
            lines.append("")
            lines.append(sec.content)
            lines.append("")
            if sec.citations:
                refs = ", ".join(f"[{c}]" for c in sec.citations)
                lines.append(f"> 本节参考文献: {refs}")
                lines.append("")

        # References
        if self.references:
            lines.append("## 参考文献")
            lines.append("")
            for ref in self.references:
                lines.append(f"[{ref.index}] **{ref.title}**")
                lines.append(f"    {ref.url}")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _anchor(title: str) -> str:
        """Convert section title to markdown anchor."""
        return title.lower().replace(" ", "-").replace("：", "").replace(":", "")


# ---------------------------------------------------------------------------
# Report Generation Request
# ---------------------------------------------------------------------------

class ReportGenerateRequest(BaseModel):
    """Request to generate a research report."""
    topic: str = Field(..., min_length=1, max_length=500, description="研究主题")
    num_sections: int = Field(default=5, ge=2, le=10, description="期望章节数")
    include_references: bool = Field(default=True, description="是否包含参考文献")
    language: str = Field(default="zh-CN", description="报告语言")


class ReportGenerateResponse(BaseModel):
    """Response metadata for a generated report (for export reference)."""
    report_id: str = Field(default="", description="报告唯一 ID，用于导出端点")
    """Request to refine a selected text passage."""
    selected_text: str = Field(..., min_length=1, max_length=5000, description="用户选中的文字")
    context_before: str = Field(default="", max_length=2000, description="选区前文")
    context_after: str = Field(default="", max_length=2000, description="选区后文")
    instruction: str = Field(default="使这段文字更加严谨和学术化", description="优化指令")


class ReportRefineResponse(BaseModel):
    """Response from the refine endpoint."""
    refined_text: str = Field(..., description="优化后的文字")
    original_text: str = Field(default="", description="原始文字 (回显)")
    changes_summary: str = Field(default="", description="改动摘要")
