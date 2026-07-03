#!/usr/bin/env python3
"""初始化数据库、管理员与日常运维。"""

from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.auth.password import hash_password
from src.config import get_settings
from src.db.database import get_db_path, init_db
from src.db.repository import Repository

app = typer.Typer(help="BLUETTI 工作流 — 数据库与账号初始化")
console = Console()


@app.command("init-db")
def init_db_cmd() -> None:
    """创建/迁移 SQLite 数据库。"""
    init_db()
    path = get_db_path()
    console.print(f"[green]数据库已就绪[/green]：{path}")
    if path.is_file():
        console.print(f"大小：{path.stat().st_size / 1024 / 1024:.2f} MB")


@app.command("create-admin")
def create_admin(
    email: str = typer.Option("", "--email", help="管理员邮箱，默认读 .env ADMIN_EMAIL"),
    password: str = typer.Option("", "--password", help="密码，默认读 .env ADMIN_PASSWORD"),
    name: str = typer.Option("", "--name", help="显示名"),
) -> None:
    """创建首个管理员（系统登录账号）。"""
    init_db()
    settings = get_settings()
    repo = Repository()
    if repo.count_users() > 0:
        console.print("[yellow]已有用户，跳过。可用 add-user 添加更多。[/yellow]")
        raise typer.Exit(0)
    email = (email or settings.admin_email).strip().lower()
    password = password or settings.admin_password
    if not email or not password:
        console.print("[red]请提供 --email/--password 或在 .env 设置 ADMIN_EMAIL / ADMIN_PASSWORD[/red]")
        raise typer.Exit(1)
    uid = str(uuid.uuid4())
    repo.create_user(
        {
            "id": uid,
            "email": email,
            "password_hash": hash_password(password),
            "display_name": name or settings.admin_display_name or "管理员",
            "role": "admin",
            "is_active": 1,
        }
    )
    console.print(f"[green]管理员已创建[/green]：{email}")


@app.command("add-user")
def add_user(
    email: str = typer.Argument(...),
    password: str = typer.Argument(...),
    role: str = typer.Option("editor", help="admin | editor"),
    name: str = typer.Option("", help="显示名"),
) -> None:
    """添加系统登录用户。"""
    init_db()
    repo = Repository()
    if repo.get_user_by_email(email):
        console.print("[red]邮箱已存在[/red]")
        raise typer.Exit(1)
    if role not in ("admin", "editor"):
        console.print("[red]role 须为 admin 或 editor[/red]")
        raise typer.Exit(1)
    uid = str(uuid.uuid4())
    repo.create_user(
        {
            "id": uid,
            "email": email.strip().lower(),
            "password_hash": hash_password(password),
            "display_name": name or email.split("@")[0],
            "role": role,
            "is_active": 1,
        }
    )
    console.print(f"[green]用户已添加[/green]：{email} ({role})")


@app.command("create-test-user")
def create_test_user(
    password: str = typer.Option("testtest", help="测试账号密码"),
) -> None:
    """创建/重置隔离测试账号（登录名 test，数据与正式 editor 不互通）。"""
    from src.auth.test_account import TEST_ACCOUNT_EMAIL

    init_db()
    repo = Repository()
    email = TEST_ACCOUNT_EMAIL
    existing = repo.get_user_by_email(email)
    if existing:
        repo.update_user(
            existing["id"],
            {
                "password_hash": hash_password(password),
                "display_name": "测试账号",
                "role": "editor",
                "is_active": 1,
                "is_test": 1,
            },
        )
        console.print(f"[green]测试账号已重置[/green]：登录名 test / {email}，密码已更新")
    else:
        uid = str(uuid.uuid4())
        repo.create_user(
            {
                "id": uid,
                "email": email,
                "password_hash": hash_password(password),
                "display_name": "测试账号",
                "role": "editor",
                "is_active": 1,
                "is_test": 1,
            }
        )
        console.print(f"[green]测试账号已创建[/green]：登录名 test（或 {email}），密码 {password}")


@app.command("list-users")
def list_users_cmd() -> None:
    """列出系统登录用户。"""
    init_db()
    users = Repository().list_users()
    table = Table("邮箱", "显示名", "角色", "状态")
    for u in users:
        table.add_row(
            u.get("email", ""),
            u.get("display_name", ""),
            u.get("role", ""),
            "启用" if u.get("is_active") else "停用",
        )
    console.print(table)


@app.command("backup-db")
def backup_db(
    dest: str = typer.Option("", help="备份路径，默认 data/backups/workflow-时间戳.db"),
) -> None:
    """备份 SQLite 数据库。"""
    init_db()
    src = get_db_path()
    if not src.is_file():
        console.print("[red]数据库文件不存在[/red]")
        raise typer.Exit(1)
    if dest:
        out = Path(dest)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = ROOT / "data" / "backups" / f"workflow-{stamp}.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    console.print(f"[green]已备份[/green] → {out}")


@app.command("export-config")
def export_config_cmd(
    output: str = typer.Option(
        "",
        "-o",
        "--output",
        help="输出 JSON 路径，默认 data/exports/fixed-config-时间戳.json",
    ),
) -> None:
    """导出固定配置（产品、账号人设、内容方向），含产品图 base64。"""
    from src.config_sync import export_fixed_config_json

    init_db()
    if output:
        out = Path(output)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = ROOT / "data" / "exports" / f"fixed-config-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = export_fixed_config_json()
    out.write_text(text, encoding="utf-8")
    size_mb = out.stat().st_size / 1024 / 1024
    console.print(f"[green]已导出固定配置[/green] → {out}（{size_mb:.2f} MB）")


@app.command("import-config")
def import_config_cmd(
    path: str = typer.Argument(..., help="固定配置 JSON 文件路径"),
) -> None:
    """导入固定配置到当前环境（按名称/序号 upsert，不删除未包含项）。"""
    from src.config_sync import import_fixed_config_json

    init_db()
    src = Path(path)
    if not src.is_file():
        console.print(f"[red]文件不存在[/red]：{src}")
        raise typer.Exit(1)
    stats = import_fixed_config_json(src.read_text(encoding="utf-8"))
    console.print("[green]导入完成[/green]")
    for k, v in stats.items():
        console.print(f"  {k}: {v}")


@app.command("import-accounts-csv")
def import_accounts_csv_cmd(
    path: str = typer.Argument(..., help="账号人设 CSV 路径（Cindy Excel 导出格式）"),
) -> None:
    """导入/更新账号人设（按 No. 或 ID 合并）。"""
    from src.config_csv_import import import_accounts_csv

    init_db()
    src = Path(path)
    if not src.is_file():
        console.print(f"[red]文件不存在[/red]：{src}")
        raise typer.Exit(1)
    stats = import_accounts_csv(src.read_text(encoding="utf-8-sig"))
    console.print("[green]账号 CSV 导入完成[/green]")
    for k, v in stats.items():
        console.print(f"  {k}: {v}")


if __name__ == "__main__":
    app()
