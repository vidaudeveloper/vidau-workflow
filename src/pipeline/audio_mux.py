"""ffmpeg 音轨混流 — TTS 后期替换 Seedance 自带口播。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("未找到 ffmpeg，无法混流音频")
    return path


def _run(cmd: list[str], *, err_label: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or err_label)[-900:])


def mp3_to_wav(mp3_path: Path, wav_path: Path, *, sample_rate: int = 44100) -> None:
    _run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(mp3_path),
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            str(wav_path),
        ],
        err_label="mp3 转 wav 失败",
    )


def trim_wav(wav_path: Path, out_path: Path, *, max_duration: float) -> None:
    _run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(wav_path),
            "-t",
            f"{max_duration:.3f}",
            "-acodec",
            "pcm_s16le",
            str(out_path),
        ],
        err_label="裁剪音频失败",
    )


def tempo_wav(wav_path: Path, out_path: Path, *, tempo: float) -> None:
    """变速不变调（atempo），用于把超长口播压进分镜时间窗。"""
    tempo = max(0.5, min(tempo, 2.0))
    _run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(wav_path),
            "-af",
            f"atempo={tempo:.4f}",
            "-acodec",
            "pcm_s16le",
            str(out_path),
        ],
        err_label="音频变速失败",
    )


def silence_wav(out_path: Path, *, duration: float, sample_rate: int = 44100) -> None:
    _run(
        [
            _ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            f"{duration:.3f}",
            "-acodec",
            "pcm_s16le",
            str(out_path),
        ],
        err_label="生成静音轨失败",
    )


def mix_delayed_segments(
    segments: list[tuple[float, Path]],
    *,
    total_duration: float,
    out_path: Path,
    sample_rate: int = 44100,
) -> None:
    """将多段 wav 按全局 start 延迟后叠加到静音底轨上。"""
    if not segments:
        silence_wav(out_path, duration=total_duration, sample_rate=sample_rate)
        return

    ffmpeg = _ffmpeg()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base.wav"
        silence_wav(base, duration=total_duration, sample_rate=sample_rate)

        inputs: list[str] = ["-i", str(base)]
        for _, wav in segments:
            inputs.extend(["-i", str(wav)])

        filters: list[str] = []
        mix_labels = ["[0:a]"]
        for idx, (start, _) in enumerate(segments, start=1):
            delay_ms = max(0, int(start * 1000))
            tag = f"d{idx}"
            filters.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[{tag}]")
            mix_labels.append(f"[{tag}]")

        n_inputs = len(segments) + 1
        filters.append(
            "".join(mix_labels)
            + f"amix=inputs={n_inputs}:duration=first:dropout_transition=0:normalize=0[aout]"
        )

        _run(
            [ffmpeg, "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[aout]", str(out_path)],
            err_label="多段口播混流失败",
        )


def strip_video_audio(video_path: Path, output_path: Path) -> None:
    """仅保留画面，彻底去掉 Seedance 等原音轨。"""
    _run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-an",
            str(output_path),
        ],
        err_label="剥离原视频音轨失败",
    )


def _media_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 30.0
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float((proc.stdout or "30").strip())
    except ValueError:
        return 30.0


def extend_video_freeze_tail(
    video_path: Path, target_duration: float, output_path: Path
) -> None:
    """口播长于视频时，末帧定格延长画面。"""
    current = _media_duration(video_path)
    if current >= target_duration - 0.05:
        shutil.copy2(video_path, output_path)
        return
    extra = max(0.1, target_duration - current)
    _run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={extra:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_path),
        ],
        err_label="片尾定格延长失败",
    )


def mux_audio_onto_video(video_path: Path, audio_path: Path, output_path: Path) -> None:
    """保留原视频画面，仅挂载一条 TTS 音轨（重编码 AAC，避免多音轨残留）。"""
    _run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-shortest",
            str(output_path),
        ],
        err_label="视频音轨替换失败",
    )


def replace_video_audio(
    video_path: Path,
    audio_path: Path,
    *,
    extend_video: bool = True,
) -> tuple[Path, float]:
    """先剥离原音轨，再写入 TTS；口播更长时片尾定格延长。返回 (路径, 成片秒数)。"""
    from src.config import get_settings

    settings = get_settings()
    do_extend = extend_video and settings.tts_extend_video
    audio_dur = _media_duration(audio_path)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        silent_video = tmp / "video_noaudio.mp4"
        staged = tmp / "muxed.mp4"
        strip_video_audio(video_path, silent_video)

        visual = silent_video
        video_dur = _media_duration(silent_video)
        if do_extend and audio_dur > video_dur + 0.12:
            extended = tmp / "extended.mp4"
            extend_video_freeze_tail(silent_video, audio_dur + 0.12, extended)
            visual = extended

        mux_audio_onto_video(visual, audio_path, staged)
        staged.replace(video_path)

    return video_path, _media_duration(video_path)
