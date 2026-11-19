"""Adversarial process/PNG controls beyond ordinary PDF parser outcomes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import base64
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import zlib

import pytest

from _pdf_fixtures import pdf_bytes
from test_pdf_input import api, read_bytes
from test_pdf_process import worker_script


def test_full_stdin_pipe_does_not_bypass_worker_timeout(tmp_path, monkeypatch):
    a = api()
    command = worker_script(tmp_path, 'import time\ntime.sleep(60)\n')
    original = subprocess.Popen
    owned = []
    def track(*args, **kwargs):
        proc = original(*args, **kwargs); owned.append(proc); return proc
    monkeypatch.setattr(a.subprocess, 'Popen', track)
    monkeypatch.setattr(a, '_worker_command', lambda *_: command)
    with pytest.raises(a.PdfReadError) as error:
        read_bytes(tmp_path, pdf_bytes() + b' ' * 1_000_000, limits=a.PdfLimits(timeout_seconds=0.4))
    assert error.value.reason == 'timeout'
    assert len(owned) == 1 and owned[0].poll() is not None


def test_stderr_flood_is_bounded_without_echoing_private_diagnostics(tmp_path, monkeypatch):
    a = api()
    command = worker_script(tmp_path, 'import sys\nsys.stderr.write("PRIVATE_DIAGNOSTIC"*100000)\n')
    monkeypatch.setattr(a, '_worker_command', lambda *_: command)
    with pytest.raises(a.PdfReadError) as error:
        read_bytes(tmp_path)
    assert error.value.reason == 'output_limit'
    assert 'PRIVATE_DIAGNOSTIC' not in str(error.value)


def test_parallel_reads_use_independent_owned_workers(tmp_path, monkeypatch):
    a = api()
    original = subprocess.Popen
    owned = []
    def track(*args, **kwargs):
        proc = original(*args, **kwargs); owned.append(proc); return proc
    monkeypatch.setattr(a.subprocess, 'Popen', track)
    path = tmp_path / 'input.pdf'; data = pdf_bytes(); path.write_bytes(data)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: a.read_pdf(path, sha256(data).hexdigest()), range(4)))
    assert [''.join(c.text for c in r.characters) for r in results] == ['Hello'] * 4
    assert len({p.pid for p in owned}) == 4 and all(p.poll() == 0 for p in owned)


@pytest.mark.parametrize('mutation', ['width', 'format', 'base64', 'crc', 'truncated', 'missing'])
def test_png_protocol_is_reconciled_and_corruption_rejected(mutation):
    a = api()
    data = pdf_bytes(); digest = sha256(data).hexdigest(); limits = a.PdfLimits()
    reply = a._run_worker(data, limits, 1)
    control = a._decode_snapshot(reply, digest, limits, 1)
    assert (control.render.width, control.render.height) == (200, 100)
    bad = deepcopy(reply)
    image = bad['snapshot']['render']
    if mutation == 'width': image['width'] += 1
    elif mutation == 'format': image['mode'] = 'RGBA'
    elif mutation == 'base64': image['png_base64'] = '*invalid*'
    elif mutation == 'missing': bad['snapshot']['render'] = None
    else:
        encoded = base64.b64decode(image['png_base64'])
        if mutation == 'crc': encoded = encoded[:20] + bytes([encoded[20] ^ 1]) + encoded[21:]
        elif mutation == 'truncated': encoded = encoded[:-1]
        image['png_base64'] = base64.b64encode(encoded).decode()
    with pytest.raises(a.PdfReadError) as error:
        a._decode_snapshot(bad, digest, limits, 1)
    assert error.value.reason == 'worker_protocol'
    with pytest.raises(a.PdfReadError) as error:
        a._decode_snapshot(reply, digest, limits, None)
    assert error.value.reason == 'worker_protocol'


def test_inherited_pipe_handles_do_not_leave_parent_threads_or_resources(tmp_path, monkeypatch):
    a = api()
    stop = tmp_path / 'release-keeper'
    marker = tmp_path / 'keeper-started'
    keeper = ("from pathlib import Path; import time; "
              f"stop=Path({str(stop)!r}); Path({str(marker)!r}).write_text('ready'); "
              "deadline=time.monotonic()+25\n"
              "while not stop.exists() and time.monotonic()<deadline: time.sleep(.01)\n")
    code = ('import subprocess,sys,time\n'
            f'subprocess.Popen([sys.executable,"-I","-c",{keeper!r}], '
            'stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr,close_fds=False, '
            'creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))\n'
            'time.sleep(60)\n')
    command = worker_script(tmp_path, code)
    original = subprocess.Popen
    owned = []
    before = {t.ident for t in threading.enumerate()}
    def track(*args, **kwargs):
        proc = original(*args, **kwargs); owned.append(proc); return proc
    monkeypatch.setattr(a.subprocess, 'Popen', track)
    monkeypatch.setattr(a, '_worker_command', lambda *_: command)
    started = time.monotonic()
    try:
        with pytest.raises(a.PdfReadError) as error:
            read_bytes(tmp_path, pdf_bytes() + b' ' * 1_000_000, limits=a.PdfLimits(timeout_seconds=0.8))
        assert marker.exists(), 'the inherited-handle control did not actually start'
        assert error.value.reason == 'timeout'
        leaked = [t.name for t in threading.enumerate() if t.ident not in before]
        assert leaked == [], f'parent transport threads leaked: {leaked}'
        assert all(s.closed for p in owned for s in (p.stdin, p.stdout, p.stderr))
        assert all(p.poll() is not None for p in owned)
        assert time.monotonic() - started < 3, 'cleanup must not wait for inherited handles to reach EOF'
    finally:
        stop.write_text('release', encoding='ascii')  # release our control, do not kill another PID


def _tiny_png(compressed):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind+payload))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', compressed) + chunk(b'IEND', b''))


@pytest.mark.parametrize('compressed', [
    b'', b'not-zlib', zlib.compress(bytes([5, 1, 2, 3, 4, 5, 6])),
    zlib.compress(bytes(6)), zlib.compress(bytes(8)),
    zlib.compress(bytes(7))[:-1], zlib.compress(bytes(7)) + b'extra',
])
def test_png_pixel_stream_is_validated_not_only_its_crc(compressed):
    a = api()
    a._png_header(_tiny_png(zlib.compress(bytes([0, 1, 2, 3, 4, 5, 6]))), 2, 1)
    with pytest.raises(ValueError):
        a._png_header(_tiny_png(compressed), 2, 1)


def test_png_metadata_is_processed_without_retaining_chunk_history():
    import tracemalloc
    a = api()
    original = _tiny_png(zlib.compress(bytes(7)))
    body = b'k\x00v'
    ancillary = (struct.pack('>I', len(body)) + b'tEXt' + body
                 + struct.pack('>I', zlib.crc32(b'tEXt' + body)))
    data = original[:33] + ancillary * 32000 + original[33:]
    # Input is allocated before tracing. A streaming validator needs no growing
    # chunk-kind history; this deterministic allocation bound avoids CPU timers.
    tracemalloc.start()
    try:
        a._png_header(data, 2, 1)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < len(data), f'chunk history retained: peak={peak}, input={len(data)}'
