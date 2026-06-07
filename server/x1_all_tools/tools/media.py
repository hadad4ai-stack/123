from __future__ import annotations
from pathlib import Path
from typing import Any
import json, math, wave, contextlib
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, require_program, run_subprocess

def image_generate_prompt(description: str, style: str = "clean, detailed", aspect_ratio: str = "1:1", negative: str = "", runtime=None) -> dict[str, Any]:
    prompt = (
        f"Create an image with aspect ratio {aspect_ratio}. "
        f"Subject: {description}. Style: {style}. "
        "Use coherent lighting, clear composition, high detail, and avoid unreadable text."
    )
    if negative:
        prompt += f" Avoid: {negative}."
    return {"prompt": prompt}

def _pil():
    try:
        from PIL import Image
        return Image
    except ImportError as exc:
        raise RuntimeError("Image tools require Pillow: pip install pillow") from exc

def image_resize(path: str, output: str, width: int, height: int, keep_aspect: bool = True, runtime=None) -> dict[str, Any]:
    Image = _pil()
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    if keep_aspect:
        img.thumbnail((width, height))
    else:
        img = img.resize((width, height))
    img.save(out)
    return {"path": str(out), "size": img.size, "bytes": out.stat().st_size}

def image_crop(path: str, output: str, left: int, top: int, right: int, bottom: int, runtime=None) -> dict[str, Any]:
    Image = _pil()
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    cropped = img.crop((left, top, right, bottom))
    cropped.save(out)
    return {"path": str(out), "size": cropped.size, "bytes": out.stat().st_size}

def image_convert(path: str, output: str, format: str | None = None, runtime=None) -> dict[str, Any]:
    Image = _pil()
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    if img.mode in ("RGBA", "P") and (format or out.suffix.lower().lstrip(".")) in ("jpg", "jpeg"):
        img = img.convert("RGB")
    img.save(out, format=format)
    return {"path": str(out), "format": format or out.suffix.lstrip(".").upper(), "bytes": out.stat().st_size}

def image_metadata(path: str, runtime=None) -> dict[str, Any]:
    Image = _pil()
    src = safe_join(runtime.workspace, path)
    img = Image.open(src)
    return {"path": str(src), "format": img.format, "mode": img.mode, "size": img.size, "info": {k: str(v) for k, v in img.info.items()}}

def image_ocr(path: str, lang: str = "eng", runtime=None) -> dict[str, Any]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("image.ocr requires pytesseract and Pillow: pip install pytesseract pillow; also install Tesseract OCR binary") from exc
    src = safe_join(runtime.workspace, path)
    text = pytesseract.image_to_string(Image.open(src), lang=lang)
    return {"path": str(src), "lang": lang, "text": text}

def audio_transcribe(path: str, model: str = "base", runtime=None) -> dict[str, Any]:
    src = safe_join(runtime.workspace, path)
    # Try openai-whisper if installed.
    try:
        import whisper
    except ImportError:
        raise RuntimeError("audio.transcribe requires openai-whisper installed locally: pip install openai-whisper, plus ffmpeg. No cloud transcription is called.")
    m = whisper.load_model(model)
    result = m.transcribe(str(src))
    return {"path": str(src), "model": model, "text": result.get("text", ""), "segments": result.get("segments", [])}

def audio_convert(path: str, output: str, runtime=None) -> dict[str, Any]:
    require_program("ffmpeg")
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = run_subprocess(["ffmpeg", "-y", "-i", str(src), str(out)], runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 10, runtime.max_output_chars)
    res["path"] = str(out)
    res["bytes"] = out.stat().st_size if out.exists() else 0
    return res

def video_extract_audio(path: str, output: str = "audio.wav", runtime=None) -> dict[str, Any]:
    require_program("ffmpeg")
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = run_subprocess(["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(out)], runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 10, runtime.max_output_chars)
    res["path"] = str(out)
    res["bytes"] = out.stat().st_size if out.exists() else 0
    return res

def video_thumbnail(path: str, output: str = "thumbnail.jpg", at_seconds: float = 1.0, runtime=None) -> dict[str, Any]:
    require_program("ffmpeg")
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = run_subprocess(["ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(src), "-frames:v", "1", str(out)], runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 10, runtime.max_output_chars)
    res["path"] = str(out)
    res["bytes"] = out.stat().st_size if out.exists() else 0
    return res

TOOLS = [
    ToolSpec("image.generate_prompt", "Build an image-generation prompt.", object_schema({"description": {"type": "string"}, "style": {"type": "string", "default": "clean, detailed"}, "aspect_ratio": {"type": "string", "default": "1:1"}, "negative": {"type": "string", "default": ""}}, ["description"]), image_generate_prompt),
    ToolSpec("image.resize", "Resize an image using Pillow.", object_schema({"path": {"type": "string"}, "output": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "keep_aspect": {"type": "boolean", "default": True}}, ["path", "output", "width", "height"]), image_resize),
    ToolSpec("image.crop", "Crop an image using Pillow.", object_schema({"path": {"type": "string"}, "output": {"type": "string"}, "left": {"type": "integer"}, "top": {"type": "integer"}, "right": {"type": "integer"}, "bottom": {"type": "integer"}}, ["path", "output", "left", "top", "right", "bottom"]), image_crop),
    ToolSpec("image.convert", "Convert an image format using Pillow.", object_schema({"path": {"type": "string"}, "output": {"type": "string"}, "format": {"type": ["string", "null"], "default": None}}, ["path", "output"]), image_convert),
    ToolSpec("image.metadata", "Read image metadata.", object_schema({"path": {"type": "string"}}, ["path"]), image_metadata),
    ToolSpec("image.ocr", "Extract text from image using Tesseract OCR if installed.", object_schema({"path": {"type": "string"}, "lang": {"type": "string", "default": "eng"}}, ["path"]), image_ocr),
    ToolSpec("audio.transcribe", "Transcribe audio locally using openai-whisper if installed.", object_schema({"path": {"type": "string"}, "model": {"type": "string", "default": "base"}}, ["path"]), audio_transcribe),
    ToolSpec("audio.convert", "Convert audio using ffmpeg.", object_schema({"path": {"type": "string"}, "output": {"type": "string"}}, ["path", "output"]), audio_convert),
    ToolSpec("video.extract_audio", "Extract audio from video using ffmpeg.", object_schema({"path": {"type": "string"}, "output": {"type": "string", "default": "audio.wav"}}, ["path"]), video_extract_audio),
    ToolSpec("video.thumbnail", "Create a video thumbnail using ffmpeg.", object_schema({"path": {"type": "string"}, "output": {"type": "string", "default": "thumbnail.jpg"}, "at_seconds": {"type": "number", "default": 1.0}}, ["path"]), video_thumbnail),
]
