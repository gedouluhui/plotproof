"""Trusted one-request child entry point; never imported by the parent reader."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys

# -I excludes both cwd and PYTHONPATH. Add only this installed package's root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plotproof.pdf_input import PdfLimits, PdfReadError, _render_size, _validate_page


def inspect_bytes(data: bytes, limits: PdfLimits, scale: float | None) -> dict:
    import pypdfium2 as pdfium

    if len(data) > limits.max_bytes:
        raise PdfReadError('input_limit')
    if not data.startswith(b'%PDF-'):
        raise PdfReadError('invalid_pdf')
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise PdfReadError('encrypted_pdf' if error.err_code == 4 else 'invalid_pdf') from None
    try:
        if pdfium.raw.FPDF_GetSecurityHandlerRevision(document) >= 0:
            raise PdfReadError('encrypted_pdf')
        count = len(document)
        if count != 1:
            raise PdfReadError('page_count')
        page = document[0]
        try:
            size, media, crop = _validate_page(count, page.get_rotation(), page.get_size(),
                                               page.get_mediabox(), page.get_cropbox())
            if scale is not None:
                _render_size(size, scale, limits)
            textpage = page.get_textpage()
            try:
                char_count = textpage.count_chars()
                if not 0 <= char_count <= limits.max_chars:
                    raise PdfReadError('character_limit')
                characters = []
                for index in range(char_count):
                    codepoint = pdfium.raw.FPDFText_GetUnicode(textpage, index)
                    if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                        raise PdfReadError('invalid_pdf')
                    characters.append({'codepoint': codepoint, 'box': list(textpage.get_charbox(index))})
            finally:
                textpage.close()
            raster = None
            if scale is not None:
                bitmap = page.render(scale=scale, may_draw_forms=False, draw_annots=False)
                try:
                    image = bitmap.to_pil().convert('RGB')
                    try:
                        width, height = image.size
                        if (width, height) != _render_size(size, scale, limits):
                            raise PdfReadError('worker_internal')
                        stream = BytesIO()
                        image.save(stream, format='PNG')
                        raster = {'width': width, 'height': height, 'mode': 'RGB',
                                  'png_base64': base64.b64encode(stream.getvalue()).decode('ascii')}
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            return {'input_sha256': sha256(data).hexdigest(),
                    'pypdfium2_version': str(pdfium.PYPDFIUM_INFO), 'pdfium_version': str(pdfium.PDFIUM_INFO),
                    'page_count': 1, 'rotation': 0, 'page_size_pt': size,
                    'cropbox': crop.as_tuple(), 'mediabox': media.as_tuple(),
                    'char_count': char_count, 'characters': characters, 'render': raster}
        finally:
            page.close()
    finally:
        document.close()


def main() -> None:
    try:
        config = json.loads(sys.argv[1])
        limits = PdfLimits(**config['limits'])
        scale = config['render_scale']
        data = sys.stdin.buffer.read(limits.max_bytes + 1)
        snapshot = inspect_bytes(data, limits, scale)
        reply = {'schema_version': 1, 'ok': True, 'snapshot': snapshot}
        encoded = json.dumps(reply, allow_nan=False, separators=(',', ':')).encode('ascii')
        if len(encoded) > limits.max_output_bytes:
            raise PdfReadError('output_limit')
    except PdfReadError as error:
        encoded = json.dumps({'schema_version': 1, 'ok': False, 'error': {'reason': error.reason}}).encode('ascii')
    except Exception:
        encoded = b'{"schema_version":1,"ok":false,"error":{"reason":"worker_internal"}}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
