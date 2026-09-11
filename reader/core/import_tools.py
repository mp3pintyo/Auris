"""Optional local OCR and Calibre adapters. No model or tool auto-downloads."""
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

CALIBRE_EXTENSIONS = {'.azw3', '.azw', '.fb2', '.rtf', '.odt', '.html', '.htm', '.doc', '.lrf'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'}


def executable(name):
    found = shutil.which(name)
    if found:
        return found
    if os.name == 'nt':
        folder = 'Tesseract-OCR' if name == 'tesseract' else 'Calibre2'
        user_programs = str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs')
        for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'), user_programs):
            if root:
                path = Path(root) / folder / (name + '.exe')
                if path.is_file():
                    return str(path)
    return None


def languages():
    tool = executable('tesseract')
    if not tool:
        return []
    try:
        result = subprocess.run([tool, '--list-langs'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=10)
        return [line.strip() for line in result.stdout.splitlines()
                if re.fullmatch(r'[a-zA-Z0-9_/-]+', line.strip())]
    except (OSError, subprocess.TimeoutExpired):
        return []


def capabilities():
    return {'ocr': bool(executable('tesseract')), 'ocr_languages': languages(),
            'calibre': bool(executable('ebook-convert'))}


def ocr_document(source, language='hun'):
    from core.parser import txt_parser
    import pymupdf
    tool = executable('tesseract')
    if not tool:
        raise ValueError('Az OCR-hez telepítsd a Tesseract programot és a magyar (hun) nyelvi adatot, majd indítsd újra az Aurist.')
    if not re.fullmatch(r'[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*', language):
        raise ValueError('Érvénytelen OCR-nyelv.')
    missing = set(language.split('+')) - set(languages())
    if missing:
        raise ValueError('Hiányzó Tesseract nyelvi adat: ' + ', '.join(sorted(missing)))
    start = time.monotonic()
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix='auris-ocr-') as temp:
        folder = Path(temp)
        texts, recognized = [], 0
        with ExitStack() as stack:
            is_pdf = source.suffix.lower() == '.pdf'
            if is_pdf:
                document = stack.enter_context(pymupdf.open(source))
                if document.needs_pass:
                    raise ValueError('A jelszóval védett dokumentum nem olvasható.')
                pages, count = document, len(document)
            else:
                from PIL import Image, ImageSequence
                document = stack.enter_context(Image.open(source))
                pages, count = ImageSequence.Iterator(document), document.n_frames if hasattr(document, 'n_frames') else 1
            if count > 1000:
                raise ValueError('Egy OCR-import legfeljebb 1000 oldal lehet.')
            for page in pages:
                if time.monotonic() - start > 900:
                    raise ValueError('Az OCR elérte a 15 perces időkorlátot. Bontsd kisebb részekre a dokumentumot.')
                text = page.get_text(sort=True).strip() if is_pdf else ''
                if not text:
                    pixels = page.rect.width * page.rect.height * (200 / 72) ** 2 if is_pdf else page.width * page.height
                    if pixels > 25_000_000:
                        raise ValueError('Az oldal túl nagy az OCR-hez.')
                    if is_pdf:
                        page.get_pixmap(dpi=200, alpha=False).save(folder / 'page.png')
                    else:
                        page.convert('RGB').save(folder / 'page.png')
                    try:
                        result = subprocess.run([tool, str(folder / 'page.png'), 'stdout', '-l', language],
                                                capture_output=True, timeout=60)
                    except subprocess.TimeoutExpired:
                        raise ValueError('Egy oldal OCR-feldolgozása túllépte a 60 másodperces időkorlátot.')
                    if result.returncode:
                        raise ValueError('A Tesseract nem tudta feldolgozni az oldalt: ' + result.stderr.decode('utf-8', errors='replace')[-500:])
                    text = result.stdout.decode('utf-8', errors='replace').strip()
                    recognized += 1
                texts.append(text)
        path = folder / 'text.txt'
        path.write_text('\n\n'.join(texts), encoding='utf-8')
        parsed = txt_parser.parse(str(path))
        parsed['title'] = 'Unknown Title'
        parsed['import_note'] = f'OCR: {recognized} oldal szövegfelismerése. Ellenőrizd a szövegmintát és az ékezeteket.'
        return parsed


def convert_document(source):
    from core.parser import epub_parser
    tool = executable('ebook-convert')
    if not tool:
        raise ValueError('Ehhez a formátumhoz telepítsd a Calibre programot, majd indítsd újra az Aurist.')
    with tempfile.TemporaryDirectory(prefix='auris-calibre-') as temp:
        target = Path(temp) / 'converted.epub'
        try:
            with tempfile.TemporaryFile() as output:
                result = subprocess.run([tool, str(Path(source).resolve()), str(target)],
                                        stdout=output, stderr=output, timeout=300)
        except subprocess.TimeoutExpired:
            raise ValueError('A Calibre átalakítás túllépte az 5 perces időkorlátot.')
        if result.returncode or not target.is_file() or target.stat().st_size == 0:
            raise ValueError('A Calibre átalakítás sikertelen. Ellenőrizd, hogy a könyv olvasható és DRM-mentes.')
        parsed = epub_parser.parse(str(target))
        parsed['import_note'] = 'Calibre segítségével átalakítva. Ellenőrizd a fejezeteket és a szövegmintát.'
        return parsed
