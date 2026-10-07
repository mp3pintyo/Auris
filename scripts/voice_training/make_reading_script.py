"""Split a book into reading sessions for recording your own voice. Run from the repository root.

reader/.venv/Scripts/python.exe scripts/voice_training/make_reading_script.py \
    --source test_docs/Rejto_Jeno-14-karatos-auto.pdf --out reader/data/voice_training/felolvasas

Writes ``felolvasas_01.txt`` ... (about ``--session-minutes`` of reading each,
whole paragraphs) and ``UTMUTATO.txt``. Record each session as a WAV with the
same name (``felolvasas_01.wav``) next to its text; prepare_dataset.py then
uses the text as the exact transcript. Use a public-domain or your own text.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'reader'))

GUIDE = """Felolvasás saját hang tanításához
==================================

1. Csendes, nem visszhangos szobában, mindig ugyanazzal a mikrofonnal és
   ugyanabból a távolságból (kb. 20-30 cm) vegyél fel.
2. Minden szövegfájlt külön WAV-ba olvass fel, és a WAV neve egyezzen a
   szövegével: felolvasas_01.txt -> felolvasas_01.wav.
3. Olvass természetes, nyugodt hangoskönyv-tempóban, a mondatok között kis
   szünettel. Ne siess, és ne színészkedj túl: a tanítás ezt a stílust tanulja meg.
4. Ha elrontasz egy mondatot, kis szünet után olvasd fel újra az egész mondatot.
   A felismerő kiszűri a rossz változatot.
5. A felvétel elején és végén legyen fél másodperc csend; ne vágd le az utolsó szót.
6. 44,1 vagy 48 kHz, 16 vagy 24 bites WAV megfelelő. Ne használj zajszűrőt vagy
   tömörítőt a felvételen.

Összesen legalább 30 perc kell a kísérlethez, 60 perc az ajánlott.
Csak a saját hangodat (vagy engedéllyel rendelkező hangot) tanítsd.
"""


def book_paragraphs(source: Path) -> list[str]:
    if source.suffix.lower() == '.pdf':
        from core.parser import pdf_parser

        chapters = pdf_parser.parse(str(source))['chapters']
        text = '\n\n'.join(c.get('content') or '' for c in chapters)
    else:
        text = source.read_text(encoding='utf-8')
    paragraphs = []
    for block in re.split(r'\n\s*\n', text):
        block = ' '.join(block.split())
        if len(block.split()) < 4 or re.fullmatch(r'[IVXLC]+\. FEJEZET', block):
            continue
        paragraphs.append(re.sub(r'^[IVXLC]+\. FEJEZET\s+', '', block))
    return paragraphs


def sessions(paragraphs: list[str], words_per_session: int, max_sessions: int) -> list[list[str]]:
    out, current, count = [], [], 0
    for paragraph in paragraphs:
        current.append(paragraph)
        count += len(paragraph.split())
        if count >= words_per_session:
            out.append(current)
            current, count = [], 0
            if len(out) >= max_sessions:
                return out
    if current and len(out) < max_sessions:
        out.append(current)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', type=Path, required=True, help='PDF or UTF-8 TXT.')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--minutes', type=float, default=60)
    p.add_argument('--session-minutes', type=float, default=10)
    p.add_argument('--words-per-minute', type=float, default=140)
    a = p.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    per_session = int(a.session_minutes * a.words_per_minute)
    count = max(1, round(a.minutes / a.session_minutes))
    parts = sessions(book_paragraphs(a.source), per_session, count)
    a.out.mkdir(parents=True, exist_ok=True)
    for n, part in enumerate(parts, 1):
        (a.out / f'felolvasas_{n:02d}.txt').write_text('\n\n'.join(part) + '\n', encoding='utf-8')
        words = sum(len(x.split()) for x in part)
        print(f'felolvasas_{n:02d}.txt: {words} szó, kb. {words / a.words_per_minute:.0f} perc', flush=True)
    (a.out / 'UTMUTATO.txt').write_text(GUIDE, encoding='utf-8')


if __name__ == '__main__':
    main()
