"""Lightweight CPU chat model for the Space.

Runs a small GGUF instruction model with llama-cpp-python so the phone app can
do real LLM inference *on the user's own free Space* — no WebGPU, no in-browser
WASM limits, works on any phone. The model is downloaded and loaded lazily on
the first request so the Space boots fast and /health stays responsive.

Configure via environment variables (all optional):
  LLM_REPO   Hugging Face repo id holding the GGUF (default Qwen2.5-0.5B-Instruct)
  LLM_FILE   GGUF filename within that repo
  LLM_CTX    context window in tokens (default 4096)
  LLM_THREADS number of CPU threads (default: all available)
"""
from __future__ import annotations

import os
import threading
from typing import Any, Iterator

# Defaults chosen to run comfortably on a free HF CPU Space (2 vCPU / 16 GB).
DEFAULT_REPO = os.environ.get("LLM_REPO", "Qwen/Qwen2.5-0.5B-Instruct-GGUF")
DEFAULT_FILE = os.environ.get("LLM_FILE", "qwen2.5-0.5b-instruct-q4_k_m.gguf")
CTX = int(os.environ.get("LLM_CTX", "4096"))
THREADS = int(os.environ.get("LLM_THREADS", "0")) or None
# Qwen2.5 (the default) uses the ChatML prompt format. Set it explicitly so we
# don't depend on the GGUF metadata being auto-detected. Override for other models.
CHAT_FORMAT = os.environ.get("LLM_CHAT_FORMAT", "chatml").strip() or None


class ChatModel:
    """Thread-safe lazy wrapper around a single llama.cpp model."""

    def __init__(self) -> None:
        self._llm: Any = None
        self._load_lock = threading.Lock()   # guards model construction
        self._gen_lock = threading.Lock()    # llama.cpp is not re-entrant
        self.state = "idle"                   # idle | downloading | loading | ready | error
        self.error: str | None = None
        self.repo = DEFAULT_REPO
        self.file = DEFAULT_FILE

    # -- status -----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "ready": self._llm is not None,
            "repo": self.repo,
            "file": self.file,
            "error": self.error,
        }

    # -- loading ----------------------------------------------------------
    def ensure(self) -> None:
        if self._llm is not None:
            return
        with self._load_lock:
            if self._llm is not None:
                return
            try:
                from huggingface_hub import hf_hub_download
                from llama_cpp import Llama

                self.state = "downloading"
                self.error = None
                path = hf_hub_download(repo_id=self.repo, filename=self.file)

                self.state = "loading"
                self._llm = Llama(
                    model_path=path,
                    n_ctx=CTX,
                    n_threads=THREADS,
                    n_batch=256,
                    chat_format=CHAT_FORMAT,
                    verbose=False,
                )
                self.state = "ready"
            except Exception as exc:  # noqa: BLE001 - surface any load failure to the client
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                self._llm = None
                raise

    def warm_async(self) -> None:
        """Start loading in the background so the client can poll /llm/health."""
        if self._llm is not None or self.state in ("downloading", "loading"):
            return

        def run() -> None:
            try:
                self.ensure()
            except Exception:  # noqa: BLE001 - state/error already recorded by ensure()
                pass

        threading.Thread(target=run, daemon=True).start()

    # -- generation -------------------------------------------------------
    def stream(self, messages: list[dict[str, str]], max_tokens: int = 320,
               temperature: float = 0.6) -> Iterator[str]:
        self.ensure()
        max_tokens = max(16, min(int(max_tokens or 320), 1024))
        temperature = max(0.0, min(float(temperature or 0.6), 1.5))
        with self._gen_lock:
            stream = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                piece = delta.get("content")
                if piece:
                    yield piece


MODEL = ChatModel()
