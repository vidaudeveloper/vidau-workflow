"""生产看板素材下载 — 文件名与脚本导出。"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

from src.pipeline.subtitles import raw_video_path
from src.pipeline.video_concat import VIDEO_OUTPUT_DIR, raw_segment_path
from src.util.download_names import build_delivery_basename


def build_board_download_filenames(
    product: str,
    direction: str,
    account: str = "",
) -> dict[str, str]:
    base = build_delivery_basename(product, direction, account)
    return {
        "package": f"{base}-素材包.json",
        "script": f"{base}-脚本.json",
        "video": f"{base}-完整视频.mp4",
        "part_a": f"{base}-PartA-无字幕.mp4",
        "part_b": f"{base}-PartB-无字幕.mp4",
        "audio": f"{base}-口播.wav",
        "zip": f"{base}-素材包.zip",
    }


def _parse_segment_data(video: dict[str, Any] | None) -> dict[str, Any]:
    if not video:
        return {}
    raw = video.get("segment_urls_json") or ""
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_segment_urls(video: dict[str, Any] | None) -> dict[str, str]:
    data = _parse_segment_data(video)
    out: dict[str, str] = {}
    for key in ("part_a", "part_b"):
        url = str(data.get(key) or "").strip()
        if url:
            out[key] = url
    return out


def resolve_raw_segment_sources(video: dict[str, Any] | None) -> dict[str, Path | str]:
    """Part A/B 无字幕原片：本地副本 → 从拼接原片切分 → Seedance 远程 URL。"""
    data = _parse_segment_data(video)
    video_id = str((video or {}).get("id") or "").strip()
    out: dict[str, Path | str] = {}
    for key in ("part_a", "part_b"):
        local_url = str(data.get(f"{key}_local") or "").strip()
        if local_url:
            local_path = local_video_path_from_url(local_url)
            if local_path:
                out[key] = local_path
                continue
        if video_id:
            local_path = raw_segment_path(video_id, key)
            if local_path.is_file():
                out[key] = local_path
                continue
    missing = [
        key
        for key in ("part_a", "part_b")
        if not (isinstance(out.get(key), Path) and out[key].is_file())
    ]
    if video_id and missing:
        for key, path in _split_concat_raw_video(video_id).items():
            if key in missing:
                out[key] = path
                missing.remove(key)
    for key in missing:
        remote = str(data.get(key) or "").strip()
        if not remote:
            continue
        local_from_upload = local_video_path_from_url(remote)
        out[key] = local_from_upload if local_from_upload else remote
    return out


def _split_concat_raw_video(video_id: str) -> dict[str, Path]:
    """从本地无字幕 30s 拼接片切出 Part A/B（Seedance 链接过期时的后备）。"""
    src = raw_video_path(video_id)
    if not src.is_file():
        return {}
    out_a = raw_segment_path(video_id, "part_a")
    out_b = raw_segment_path(video_id, "part_b")
    if out_a.is_file() and out_b.is_file():
        return {"part_a": out_a, "part_b": out_b}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {}
    specs = ((0, 15, out_a), (15, 15, out_b))
    for start, duration, dest in specs:
        if dest.is_file():
            continue
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                str(start),
                "-i",
                str(src),
                "-t",
                str(duration),
                "-c",
                "copy",
                str(dest),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dest.is_file():
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    str(start),
                    "-i",
                    str(src),
                    "-t",
                    str(duration),
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    str(dest),
                ],
                capture_output=True,
                text=True,
            )
        if proc.returncode != 0 or not dest.is_file():
            dest.unlink(missing_ok=True)
            return {}
    return {"part_a": out_a, "part_b": out_b} if out_a.is_file() and out_b.is_file() else {}


def _segment_local_url(video_id: str, segment: str) -> str:
    return f"/uploads/videos/{video_id}_{segment}.mp4"


def persist_raw_segment_locals(video: dict[str, Any], repo: Any | None = None) -> bool:
    """将已存在的本地 Part A/B 路径写回 segment_urls_json。"""
    video_id = str(video.get("id") or "").strip()
    if not video_id:
        return False
    data = _parse_segment_data(video)
    changed = False
    for key in ("part_a", "part_b"):
        path = raw_segment_path(video_id, key)
        if not path.is_file():
            continue
        local_url = _segment_local_url(video_id, key)
        if data.get(f"{key}_local") != local_url:
            data[f"{key}_local"] = local_url
            changed = True
    if not changed:
        return False
    if repo is None:
        from src.db.repository import Repository

        repo = Repository()
    repo.update_video(
        video_id,
        {"segment_urls_json": json.dumps(data, ensure_ascii=False)},
    )
    return True


async def backfill_raw_segments_for_video(video: dict[str, Any]) -> dict[str, Any]:
    """为旧任务补救 Part A/B 无字幕原片：下载 Seedance 链接或从本地拼接原片切分。"""
    video_id = str(video.get("id") or "").strip()
    if not video_id:
        return {"video_id": "", "status": "skip", "detail": "无视频 ID"}

    data = _parse_segment_data(video)
    methods: dict[str, str] = {}

    for key in ("part_a", "part_b"):
        path = raw_segment_path(video_id, key)
        if path.is_file():
            methods[key] = "local"
            continue

        remote = str(data.get(key) or "").strip()
        if remote and not remote.startswith("/uploads/"):
            dest = raw_segment_path(video_id, key)
            async with httpx.AsyncClient(timeout=300) as client:
                if await _download_url(client, remote, dest):
                    methods[key] = "seedance"
                    continue
                dest.unlink(missing_ok=True)

    missing = [k for k in ("part_a", "part_b") if not raw_segment_path(video_id, k).is_file()]
    if missing:
        split = _split_concat_raw_video(video_id)
        for key in missing:
            if key in split:
                methods[key] = "split"

    still_missing = [k for k in ("part_a", "part_b") if not raw_segment_path(video_id, k).is_file()]
    if still_missing:
        return {
            "video_id": video_id,
            "status": "failed",
            "detail": f"缺少 {'/'.join(still_missing)}；无本地拼接原片且 Seedance 链接已过期",
            "methods": methods,
        }

    from src.db.repository import Repository

    repo = Repository()
    fresh = repo.get_video(video_id) or video
    persist_raw_segment_locals(fresh, repo)
    if all(m == "seedance" for m in methods.values()):
        detail = "已从 Seedance 原链接下载"
    elif any(m == "split" for m in methods.values()):
        detail = "已从本地无字幕拼接片切分（无烧录字幕，非 Seedance 原始文件）"
    elif methods:
        detail = "本地原片已就绪"
    else:
        detail = "原片副本已存在"
    return {"video_id": video_id, "status": "ok", "detail": detail, "methods": methods}


async def backfill_all_raw_segments(
    *,
    only_delivered: bool = True,
) -> dict[str, Any]:
    from src.db.repository import Repository

    repo = Repository()
    ok = failed = skipped = 0
    items: list[dict[str, Any]] = []
    for video in repo.list_videos():
        status = video.get("output_status") or ""
        if only_delivered and status not in ("待交付", "已交付", "剪辑中"):
            skipped += 1
            continue
        result = await backfill_raw_segments_for_video(video)
        items.append(result)
        if result["status"] == "ok":
            ok += 1
        elif result["status"] == "failed":
            failed += 1
        else:
            skipped += 1
    return {"ok": ok, "failed": failed, "skipped": skipped, "items": items}


def build_script_export(
    script: dict[str, Any],
    prompt: dict[str, Any] | None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    if prompt:
        try:
            spec = json.loads(prompt.get("product_spec_json") or "{}")
        except json.JSONDecodeError:
            spec = {}
    shots = script.get("shots") or []
    if isinstance(shots, str):
        try:
            shots = json.loads(shots)
        except json.JSONDecodeError:
            shots = []
    return {
        "script_id": script.get("id", ""),
        "product": script.get("product", ""),
        "direction": script.get("direction", ""),
        "theme": script.get("theme", ""),
        "hook": script.get("hook", ""),
        "outline": script.get("outline", ""),
        "cta": script.get("cta", ""),
        "suspense_hook": script.get("suspense_hook", ""),
        "language": script.get("language", ""),
        "difficulty_level": script.get("difficulty_level", ""),
        "shots": shots,
        "voiceover_part_a": spec.get("voiceover_part_a", []),
        "voiceover_part_b": spec.get("voiceover_part_b", []),
        "prompt_part_a": (prompt or {}).get("prompt_text", ""),
        "prompt_part_b": (prompt or {}).get("prompt_part_b", ""),
    }


def local_video_path_from_url(video_url: str) -> Path | None:
    if not video_url or not video_url.startswith("/uploads/videos/"):
        return None
    name = video_url.rsplit("/", 1)[-1]
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    path = VIDEO_OUTPUT_DIR / name
    return path if path.is_file() else None


def resolve_delivered_video_path(video: dict[str, Any] | None, video_url: str) -> Path | None:
    local = local_video_path_from_url(video_url)
    if local:
        return local
    video_id = str((video or {}).get("id") or "").strip()
    if not video_id:
        return None
    raw = raw_video_path(video_id)
    return raw if raw.is_file() else None


def extract_audio_wav(video_path: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法导出口播音频")
    if not video_path.is_file():
        raise FileNotFoundError(f"视频不存在: {video_path}")
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 64:
        tmp.unlink(missing_ok=True)
        raise RuntimeError((proc.stderr or "ffmpeg 提取音频失败")[-500:])
    return tmp


def build_board_package(
    script: dict[str, Any],
    prompt: dict[str, Any] | None,
    video: dict[str, Any] | None,
    account_name: str = "",
) -> dict[str, Any]:
    product = script.get("product", "")
    direction = script.get("direction", "")
    filenames = build_board_download_filenames(product, direction, account_name)
    segments = parse_segment_urls(video)
    raw_segments = resolve_raw_segment_sources(video)
    video_url = (video or {}).get("video_url") or ""
    delivered_local = resolve_delivered_video_path(video, video_url)
    return {
        "script": script,
        "prompt": prompt,
        "video": video,
        "account_name": account_name,
        "download_basename": build_delivery_basename(product, direction, account_name),
        "download_filenames": filenames,
        "script_export": build_script_export(script, prompt),
        "segments": segments,
        "raw_segments": {
            key: (str(value) if isinstance(value, Path) else value)
            for key, value in raw_segments.items()
        },
        "video_url": video_url,
        "has_local_video": delivered_local is not None,
    }


def _zip_json(zf: zipfile.ZipFile, arcname: str, data: Any) -> None:
    zf.writestr(
        arcname,
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
    )


async def _download_url(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        if len(resp.content) < 128:
            return False
        dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size >= 128
    except Exception:
        return False


async def _zip_video_source(
    zf: zipfile.ZipFile,
    client: httpx.AsyncClient,
    tmpdir: Path,
    source: Path | str | None,
    arcname: str,
    manifest: list[str],
    *,
    missing_label: str,
    fallback: Path | None = None,
) -> None:
    if isinstance(source, Path) and source.is_file():
        zf.write(source, arcname=arcname)
        manifest.append(f"✓ {arcname}")
        return
    if isinstance(source, str) and source.strip():
        if source.startswith("/"):
            local = local_video_path_from_url(source)
            if local:
                zf.write(local, arcname=arcname)
                manifest.append(f"✓ {arcname}")
                return
        remote = tmpdir / f"dl_{uuid.uuid4().hex}.mp4"
        if await _download_url(client, source, remote):
            zf.write(remote, arcname=arcname)
            manifest.append(f"✓ {arcname}")
            return
    if fallback and fallback.is_file():
        zf.write(fallback, arcname=arcname)
        manifest.append(f"✓ {arcname}（本地拼接原片切分）")
        return
    if isinstance(source, str) and source.strip():
        manifest.append(f"✗ {arcname}（下载失败）")
        return
    manifest.append(f"✗ {arcname}（{missing_label}）")


async def build_delivery_zip(package: dict[str, Any]) -> Path:
    """打包脚本、成片、无字幕分镜原片与口播音频为 ZIP，返回临时文件路径。"""
    video = package.get("video") or {}
    if video.get("id"):
        await backfill_raw_segments_for_video(video)
        package["raw_segments"] = {
            key: (str(value) if isinstance(value, Path) else value)
            for key, value in resolve_raw_segment_sources(video).items()
        }

    filenames = package["download_filenames"]
    raw_segments = package.get("raw_segments") or {}
    video = package.get("video") or {}
    video_url = package.get("video_url") or ""
    tmpdir = Path(tempfile.mkdtemp(prefix="board_zip_"))
    zip_path = Path(tempfile.mkstemp(suffix=".zip")[1])
    manifest: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                _zip_json(zf, filenames["package"], package)
                manifest.append(f"✓ {filenames['package']}")

                script_export = package.get("script_export")
                if script_export:
                    _zip_json(zf, filenames["script"], script_export)
                    manifest.append(f"✓ {filenames['script']}")
                else:
                    manifest.append(f"✗ {filenames['script']}（无脚本数据）")

                delivered_local = resolve_delivered_video_path(video, video_url)
                await _zip_video_source(
                    zf,
                    client,
                    tmpdir,
                    delivered_local or video_url,
                    filenames["video"],
                    manifest,
                    missing_label="暂无成片",
                )

                split_parts = _split_concat_raw_video(str(video.get("id") or ""))

                for key, label in (("part_a", "Part A"), ("part_b", "Part B")):
                    await _zip_video_source(
                        zf,
                        client,
                        tmpdir,
                        raw_segments.get(key),
                        filenames[key],
                        manifest,
                        missing_label=f"暂无{label}原片",
                        fallback=split_parts.get(key),
                    )

                audio_source = delivered_local
                if not audio_source and video_url:
                    audio_source = local_video_path_from_url(video_url)
                if audio_source:
                    try:
                        wav_tmp = extract_audio_wav(audio_source)
                        try:
                            zf.writestr(filenames["audio"], wav_tmp.read_bytes())
                            manifest.append(f"✓ {filenames['audio']}")
                        finally:
                            wav_tmp.unlink(missing_ok=True)
                    except Exception as exc:
                        manifest.append(f"✗ {filenames['audio']}（{exc}）")
                else:
                    manifest.append(f"✗ {filenames['audio']}（暂无成片）")

                zf.writestr("下载清单.txt", "\n".join(manifest).encode("utf-8"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not zip_path.is_file() or zip_path.stat().st_size < 64:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError("ZIP 打包失败")
    return zip_path
