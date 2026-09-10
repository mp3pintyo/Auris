"""Mobipocket / PalmDOC reader for ``.prc`` (and the identical ``.mobi``) files.

A ``.prc`` book is a Palm Database (PDB) container.  Record 0 holds the
PalmDOC header — and, for Mobipocket books, a MOBI header and an EXTH
metadata block after it.  The records that follow hold the compressed book
text, then the images.

The module is deliberately dependency-free: ``scripts/prc_to_epub.py`` runs it
as a standalone converter outside the app venv, and ``prc_parser`` uses it for
direct import.
"""

import re
import struct
from html import escape, unescape
from html.parser import HTMLParser

PDB_HEADER_LEN = 78
RECORD_INFO_LEN = 8

NO_COMPRESSION = 1
PALMDOC_COMPRESSION = 2
HUFFDIC_COMPRESSION = 17480

# EXTH record types we care about.
EXTH_AUTHOR = 100
EXTH_PUBLISHER = 101
EXTH_DESCRIPTION = 103
EXTH_ISBN = 104
EXTH_SUBJECT = 105
EXTH_PUBDATE = 106
EXTH_COVER_OFFSET = 201
EXTH_THUMB_OFFSET = 202
EXTH_UPDATED_TITLE = 503
EXTH_LANGUAGE = 524


class MobiError(Exception):
    """Raised when a file is not a readable Mobipocket/PalmDOC book."""


# ── Palm database container ──────────────────────────────────────────────────

def _read_pdb(data):
    """Split a Palm database into (name, 8-byte type+creator, [record bytes])."""
    if len(data) < PDB_HEADER_LEN:
        raise MobiError('File is too small to be a Palm database')

    name = data[0:32].split(b'\x00')[0].decode('latin-1', 'replace')
    ident = data[60:68]
    count = struct.unpack_from('>H', data, 76)[0]

    end_of_index = PDB_HEADER_LEN + count * RECORD_INFO_LEN
    if count == 0 or len(data) < end_of_index:
        raise MobiError('Palm database record index is truncated')

    offsets = [
        struct.unpack_from('>L', data, PDB_HEADER_LEN + i * RECORD_INFO_LEN)[0]
        for i in range(count)
    ]
    offsets.append(len(data))

    records = []
    for i in range(count):
        start = min(offsets[i], len(data))
        end = offsets[i + 1]
        if end < start or end > len(data):
            end = len(data)
        records.append(data[start:end])
    return name, ident, records


# ── Decompression ────────────────────────────────────────────────────────────

def decompress_palmdoc(data):
    """PalmDOC LZ77: literals, 8-byte literal runs, back-references, space pairs."""
    out = bytearray()
    i = 0
    size = len(data)
    while i < size:
        byte = data[i]
        i += 1
        if byte == 0x00:
            out.append(byte)
        elif byte <= 0x08:                      # copy the next `byte` literals
            out += data[i:i + byte]
            i += byte
        elif byte <= 0x7F:                      # plain literal
            out.append(byte)
        elif byte <= 0xBF:                      # back-reference (2 bytes)
            if i >= size:
                break
            pair = (byte << 8) | data[i]
            i += 1
            distance = (pair >> 3) & 0x07FF
            length = (pair & 0x07) + 3
            start = len(out) - distance
            if distance == 0 or start < 0:
                break
            for offset in range(length):        # may overlap its own output
                out.append(out[start + offset])
        else:                                   # space + literal
            out.append(0x20)
            out.append(byte ^ 0x80)
    return bytes(out)


class HuffcdicReader:
    """HUFF/CDIC decompressor (compression type 17480)."""

    _q = struct.Struct('>Q').unpack_from

    def __init__(self):
        self.dict1 = []
        self.mincode = ()
        self.maxcode = ()
        self.dictionary = []

    def load_huff(self, huff):
        if huff[0:8] != b'HUFF\x00\x00\x00\x18':
            raise MobiError('Invalid HUFF record')
        off1, off2 = struct.unpack_from('>LL', huff, 8)

        def unpack_entry(value):
            codelen, term, maxcode = value & 0x1F, value & 0x80, value >> 8
            if codelen == 0:
                raise MobiError('Corrupt HUFF table')
            if codelen <= 8 and not term:
                raise MobiError('Corrupt HUFF table')
            return codelen, term, ((maxcode + 1) << (32 - codelen)) - 1

        self.dict1 = [unpack_entry(v) for v in struct.unpack_from('>256L', huff, off1)]

        dict2 = struct.unpack_from('>64L', huff, off2)
        self.mincode = tuple(
            mincode << (32 - codelen) for codelen, mincode in enumerate(dict2[0::2])
        )
        self.maxcode = tuple(
            ((maxcode + 1) << (32 - codelen)) - 1
            for codelen, maxcode in enumerate(dict2[1::2])
        )
        self.dictionary = []

    def load_cdic(self, cdic):
        if cdic[0:8] != b'CDIC\x00\x00\x00\x10':
            raise MobiError('Invalid CDIC record')
        phrases, bits = struct.unpack_from('>LL', cdic, 8)
        n = min(1 << bits, phrases - len(self.dictionary))
        if n <= 0:
            return
        for offset in struct.unpack_from('>%dH' % n, cdic, 16):
            blen = struct.unpack_from('>H', cdic, 16 + offset)[0]
            slice_ = cdic[18 + offset:18 + offset + (blen & 0x7FFF)]
            self.dictionary.append((slice_, blen & 0x8000))

    def unpack(self, data):
        bitsleft = len(data) * 8
        data += b'\x00' * 8
        pos = 0
        x = self._q(data, pos)[0]
        n = 32

        out = []
        while True:
            if n <= 0:
                pos += 4
                x = self._q(data, pos)[0]
                n += 32
            code = (x >> n) & 0xFFFFFFFF

            codelen, term, maxcode = self.dict1[code >> 24]
            if not term:
                while code < self.mincode[codelen]:
                    codelen += 1
                maxcode = self.maxcode[codelen]

            n -= codelen
            bitsleft -= codelen
            if bitsleft < 0:
                break

            index = (maxcode - code) >> (32 - codelen)
            if index >= len(self.dictionary):
                raise MobiError('HUFF/CDIC dictionary reference out of range')
            slice_, flag = self.dictionary[index]
            if not flag:
                # Nested entry: expand it once and cache the expansion.
                self.dictionary[index] = (b'', 1)
                slice_ = self.unpack(slice_)
                self.dictionary[index] = (slice_, 1)
            out.append(slice_)
        return b''.join(out)


def _trailing_entry_size(record, size):
    bitpos, result = 0, 0
    while size > 0:
        value = record[size - 1]
        result |= (value & 0x7F) << bitpos
        bitpos += 7
        size -= 1
        if value & 0x80 or bitpos >= 28 or size == 0:
            break
    return result


def _trailing_size(record, flags):
    """Bytes of index/multibyte overlap data appended to a text record."""
    num = 0
    size = len(record)
    testflags = flags >> 1
    while testflags:
        if testflags & 1:
            num += _trailing_entry_size(record, size - num)
        testflags >>= 1
    if flags & 1 and size - num - 1 >= 0:
        num += (record[size - num - 1] & 0x03) + 1
    return min(num, size)


# ── Images ───────────────────────────────────────────────────────────────────

_IMAGE_MAGIC = (
    (b'\xff\xd8\xff', 'jpeg', '.jpg'),
    (b'\x89PNG\r\n\x1a\n', 'png', '.png'),
    (b'GIF87a', 'gif', '.gif'),
    (b'GIF89a', 'gif', '.gif'),
    (b'BM', 'bmp', '.bmp'),
)


def image_kind(data):
    """Return ``(mediatype_suffix, file_extension)`` or ``None``."""
    for magic, kind, ext in _IMAGE_MAGIC:
        if data.startswith(magic):
            return kind, ext
    return None


# ── HTML helpers ─────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r'<[^>]*>')
_BLOCK_TAGS = {
    'p', 'div', 'section', 'article', 'header', 'footer', 'li', 'ul', 'ol',
    'tr', 'td', 'th', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'br', 'hr', 'center', 'pre',
}
# MOBI markup is HTML 3.2 flavoured.  Keep what carries meaning, map the rest
# onto XHTML equivalents, drop everything else.
_TAG_MAP = {
    'p': 'p', 'div': 'div', 'br': 'br', 'hr': 'hr',
    'h1': 'h1', 'h2': 'h2', 'h3': 'h3', 'h4': 'h4', 'h5': 'h5', 'h6': 'h6',
    'b': 'b', 'strong': 'strong', 'i': 'i', 'em': 'em',
    'blockquote': 'blockquote', 'ul': 'ul', 'ol': 'ol', 'li': 'li',
    'sup': 'sup', 'sub': 'sub', 'span': 'span', 'pre': 'pre',
    'table': 'table', 'tr': 'tr', 'td': 'td', 'th': 'th',
    'center': 'div', 'font': 'span', 'big': 'span', 'small': 'span',
    'u': 'span', 'a': 'span', 'img': 'img',
}
_VOID_TAGS = {'br', 'hr', 'img'}
_DROP_CONTENT_TAGS = {'script', 'style', 'head', 'title'}


def strip_tags(fragment):
    """Plain text of an HTML fragment, whitespace collapsed."""
    if isinstance(fragment, bytes):
        fragment = fragment.decode('utf-8', 'replace')
    return re.sub(r'\s+', ' ', unescape(_TAG_RE.sub(' ', fragment))).strip()


class _LineExtractor(HTMLParser):
    """Collect the visible text of a document as one line per block element."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def _line_break(self):
        if not self.parts or self.parts[-1] != '\n':
            self.parts.append('\n')

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_CONTENT_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._line_break()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_CONTENT_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self._line_break()

    def handle_data(self, data):
        if self._skip == 0 and data:
            self.parts.append(data)

    def get_lines(self):
        raw = ''.join(self.parts).replace('\xa0', ' ').replace('\r', '\n')
        lines = []
        for line in raw.splitlines():
            normalized = re.sub(r'\s+', ' ', line).strip()
            if normalized:
                lines.append(normalized)
        return lines


def html_to_lines(html):
    parser = _LineExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_lines()


class _XhtmlWriter(HTMLParser):
    """Re-serialize MOBI markup as well-formed XHTML using a tag whitelist."""

    def __init__(self, image_src=None):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.image_src = image_src or {}
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_CONTENT_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        name = _TAG_MAP.get(tag)
        if not name:
            return
        if name in _VOID_TAGS:
            if name == 'img':
                self._write_image(dict(attrs))
            else:
                self.out.append('<%s/>' % name)
            return
        self.out.append('<%s>' % name)
        self.stack.append(name)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        name = _TAG_MAP.get(tag)
        if self._skip or not name:
            return
        if name in _VOID_TAGS:
            self.handle_starttag(tag, attrs)
        else:
            self.out.append('<%s></%s>' % (name, name))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_CONTENT_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        name = _TAG_MAP.get(tag)
        if not name or name in _VOID_TAGS or name not in self.stack:
            return
        while self.stack:                       # close anything left open inside
            top = self.stack.pop()
            self.out.append('</%s>' % top)
            if top == name:
                break

    def handle_data(self, data):
        if self._skip == 0 and data:
            self.out.append(escape(data, quote=False))

    def _write_image(self, attrs):
        recindex = attrs.get('recindex') or attrs.get('lowrecindex')
        src = None
        if recindex and recindex.strip().isdigit():
            src = self.image_src.get(int(recindex.strip()))
        if src:
            self.out.append('<img src="%s" alt=""/>' % escape(src, quote=True))

    def result(self):
        while self.stack:
            self.out.append('</%s>' % self.stack.pop())
        return ''.join(self.out)


def html_to_xhtml(html, image_src=None):
    """Whitelist-clean an HTML fragment into balanced XHTML."""
    writer = _XhtmlWriter(image_src)
    writer.feed(html)
    writer.close()
    body = writer.result().strip()
    return '<div>%s</div>' % body if body else '<div/>'


def text_to_xhtml(text):
    """Wrap plain PalmDOC text as XHTML paragraphs."""
    blocks = re.split(r'\n\s*\n', text.replace('\r\n', '\n').replace('\r', '\n'))
    parts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = [escape(line.strip(), quote=False) for line in block.split('\n') if line.strip()]
        parts.append('<p>%s</p>' % '<br/>'.join(lines))
    return '<div>%s</div>' % ''.join(parts) if parts else '<div/>'


# ── Section splitting ────────────────────────────────────────────────────────

_ANCHOR_RE = re.compile(rb'<a\b[^>]*?filepos=["\']?0*(\d+)[^>]*>(.*?)</a>', re.I | re.S)
_PAGEBREAK_RE = re.compile(rb'<mbp:pagebreak[^>]*>', re.I)
_HEADING_RE = re.compile(rb'<h([1-3])\b[^>]*>(.*?)</h[1-3]>', re.I | re.S)

# Two TOC links more than this far apart in the source are not the same list.
_TOC_CLUSTER_GAP = 4096
MIN_TOC_LINKS = 3


def _anchor_clusters(raw):
    anchors = [
        (match.start(), match.end(), int(match.group(1)), strip_tags(match.group(2)))
        for match in _ANCHOR_RE.finditer(raw)
    ]
    clusters = []
    for anchor in anchors:
        if clusters and anchor[0] - clusters[-1][-1][1] <= _TOC_CLUSTER_GAP:
            clusters[-1].append(anchor)
        else:
            clusters.append([anchor])
    return clusters


def _titles_from_html(chunk):
    match = _HEADING_RE.search(chunk)
    if match:
        title = strip_tags(match.group(2))
        if title:
            return title[:160]
    for line in html_to_lines(chunk.decode('utf-8', 'replace'))[:3]:
        if 0 < len(line) <= 120:
            return line
    return ''


def _sections_from_offsets(raw, offsets, titles, drop_span=None):
    if drop_span:
        start, end = drop_span
        raw = raw[:start] + b' ' * (end - start) + raw[end:]

    bounds = sorted({o for o in offsets if 0 < o < len(raw)})
    sections = []
    starts = [0] + bounds
    ends = bounds + [len(raw)]
    for start, end in zip(starts, ends):
        chunk = raw[start:end]
        if not chunk.strip():
            continue
        sections.append({
            'title': titles.get(start) or _titles_from_html(chunk),
            'html': chunk,
            'offset': start,
        })
    return sections


def split_html_sections(raw):
    """Split the raw MOBI HTML into chapter-sized pieces.

    Uses the book's own TOC links (``filepos`` anchors) when it has them,
    then ``<mbp:pagebreak>`` markers, then top-level headings.
    """
    clusters = [c for c in _anchor_clusters(raw) if len(c) >= MIN_TOC_LINKS]
    if clusters:
        toc = max(clusters, key=len)
        titles = {}
        for _, _, target, text in toc:
            if text and target not in titles:
                titles[target] = text[:160]
        sections = _sections_from_offsets(
            raw,
            [target for _, _, target, _ in toc],
            titles,
            drop_span=(toc[0][0], toc[-1][1]),
        )
        if len(sections) >= MIN_TOC_LINKS:
            return sections

    breaks = [match.start() for match in _PAGEBREAK_RE.finditer(raw)]
    if len(breaks) >= 2:
        return _sections_from_offsets(raw, breaks, {})

    headings = [match.start() for match in _HEADING_RE.finditer(raw)]
    if len(headings) >= 2:
        return _sections_from_offsets(raw, headings, {})

    return _sections_from_offsets(raw, [], {})


# ── The book ─────────────────────────────────────────────────────────────────

class MobiBook:
    """A parsed ``.prc``/``.mobi`` book."""

    def __init__(self, data):
        self.db_name, self.ident, self.records = _read_pdb(data)
        if self.ident not in (b'BOOKMOBI', b'TEXtREAd'):
            raise MobiError(
                'Not a Mobipocket or PalmDOC book (Palm type %r)'
                % self.ident.decode('latin-1', 'replace')
            )

        record0 = self.records[0]
        if len(record0) < 16:
            raise MobiError('PalmDOC header is truncated')

        compression, = struct.unpack_from('>H', record0, 0)
        text_length, = struct.unpack_from('>L', record0, 4)
        text_records, = struct.unpack_from('>H', record0, 8)
        encryption, = struct.unpack_from('>H', record0, 12)
        if encryption:
            raise MobiError(
                'The book is DRM-protected (encryption type %d) and cannot be converted'
                % encryption
            )

        self.encoding = 'cp1252'
        self.exth = {}
        first_image = 0
        huff_offset = huff_count = 0
        extra_flags = 0
        full_name = ''

        if self.records[0][16:20] == b'MOBI':
            mobi_len, = struct.unpack_from('>L', record0, 20)
            limit = min(16 + mobi_len, len(record0))

            def field(offset):
                if offset + 4 > limit:
                    return 0
                return struct.unpack_from('>L', record0, offset)[0]

            self.encoding = {65001: 'utf-8', 1252: 'cp1252'}.get(field(28), 'cp1252')
            name_offset, name_length = field(0x54), field(0x58)
            first_image = field(0x6C)
            huff_offset, huff_count = field(0x70), field(0x74)
            exth_flags = field(0x80)
            if mobi_len >= 0xE4 and len(record0) >= 0xF4:
                extra_flags, = struct.unpack_from('>H', record0, 0xF2)
            if name_offset and name_length:
                full_name = record0[name_offset:name_offset + name_length].decode(
                    self.encoding, 'replace'
                )
            if exth_flags & 0x40:
                self.exth = _parse_exth(record0, 16 + mobi_len)

        self.raw = self._decompress(
            compression, text_records, text_length, huff_offset, huff_count, extra_flags
        )
        self.images = self._read_images(first_image)
        self.cover_index = self._find_cover(first_image)
        self.cover = self.images.get(self.cover_index) if self.cover_index else None

        self.title = (
            self._exth_str(EXTH_UPDATED_TITLE) or full_name or self.db_name or 'Unknown Title'
        )
        self.author = self._exth_str(EXTH_AUTHOR) or 'Unknown Author'
        self.publisher = self._exth_str(EXTH_PUBLISHER)
        self.description = self._exth_str(EXTH_DESCRIPTION)
        self.isbn = self._exth_str(EXTH_ISBN)
        self.subject = self._exth_str(EXTH_SUBJECT)
        self.pubdate = self._exth_str(EXTH_PUBDATE)
        self.language = (self._exth_str(EXTH_LANGUAGE) or '').replace('_', '-')

        head = self.raw[:4096].lower()
        self.is_html = b'<html' in head or b'<body' in head or b'<p>' in head or b'<p ' in head

    # -- helpers ------------------------------------------------------------

    def _exth_str(self, record_type):
        values = self.exth.get(record_type)
        if not values:
            return ''
        return values[0].decode(self.encoding, 'replace').strip()

    def _decompress(self, compression, text_records, text_length, huff_offset,
                    huff_count, extra_flags):
        if compression == NO_COMPRESSION:
            unpack = lambda chunk: chunk  # noqa: E731 - trivial passthrough
        elif compression == PALMDOC_COMPRESSION:
            unpack = decompress_palmdoc
        elif compression == HUFFDIC_COMPRESSION:
            if not huff_offset or huff_offset >= len(self.records):
                raise MobiError('HUFF/CDIC book is missing its dictionary records')
            reader = HuffcdicReader()
            reader.load_huff(self.records[huff_offset])
            for index in range(1, huff_count):
                if huff_offset + index < len(self.records):
                    reader.load_cdic(self.records[huff_offset + index])
            unpack = reader.unpack
        else:
            raise MobiError('Unsupported compression type %d' % compression)

        parts = []
        for index in range(1, min(text_records, len(self.records) - 1) + 1):
            record = self.records[index]
            trailing = _trailing_size(record, extra_flags)
            if trailing:
                record = record[:len(record) - trailing]
            parts.append(unpack(record))
        raw = b''.join(parts)
        return raw[:text_length] if text_length else raw

    def _read_images(self, first_image):
        images = {}
        if not first_image:
            return images
        for index in range(first_image, len(self.records)):
            record = self.records[index]
            kind = image_kind(record)
            if kind:
                images[index - first_image + 1] = {
                    'media_type': 'image/%s' % kind[0],
                    'extension': kind[1],
                    'data': record,
                }
        return images

    def _find_cover(self, first_image):
        for record_type in (EXTH_COVER_OFFSET, EXTH_THUMB_OFFSET):
            values = self.exth.get(record_type)
            if not values or len(values[0]) < 4:
                continue
            offset, = struct.unpack('>L', values[0][:4])
            if offset + 1 in self.images:
                return offset + 1
        # No EXTH pointer: the first image in a MOBI is conventionally the cover.
        if self.images and first_image:
            return min(self.images)
        return None

    # -- content ------------------------------------------------------------

    @property
    def text(self):
        return self.raw.decode(self.encoding, 'replace')

    def image_filenames(self):
        """Record index → path inside the EPUB.

        The cover is named ``cover.…`` on purpose: ebooklib only reports
        jpeg/png/svg as EPUB cover items, so readers built on it (Auris
        included) fall back to matching "cover" in the file name, which is
        how a GIF cover — common in older .prc books — survives the trip.
        """
        names = {}
        for index, image in self.images.items():
            if index == self.cover_index:
                names[index] = 'images/cover%s' % image['extension']
            else:
                names[index] = 'images/img%05d%s' % (index, image['extension'])
        return names

    def sections(self):
        """Chapter-sized pieces as ``{'title', 'html', 'lines'}`` dicts."""
        if not self.is_html:
            text = self.text
            return [{
                'title': self.title,
                'html': text_to_xhtml(text),
                'lines': [line.strip() for line in text.splitlines() if line.strip()],
            }]

        names = self.image_filenames()
        out = []
        for section in split_html_sections(self.raw):
            html = section['html'].decode(self.encoding, 'replace')
            out.append({
                'title': section['title'],
                'html': html_to_xhtml(html, names),
                'lines': html_to_lines(html),
            })
        return out


def _parse_exth(record0, start):
    exth = {}
    if record0[start:start + 4] != b'EXTH':
        return exth
    try:
        _, count = struct.unpack_from('>LL', record0, start + 4)
    except struct.error:
        return exth
    position = start + 12
    for _ in range(count):
        if position + 8 > len(record0):
            break
        record_type, record_len = struct.unpack_from('>LL', record0, position)
        if record_len < 8:
            break
        exth.setdefault(record_type, []).append(record0[position + 8:position + record_len])
        position += record_len
    return exth


def read(path):
    """Read a ``.prc``/``.mobi`` file into a :class:`MobiBook`."""
    if isinstance(path, (bytes, bytearray)):
        return MobiBook(bytes(path))
    with open(path, 'rb') as handle:
        return MobiBook(handle.read())
