"""
Auris / OmniReader installer.

Detects hardware, installs the appropriate PyTorch build, then installs
OmniVoice and the reader dependencies.

Usage:
    python setup.py

Environment:
    AURIS_OFFLINE=1          Force local-wheel-only installs.
    AURIS_USE_LOCAL_WHEELS=1 Use a local wheel directory before package indexes.
    AURIS_WHEELS_DIR=...     Override the local wheel directory path.
"""

import os
import platform
import re
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
REPO_DIR = APP_DIR.parent

OMNIVOICE_SRC = REPO_DIR / "OmniVoice"
_WHEELS_OVERRIDE = os.environ.get("AURIS_WHEELS_DIR", "").strip()
WHEELS_DIR = Path(_WHEELS_OVERRIDE) if _WHEELS_OVERRIDE else (REPO_DIR / "wheels")
STRICT_OFFLINE = os.environ.get("AURIS_OFFLINE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
USE_LOCAL_WHEELS = STRICT_OFFLINE or os.environ.get("AURIS_USE_LOCAL_WHEELS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

PIP = [sys.executable, "-m", "pip", "install", "--upgrade"]

W = "\033[0m"
G = "\033[32m"
Y = "\033[33m"
R = "\033[31m"
B = "\033[34m"
BD = "\033[1m"


def banner():
    print(
        f"""
{BD}+------------------------------------------+{W}
{BD}|         Auris Setup Installer            |{W}
{BD}|   Audiobook Reader + OmniVoice stack    |{W}
{BD}+------------------------------------------+{W}
"""
    )


def info(msg):
    print(f"  {G}*{W} {msg}")


def warn(msg):
    print(f"  {Y}!{W} {msg}")


def error(msg):
    print(f"  {R}x{W} {msg}")


def step(msg):
    print(f"\n{BD}{B}>{W} {BD}{msg}{W}")


def ok(msg):
    print(f"  {G}OK{W} {msg}")


def run(cmd, check=True, **kwargs):
    info(f"Running: {' '.join(str(part) for part in cmd)}")
    return subprocess.run(cmd, check=check, **kwargs)


def detect_cuda_version():
    """Return a CUDA version string like '12.8', or None."""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            match = re.search(r"CUDA Version:\s*(\d+\.\d+)", result.stdout)
            if match:
                return match.group(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        result = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            match = re.search(r"release (\d+\.\d+)", result.stdout)
            if match:
                return match.group(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def is_apple_silicon():
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def cuda_to_wheel_tag(cuda_version):
    """Map the detected CUDA version to the PyTorch wheel index tag."""
    if cuda_version is None:
        return None

    major, minor = (int(part) for part in cuda_version.split(".", 1))
    if (major, minor) >= (12, 8):
        return "cu128"
    if (major, minor) >= (12, 4):
        return "cu124"
    if (major, minor) >= (12, 1):
        return "cu121"
    if (major, minor) >= (11, 8):
        return "cu118"

    warn(f"CUDA {cuda_version} is older than 11.8. Installing CPU torch.")
    return None


def detect_hardware():
    step("Detecting hardware")

    if is_apple_silicon():
        ok("Apple Silicon (MPS) detected")
        return "mps"

    cuda_version = detect_cuda_version()
    if cuda_version:
        tag = cuda_to_wheel_tag(cuda_version)
        if tag:
            ok(f"NVIDIA GPU detected. CUDA {cuda_version} -> torch wheel: {tag}")
            return tag
        warn("CUDA version too old. Falling back to CPU torch.")
        return "cpu"

    warn("No GPU detected. Installing CPU torch.")
    return "cpu"


def offline_wheels_available():
    return USE_LOCAL_WHEELS and WHEELS_DIR.exists() and any(WHEELS_DIR.glob("*.whl"))


def running_in_virtualenv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def pip_install(*args, no_index=False, index_url=None):
    cmd = [*PIP]
    wheels_ready = offline_wheels_available()

    if wheels_ready:
        cmd.append(f"--find-links={WHEELS_DIR}")
        if STRICT_OFFLINE or no_index:
            cmd.append("--no-index")
    elif STRICT_OFFLINE or no_index:
        raise RuntimeError(
            f"Offline install requested, but no local wheels were found in: {WHEELS_DIR}"
        )

    if index_url:
        cmd.extend(["--index-url", index_url])

    cmd.extend(str(arg) for arg in args)
    run(cmd)


def install_torch(hw_tag):
    step("Installing PyTorch + torchaudio")

    if hw_tag == "mps":
        pip_install("torch", "torchaudio")
    elif hw_tag == "cpu":
        if offline_wheels_available():
            info("Local wheels found; using them before package indexes.")
        pip_install("torch", "torchaudio")
    else:
        index_url = f"https://download.pytorch.org/whl/{hw_tag}"
        info(f"PyTorch index: {index_url}")

        if offline_wheels_available():
            cuda_wheels = list(WHEELS_DIR.glob(f"torch-*{hw_tag}*.whl"))
            if cuda_wheels:
                info(f"Found cached CUDA wheel: {cuda_wheels[0].name}")
                pip_install("torch", "torchaudio", no_index=True)
                ok("PyTorch installed")
                return

        pip_install("torch", "torchaudio", index_url=index_url)

    ok("PyTorch installed")


def install_omnivoice_deps():
    step("Installing OmniVoice runtime dependencies")
    deps = [
        # OmniVoice currently loads correctly with 5.3.0; newer 5.x builds can
        # miss or reshuffle Higgs Audio classes and break model startup.
        "transformers==5.3.0",
        "accelerate",
        "pydub",
        "tensorboardX",
        "webdataset",
        "numpy",
        "soundfile",
        "librosa",
    ]
    pip_install(*deps)
    ok("OmniVoice dependencies installed")


def install_omnivoice():
    step("Installing OmniVoice")

    if offline_wheels_available():
        cached_wheels = list(WHEELS_DIR.glob("omnivoice-*.whl"))
        if cached_wheels:
            info(f"Using cached wheel: {cached_wheels[0].name}")
            pip_install(str(cached_wheels[0]), no_index=True)
            ok("OmniVoice installed from offline wheel")
            return

    if OMNIVOICE_SRC.exists():
        info(f"Installing from local source: {OMNIVOICE_SRC}")
        run([*PIP, "--no-deps", str(OMNIVOICE_SRC)])
        ok("OmniVoice installed from source")
        return

    warn("No local source or wheel found. Installing OmniVoice from PyPI.")
    pip_install("omnivoice")
    ok("OmniVoice installed from PyPI")


def install_reader_deps():
    step("Installing remaining dependencies from requirements.txt")
    pip_install("-r", str(APP_DIR / "requirements.txt"))
    ok("Dependencies installed")


def install_spacy_model():
    step("Installing spaCy language model (en_core_web_sm)")

    if STRICT_OFFLINE:
        warn("Strict offline mode enabled. Skipping spaCy model download.")
        warn("Install en_core_web_sm later from Settings or with: python -m spacy download en_core_web_sm")
        return

    try:
        import spacy

        try:
            spacy.load("en_core_web_sm")
            ok("en_core_web_sm already installed")
            return
        except OSError:
            pass
    except ImportError:
        warn("spaCy is not installed yet. Model download will be attempted after dependency install.")

    try:
        run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
        ok("en_core_web_sm installed")
    except subprocess.CalledProcessError:
        warn("Could not download en_core_web_sm during setup.")
        warn("Install it later from Settings or with: python -m spacy download en_core_web_sm")


def print_summary(hw_tag):
    device_label = {
        "mps": "Apple Silicon (MPS)",
        "cpu": "CPU only",
    }.get(hw_tag, f"NVIDIA GPU ({hw_tag})")

    launch_hint = (
        r".venv\Scripts\python.exe app.py"
        if os.name == "nt"
        else "./.venv/bin/python app.py"
    )

    print(
        f"""
{BD}+------------------------------------------+{W}
{BD}|              Setup Complete              |{W}
{BD}+------------------------------------------+{W}

  Device      : {G}{device_label}{W}
  To launch   : {BD}{launch_hint}{W}
  Windows     : {BD}run.bat{W}
  Linux / Mac : {BD}bash run.sh{W}
  Browser     : http://127.0.0.1:7860

  Model path is configured in Settings.
  The spaCy model can also be installed later from Settings.
"""
    )


def main():
    banner()
    os.chdir(APP_DIR)

    if running_in_virtualenv():
        ok(f"Using virtual environment: {sys.prefix}")
    else:
        warn("No virtual environment detected. setup.bat/setup.sh will create one automatically.")

    if offline_wheels_available():
        if STRICT_OFFLINE:
            info(f"Strict offline mode enabled with wheel cache: {WHEELS_DIR}")
        else:
            info(f"Using local wheels from {WHEELS_DIR}; missing packages will be downloaded if needed.")
    elif WHEELS_DIR.exists() and not USE_LOCAL_WHEELS:
        info(f"Ignoring local wheels at {WHEELS_DIR} unless AURIS_USE_LOCAL_WHEELS=1 is set.")
    elif STRICT_OFFLINE:
        raise RuntimeError(
            f"AURIS_OFFLINE=1 was set, but no wheel cache was found in: {WHEELS_DIR}"
        )

    hw_tag = detect_hardware()
    install_torch(hw_tag)
    install_omnivoice_deps()
    install_omnivoice()
    install_reader_deps()
    install_spacy_model()
    print_summary(hw_tag)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        error(f"A step failed (exit code {exc.returncode}). Check the output above.")
        sys.exit(1)
    except RuntimeError as exc:
        error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        warn("Setup cancelled.")
        sys.exit(0)
