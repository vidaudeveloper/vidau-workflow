"""下载两段视频并用 ffmpeg 拼接为 30s 成片。"""

import asyncio
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx

from src.config import ROOT

VIDEO_OUTPUT_DIR = ROOT / "data" / "uploads" / "videos"


def ensure_video_dir() -> None:
    VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def _download(client: httpx.AsyncClient, url: str, path: Path) -> None:
    resp = await client.get(url, follow_redirects=True)
    resp.raise_for_status()
    path.write_bytes(resp.content)


def _concat_with_ffmpeg(file_a: Path, file_b: Path, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法自动拼接视频。请安装 ffmpeg 或手动拼接两段成片。")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_path = Path(f.name)
        # concat demuxer 需要转义路径
        f.write(f"file '{file_a.as_posix()}'\n")
        f.write(f"file '{file_b.as_posix()}'\n")

    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-500:] or "ffmpeg 拼接失败")
    finally:
        list_path.unlink(missing_ok=True)


def raw_segment_path(video_id: str, segment: str) -> Path:
    if segment not in ("part_a", "part_b"):
        raise ValueError("segment 须为 part_a 或 part_b")
    return VIDEO_OUTPUT_DIR / f"{video_id}_{segment}.mp4"


async def download_remote_video(url: str, *, video_id: str = "", segment: str = "part_a") -> dict[str, str]:
    """下载单段远程视频到本地成片路径。"""
    ensure_video_dir()
    vid = video_id or uuid.uuid4().hex
    output = VIDEO_OUTPUT_DIR / f"{vid}.mp4"
    local_seg = raw_segment_path(vid, segment)

    async with httpx.AsyncClient(timeout=300) as client:
        await _download(client, url, output)
        shutil.copy2(output, local_seg)

    return {
        "video_url": f"/uploads/videos/{output.name}",
        "local_path": str(output),
        "part_a_local": f"/uploads/videos/{local_seg.name}",
        "part_b_local": "",
    }


async def concat_remote_videos(url_a: str, url_b: str, *, video_id: str = "") -> dict[str, str]:
    """下载两段远程视频，拼接后保存到本地，并保留无字幕原片副本。"""
    ensure_video_dir()
    vid = video_id or uuid.uuid4().hex
    output = VIDEO_OUTPUT_DIR / f"{vid}.mp4"
    local_a = raw_segment_path(vid, "part_a")
    local_b = raw_segment_path(vid, "part_b")

    async with httpx.AsyncClient(timeout=300) as client:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_a = tmp_path / "part_a.mp4"
            file_b = tmp_path / "part_b.mp4"
            await asyncio.gather(_download(client, url_a, file_a), _download(client, url_b, file_b))
            shutil.copy2(file_a, local_a)
            shutil.copy2(file_b, local_b)
            await asyncio.to_thread(_concat_with_ffmpeg, file_a, file_b, output)

    return {
        "video_url": f"/uploads/videos/{output.name}",
        "local_path": str(output),
        "part_a_local": f"/uploads/videos/{local_a.name}",
        "part_b_local": f"/uploads/videos/{local_b.name}",
    }
