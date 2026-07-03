#!/usr/bin/env python3
"""CLI：启动 Web 服务或命令行批量生成。"""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.pipeline.gemini_client import gemini_configured  # noqa: E402
from src.db.database import init_db  # noqa: E402
from src.pipeline.orchestrator import WorkflowOrchestrator  # noqa: E402

app = typer.Typer(help="BLUETTI 素材生产工作流")
console = Console()


@app.command()
def batch(
    product: str = typer.Option("Elite 300", help="产品名称"),
    direction: str = typer.Option("⑤功能解说型", help="内容方向"),
    count: int = typer.Option(3, min=1, max=20, help="一次生成脚本条数"),
    extra: str = typer.Option("", help="补充指令"),
    creator: str = typer.Option("", help="创建人"),
) -> None:
    """命令行创建批次（也可在网页「新建批次」操作）。"""
    settings = get_settings()
    ok = (
        (settings.llm_provider == "gemini" and gemini_configured(settings))
        or (settings.llm_provider == "openai" and settings.openai_api_key)
    )
    if not ok:
        console.print("[red]请先配置 GEMINI（含 Vertex 凭据）或 OPENAI_API_KEY[/red]")
        raise typer.Exit(1)

    init_db()

    async def _run() -> str:
        orch = WorkflowOrchestrator()
        return await orch.create_batch(
            product=product,
            direction=direction,
            count=count,
            extra_instruction=extra,
            creator=creator,
        )

    batch_id = asyncio.run(_run())
    table = Table(title="批次已创建")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("批次ID", batch_id)
    table.add_row("下一步", "打开 http://127.0.0.1:8787 在网页审核")
    console.print(table)


@app.command()
def serve(
    host: str = typer.Option(None, help="监听地址"),
    port: int = typer.Option(None, help="端口"),
) -> None:
    """启动 Web 服务（前端 + API 一体）。"""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.app:app",
        host=host or settings.webhook_host,
        port=port or settings.webhook_port,
        reload=False,
    )


if __name__ == "__main__":
    app()
