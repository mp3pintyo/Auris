import struct
import tempfile
import unittest
from pathlib import Path

from core import import_service
from core.parser import mobi, prc_parser


def build_pdb(records, ident=b'TEXtREAd', name=b'Tesztkonyv'):
    header = bytearray(78)
    header[0:32] = name.ljust(32, b'\0')[:32]
    header[60:68] = ident
    struct.pack_into('>H', header, 76, len(records))
    offset = 78 + len(records) * 8
    index = bytearray()
    for position, record in enumerate(records):
        index += struct.pack('>L', offset) + b'\0' + struct.pack('>L', position)[1:]
        offset += len(record)
    return bytes(header) + bytes(index) + b''.join(records)


def build_palmdoc(text, *, encrypted=False):
    raw = text.encode('cp1252')
    record0 = bytearray(16)
    struct.pack_into('>H', record0, 0, mobi.NO_COMPRESSION)
    struct.pack_into('>L', record0, 4, len(raw))
    struct.pack_into('>H', record0, 8, 1)
    struct.pack_into('>H', record0, 10, 4096)
    struct.pack_into('>H', record0, 12, 1 if encrypted else 0)
    return build_pdb([bytes(record0), raw])


class PrcImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def write(self, data, name='book.prc'):
        path = Path(self.temp.name) / name
        path.write_bytes(data)
        return path

    def test_plain_palmdoc_uses_hungarian_chapter_detection(self):
        paragraph = ' '.join(['Az egyik ember es egy masik ember, aki nem marad csendben.'] * 30)
        text = f'Tesztkonyv\n\nELSO FEJEZET\n\n{paragraph}\n\nMASODIK FEJEZET\n\n{paragraph}'
        parsed = prc_parser.parse(self.write(build_palmdoc(text)))
        self.assertEqual([chapter['title'] for chapter in parsed['chapters']], [
            'ELSO FEJEZET', 'MASODIK FEJEZET'
        ])
        self.assertEqual(parsed['language'], 'hu')

    def test_import_service_accepts_mobi_extension(self):
        paragraph = ' '.join(['Readable story text.'] * 70)
        path = self.write(build_palmdoc(paragraph), 'book.mobi')
        parsed = import_service.prepare_file(path)
        self.assertTrue(parsed['chapters'])
        self.assertEqual(len(parsed['content_hash']), 64)

    def test_drm_protected_book_is_rejected(self):
        path = self.write(build_palmdoc('Titkos könyv', encrypted=True))
        with self.assertRaisesRegex(mobi.MobiError, 'DRM'):
            prc_parser.parse(path)

    def test_non_palm_file_is_rejected(self):
        path = self.write(b'PK\x03\x04' + b'\0' * 100)
        with self.assertRaises(mobi.MobiError):
            prc_parser.parse(path)


if __name__ == '__main__':
    unittest.main()
