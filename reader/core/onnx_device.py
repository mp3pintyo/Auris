"""ONNX Runtime execution providers for the ONNX engines.

Supertonic 3 and Parakeet run through ONNX Runtime. On Windows
``onnxruntime-directml`` drives any DirectX 12 GPU (AMD, Intel or NVIDIA);
elsewhere, or when the ``onnx_device`` setting is ``cpu``, the CPU provider
is used. DirectML sessions cannot run concurrently, so callers keep one
``run`` at a time per session (the engine and transcriber hold a lock).
MOSS-TTS-Nano stays on the CPU, where it measured faster.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

ONNX_DEVICES = ("auto", "cpu")
DIRECTML = "DmlExecutionProvider"
CPU = "CPUExecutionProvider"


def onnx_device_setting() -> str:
    try:
        from core import settings

        value = str(settings.get("onnx_device", "auto") or "auto")
    except Exception:
        value = "auto"
    return value if value in ONNX_DEVICES else "auto"


def onnx_providers() -> list[str]:
    """Providers in priority order; the CPU provider is always last."""
    if onnx_device_setting() == "cpu":
        return [CPU]
    try:
        import onnxruntime as ort

        available = ort.get_available_providers()
    except Exception:
        return [CPU]
    return [DIRECTML, CPU] if DIRECTML in available else [CPU]


def onnx_device_label(providers: list[str]) -> str:
    return "GPU · DirectML" if DIRECTML in providers else "CPU · ONNX Runtime"


def load_with_cpu_fallback(load, providers: list[str]):
    """Call ``load(providers)``; retry on the CPU when DirectML fails.

    Returns ``(result, providers_used)``. An old or broken GPU driver must
    not make the engine unusable when the CPU can still run it.
    """
    try:
        return load(providers), providers
    except Exception as exc:
        if DIRECTML not in providers:
            raise
        log.warning("DirectML could not start (%s); using the CPU instead", exc)
        return load([CPU]), [CPU]


def directml_installed() -> bool:
    """True when the onnxruntime-directml distribution is installed."""
    from importlib import metadata

    try:
        metadata.version("onnxruntime-directml")
    except metadata.PackageNotFoundError:
        return False
    return True
