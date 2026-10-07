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
    AURIS_TRITON=1           Also install the optional Triton kernels (NVIDIA).
    AURIS_TORCH_VARIANT=...  Force the PyTorch build: cu128, cu124, rocm, cpu...
    AURIS_ROCM_GFX=gfxNNNN   AMD GPU target when auto-detection cannot name it.
    AURIS_ROCM_INDEX_URL=... AMD ROCm wheel index (default: stable channel).
"""

import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
REPO_DIR = APP_DIR.parent

# Prefer vendored source under source/omnivoice_repo; fall back to legacy ./OmniVoice.
_OMNIVOICE_CANDIDATES = (
    REPO_DIR / "source" / "omnivoice_repo",
    REPO_DIR / "OmniVoice",
)
OMNIVOICE_SRC = next((p for p in _OMNIVOICE_CANDIDATES if p.exists()), _OMNIVOICE_CANDIDATES[0])
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
            match = re.search(r"CUDA (?:UMD )?Version:\s*(\d+\.\d+)", result.stdout)
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

    # Container builds have no GPU attached; AURIS_TORCH_VARIANT=cu128 (or cpu)
    # selects the PyTorch build explicitly.
    forced = os.environ.get("AURIS_TORCH_VARIANT", "").strip().lower()
    if forced:
        ok(f"PyTorch variant forced by AURIS_TORCH_VARIANT: {forced}")
        return forced

    if is_apple_silicon():
        ok("Apple Silicon (MPS) detected")
        return "mps"

    # AMD wheels are GPU/OS/Python-specific. Preserve an already installed,
    # working vendor pair rather than replacing it with a generic CPU wheel.
    if rocm_runtime_works():
        ok("Working AMD ROCm PyTorch runtime detected; preserving it")
        return "rocm"

    cuda_version = detect_cuda_version()
    if cuda_version:
        tag = cuda_to_wheel_tag(cuda_version)
        if tag:
            ok(f"NVIDIA GPU detected. CUDA {cuda_version} -> torch wheel: {tag}")
            return tag
        warn("CUDA version too old. Falling back to CPU torch.")
        return "cpu"

    gfx = detect_amd_gfx_target()
    if gfx:
        ok(f"AMD GPU detected ({gfx}) -> ROCm torch wheel")
        return "rocm"

    warn("No GPU detected. Installing CPU torch.")
    return "cpu"


# AMD ROCm PyTorch for Windows and Linux (TheRock multi-arch builds). The
# kernels for one GPU arrive through the torch `[device-gfxNNNN]` extra.
ROCM_INDEX_URL = os.environ.get(
    "AURIS_ROCM_INDEX_URL", "https://stable.repo.amd.com/rocm/whl-next/"
).strip()
ROCM_TORCH_VERSION = "2.11.0+rocm10.0.0"

# Marketing name fragment -> LLVM target, most specific first. Unlisted
# cards can be named explicitly with AURIS_ROCM_GFX=gfxNNNN.
AMD_GFX_TARGETS = (
    ("RX 9070", "gfx1201"), ("R9700", "gfx1201"), ("RX 9060", "gfx1200"),
    ("RX 7900", "gfx1100"), ("W7900", "gfx1100"), ("W7800", "gfx1100"),
    ("RX 7800", "gfx1101"), ("RX 7700", "gfx1101"), ("W7700", "gfx1101"),
    ("RX 7650", "gfx1102"), ("RX 7600", "gfx1102"), ("890M", "gfx1150"), ("880M", "gfx1150"),
    ("8060S", "gfx1151"), ("780M", "gfx1103"), ("760M", "gfx1103"),
    ("RX 6950", "gfx1030"), ("RX 6900", "gfx1030"), ("RX 6800", "gfx1030"),
    ("W6800", "gfx1030"), ("RX 6750", "gfx1031"), ("RX 6700", "gfx1031"),
    ("RX 6650", "gfx1032"), ("RX 6600", "gfx1032"), ("W6600", "gfx1032"),
    ("RX 6500", "gfx1034"), ("RX 6400", "gfx1034"), ("680M", "gfx1035"), ("660M", "gfx1035"),
)


def amd_gpu_names():
    """Names of the installed display adapters that look like AMD GPUs.

    ROCm PyTorch exists for Windows and Linux only; macOS returns none.
    """
    names = []
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=30,
            )
            names = result.stdout.splitlines() if result.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            names = []
    elif platform.system() == "Linux":
        try:
            result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
            names = [line for line in result.stdout.splitlines()
                     if "VGA" in line or "Display" in line]
        except (OSError, subprocess.TimeoutExpired):
            names = []
    return [n.strip() for n in names if re.search(r"\b(AMD|Radeon|ATI)\b", n)]


def detect_amd_gfx_target():
    """Return the gfx target (e.g. 'gfx1032') of the AMD GPU, or None."""
    forced = os.environ.get("AURIS_ROCM_GFX", "").strip().lower()
    if forced:
        return forced
    names = amd_gpu_names()
    for name in names:
        for fragment, gfx in AMD_GFX_TARGETS:
            if fragment.lower() in name.lower():
                return gfx
    if names:
        warn(f"AMD GPU not in the ROCm table: {names[0]}. "
             "Set AURIS_ROCM_GFX=gfxNNNN to install ROCm torch for it.")
    return None


def rocm_runtime_works():
    try:
        existing = subprocess.run(
            [sys.executable, "-c", "import torch, torchaudio; "
             "assert torch.version.hip and torch.cuda.is_available()"],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return existing.returncode == 0


def install_rocm_torch():
    gfx = detect_amd_gfx_target()
    if not gfx:
        raise RuntimeError("No supported AMD GPU found for ROCm torch. Set AURIS_ROCM_GFX=gfxNNNN.")
    info(f"ROCm index: {ROCM_INDEX_URL} (device extra: device-{gfx})")
    # The exact local version exists only on the AMD index, so PyPI can
    # safely supply ordinary dependencies without swapping in a CPU build.
    run([
        sys.executable, "-m", "pip", "install", "--upgrade",
        "--index-url", ROCM_INDEX_URL,
        "--extra-index-url", "https://pypi.org/simple",
        f"torch[device-{gfx}]=={ROCM_TORCH_VERSION}",
        f"torchaudio=={ROCM_TORCH_VERSION}",
    ])


def offline_wheels_available():
    return USE_LOCAL_WHEELS and WHEELS_DIR.exists() and any(WHEELS_DIR.glob("*.whl"))


def running_in_virtualenv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def ensure_pip():
    """Upgrade pip and wheel so dependency resolution is reliable.

    setuptools is left to the packages that declare it: pip builds source
    packages in isolated environments with their own setuptools, while
    forcing the newest one broke torch 2.11's ``setuptools<82`` requirement
    on every re-run. wheel stays: `python -m venv` does not install it and
    the Windows desktop build (scripts/windows/build.py) bundles it.
    """
    step("Upgrading pip")
    # Use ensurepip-safe invocation (not PIP, which already includes --upgrade).
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "wheel"])
    ok("pip upgraded")


def ensure_torch_requirements():
    """Re-require the installed torch pair so pip satisfies its dependencies.

    Earlier installers upgraded setuptools past the bound torch declares,
    and a preserved torch is never reinstalled, so pip never repaired it.
    Naming the installed versions keeps torch in place and lets pip fix only
    the dependencies, whatever bounds a future torch declares.
    """
    from importlib import metadata

    try:
        pins = [f"{name}=={metadata.version(name)}" for name in ("torch", "torchaudio")]
    except metadata.PackageNotFoundError:
        return
    step("Checking PyTorch dependencies")
    try:
        pip_install(*pins)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        warn(f"Could not reconcile PyTorch dependencies ({exc}); run `pip check` in the venv.")


def pip_install(*args, no_index=False, index_url=None, extra_index_url=None):
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
    if extra_index_url:
        cmd.extend(["--extra-index-url", extra_index_url])

    cmd.extend(str(arg) for arg in args)
    run(cmd)


# Tested range. torchaudio 2.9+ changed its I/O backends; an unbounded
# "latest" install could break OmniVoice on a future release.
TORCH_SPEC = "torch>=2.4,<2.12"
TORCHAUDIO_SPEC = "torchaudio>=2.4,<2.12"


def install_torch(hw_tag):
    """Install the PyTorch build for ``hw_tag``; return the tag installed."""
    step("Installing PyTorch + torchaudio")

    if hw_tag == "rocm":
        return install_rocm_or_cpu_torch()
    if hw_tag == "mps":
        pip_install(TORCH_SPEC, TORCHAUDIO_SPEC)
    elif hw_tag == "cpu":
        if offline_wheels_available():
            info("Local wheels found; using them before package indexes.")
        pip_install(TORCH_SPEC, TORCHAUDIO_SPEC)
    else:
        index_url = f"https://download.pytorch.org/whl/{hw_tag}"
        info(f"PyTorch index: {index_url}")

        if offline_wheels_available():
            cuda_wheels = list(WHEELS_DIR.glob(f"torch-*{hw_tag}*.whl"))
            if cuda_wheels:
                info(f"Found cached CUDA wheel: {cuda_wheels[0].name}")
                pip_install("torch", "torchaudio", no_index=True)
                ok("PyTorch installed")
                return hw_tag

        # Resolve the native pair ONLY against the hardware-specific index.
        # Mixing this index with PyPI selected a newer CPU torch alongside CUDA
        # torchaudio. Download without dependencies, then install exact wheels;
        # ordinary dependencies may safely come from PyPI in the second step.
        with tempfile.TemporaryDirectory(prefix="auris-torch-") as wheel_dir:
            run([
                sys.executable, "-m", "pip", "download", "--no-deps",
                "--index-url", index_url, "--dest", wheel_dir,
                TORCH_SPEC, TORCHAUDIO_SPEC,
            ])
            wheels = sorted(Path(wheel_dir).glob("*.whl"))
            if len(wheels) != 2 or any(f"+{hw_tag}-" not in p.name for p in wheels):
                raise RuntimeError(f"Expected two {hw_tag} PyTorch wheels; refusing mixed builds.")
            pip_install(*(str(p) for p in wheels))

    ok("PyTorch installed")
    return hw_tag


def install_rocm_or_cpu_torch():
    """Keep or install ROCm torch; fall back to CPU torch when it fails.

    An AMD card with an unsupported driver, a failed download or a strict
    offline install must not stop setup: Auris also runs on the CPU.
    """
    if rocm_runtime_works():
        verify_torch("rocm")
        return "rocm"
    if STRICT_OFFLINE:
        warn("Strict offline mode: ROCm PyTorch is downloaded from AMD's index. Installing CPU torch.")
        return install_torch("cpu")
    try:
        install_rocm_torch()
        verify_torch("rocm")
        return "rocm"
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        warn(f"ROCm PyTorch could not be installed or started ({exc}).")
        warn("Installing CPU torch instead; run setup again to retry ROCm.")
    # A ROCm 2.11 build left behind would already satisfy TORCH_SPEC, so
    # pip would keep it; remove it before installing the CPU pair.
    run([sys.executable, "-m", "pip", "uninstall", "-y", "torch", "torchaudio"], check=False)
    return install_torch("cpu")


def verify_torch(hw_tag):
    """Import native libraries in a fresh process before declaring setup ready."""
    step("Checking PyTorch + torchaudio runtime")
    code = (
        "import torch; import torchaudio; "
        "print('torch:', torch.__version__, 'torchaudio:', torchaudio.__version__); "
    )
    if hw_tag.startswith("cu"):
        code += (
            "assert torch.version.cuda and torch.cuda.is_available(), "
            "'CUDA is unavailable: check the PyTorch build and NVIDIA driver'; "
            "print('GPU:', torch.cuda.get_device_name(0))"
        )
    elif hw_tag == "rocm":
        code += (
            "assert torch.version.hip and torch.cuda.is_available(), "
            "'ROCm is unavailable: install the AMD-supported torch/torchaudio pair'; "
            "print('GPU:', torch.cuda.get_device_name(0))"
        )
    run([sys.executable, "-c", code])
    ok("Native audio runtime verified")


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
        "num2words",  # number → words fallback for text normalization
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


def install_higgs_transformers_runtime():
    """Install Higgs' newer Transformers in an isolated subprocess path.

    OmniVoice remains pinned to 5.3.0 in the main venv. Higgs' community
    adapter requires >=5.5, so importing both versions in one interpreter is
    deliberately avoided.
    """
    step("Installing isolated Higgs Transformers runtime")
    target = APP_DIR / ".higgs_runtime"
    pip_install(
        "--target",
        str(target),
        "--no-deps",
        "transformers==5.13.0",
    )
    ok("Higgs Transformers runtime installed (isolated from OmniVoice)")


def install_reader_deps():
    step("Installing remaining dependencies from requirements.txt")
    # requirements.txt intentionally omits torch/torchaudio so this step cannot
    # replace a CUDA build with a CPU wheel from PyPI.
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


def install_hungarian_spacy_model():
    """HuSpaCy powers Hungarian character detection without a language model."""
    step("Installing Hungarian spaCy model (HuSpaCy hu_core_news_md)")
    if STRICT_OFFLINE:
        warn("Strict offline mode enabled. Install HuSpaCy later from Settings.")
        return
    import importlib.util

    if any(importlib.util.find_spec(name) for name in
           ("hu_core_news_lg", "hu_core_news_md", "hu_core_news_trf")):
        ok("HuSpaCy already installed")
        return
    try:
        sys.path.insert(0, str(APP_DIR))
        from core.settings import install_spacy_model as install_model

        result = install_model("hu")
    except Exception as exc:  # network or import failure must not stop setup
        result = {"ok": False, "message": str(exc)}
    if result.get("ok"):
        ok("HuSpaCy installed")
    else:
        warn("Could not install HuSpaCy during setup: " + str(result.get("message", ""))[-300:])
        warn("Install it later from Settings -> Character detection.")


def install_triton_acceleration(hw_tag):
    """Optional Triton kernels for the hybrid OmniVoice mode (NVIDIA only)."""
    if os.environ.get("AURIS_TRITON", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    step("Installing optional Triton acceleration")
    if not hw_tag.startswith("cu"):
        warn("Triton acceleration needs an NVIDIA GPU; skipped.")
        return
    try:
        sys.path.insert(0, str(APP_DIR))
        from core.tts_accel import install_triton

        result = install_triton()
    except Exception as exc:  # optional step must not stop setup
        result = {"ok": False, "message": str(exc)}
    if result.get("ok"):
        ok("Triton kernels installed; choose the Hybrid mode in Settings.")
    else:
        warn("Triton acceleration was not installed: " + str(result.get("message", ""))[-300:])


def print_summary(hw_tag):
    device_label = {
        "rocm": "AMD GPU (ROCm)",
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

    if not STRICT_OFFLINE:
        ensure_pip()

    hw_tag = install_torch(detect_hardware())
    ensure_torch_requirements()
    verify_torch(hw_tag)
    install_omnivoice_deps()
    install_omnivoice()
    install_higgs_transformers_runtime()
    install_reader_deps()
    install_spacy_model()
    install_hungarian_spacy_model()
    install_triton_acceleration(hw_tag)
    verify_torch(hw_tag)
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
