"""Prepare local documents and public web articles for Auris imports."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from core.parser import docx_parser, epub_parser, pdf_parser, txt_parser
from core.parser.language import detect_language


DOWNLOAD_TIMEOUT_SECONDS = 10
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_USER_AGENT = "Auris/1.0 article importer"


def _content_hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_readable_chapters(result: dict, *, web: bool = False) -> dict:
    chapters = result.get("chapters") or []
    readable = [chapter for chapter in chapters if (chapter.get("content") or "").strip()]
    if not readable:
        if web:
            raise ValueError(
                "A weboldalból nem sikerült olvasható cikkszöveget kinyerni. "
                "Ellenőrizd, hogy a tartalom bejelentkezés és JavaScript nélkül is elérhető."
            )
        raise ValueError(
            "A dokumentumban nincs olvasható szövegréteg. Ha ez egy szkennelt "
            "PDF, importálás előtt OCR-rel kell szövegfelismerést végezni rajta."
        )
    result["chapters"] = readable
    return result


def prepare_file(path) -> dict:
    """Parse a local document and add a SHA-256 hash of its original bytes."""
    source = Path(path)
    if not source.is_file():
        raise ValueError("A kiválasztott dokumentum nem található.")

    parsers = {
        ".epub": epub_parser.parse,
        ".pdf": pdf_parser.parse,
        ".docx": docx_parser.parse,
        ".txt": txt_parser.parse,
    }
    parser = parsers.get(source.suffix.lower())
    if parser is None:
        raise ValueError("Nem támogatott fájltípus. Használj EPUB, PDF, DOCX vagy TXT fájlt.")

    result = parser(str(source))
    _ensure_readable_chapters(result)
    result["content_hash"] = _file_content_hash(source)
    return result


def prepare_html(html, url) -> dict:
    """Extract article metadata and paragraphs from already downloaded HTML."""
    try:
        from trafilatura import bare_extraction
    except ImportError as exc:  # pragma: no cover - installation error path
        raise RuntimeError("A webcikk-importhoz telepíteni kell a Trafilatura csomagot.") from exc

    if isinstance(html, bytes):
        raw_html = html
        extraction_input = html
    elif isinstance(html, str):
        raw_html = html.encode("utf-8")
        extraction_input = html
    else:
        raise ValueError("A weboldal tartalma csak szöveg vagy bájtsorozat lehet.")

    try:
        document = bare_extraction(
            extraction_input,
            url=str(url),
            with_metadata=True,
            include_comments=False,
            include_tables=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("A weboldal cikkszövege nem dolgozható fel.") from exc

    text = (getattr(document, "text", "") or "").strip() if document else ""
    if not text or len(text.split()) < 10:
        return _ensure_readable_chapters({"chapters": []}, web=True)

    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    content = "\n\n".join(paragraphs)
    title = (getattr(document, "title", "") or "").strip()
    author = (getattr(document, "author", "") or "").strip()
    language = (getattr(document, "language", "") or "").strip()[:2]
    if not language:
        language = detect_language(content)
    if not title:
        title = urlsplit(str(url)).hostname or "Webcikk"

    result = {
        "title": title,
        "author": author or "Unknown Author",
        "language": language,
        "cover_b64": None,
        "chapters": [
            {
                "title": title,
                "order_num": 0,
                "content": content,
                "word_count": len(content.split()),
            }
        ],
        "source_url": str(url),
        "content_hash": _content_hash_bytes(raw_html),
    }
    return _ensure_readable_chapters(result, web=True)


def _parsed_public_url(url: str):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("Érvénytelen webcím.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Csak publikus HTTP(S) webcím importálható.")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Érvénytelen publikus HTTP(S) webcím.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("A webcím nem publikus hálózati címre mutat.")
    return parsed, hostname, port or (443 if parsed.scheme.lower() == "https" else 80)


def _resolve_public_addresses(hostname, port) -> list[str]:
    try:
        literal = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal = None

    if literal is not None:
        if not literal.is_global:
            raise ValueError("A webcím nem publikus hálózati címre mutat.")
        return [str(literal)]

    try:
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise ValueError("A webcím hálózati címe nem oldható fel.") from exc

    addresses = []
    for answer in answers:
        address = answer[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("A webcím hálózati címe érvénytelen.") from exc
        if not ip.is_global:
            raise ValueError("A webcím nem kizárólag publikus hálózati címre mutat.")
        normalized = str(ip)
        if normalized not in addresses:
            addresses.append(normalized)

    if not addresses:
        raise ValueError("A webcímhez nem található hálózati cím.")
    return addresses


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname, port, pinned_ip):
        super().__init__(hostname, port=port, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, port, pinned_ip):
        super().__init__(
            hostname,
            port=port,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        self._pinned_ip = pinned_ip

    def connect(self):
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _download_once(url, resolved_ip):
    parsed, hostname, port = _parsed_public_url(url)
    connection_class = (
        _PinnedHTTPSConnection if parsed.scheme.lower() == "https" else _PinnedHTTPConnection
    )
    connection = connection_class(hostname, port, resolved_ip)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}

        declared_length = headers.get("content-length")
        if declared_length:
            try:
                declared_length_value = int(declared_length)
            except ValueError as exc:
                raise ValueError("A weboldal hibás Content-Length fejlécet küldött.") from exc
            if declared_length_value > MAX_DOWNLOAD_BYTES:
                raise ValueError("A weboldal nagyobb az engedélyezett 5 MB-nál.")

        body = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(body) > MAX_DOWNLOAD_BYTES:
            raise ValueError("A weboldal nagyobb az engedélyezett 5 MB-nál.")
        return response.status, headers, body
    except ValueError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise ValueError("A weboldal nem tölthető le a megadott időkorláton belül.") from exc
    finally:
        connection.close()


def _fetch_public_html(url: str):
    current_url = str(url)
    for redirect_count in range(MAX_REDIRECTS + 1):
        _parsed, hostname, port = _parsed_public_url(current_url)
        addresses = _resolve_public_addresses(hostname, port)
        status, headers, body = _download_once(current_url, addresses[0])

        if status in _REDIRECT_STATUSES:
            location = headers.get("location")
            if not location:
                raise ValueError("A weboldal hiányos átirányítási választ adott.")
            if redirect_count >= MAX_REDIRECTS:
                raise ValueError("A weboldal túl sok átirányítást használ.")
            current_url = urljoin(current_url, location)
            continue

        if not 200 <= status < 300:
            raise ValueError(f"A weboldal HTTP {status} hibával válaszolt.")

        content_encoding = headers.get("content-encoding", "identity").lower()
        if content_encoding not in {"", "identity"}:
            raise ValueError("A weboldal nem támogatott tömörített választ küldött.")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
            raise ValueError("A webcím nem HTML-oldalra mutat.")
        return body, current_url

    raise ValueError("A weboldal túl sok átirányítást használ.")


def prepare_url(url) -> dict:
    """Download a public HTTP(S) article safely and prepare it for preview."""
    try:
        html, final_url = _fetch_public_html(str(url))
        return prepare_html(html, final_url)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("A webcikk importálása nem sikerült.") from exc
