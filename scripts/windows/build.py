"""Build a self-contained Windows x64 installer from the tested project venv.

Run from repo root: reader\\.venv\\Scripts\\python.exe scripts\\windows\\build.py
Runtime package copies are limited to declared dependencies; no library/settings/model data is copied.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build' / 'windows'
CACHE = WORK / 'cache'
PACKAGE = WORK / 'package'
OUTPUT = ROOT / 'dist' / 'windows'
PYTHON_VERSION = '3.11.9'
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
FFMPEG_URL = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
FFMPEG_SHA256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
WEBVIEW_URL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'
INNO_URL = 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe'


def run(*args, **kwargs):
    print('Running:', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def download(url: str, name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if not target.is_file():
        print('Downloading:', url, flush=True)
        partial = target.with_suffix(target.suffix + '.partial')
        with urllib.request.urlopen(url, timeout=120) as source, partial.open('wb') as out:
            shutil.copyfileobj(source, out)
        partial.replace(target)
    return target


def clean_owned(path: Path):
    if path.resolve().parent != WORK.resolve():
        raise ValueError(f'Refusing to clean outside build/windows: {path}')
    if path.exists():
        shutil.rmtree(path)


def onnxruntime_distribution() -> str:
    """The installed ONNX Runtime build; both provide the `onnxruntime` module.

    requirements.txt selects onnxruntime-directml on Windows with Python 3.11+.
    """
    for name in ('onnxruntime-directml', 'onnxruntime'):
        try:
            metadata.distribution(name)
            return name
        except metadata.PackageNotFoundError:
            pass
    return 'onnxruntime'


def dependency_closure():
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    roots = ['omnivoice', 'flask', 'ebooklib', 'pymupdf', 'pillow', 'python-docx', 'spacy',
             'trafilatura', 'pyphen', 'num2words', onnxruntime_distribution(), 'onnx-asr',
             'sentencepiece', 'pip', 'setuptools', 'wheel']
    for optional in ['en-core-web-sm', 'hu-core-news-md', 'wetext']:
        try:
            metadata.distribution(optional)
            roots.append(optional)
        except metadata.PackageNotFoundError:
            pass
    found, queue = {}, [(name, set()) for name in roots]
    seen_extras = {}
    while queue:
        name, extras = queue.pop()
        key = canonicalize_name(name)
        if key in ('triton', 'triton-windows'):
            continue
        if key in found and extras.issubset(seen_extras[key]):
            continue
        dist = metadata.distribution(name)
        found[key] = dist
        seen_extras.setdefault(key, set()).update(extras)
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not any(requirement.marker.evaluate({'extra': extra}) for extra in [''] + list(seen_extras[key])):
                continue
            queue.append((requirement.name, set(requirement.extras)))
    # Replace the GPU binaries with CPU wheels, but retain Torch's Python dependencies.
    return {name: dist for name, dist in found.items() if name not in ('torch', 'torchaudio')}


def copy_distribution(dist, destination: Path):
    source_root = Path(dist.locate_file('')).resolve()
    for record in dist.files or []:
        source = Path(dist.locate_file(record)).resolve()
        try:
            relative = source.relative_to(source_root)
        except ValueError:
            continue  # pip console launchers outside site-packages are not portable.
        if '__pycache__' in relative.parts or source.suffix == '.pyc' or not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def prepare_runtime():
    embedded = download(PYTHON_URL, 'python-embed.zip')
    site = PACKAGE / 'runtime' / 'Lib' / 'site-packages'
    site.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(embedded) as archive:
        archive.extractall(PACKAGE / 'runtime')
    # Isolate the app from every system Python/PYTHONPATH while retaining site-packages.
    (PACKAGE / 'runtime' / 'python311._pth').write_text(
        'python311.zip\n.\nLib/site-packages\n../app/reader\nimport site\n', encoding='utf-8')
    dependencies = dependency_closure()
    print(f'Copying {len(dependencies)} tested runtime dependencies', flush=True)
    for name, dist in sorted(dependencies.items()):
        copy_distribution(dist, site)
    desktop_deps = WORK / 'desktop-deps'
    if not (desktop_deps / 'webview').is_dir():
        run(sys.executable, '-m', 'pip', 'install', '--target', desktop_deps, 'pywebview==6.2.0')
    for entry in desktop_deps.iterdir():
        if entry.name in ('bin', '__pycache__'):
            continue
        target = site / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)
    cpu_wheels = CACHE / 'cpu-wheels'
    cpu_wheels.mkdir(parents=True, exist_ok=True)
    if not (list(cpu_wheels.glob('torch-2.11.0+cpu-*.whl')) and
            list(cpu_wheels.glob('torchaudio-2.11.0+cpu-*.whl'))):
        run(sys.executable, '-m', 'pip', 'download', '--no-deps', '--dest', cpu_wheels,
            'torch==2.11.0+cpu', 'torchaudio==2.11.0+cpu', '--index-url', 'https://download.pytorch.org/whl/cpu')
    run(sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-compile', '--target', site,
        *sorted(cpu_wheels.glob('*.whl')))
    lock = {name: dist.version for name, dist in sorted(dependencies.items())}
    lock.update({dist.metadata['Name']: dist.version for dist in metadata.distributions(path=[str(desktop_deps)])})
    lock.update(torch='2.11.0+cpu', torchaudio='2.11.0+cpu', python=PYTHON_VERSION, pywebview='6.2.0')
    (PACKAGE / 'runtime-manifest.json').write_text(json.dumps(lock, indent=2), encoding='utf-8')
    (PACKAGE / 'runtime' / 'runtime-ready').write_text('ready', encoding='ascii')


def prepare_tools():
    # NumPy wheels carry Microsoft's redistributable C++ runtime under a hashed
    # filename. Torch needs its original DLL name on fresh Windows systems.
    # CPython already supplies vcruntime140.dll and vcruntime140_1.dll.
    cpp_runtime = list((PACKAGE / 'runtime' / 'Lib' / 'site-packages' / 'numpy.libs').glob('msvcp140-*.dll'))
    if len(cpp_runtime) != 1:
        raise RuntimeError('The tested NumPy wheel must contain exactly one Microsoft C++ runtime DLL')
    shutil.copy2(cpp_runtime[0], PACKAGE / 'runtime' / 'msvcp140.dll')
    manifest_path = PACKAGE / 'runtime-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['msvcp140.dll'] = 'sha256:' + hashlib.sha256(cpp_runtime[0].read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = download(FFMPEG_URL, 'ffmpeg-9.0.2-essentials_build.zip')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != FFMPEG_SHA256:
        raise RuntimeError('FFmpeg SHA256 mismatch')
    tools = PACKAGE / 'tools'
    tools.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.endswith(('/bin/ffmpeg.exe', '/bin/ffprobe.exe', '/LICENSE', '/LICENSE.txt', '/README.txt')):
                (tools / Path(name).name).write_bytes(bundle.read(name))
    shutil.copy2(download(WEBVIEW_URL, 'MicrosoftEdgeWebview2Setup.exe'), PACKAGE)
    (PACKAGE / 'SOURCE-NOTICES.md').write_text(
        '# Desktop binary source notices\n\n'
        'FFmpeg/ffprobe: Gyan essentials 9.0.2 (GPL-3.0), separate command-line programs.\n'
        'Binary archive: ' + FFMPEG_URL + '\nSHA256: ' + FFMPEG_SHA256 + '\n'
        'Corresponding FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/946fcce07b\n'
        'Source archive: https://github.com/FFmpeg/FFmpeg/archive/946fcce07b.zip\n'
        'Build configuration and external library/source references: https://www.gyan.dev/ffmpeg/builds/\n\n'
        'CPython 3.11.9 source and license: https://www.python.org/downloads/release/python-3119/\n'
        'Runtime component license files are retained in runtime/Lib/site-packages.\n'
        'See THIRD_PARTY_NOTICES.md and runtime-manifest.json for the other components.\n', encoding='utf-8')


def prepare_app():
    reader = PACKAGE / 'app' / 'reader'
    reader.mkdir(parents=True, exist_ok=True)
    for name in ['core', 'static', 'templates']:
        shutil.copytree(ROOT / 'reader' / name, reader / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    for name in ['app.py', 'desktop.py', 'auris_cli.py', 'requirements.txt']:
        shutil.copy2(ROOT / 'reader' / name, reader)
    shutil.copytree(ROOT / 'reader' / '.higgs_runtime', reader / '.higgs_runtime',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md', 'VERSION']:
        shutil.copy2(ROOT / name, PACKAGE)
    shutil.copy2(ROOT / 'docs' / 'windows-desktop.md', PACKAGE / 'Windows-utmutato.md')


def compile_launcher():
    from PIL import Image, ImageDraw, ImageFont
    icon = Image.new('RGBA', (256, 256))
    canvas = ImageDraw.Draw(icon)
    canvas.rounded_rectangle((4, 4, 252, 252), radius=52, fill='#211f1b')
    font = ImageFont.truetype('C:/Windows/Fonts/georgia.ttf', 180)
    canvas.text((128, 118), 'A', font=font, anchor='mm', fill='#e2ad6b')
    icon.save(PACKAGE / 'Auris.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
    run(compiler, '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/reference:System.Windows.Forms.dll', '/win32icon:' + str(PACKAGE / 'Auris.ico'),
        '/out:' + str(PACKAGE / 'Auris.exe'), ROOT / 'scripts' / 'windows' / 'launcher.cs')


def installer_compiler() -> Path:
    candidates = [WORK / 'inno' / 'ISCC.exe', Path('C:/Program Files/Inno Setup 7/ISCC.exe'),
                  Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe')]
    for path in candidates:
        if path.exists():
            return path
    setup = download(INNO_URL, 'innosetup-x64.exe')
    run(setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/NOICONS', '/DIR=' + str(WORK / 'inno'))
    return candidates[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-only', action='store_true', help='Reuse runtime after source-only changes')
    parser.add_argument('--stage-only', action='store_true', help='Stage and compile launcher without compressing installer')
    args = parser.parse_args()
    if os.name != 'nt' or sys.version_info[:2] != (3, 11) or sys.maxsize < 2**32:
        parser.error('Use the project Windows x64 Python 3.11 venv.')
    WORK.mkdir(parents=True, exist_ok=True)
    if not args.app_only:
        clean_owned(PACKAGE)
    PACKAGE.mkdir(parents=True, exist_ok=True)
    if not args.app_only or not (PACKAGE / 'runtime' / 'runtime-ready').is_file():
        prepare_runtime()
    prepare_tools()
    prepare_app()
    compile_launcher()
    if args.stage_only:
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    version = (ROOT / 'VERSION').read_text().strip()
    run(installer_compiler(), '/DAppVersion=' + version, '/DPackageDir=' + str(PACKAGE),
        '/DOutputDir=' + str(OUTPUT), ROOT / 'scripts' / 'windows' / 'installer.iss')
    installer = OUTPUT / f'Auris-Setup-{version}-x64.exe'
    shutil.copy2(PACKAGE / 'runtime-manifest.json', OUTPUT / f'Auris-{version}-runtime-manifest.json')
    source = download('https://github.com/FFmpeg/FFmpeg/archive/946fcce07b.zip', 'FFmpeg-9.0.2-source.zip')
    shutil.copy2(source, OUTPUT / source.name)
    attachments = [installer, OUTPUT / f'Auris-{version}-runtime-manifest.json', OUTPUT / source.name]
    checksums = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in attachments)
    (OUTPUT / 'SHA256SUMS.txt').write_text(checksums, encoding='ascii')
    print(f'Installer: {installer} ({installer.stat().st_size / 1048576:.1f} MB)', flush=True)


if __name__ == '__main__':
    main()
