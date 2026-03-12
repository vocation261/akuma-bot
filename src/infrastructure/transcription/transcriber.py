"""Audio transcription using Vosk."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

from infrastructure.runtime.text_utils import probe_audio_duration_seconds

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
    Transcribe audio file using Vosk.

    Args:
        audio_path: Path to audio file (MP3, M4A, WAV, etc.)
        output_dir: Directory to save transcription TXT
        model_size: Ignored (Vosk uses lightweight models)
        language: Language code (es, en, etc.)
        device: Ignored (Vosk runs on CPU)
        compute_type: Ignored (Vosk runs on CPU)
        timestamp_offset_sec: Timestamp offset for this part
        progress_callback: Optional callback(percent)

    Returns:
        Tuple of (success: bool, message: str, result: TranscriptionResult | None)
    """
    try:
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return False, "ffmpeg not found", None

        try:
            import vosk
        except ImportError:
            return False, "vosk not installed", None

        output_dir.mkdir(parents=True, exist_ok=True)

        # Convert to WAV if needed
        if audio_path.suffix.lower() not in [".wav"]:
            logger.info(f"Converting {audio_path.name} to WAV...")
            success, msg, wav_path = _convert_to_wav(audio_path, ffmpeg)
            if not success:
                return False, msg, None
            audio_for_transcription = wav_path
        else:
            audio_for_transcription = audio_path

        # Load Vosk model
        logger.info(f"Loading Vosk model: {language}")
        try:
            model = vosk.Model(lang=language)
        except Exception as e:
            return False, f"Model loading failed: {str(e)[:200]}", None

        if progress_callback:
            try:
                progress_callback(0)
            except Exception:
                pass

        # Open WAV file
        wf = wave.open(str(audio_for_transcription), "rb")
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() not in [8000, 16000, 32000, 48000]:
            wf.close()
            return False, "Audio must be WAV mono PCM 16kHz", None

        # Initialize recognizer
        recognizer = vosk.KaldiRecognizer(model, wf.getframerate())
        recognizer.SetWords(True)

        logger.info(f"Transcribing {audio_for_transcription.name}...")

        # Format timestamp helper
        def format_timestamp(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"

        # Process audio in chunks and group by minute intervals
        minute_segments: dict[int, list[str]] = {}  # {minute_number: [words]}
        total_frames = wf.getnframes()
        processed_frames = 0
        last_reported_percent = -1
        frame_rate = wf.getframerate()

        def add_result_to_minutes(result_payload: dict[str, object]) -> None:
            words = result_payload.get("result")
            if not isinstance(words, list):
                text = str(result_payload.get("text") or "").strip()
                if not text:
                    return
                current_sec = timestamp_offset_sec + (processed_frames / frame_rate)
                minute_number = int(current_sec // 60)
                minute_segments.setdefault(minute_number, []).append(text)
                return

            for word_item in words:
                if not isinstance(word_item, dict):
                    continue
                token = str(word_item.get("word") or "").strip()
                if not token:
                    continue
                start_value = word_item.get("start", 0.0)
                try:
                    word_start = float(start_value)
                except (TypeError, ValueError):
                    word_start = 0.0
                absolute_sec = timestamp_offset_sec + word_start
                minute_number = int(absolute_sec // 60)
                minute_segments.setdefault(minute_number, []).append(token)
        
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break

            processed_frames += 4000

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                add_result_to_minutes(result)

            # Update progress
            if progress_callback and total_frames > 0:
                try:
                    percent = int(min(100, max(0, (processed_frames * 100) / total_frames)))
                    if percent > last_reported_percent:
                        last_reported_percent = percent
                        progress_callback(percent)
                except Exception:
                    pass

        # Get final result
        final_result = json.loads(recognizer.FinalResult())
        add_result_to_minutes(final_result)

        wf.close()

        # Get duration
        duration_sec = float(probe_audio_duration_seconds(audio_for_transcription))
        
        # Format output by minute ranges
        txt_filename = audio_path.stem + "_transcription.txt"
        txt_path = output_dir / txt_filename

        if minute_segments:
            minute_lines = []
            for minute_num in sorted(minute_segments.keys()):
                start_sec = minute_num * 60
                end_sec = (minute_num + 1) * 60
                
                start_ts = format_timestamp(start_sec)
                end_ts = format_timestamp(end_sec)
                
                minute_text = " ".join(minute_segments[minute_num])
                minute_lines.append(f"[{start_ts}-{end_ts}] {minute_text}")
            
            formatted_text = "\n\n".join(minute_lines)
        else:
            start_ts = format_timestamp(timestamp_offset_sec)
            end_ts = format_timestamp(timestamp_offset_sec + duration_sec)
            formatted_text = f"[{start_ts}-{end_ts}] (no speech detected)"
        
        txt_path.write_text(formatted_text, encoding="utf-8")

        logger.info(f"Transcription saved: {txt_path}")

        result = TranscriptionResult(
            txt_path=txt_path,
            full_text=formatted_text,
            duration_sec=duration_sec,
            line_count=len(minute_segments) if minute_segments else 1,
        )

        if progress_callback:
            try:
                progress_callback(100)
            except Exception:
                pass

        return True, f"Transcription complete: {duration_sec:.1f}s", result

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
    Transcribe a single audio file with an already-loaded Vosk model.

    Args:
        audio_path: Path to audio file
        timestamp_offset_sec: Timestamp offset for this part
        output_dir: Directory to save transcription TXT
        model: Already-loaded Vosk Model instance
        language: Language code (ignored, model already loaded)
        ffmpeg: Path to ffmpeg executable
        progress_callback: Optional callback(part_index, total_parts, percent)
        part_idx: Index of this part (for progress reporting)
        total_parts: Total number of parts (for progress reporting)

    Returns:
        Tuple of (success: bool, message: str, result: TranscriptionResult | None)
    """
    try:
        import vosk
        
        # Convert to WAV if needed
        if audio_path.suffix.lower() not in [".wav"]:
            logger.info(f"Converting {audio_path.name} to WAV (part {part_idx}/{total_parts})...")
            success, msg, wav_path = _convert_to_wav(audio_path, ffmpeg)
            if not success:
                return False, msg, None
            audio_for_transcription = wav_path
        else:
            audio_for_transcription = audio_path

        if progress_callback:
            try:
                progress_callback(part_idx, total_parts, 0)
            except Exception:
                pass

        # Open WAV file
        wf = wave.open(str(audio_for_transcription), "rb")
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() not in [8000, 16000, 32000, 48000]:
            wf.close()
            return False, "Audio must be WAV mono PCM", None

        # Initialize recognizer
        recognizer = vosk.KaldiRecognizer(model, wf.getframerate())
        recognizer.SetWords(False)

        logger.info(f"Transcribing {audio_for_transcription.name} (part {part_idx}/{total_parts})...")

        # Process audio in chunks
        full_text_parts = []
        total_frames = wf.getnframes()
        processed_frames = 0
        last_reported_percent = -1

        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break

            processed_frames += 4000

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    full_text_parts.append(text)

            # Update progress
            if progress_callback and total_frames > 0:
                try:
                    percent = int(min(100, max(0, (processed_frames * 100) / total_frames)))
                    if percent > last_reported_percent:
                        last_reported_percent = percent
                        progress_callback(part_idx, total_parts, percent)
                except Exception:
                    pass

        # Get final result
        final_result = json.loads(recognizer.FinalResult())
        final_text = final_result.get("text", "").strip()
        if final_text:
            full_text_parts.append(final_text)

        wf.close()

        # Combine all text
        full_text = " ".join(full_text_parts)

        # Get duration
        duration_sec = float(probe_audio_duration_seconds(audio_for_transcription))
        
        start_ts = _format_timestamp(timestamp_offset_sec)
        end_ts = _format_timestamp(timestamp_offset_sec + duration_sec)

        # Save to file
        txt_filename = audio_path.stem + "_transcription.txt"
        txt_path = output_dir / txt_filename

        formatted_text = f"[{start_ts} - {end_ts}] {full_text}" if full_text else f"[{start_ts} - {end_ts}]"
        txt_path.write_text(formatted_text, encoding="utf-8")

        logger.info(f"Transcription saved: {txt_path}")

        result = TranscriptionResult(
            txt_path=txt_path,
            full_text=formatted_text,
            duration_sec=duration_sec,
            line_count=1,
        )

        if progress_callback:
            try:
                progress_callback(part_idx, total_parts, 100)
            except Exception:
                pass

        return True, f"Transcription complete: {duration_sec:.1f}s", result

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
    Transcribe multiple audio files using a single Vosk model instance sequentially.

    Processes audio files one by one in order. Progress callback is invoked per-part completion.

    Args:
        audio_paths: List of (audio_path, timestamp_offset_sec) tuples
        output_dir: Directory to save transcription TXT files
        model_size: Ignored (Vosk uses lightweight models)
        language: Language code (es, en, etc.)
        device: Ignored (Vosk runs on CPU)
        compute_type: Ignored (Vosk runs on CPU)
        progress_callback: Optional callback(part_index, total_parts, percent)

    Returns:
        List of (success, message, result) tuples for each audio file in input order
    """
    try:
        ffmpeg = _which("ffmpeg")
        if not ffmpeg:
            return [(False, "ffmpeg not found", None) for _ in audio_paths]

        try:
            import vosk
        except ImportError:
            return [(False, "vosk not installed", None) for _ in audio_paths]

        output_dir.mkdir(parents=True, exist_ok=True)

        # Load model once (shared across all transcriptions)
        logger.info(f"Loading Vosk model: {language}")
        try:
            model = vosk.Model(lang=language)
        except Exception as e:
            error_msg = f"Model loading failed: {str(e)[:200]}"
            logger.exception(error_msg)
            return [(False, error_msg, None) for _ in audio_paths]

        total_parts = len(audio_paths)
        results: List[Tuple[bool, str, TranscriptionResult | None]] = []

        logger.info(f"Starting sequential transcription for {total_parts} part(s)")

        # Process each audio file sequentially
        for idx, (audio_path, timestamp_offset_sec) in enumerate(audio_paths, start=1):
            logger.info(f"Processing part {idx}/{total_parts}: {audio_path.name}")
            
            result = _transcribe_single_audio(
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
            
            results.append(result)
            
            success, message, _ = result
            if success:
                logger.info(f"Completed transcription for part {idx}/{total_parts}")
            else:
                logger.error(f"Failed transcription for part {idx}/{total_parts}: {message}")

        logger.info(f"Batch transcription complete: {total_parts} part(s)")
        return results

    except Exception as e:
        logger.exception(f"Batch transcription error: {e}")
        return [(False, f"Batch processing failed: {str(e)[:200]}", None) for _ in audio_paths]
