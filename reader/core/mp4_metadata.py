"""Add UTF-8 iTunes freeform fields to a terminal MP4 moov atom.

FFmpeg writes standard title/cover atoms. Its alternative mdta mode drops
covers, so append the additional book fields without moving audio chunks.
Only FFmpeg's own freshly generated, non-faststart output is accepted here.
"""
import struct


def _atom(kind, data):
    return struct.pack('>I4s', len(data) + 8, kind) + data


def add_book_tags(path, tags):
    payload = b''
    for key, value in tags.items():
        if value:
            payload += _atom(b'----', _atom(b'mean', b'\0' * 4 + b'com.apple.iTunes')
                             + _atom(b'name', b'\0' * 4 + key.encode('utf-8'))
                             + _atom(b'data', b'\0\0\0\1' + b'\0' * 4 + str(value).encode('utf-8')))
    if not payload:
        return
    with open(path, 'r+b') as file:
        file.seek(0, 2)
        length = file.tell()
        offset = 0
        while offset + 8 <= length:
            file.seek(offset)
            size, kind = struct.unpack('>I4s', file.read(8))
            if size == 1:
                size = struct.unpack('>Q', file.read(8))[0]
            if size < 8 or offset + size > length:
                raise ValueError('Invalid generated MP4 atom')
            if kind == b'moov':
                if offset + size != length or size > 256 * 1024**2:
                    raise ValueError('Expected a terminal MP4 moov atom')
                file.seek(offset)
                moov = bytearray(file.read(size))
                break
            offset += size
        else:
            raise ValueError('Missing MP4 moov atom')
        ancestors = [0]
        start, end = 8, len(moov)
        for wanted in (b'udta', b'meta', b'ilst'):
            pos = start
            while pos + 8 <= end:
                child_size, kind = struct.unpack_from('>I4s', moov, pos)
                if child_size < 8 or pos + child_size > end:
                    raise ValueError('Invalid MP4 metadata atom')
                if kind == wanted:
                    ancestors.append(pos)
                    start, end = pos + 8 + (4 if kind == b'meta' else 0), pos + child_size
                    break
                pos += child_size
            else:
                raise ValueError('Missing MP4 metadata container')
        for pos in ancestors:
            struct.pack_into('>I', moov, pos, struct.unpack_from('>I', moov, pos)[0] + len(payload))
        moov[end:end] = payload
        file.seek(offset)
        file.write(moov)
        file.truncate()
