"""下载 faster-whisper 模型到本地（优先 ModelScope，国内网络可用）。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402
from src.pipeline.subtitle_align import _default_modelscope_paths, _resolve_model_path  # noqa: E402

MODELSCOPE_ID = "Systran/faster-whisper-base.en"


def download_via_modelscope() -> Path:
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError as exc:
        raise SystemExit("请先安装: pip install modelscope") from exc

    settings = get_settings()
    cache = ROOT / settings.subtitle_whisper_download_root / "ms"
    cache.mkdir(parents=True, exist_ok=True)
    print(f"从 ModelScope 下载: {MODELSCOPE_ID}")
    path = Path(snapshot_download(MODELSCOPE_ID, cache_dir=str(cache)))
    if not (path / "model.bin").is_file():
        raise SystemExit(f"下载不完整，缺少 model.bin: {path}")
    print(f"完成: {path}")
    return path


def link_to_base_en(source: Path) -> Path:
    dest = ROOT / get_settings().subtitle_whisper_download_root / "base.en"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        src = source / name
        if not src.is_file():
            continue
        target = dest / name
        if target.exists():
            target.unlink()
        try:
            target.symlink_to(src)
        except OSError:
            shutil.copy2(src, target)
    return dest


def main() -> None:
    settings = get_settings()
    existing = Path(_resolve_model_path())
    if existing.is_dir() and (existing / "model.bin").is_file():
        print(f"模型已存在: {existing}")
        print(f"大小: {(existing / 'model.bin').stat().st_size // (1024 * 1024)} MB")
    else:
        source = download_via_modelscope()
        link_to_base_en(source)
        existing = Path(_resolve_model_path())

    print("\n验证加载…")
    from faster_whisper import WhisperModel

    WhisperModel(
        str(existing),
        device=settings.subtitle_whisper_device,
        compute_type=settings.subtitle_whisper_compute_type,
    )
    print("模型已就绪。可在 .env 设置（可选）:")
    print(f"SUBTITLE_WHISPER_MODEL={existing.relative_to(ROOT).as_posix()}")
    print("然后对成片点「重烧字幕」即可口播对齐。")


if __name__ == "__main__":
    main()
