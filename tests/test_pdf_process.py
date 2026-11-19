from copy import deepcopy
from hashlib import sha256
import json
import subprocess
import sys

import pytest

from _pdf_fixtures import pdf_bytes
from test_pdf_input import api, read_bytes


def worker_script(tmp_path, code):
    path = tmp_path / 'controlled_worker.py'
    path.write_text(code, encoding='utf-8')
    return [sys.executable, '-I', str(path)]


def test_timeout_reaps_only_its_owned_process_and_next_read_recovers(tmp_path, monkeypatch):
    a = api()
    command = worker_script(tmp_path, 'import sys,time\nsys.stdin.buffer.read()\ntime.sleep(60)\n')
    real_command = a._worker_command
    real_popen = subprocess.Popen
    owned = []
    def track(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        owned.append(child)
        return child
    control = real_popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
    try:
        monkeypatch.setattr(a.subprocess, 'Popen', track)
        monkeypatch.setattr(a, '_worker_command', lambda *_: command)
        with pytest.raises(a.PdfReadError) as error:
            read_bytes(tmp_path, limits=a.PdfLimits(timeout_seconds=0.4))
        assert error.value.reason == 'timeout'
        assert len(owned) == 1 and owned[0].poll() is not None
        assert control.poll() is None  # unrelated live process was not killed
        monkeypatch.setattr(a, '_worker_command', real_command)
        assert read_bytes(tmp_path).page_count == 1
        assert owned[-1].poll() == 0
    finally:
        control.kill(); control.wait(timeout=5)


@pytest.mark.parametrize('code,reason', [
    ('import sys; sys.exit(3)', 'worker_crash'),
    ('print("not JSON")', 'worker_protocol'),
    ('print(\'{"schema_version":1,"schema_version":1,"ok":true}\')', 'worker_protocol'),
    ('print(\'{"schema_version":1,"ok":NaN}\')', 'worker_protocol'),
    ('import sys; sys.stdout.write("x"*1000000)', 'output_limit'),
])
def test_failed_workers_never_return_success_and_diagnostics_are_sanitized(tmp_path, monkeypatch, code, reason):
    a = api()
    command = worker_script(tmp_path, code)
    monkeypatch.setattr(a, '_worker_command', lambda *_: command)
    with pytest.raises(a.PdfReadError) as error:
        read_bytes(tmp_path, limits=a.PdfLimits(max_output_bytes=1024))
    assert error.value.reason == reason
    assert str(tmp_path) not in str(error.value)


def reply():
    a = api()
    data = pdf_bytes()
    return a._run_worker(data, a.PdfLimits(), None)


@pytest.mark.parametrize('change', [
    'schema_bool', 'ok_int', 'extra', 'missing', 'hash', 'char_count', 'bad_box',
    'nan_box', 'bool_codepoint', 'surrogate', 'page_rotation', 'crop', 'versions',
])
def test_worker_protocol_reconciles_every_claimed_field(change):
    a = api()
    bad = deepcopy(reply())
    body = bad['snapshot']
    if change == 'schema_bool': bad['schema_version'] = True
    elif change == 'ok_int': bad['ok'] = 1
    elif change == 'extra': body['unexpected'] = 'field'
    elif change == 'missing': del body['characters']
    elif change == 'hash': body['input_sha256'] = '0' * 64
    elif change == 'char_count': body['char_count'] += 1
    elif change == 'bad_box': body['characters'][0]['box'] = [2, 0, 1, 1]
    elif change == 'nan_box': body['characters'][0]['box'][0] = float('nan')
    elif change == 'bool_codepoint': body['characters'][0]['codepoint'] = True
    elif change == 'surrogate': body['characters'][0]['codepoint'] = 0xD800
    elif change == 'page_rotation': body['rotation'] = 90
    elif change == 'crop': body['cropbox'][2] -= 1
    elif change == 'versions': body['pdfium_version'] = ''
    with pytest.raises(a.PdfReadError) as error:
        a._decode_snapshot(bad, sha256(pdf_bytes()).hexdigest(), a.PdfLimits(), None)
    assert error.value.reason == 'worker_protocol'


def test_successful_protocol_control_matches_real_text():
    a = api()
    snapshot = a._decode_snapshot(reply(), sha256(pdf_bytes()).hexdigest(), a.PdfLimits(), None)
    assert ''.join(c.text for c in snapshot.characters) == 'Hello'


def test_worker_uses_bytes_not_a_reopened_path(tmp_path, monkeypatch):
    a = api()
    real = a._run_worker
    path = tmp_path / 'input.pdf'
    data = pdf_bytes()
    path.write_bytes(data)
    def mutate_after_read(payload, *args):
        path.write_bytes(b'changed after the parent read')
        return real(payload, *args)
    monkeypatch.setattr(a, '_run_worker', mutate_after_read)
    result = a.read_pdf(path, sha256(data).hexdigest())
    assert ''.join(c.text for c in result.characters) == 'Hello'
    assert result.input_sha256 == sha256(data).hexdigest()
