"""从参考视频提取产品关键帧，供 Seedance reference_image 使用。"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from src.uploads import PRODUCT_IMAGES_DIR, ensure_upload_dirs


def extract_product_frames(
    video_path: Path,
    *,
    count: int = 4,
    max_sec: float = 12.0,
) -> list[str]:
    """均匀截取前 max_sec 秒若干帧，返回 /uploads/products/... 路径列表。"""
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    if shutil.which("ffmpeg") is None:
        return []
    ensure_upload_dirs()
    out_paths: list[str] = []
    interval = max(0.5, max_sec / max(count, 1))
    for i in range(count):
        t = min(max_sec - 0.1, i * interval + 0.3)
        name = f"ref_{uuid.uuid4().hex[:10]}_{i}.jpg"
        dest = PRODUCT_IMAGES_DIR / name
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(t),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and dest.is_file():
            out_paths.append(f"/uploads/products/{name}")
    return out_paths
