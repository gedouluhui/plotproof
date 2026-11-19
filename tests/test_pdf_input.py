from hashlib import sha256
from importlib import import_module, util
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from _pdf_fixtures import pdf_bytes
from plotproof.geometry import Rect


def api():
    assert util.find_spec('plotproof.pdf_input') is not None, 'bounded PDF reader missing'
    return import_module('plotproof.pdf_input')


def read_bytes(tmp_path, data=None, **options):
    data = pdf_bytes() if data is None else data
    path = tmp_path / 'input.pdf'
    path.write_bytes(data)
    return api().read_pdf(path, sha256(data).hexdigest(), **options)


def test_real_pdf_bytes_become_unrounded_typed_characters(tmp_path):
    result = read_bytes(tmp_path)
    assert result.page_size_pt == (200, 100) and result.page_count == 1
    assert result.cropbox == result.mediabox == Rect(0, 0, 200, 100)
    assert result.rotation == 0 and result.render is None
    assert ''.join(c.text for c in result.characters) == 'Hello'
    assert len(result.characters) == 5 and all(c.box.area > 0 for c in result.characters)
    assert result.input_sha256 == sha256(pdf_bytes()).hexdigest()
    assert result.pypdfium2_version and result.pdfium_version


def test_render_dimensions_and_pixels_are_from_the_pdf(tmp_path):
    from PIL import Image
    result = read_bytes(tmp_path, render_scale=2.25)
    assert (result.render.width, result.render.height, result.render.mode) == (450, 225, 'RGB')
    with Image.open(BytesIO(result.render.png_bytes)) as image:
        assert image.size == (450, 225)
        low, high = image.convert('L').getextrema()
        assert low < 100 and high == 255


@pytest.mark.parametrize('data,reason', [
    (b'not a PDF', 'invalid_pdf'),
    (b'%PDF-1.7\ntruncated', 'invalid_pdf'),
    (pdf_bytes(user_password='secret'), 'encrypted_pdf'),
    (pdf_bytes(user_password=''), 'encrypted_pdf'),
    (pdf_bytes(pages=2), 'page_count'),
    (pdf_bytes(rotation=90), 'page_rotation'),
    (pdf_bytes(crop=(0, 0, 150, 100)), 'page_boxes'),
    (pdf_bytes(size=(2000, 100)), 'page_size'),
    (pdf_bytes(size=(0, 100)), 'page_size'),
])
def test_invalid_pdf_shapes_are_errors_not_empty_success(tmp_path, data, reason):
    a = api()
    with pytest.raises(a.PdfReadError) as error:
        read_bytes(tmp_path, data)
    assert error.value.reason == reason
    assert str(tmp_path) not in str(error.value)


def test_encrypt_marker_in_plain_pdf_is_not_an_encryption_test(tmp_path):
    assert read_bytes(tmp_path, pdf_bytes(marker='/Encrypt is just a comment')).page_count == 1


def test_a2_limits_allow_both_orientations(tmp_path):
    a2 = (420 * 72 / 25.4, 594 * 72 / 25.4)
    for size in (a2, a2[::-1]):
        snapshot = read_bytes(tmp_path, pdf_bytes(size=size))
        assert snapshot.page_size_pt == pytest.approx(size, abs=0.0001)
    with pytest.raises(api().PdfReadError) as error:
        read_bytes(tmp_path, pdf_bytes(size=(a2[0], a2[1] + 0.01)))
    assert error.value.reason == 'page_size'
    assert read_bytes(tmp_path, pdf_bytes(size=(a2[0], a2[1] - 0.01))).page_count == 1


def test_hash_mismatch_and_size_limit_fail_before_worker(tmp_path, monkeypatch):
    a = api()
    data = pdf_bytes()
    path = tmp_path / 'input.pdf'; path.write_bytes(data)
    def forbid(*args, **kwargs):
        raise AssertionError('worker must not start for rejected source bytes')
    monkeypatch.setattr(a, '_run_worker', forbid)
    with pytest.raises(a.PdfReadError) as err:
        a.read_pdf(path, '0' * 64)
    assert err.value.reason == 'hash_mismatch'
    with pytest.raises(a.PdfReadError) as err:
        a.read_pdf(path, sha256(data).hexdigest(), limits=a.PdfLimits(max_bytes=len(data)-1))
    assert err.value.reason == 'input_limit'


def test_character_pixel_and_response_limits_are_enforced(tmp_path):
    a = api()
    for kwargs, reason in [({'limits': a.PdfLimits(max_chars=4)}, 'character_limit'),
                           ({'limits': a.PdfLimits(max_pixels=19999), 'render_scale': 1}, 'pixel_limit'),
                           ({'limits': a.PdfLimits(max_output_bytes=32)}, 'output_limit')]:
        with pytest.raises(a.PdfReadError) as err:
            read_bytes(tmp_path, **kwargs)
        assert err.value.reason == reason
    assert len(read_bytes(tmp_path, limits=a.PdfLimits(max_chars=5)).characters) == 5
    assert read_bytes(tmp_path, limits=a.PdfLimits(max_pixels=20000), render_scale=1).render.width == 200


@pytest.mark.parametrize('changes', [
    {'max_bytes': 0}, {'max_bytes': True}, {'max_bytes': 16*1024*1024+1},
    {'max_chars': 0}, {'max_chars': 1.5}, {'max_chars': 200001},
    {'max_pixels': 0}, {'max_pixels': 16000001}, {'max_output_bytes': 0},
    {'timeout_seconds': 0}, {'timeout_seconds': math.nan}, {'timeout_seconds': 30.1},
])
def test_limits_cannot_disable_or_relax_hard_ceilings(changes):
    with pytest.raises((ValueError, TypeError)):
        api().PdfLimits(**changes)


@pytest.mark.parametrize('scale', [0, -1, True, math.nan, math.inf, 8.001, '2', 10**400])
def test_invalid_render_scale_fails_before_launch(tmp_path, scale):
    a = api()
    with pytest.raises(a.PdfReadError) as err:
        read_bytes(tmp_path, render_scale=scale)
    assert err.value.reason == 'invalid_input'


def test_invalid_hash_path_and_non_pdf_extension_are_explicit(tmp_path):
    a = api()
    path = tmp_path / 'input.pdf'; path.write_bytes(pdf_bytes())
    for digest in ('', '0' * 63, 'Z' * 64, None, 5):
        with pytest.raises(a.PdfReadError) as err:
            a.read_pdf(path, digest)
        assert err.value.reason == 'invalid_input'
    with pytest.raises(a.PdfReadError) as err:
        a.read_pdf(tmp_path / 'missing.pdf', '0' * 64)
    assert err.value.reason == 'file_error'
    wrong = tmp_path / 'not-pdf.png'; wrong.write_bytes(pdf_bytes())
    with pytest.raises(a.PdfReadError) as err:
        a.read_pdf(wrong, sha256(pdf_bytes()).hexdigest())
    assert err.value.reason == 'invalid_input'


def test_reader_parent_never_loads_native_stack_even_when_rendering(tmp_path):
    a = api()
    path = tmp_path / 'input.pdf'; path.write_bytes(pdf_bytes())
    code = """
import sys, json
from plotproof.pdf_input import read_pdf
r=read_pdf(sys.argv[1],sys.argv[2],render_scale=1)
heavy=[m for m in ('pypdfium2','PIL','matplotlib','numpy','fontTools') if m in sys.modules]
print(json.dumps({'text': ''.join(c.text for c in r.characters), 'heavy':heavy}))
"""
    run = subprocess.run([sys.executable, '-c', code, str(path), sha256(pdf_bytes()).hexdigest()],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {'text': 'Hello', 'heavy': []}
