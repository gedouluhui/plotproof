"""Bounded subprocess-only PDFium input. This does not establish wrapper provenance."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import ceil
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib

from .evidence import PdfChar
from .geometry import Rect, finite_number

_CEILINGS = {'max_bytes': 16 * 1024 * 1024, 'max_chars': 200_000,
             'max_pixels': 16_000_000, 'max_output_bytes': 64 * 1024 * 1024}
# PDFium exposes page dimensions at binary32 precision. Compare against the
# same representation of A2 rather than rejecting a rounded-up legal boundary.
_A2 = tuple(struct.unpack('f', struct.pack('f', value))[0]
            for value in (420 * 72 / 25.4, 594 * 72 / 25.4))
_ERRORS = {
    'invalid_input': 'Invalid PDF reader argument.', 'file_error': 'Cannot read the local PDF file.',
    'input_limit': 'PDF input exceeds the byte limit.', 'hash_mismatch': 'PDF hash differs from the expected hash.',
    'invalid_pdf': 'PDF cannot be parsed.', 'encrypted_pdf': 'Encrypted PDFs are unsupported.',
    'page_count': 'Exactly one PDF page is required.', 'page_rotation': 'Rotated PDF pages are unsupported.',
    'page_boxes': 'PDF media and crop boxes must match with origin zero.',
    'page_size': 'PDF page must have a finite positive size no larger than A2.',
    'character_limit': 'PDF text exceeds the character limit.', 'pixel_limit': 'PDF raster exceeds the pixel limit.',
    'timeout': 'PDF worker exceeded its wall-time limit.', 'output_limit': 'PDF worker exceeded its output limit.',
    'worker_crash': 'PDF worker failed.', 'worker_protocol': 'PDF worker returned invalid evidence.',
    'worker_internal': 'PDF worker could not complete the request.',
}


class PdfReadError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason if reason in _ERRORS else 'worker_protocol'
        super().__init__(_ERRORS[self.reason])


@dataclass(frozen=True)
class PdfLimits:
    max_bytes: int = _CEILINGS['max_bytes']
    max_chars: int = _CEILINGS['max_chars']
    max_pixels: int = _CEILINGS['max_pixels']
    max_output_bytes: int = _CEILINGS['max_output_bytes']
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for field, ceiling in _CEILINGS.items():
            value = getattr(self, field)
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError(f'{field} must be an integer in [1, {ceiling}]')
        value = finite_number(self.timeout_seconds, 'timeout_seconds')
        if not 0 < value <= 30:
            raise ValueError('timeout_seconds must be in (0, 30]')
        object.__setattr__(self, 'timeout_seconds', value)


@dataclass(frozen=True)
class PdfRender:
    width: int
    height: int
    mode: str
    png_bytes: bytes


@dataclass(frozen=True)
class PdfSnapshot:
    input_sha256: str
    pypdfium2_version: str
    pdfium_version: str
    page_count: int
    page_size_pt: tuple[float, float]
    cropbox: Rect
    mediabox: Rect
    rotation: int
    characters: tuple[PdfChar, ...]
    render: PdfRender | None


def _render_size(size: tuple[float, float], scale: float, limits: PdfLimits) -> tuple[int, int]:
    width, height = (ceil(side * scale) for side in size)
    if width <= 0 or height <= 0 or width * height > limits.max_pixels:
        raise PdfReadError('pixel_limit')
    return width, height


def _validate_page(count, rotation, size, media, crop) -> tuple[tuple[float, float], Rect, Rect]:
    if type(count) is not int or count != 1:
        raise PdfReadError('page_count')
    if type(rotation) is not int or rotation != 0:
        raise PdfReadError('page_rotation')
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise PdfReadError('page_size')
    try:
        width, height = (finite_number(v, 'page dimension') for v in size)
        media, crop = Rect(*media), Rect(*crop)
    except (ValueError, TypeError, OverflowError):
        raise PdfReadError('page_size') from None
    if (width <= 0 or height <= 0 or media.area <= 0 or crop.area <= 0
            or not ((width <= _A2[0] and height <= _A2[1])
                    or (width <= _A2[1] and height <= _A2[0]))):
        raise PdfReadError('page_size')
    if media != crop or media != Rect(0, 0, width, height):
        raise PdfReadError('page_boxes')
    return (width, height), media, crop


def _worker_command(limits: PdfLimits, scale: float | None) -> list[str]:
    config = json.dumps({'limits': asdict(limits), 'render_scale': scale}, allow_nan=False)
    return [sys.executable, '-I', str(Path(__file__).with_name('_pdf_worker.py')), config]


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('nonfinite JSON constant')


def _run_worker(data: bytes, limits: PdfLimits, scale: float | None) -> dict:
    """Nonblocking pipes with a single deadline; no transport threads can linger.

    Python 3.12 supports os.set_blocking on Windows pipes as well as POSIX.
    Stop at the owned process's completion, not EOF from potential inheritors.
    """
    deadline = time.monotonic() + limits.timeout_seconds
    try:
        process = subprocess.Popen(_worker_command(limits, scale), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, bufsize=0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        raise PdfReadError('worker_crash') from None
    output = bytearray()
    pipes = (process.stdin, process.stdout, process.stderr)
    counts = {process.stdout: 0, process.stderr: 0}
    position = 0
    view = memoryview(data)
    try:
        for pipe in pipes:
            os.set_blocking(pipe.fileno(), False)
        while True:
            if time.monotonic() >= deadline:
                raise PdfReadError('timeout')
            exited = process.poll() is not None
            progressed = False
            if not process.stdin.closed:
                if exited or position == len(data):
                    process.stdin.close()
                else:
                    try:
                        sent = os.write(process.stdin.fileno(), view[position:position+65536])
                        position += sent
                        progressed |= sent > 0
                    except BlockingIOError:
                        pass
                    except BrokenPipeError:
                        process.stdin.close()
            read_progress = False
            for pipe in (process.stdout, process.stderr):
                if pipe.closed:
                    continue
                # Fair bounded draining keeps the deadline and other pipe live.
                for _ in range(4):
                    try:
                        chunk = os.read(pipe.fileno(), 65536)
                    except BlockingIOError:
                        break
                    except BrokenPipeError:
                        chunk = b''
                    if not chunk:
                        pipe.close()
                        break
                    read_progress = True
                    counts[pipe] += len(chunk)
                    cap = limits.max_output_bytes if pipe is process.stdout else 65536
                    if counts[pipe] > cap:
                        raise PdfReadError('output_limit')
                    if pipe is process.stdout:
                        output.extend(chunk)
            if exited and not read_progress:
                break
            if not progressed and not read_progress:
                time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
    except OSError:
        raise PdfReadError('worker_crash') from None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for pipe in pipes:
            pipe.close()
        view.release()
    if process.returncode != 0:
        raise PdfReadError('worker_crash')
    try:
        return json.loads(output, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise PdfReadError('worker_protocol') from None


def _exact(record, keys):
    if type(record) is not dict or set(record) != set(keys):
        raise ValueError('protocol shape')


def _png_header(data: bytes, width: int, height: int) -> None:
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG signature')
    cursor = 8
    last_kind = None
    seen_idat = False
    inflater = zlib.decompressobj()
    row_bytes = width * 3 + 1  # one legal PNG filter byte before each RGB scanline
    expected = row_bytes * height
    decoded_count = 0

    def consume(compressed):
        nonlocal decoded_count
        for offset in range(0, len(compressed), 65536):
            pending = compressed[offset:offset+65536]
            while True:
                try:
                    decoded = inflater.decompress(pending, 65536)
                except zlib.error:
                    raise ValueError('invalid PNG compression stream') from None
                if inflater.unused_data:
                    raise ValueError('data after PNG compression stream')
                if decoded_count + len(decoded) > expected:
                    raise ValueError('PNG pixel stream is longer than declared dimensions')
                for index in range((-decoded_count) % row_bytes, len(decoded), row_bytes):
                    if decoded[index] > 4:
                        raise ValueError('invalid PNG row filter')
                decoded_count += len(decoded)
                pending = inflater.unconsumed_tail
                if not pending and (len(decoded) < 65536 or inflater.eof):
                    break

    idat_ended = False
    while cursor < len(data):
        length = int.from_bytes(data[cursor:cursor+4], 'big')
        end = cursor + 12 + length
        if end > len(data):
            raise ValueError('PNG chunk bounds')
        kind = data[cursor+4:cursor+8]
        body = data[cursor+8:cursor+8+length]
        crc = int.from_bytes(data[end-4:end], 'big')
        if zlib.crc32(kind + body) != crc:
            raise ValueError('PNG CRC')
        if last_kind is None:
            if kind != b'IHDR' or length != 13:
                raise ValueError('PNG header')
            w, h, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', body)
            if (w, h, depth, color, compression, filtering, interlace) != (width, height, 8, 2, 0, 0, 0):
                raise ValueError('PNG dimensions or format')
        elif kind == b'IHDR':
            raise ValueError('duplicate PNG header')
        if kind == b'IDAT':
            if idat_ended:
                raise ValueError('PNG data chunks must be consecutive')
            consume(body)
            seen_idat = True
        elif seen_idat:
            idat_ended = True
        if kind == b'IEND' and (length != 0 or end != len(data)):
            raise ValueError('PNG ending')
        last_kind = kind
        cursor = end
    if last_kind != b'IEND' or not seen_idat:
        raise ValueError('PNG data/ending absent')
    if not inflater.eof or decoded_count != expected:
        raise ValueError('PNG pixel stream is incomplete')


def _decode_snapshot(reply, digest: str, limits: PdfLimits, scale: float | None) -> PdfSnapshot:
    try:
        if type(reply) is not dict or type(reply.get('schema_version')) is not int or reply['schema_version'] != 1:
            raise ValueError('schema')
        if reply.get('ok') is False:
            _exact(reply, ('schema_version', 'ok', 'error'))
            _exact(reply['error'], ('reason',))
            reason = reply['error']['reason']
            if not isinstance(reason, str) or reason not in _ERRORS:
                raise ValueError('error reason')
            raise PdfReadError(reason)
        _exact(reply, ('schema_version', 'ok', 'snapshot'))
        if reply['ok'] is not True:
            raise ValueError('ok type')
        body = reply['snapshot']
        _exact(body, ('input_sha256', 'pypdfium2_version', 'pdfium_version', 'page_count',
                      'rotation', 'page_size_pt', 'cropbox', 'mediabox', 'char_count', 'characters', 'render'))
        if body['input_sha256'] != digest:
            raise ValueError('hash')
        for name in ('pypdfium2_version', 'pdfium_version'):
            if not isinstance(body[name], str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+(?:[a-zA-Z0-9+.-]*)', body[name]):
                raise ValueError('version')
        try:
            size, media, crop = _validate_page(body['page_count'], body['rotation'], body['page_size_pt'],
                                                body['mediabox'], body['cropbox'])
        except PdfReadError:
            raise ValueError('page evidence') from None
        chars = body['characters']
        count = body['char_count']
        if (type(count) is not int or not 0 <= count <= limits.max_chars
                or type(chars) is not list or len(chars) != count):
            raise ValueError('char count')
        characters = []
        for char in chars:
            _exact(char, ('codepoint', 'box'))
            cp = char['codepoint']
            if type(cp) is not int or not 0 <= cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                raise ValueError('code point')
            characters.append(PdfChar(chr(cp), Rect(*char['box'])))
        raster = body['render']
        render = None
        if scale is None:
            if raster is not None:
                raise ValueError('unexpected raster')
        else:
            _exact(raster, ('width', 'height', 'mode', 'png_base64'))
            width, height = _render_size(size, scale, limits)
            if (type(raster['width']) is not int or type(raster['height']) is not int
                    or (raster['width'], raster['height'], raster['mode']) != (width, height, 'RGB')):
                raise ValueError('raster dimensions')
            data = base64.b64decode(raster['png_base64'], validate=True)
            _png_header(data, width, height)
            render = PdfRender(width, height, 'RGB', data)
        return PdfSnapshot(digest, body['pypdfium2_version'], body['pdfium_version'], 1, size,
                           crop, media, 0, tuple(characters), render)
    except PdfReadError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, struct.error) as error:
        # Keep the machine-readable reason first; the detail makes a failed
        # platform build diagnosable without guessing which check rejected it.
        raise PdfReadError('worker_protocol: ' + str(error)[:120]) from None


def read_pdf(path, expected_sha256: str, *, limits: PdfLimits = PdfLimits(),
             render_scale: float | None = None) -> PdfSnapshot:
    """Read one immutable, hash-bound local PDF snapshot in an owned process."""
    if not isinstance(limits, PdfLimits):
        raise PdfReadError('invalid_input')
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise PdfReadError('invalid_input')
    if render_scale is not None:
        try:
            render_scale = finite_number(render_scale, 'render_scale')
            if not 0 < render_scale <= 8:
                raise ValueError('scale')
        except (ValueError, TypeError, OverflowError):
            raise PdfReadError('invalid_input') from None
    try:
        source = Path(path)
        if source.suffix.lower() != '.pdf':
            raise PdfReadError('invalid_input')
        if not source.is_file():
            raise PdfReadError('file_error')
        if source.stat().st_size > limits.max_bytes:
            raise PdfReadError('input_limit')
        with source.open('rb') as stream:
            data = stream.read(limits.max_bytes + 1)
    except (OSError, TypeError, ValueError) as error:
        if isinstance(error, PdfReadError):
            raise
        raise PdfReadError('file_error') from None
    if len(data) > limits.max_bytes:
        raise PdfReadError('input_limit')
    if sha256(data).hexdigest() != expected_sha256:
        raise PdfReadError('hash_mismatch')
    reply = _run_worker(data, limits, render_scale)
    return _decode_snapshot(reply, expected_sha256, limits, render_scale)
