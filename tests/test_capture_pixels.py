"""Cross-check captured alpha and crop against a separate real PDFium process."""
from hashlib import sha256
from io import BytesIO

from PIL import Image
from matplotlib.patches import Rectangle
import pytest

from plotproof.pdf_input import read_pdf
from test_capture import api, figure


@pytest.mark.parametrize('alpha,gray', [(None,102),(.6,102),(1,0)])
def test_captured_applied_alpha_predicts_real_pdf_pixels(tmp_path,alpha,gray):
    fig=figure();fig.add_artist(Rectangle((.25,.25),.5,.5,transform=fig.transFigure,
        facecolor=(0,0,0,.6),alpha=alpha,edgecolor='none'))
    c=api().capture_pdf(fig)
    event=[e for e in c.events if e.kind=='filled_path'][-1]
    path=tmp_path/'alpha.pdf';path.write_bytes(c.pdf_bytes)
    snapshot=read_pdf(path,c.input_sha256,render_scale=1)
    with Image.open(BytesIO(snapshot.render.png_bytes)) as image:
        assert image.getpixel((144,108))==(gray,gray,gray)
        assert image.getpixel((0,0))==(255,255,255)
    assert round(255*(1-event.alpha.effective))==gray
    if alpha==.6:
        assert round(255*(1-event.raw_color_alpha*event.raw_artist_alpha))==163


def test_tight_outside_annotation_remains_on_captured_saved_page(tmp_path):
    fig=figure();fig.text(1.02,.5,'Outside',ha='left',va='center')
    c=api().capture_pdf(fig,bbox_inches='tight',pad_inches=.1)
    path=tmp_path/'tight.pdf';path.write_bytes(c.pdf_bytes)
    snapshot=read_pdf(path,c.input_sha256)
    assert ''.join(x.text for x in snapshot.characters)=='Outside'
    event=next(e for e in c.events if e.kind=='text')
    assert snapshot.cropbox.contains(event.bbox_pdf)
    restored=c.to_source_display(event.bbox_pdf)
    assert restored.x0>400  # original Figure is 400 px wide at 100 dpi
    assert event.bbox_pdf.x0<20  # saved tight page is translated, not scale-only
