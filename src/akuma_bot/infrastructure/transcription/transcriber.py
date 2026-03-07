"""Audio transcription using faster-whisper."""

from __future__ import annotations

import concurrent.futures
import logging
import multiprocessing
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from akuma_bot.infrastructure.runtime.text_utils import probe_audio_duration_seconds

logger = logging.getLogger("akuma_bot")


@dataclass
class TranscriptionResult:
    txt_path: Path
    full_text: str
    duration_sec: float
    line_count: int


def _which(cmd: str) -> str | None:
    try:
        result = subprocess.run(
            ["where" if os.name == "nt" else "which", cmd],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().split("\n")[0]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def split_audio_max_1h(
    audio_path: Path,
    output_dir: Path,
    max_part_seconds: int = 3600,
    bitrate_kbps: int = 64,
) -> Tuple[bool, str, list[Path], float]:
    try:
        ffmpeg = _which("ffmpeg")
        ffprobe = _which("ffprobe")
        if not ffmpeg or not ffprobe:
            return False, "ffmpeg/ffprobe not found", [], 0.0

        output_dir.mkdir(parents=True, exist_ok=True)

        total_duration = float(probe_audio_duration_seconds(audio_path, ffprobe))
        if total_duration <= 0:
            return False, "Could not probe duration", [], 0.0

        pattern = output_dir / "part-%03d.mp3"
        cmd = [
            ffmpeg,
            "-i",
            str(audio_path),
            "-f",
            "segment",
            "-segment_time",
            str(max_part_seconds),
            "-reset_timestamps",
            "1",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{int(bitrate_kbps)}k",
            "-y",
            str(pattern),
        ]

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1200,
            check=True,
        )

        parts = sorted(output_dir.glob("part-*.mp3"))
        if not parts:
            return False, "No parts generated", [], float(total_duration)

        return True, f"{len(parts)} part(s)", parts, float(total_duration)
    except subprocess.TimeoutExpired:
        return False, "Timeout", [], 0.0
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or str(e))[:200], [], 0.0
    except Exception as e:
        return False, str(e)[:200], [], 0.0


def _convert_to_wav(
    audio_path: Path,
    ffmpeg: str,
    sample_rate: int = 16000,
) -> Tuple[bool, str, Path | None]:
    try:
        wav_path = audio_path.with_suffix(".wav")
        cmd = [
            ffmpeg,
            "-i",
            str(audio_path),
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-y",
            str(wav_path),
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        
        if not wav_path.exists():
            return False, "Conversion failed", None
        
        return True, wav_path.name, wav_path
    
    except subprocess.TimeoutExpired:
        return False, "Timeout", None
    except subprocess.CalledProcessError as e:
        return False, (e.stderr[:200] if e.stderr else str(e)), None
    except Exception as e:
        return False, str(e), None


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    model_size: str = "base",
    language: str = "es",
    device: str = "cpu",
    compute_type: str = "int8",
    timestamp_offset_sec: int = 0,
    progress_callback: Callable[[int], None] | None = None,
) -> Tuple[bool, str, TranscriptionResult | None]:
    """
    Transcribe audio file using faster-whisper.

    Args:
        audio_path: Path to audio file (MP3, M4A, WAV, etc.)
        output_dir: Directory to save transcription TXT
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code (es, en, etc.)
        device: Device to use (cpu, cuda)
        compute_type: Compute precision (int8, float16, float32)

    Returns:
        Tuple of (success: bool, message: str, result: TranscriptionResult | None)
    """
    try:
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return False, "ffmpeg not found", None

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return False, "faster-whisper not installed", None

        output_dir.mkdir(parents=True, exist_ok=True)

        if audio_path.suffix.lower() not in [".wav"]:
            logger.info(f"Converting {audio_path.name} to WAV...")
            success, msg, wav_path = _convert_to_wav(audio_path, ffmpeg)
            if not success:
                return False, msg, None
            audio_for_transcription = wav_path
        else:
            audio_for_transcription = audio_path

        logger.info(f"Loading Whisper model: {model_size} ({device}/{compute_type})")
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=max(1, multiprocessing.cpu_count() - 1),
        )

        logger.info(f"Transcribing {audio_for_transcription.name}...")
        segments, info = model.transcribe(
            str(audio_for_transcription),
            language=language,
            beam_size=1,
            vad_filter=True,
            word_timestamps=False,
        )

        lines: List[str] = []
        minute_segments: Dict[int, List[str]] = {}
        current_minute = -1
        minute_text: List[str] = []
        duration_for_progress = float(info.duration or 0.0)
        last_reported_percent = -1

        if progress_callback:
            try:
                progress_callback(0)
            except Exception:
                pass

        for segment in segments:
            start_min = int(segment.start // 60)

            if progress_callback and duration_for_progress > 0:
                try:
                    raw_percent = int(min(100, max(0, (float(segment.end) / duration_for_progress) * 100)))
                    if raw_percent > last_reported_percent:
                        last_reported_percent = raw_percent
                        progress_callback(raw_percent)
                except Exception:
                    pass
            
            if start_min != current_minute:
                if minute_text and current_minute >= 0:
                    minute_segments[current_minute] = minute_text
                    minute_text = []
                current_minute = start_min
            
            cleaned_text = segment.text.strip()
            cleaned_text = "".join(c if c.isprintable() or c in "\n\t" else "" for c in cleaned_text)
            cleaned_text = "".join(c for c in cleaned_text if ord(c) < 0x3000 or ord(c) > 0x9FFF)
            cleaned_text = " ".join(cleaned_text.split())
            if cleaned_text:
                minute_text.append(cleaned_text)

        if minute_text and current_minute >= 0:
            minute_segments[current_minute] = minute_text

        # Fill gaps left by VAD silence removal
        total_minutes = int(duration_for_progress // 60) + 1
        for min_idx in range(total_minutes):
            start_ts = _format_timestamp((min_idx * 60) + int(timestamp_offset_sec))
            end_ts = _format_timestamp(((min_idx + 1) * 60) + int(timestamp_offset_sec))
            
            if min_idx in minute_segments:
                content = " ".join(minute_segments[min_idx])
                lines.append(f"[{start_ts} - {end_ts}] {content}")
            else:
                lines.append(f"[{start_ts} - {end_ts}]")

        txt_filename = audio_path.stem + "_transcription.txt"
        txt_path = output_dir / txt_filename

        full_text = "\n\n".join(lines)
        txt_path.write_text(full_text, encoding="utf-8")

        logger.info(f"Transcription saved: {txt_path}")

        result = TranscriptionResult(
            txt_path=txt_path,
            full_text=full_text,
            duration_sec=info.duration,
            line_count=len(lines),
        )

        if progress_callback:
            try:
                progress_callback(100)
            except Exception:
                pass

        return True, f"Transcription complete: {len(lines)} segments, {info.duration:.1f}s", result

    except Exception as e:
        logger.exception(f"Transcription error: {e}")
        return False, f"Transcription failed: {str(e)[:200]}", None


def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _transcribe_single_audio(
    audio_path: Path,
    timestamp_offset_sec: int,
    output_dir: Path,
    model,
    language: str,
    ffmpeg: str,
    progress_callback: Callable[[int, int, int], None] | None = None,
    part_idx: int = 1,
    total_parts: int = 1,
) -> Tuple[bool, str, TranscriptionResult | None]:
    """
    Transcribe a single audio file with an already-loaded Whisper model.
    
    This is a helper function designed to run within a ThreadPoolExecutor.
    
    Args:
        audio_path: Path to audio file
        timestamp_offset_sec: Timestamp offset for this part
        output_dir: Directory to save transcription TXT
        model: Already-loaded WhisperModel instance
        language: Language code
        ffmpeg: Path to ffmpeg executable
        progress_callback: Optional callback(part_index, total_parts, percent)
        part_idx: Index of this part (for progress reporting)
        total_parts: Total number of parts (for progress reporting)
    
    Returns:
        Tuple of (success: bool, message: str, result: TranscriptionResult | None)
    """
    try:
        # Convert to WAV if needed
        if audio_path.suffix.lower() not in [".wav"]:
            logger.info(f"Converting {audio_path.name} to WAV...")
            success, msg, wav_path = _convert_to_wav(audio_path, ffmpeg)
            if not success:
                return False, msg, None
            audio_for_transcription = wav_path
        else:
            audio_for_transcription = audio_path

        logger.info(f"Transcribing {audio_for_transcription.name} (part {part_idx}/{total_parts})...")
        segments, info = model.transcribe(
            str(audio_for_transcription),
            language=language,
            beam_size=1,
            vad_filter=True,
            word_timestamps=False,
        )

        lines: List[str] = []
        minute_segments: Dict[int, List[str]] = {}
        current_minute = -1
        minute_text: List[str] = []
        duration_for_progress = float(info.duration or 0.0)
        last_reported_percent = -1

        if progress_callback:
            try:
                progress_callback(part_idx, total_parts, 0)
            except Exception:
                pass

        for segment in segments:
            start_min = int(segment.start // 60)

            if progress_callback and duration_for_progress > 0:
                try:
                    raw_percent = int(min(100, max(0, (float(segment.end) / duration_for_progress) * 100)))
                    if raw_percent > last_reported_percent:
                        last_reported_percent = raw_percent
                        progress_callback(part_idx, total_parts, raw_percent)
                except Exception:
                    pass
            
            if start_min != current_minute:
                if minute_text and current_minute >= 0:
                    minute_segments[current_minute] = minute_text
                    minute_text = []
                current_minute = start_min
            
            cleaned_text = segment.text.strip()
            cleaned_text = "".join(c if c.isprintable() or c in "\n\t" else "" for c in cleaned_text)
            cleaned_text = "".join(c for c in cleaned_text if ord(c) < 0x3000 or ord(c) > 0x9FFF)
            cleaned_text = " ".join(cleaned_text.split())
            if cleaned_text:
                minute_text.append(cleaned_text)

        if minute_text and current_minute >= 0:
            minute_segments[current_minute] = minute_text

        # Fill gaps left by VAD silence removal
        total_minutes = int(duration_for_progress // 60) + 1
        for min_idx in range(total_minutes):
            start_ts = _format_timestamp((min_idx * 60) + int(timestamp_offset_sec))
            end_ts = _format_timestamp(((min_idx + 1) * 60) + int(timestamp_offset_sec))
            
            if min_idx in minute_segments:
                content = " ".join(minute_segments[min_idx])
                lines.append(f"[{start_ts} - {end_ts}] {content}")
            else:
                lines.append(f"[{start_ts} - {end_ts}]")

        txt_filename = audio_path.stem + "_transcription.txt"
        txt_path = output_dir / txt_filename

        full_text = "\n\n".join(lines)
        txt_path.write_text(full_text, encoding="utf-8")

        logger.info(f"Transcription saved: {txt_path}")

        result = TranscriptionResult(
            txt_path=txt_path,
            full_text=full_text,
            duration_sec=info.duration,
            line_count=len(lines),
        )

        if progress_callback:
            try:
                progress_callback(part_idx, total_parts, 100)
            except Exception:
                pass

        return True, f"Transcription complete: {len(lines)} segments, {info.duration:.1f}s", result

    except Exception as e:
        logger.exception(f"Transcription error for {audio_path.name} (part {part_idx}/{total_parts}): {e}")
        return False, f"Transcription failed: {str(e)[:200]}", None


def transcribe_audio_batch(
    audio_paths: List[Tuple[Path, int]],
    output_dir: Path,
    model_size: str = "base",
    language: str = "es",
    device: str = "cpu",
    compute_type: str = "int8",
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> List[Tuple[bool, str, TranscriptionResult | None]]:
    """
    Transcribe multiple audio files using a single Whisper model instance with parallelism.

    Uses ThreadPoolExecutor to transcribe parts in parallel, maintaining chronological order
    of results based on input order. Progress callback is invoked per-part completion.

    Args:
        audio_paths: List of (audio_path, timestamp_offset_sec) tuples
        output_dir: Directory to save transcription TXT files
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code (es, en, etc.)
        device: Device to use (cpu, cuda)
        compute_type: Compute precision (int8, float16, float32)
        progress_callback: Optional callback(part_index, total_parts, percent)

    Returns:
        List of (success, message, result) tuples for each audio file in input order
    """
    try:
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return [(False, "ffmpeg not found", None) for _ in audio_paths]

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return [(False, "faster-whisper not installed", None) for _ in audio_paths]

        output_dir.mkdir(parents=True, exist_ok=True)

        # Load model once (shared across all threads)
        logger.info(f"Loading Whisper model: {model_size} ({device}/{compute_type}) with cpu_threads={max(1, multiprocessing.cpu_count() - 1)}")
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=max(1, multiprocessing.cpu_count() - 1),
        )

        total_parts = len(audio_paths)
        
        # Initialize results dict to maintain order (will be indexed by part_idx - 1)
        results: Dict[int, Tuple[bool, str, TranscriptionResult | None]] = {}
        
        # Determine optimal number of workers (limit to avoid threadpool saturation on CPU)
        # On CPU, we typically want fewer workers to avoid contention
        max_workers = max(1, min(total_parts, max(2, multiprocessing.cpu_count() // 2)))
        
        logger.info(f"Starting parallel transcription with {max_workers} workers for {total_parts} part(s)")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_idx: Dict[concurrent.futures.Future, int] = {}
            for idx, (audio_path, timestamp_offset_sec) in enumerate(audio_paths, start=1):
                future = executor.submit(
                    _transcribe_single_audio,
                    audio_path=audio_path,
                    timestamp_offset_sec=timestamp_offset_sec,
                    output_dir=output_dir,
                    model=model,
                    language=language,
                    ffmpeg=ffmpeg,
                    progress_callback=progress_callback,
                    part_idx=idx,
                    total_parts=total_parts,
                )
                future_to_idx[future] = idx
            
            # Collect results as they complete (but store them indexed by original position)
            completed_count = 0
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                    results[idx] = result
                    completed_count += 1
                    logger.info(f"Completed transcription for part {idx}/{total_parts} ({completed_count}/{total_parts})")
                except Exception as e:
                    logger.exception(f"Exception in parallel transcription for part {idx}: {e}")
                    results[idx] = (False, f"Transcription failed: {str(e)[:200]}", None)
        
        # Reconstruct results in original order
        ordered_results: List[Tuple[bool, str, TranscriptionResult | None]] = []
        for idx in range(1, total_parts + 1):
            if idx in results:
                ordered_results.append(results[idx])
            else:
                ordered_results.append((False, "Result missing (thread error)", None))
        
        logger.info(f"Batch transcription complete: {total_parts} part(s)")
        return ordered_results

    except Exception as e:
        logger.exception(f"Batch transcription error: {e}")
        return [(False, f"Model loading failed: {str(e)[:200]}", None) for _ in audio_paths]
