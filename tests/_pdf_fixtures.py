"""Small independently constructed PDFs, not dev/holdout benchmark samples."""
import hashlib
import struct

_PADDING = bytes.fromhex('28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a')


def _rc4(key, data):
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0
    result = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        result.append(byte ^ state[(state[i] + state[j]) % 256])
    return bytes(result)


def _pad(password):
    return (password + _PADDING)[:32]


def pdf_bytes(*, text='Hello', size=(200, 100), rotation=0, crop=None, pages=1,
              user_password=None, marker=None):
    """PDF 1.4, built-in Helvetica; optional Standard Security V1/R2 encryption."""
    escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = ('BT /F1 12 Tf 10 60 Td (' + escaped + ') Tj ET').encode('ascii')
    file_id = hashlib.md5(b'plotproof-input-test').digest()
    encryption = None
    if user_password is not None:
        owner_key = hashlib.md5(_pad(b'owner-only')).digest()[:5]
        owner = _rc4(owner_key, _pad(user_password.encode('ascii')))
        key = hashlib.md5(_pad(user_password.encode('ascii')) + owner + struct.pack('<i', -4) + file_id).digest()[:5]
        user = _rc4(key, _PADDING)
        object_key = hashlib.md5(key + bytes((5, 0, 0, 0, 0))).digest()[:10]
        stream = _rc4(object_key, stream)
        encryption = (f'<< /Filter /Standard /V 1 /R 2 /Length 40 /O <{owner.hex()}> '
                      f'/U <{user.hex()}> /P -4 >>').encode()
    extra = '' if crop is None else ' /CropBox [' + ' '.join(map(str, crop)) + ']'
    page = (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] '
            f'/Rotate {rotation}{extra} /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>').encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               ('<< /Type /Pages /Count ' + str(pages) + ' /Kids [' + ' '.join(['3 0 R'] * pages) + '] >>').encode(),
               page, b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    if encryption:
        objects.append(encryption)
    data = b'%PDF-1.4\n'
    if marker:
        data += b'% ' + marker.encode('ascii') + b'\n'
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(data)
    data += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    trailer = f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R'
    if encryption:
        trailer += f' /Encrypt 6 0 R /ID [<{file_id.hex()}> <{file_id.hex()}>]'
    data += (trailer + f' >>\nstartxref\n{xref}\n%%EOF\n').encode()
    return data
