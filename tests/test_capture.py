from dataclasses import asdict
from hashlib import sha256
from importlib import import_module, util
from io import BytesIO
import json

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import RendererPdf
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import pytest

from plotproof.pdf_input import read_pdf


def api():
    assert util.find_spec('plotproof.capture') is not None, 'actual-save capture layer missing'
    return import_module('plotproof.capture')


@pytest.fixture(autouse=True)
def style():
    with mpl.rc_context({'pdf.fonttype':42,'font.family':['DejaVu Sans'],
                         'text.usetex':False,'pdf.use14corefonts':False,'savefig.bbox':None,
                         'savefig.transparent':False}):
        yield


def figure(layout=None):
    fig=Figure(figsize=(4,3),dpi=100,layout=layout)
    FigureCanvasAgg(fig)
    return fig


def snapshot(capture,tmp_path):
    path=tmp_path/'figure.pdf';path.write_bytes(capture.pdf_bytes)
    return read_pdf(path,capture.input_sha256)


@pytest.mark.parametrize('source_alpha,want', [(None,.6),(.6,.6),(1,1)])
def test_emitted_alpha_is_not_double_counted_and_keeps_source_values(source_alpha,want,tmp_path):
    fig=figure()
    fig.add_artist(Rectangle((.2,.2),.4,.4,transform=fig.transFigure,
                  facecolor=(0,0,0,.6),alpha=source_alpha,edgecolor='none'))
    c=api().capture_pdf(fig)
    events=[e for e in c.events if e.artist_class=='Rectangle' and e.source_object_id!=0]
    assert len(events)==1
    event=events[0]
    assert event.alpha.effective==want
    assert event.alpha.gc_forced is (source_alpha is not None)
    assert event.raw_artist_alpha==source_alpha
    assert event.raw_color_alpha==(.6 if source_alpha is None else source_alpha)
    assert c.input_sha256==sha256(c.pdf_bytes).hexdigest()
    assert c.capture_revision=='CA1'
    assert snapshot(c,tmp_path).page_size_pt==(288,216)


def test_text_effective_alpha_obeys_same_forced_rule():
    fig=figure();fig.text(.3,.3,'Alpha',color=(0,0,0,.7),alpha=.4)
    e=next(e for e in api().capture_pdf(fig).events if e.kind=='text')
    assert e.alpha.effective==.4 and e.raw_artist_alpha==.4 and e.raw_color_alpha==.7


@pytest.mark.parametrize('layout', [None,'constrained'])
def test_tight_origin_is_from_actual_save_not_agg_pre_draw(layout,tmp_path):
    fig=figure(layout);ax=fig.subplots();ax.plot([0,1,2],[0,1,4])
    ax.set_ylabel('Value',rotation=0,ha='right');ax.set_xlabel('Time')
    c=api().capture_pdf(fig,bbox_inches='tight',pad_inches=.1)
    p=snapshot(c,tmp_path)
    assert c.save_tight_bbox_inches is not None
    x,y,w,h=c.save_tight_bbox_inches
    assert c.origin_display==pytest.approx(((x-.1)*100,(y-.1)*100))
    assert p.page_size_pt==pytest.approx(((w+.2)*72,(h+.2)*72),abs=1e-4)
    if layout is None:
        assert abs(c.pre_tight_bbox_inches[1]-y)>.005
    for e in c.events:
        if e.kind=='text':
            assert c.to_source_display(e.bbox_pdf).y0==pytest.approx(e.bbox_pdf.y0*100/72+c.origin_display[1])
    assert fig.dpi==100


def test_actual_order_background_and_multiline_identity():
    fig=figure();fig.text(.2,.5,'First\nSecond',bbox={'facecolor':'white','boxstyle':'square'})
    c=api().capture_pdf(fig)
    texts=[e for e in c.events if e.kind=='text']
    assert [e.text for e in texts]==['First','Second']
    assert texts[0].source_object_id==texts[1].source_object_id
    source=next(s for s in c.sources if s.source_object_id==texts[0].source_object_id)
    patch=next(s for s in c.sources if s.source_object_id==source.background_patch_id)
    assert patch.owner_unit_id==source.source_object_id
    paint=next(e for e in c.events if e.source_object_id==patch.source_object_id)
    assert paint.sequence<texts[0].sequence
    assert [e.sequence for e in c.events]==list(range(len(c.events)))


def test_unpainted_text_is_retained_not_declared_checked():
    fig=figure();fig.text(.2,.2,'invisible',visible=False)
    ax=fig.subplots();ax.text(.2,.2,'hidden-parent');ax.set_visible(False)
    c=api().capture_pdf(fig)
    assert {'invisible','hidden-parent'} <= {s.text for s in c.sources}
    assert not any(e.kind=='text' for e in c.events)
    assert c.complete_source_manifest is False


def test_patch_after_text_is_observed_after_not_sorted_globally():
    fig=figure();ax=fig.subplots();ax.text(.2,.2,'in axes',zorder=100)
    fig.text(.5,.5,'figure text',zorder=4)
    c=api().capture_pdf(fig)
    assert [e.text for e in c.events if e.kind=='text' and e.text in ('in axes','figure text')]==['in axes','figure text']


def test_draw_output_is_unchanged_and_hooks_are_restored(tmp_path):
    fig=figure();fig.text(.2,.3,'Baseline');fig.canvas.draw()
    before=RendererPdf.draw_text
    c=api().capture_pdf(fig)
    assert RendererPdf.draw_text is before
    assert 'get_tightbbox' not in fig.__dict__
    b=BytesIO();fig.savefig(b,format='pdf',bbox_inches=None,pad_inches=.1,transparent=False,
        metadata={'CreationDate':None,'ModDate':None,'Creator':'PlotProof CA1 capture'})
    assert c.pdf_bytes==b.getvalue()
    assert c.capture_issues==()


def test_failure_and_recursive_capture_restore_all_hooks(monkeypatch):
    a=api();fig=figure();fig.text(.2,.3,'Text')
    original=RendererPdf.draw_text
    def fail(*args,**kwargs): raise RuntimeError('injected')
    monkeypatch.setattr(fig,'savefig',fail)
    with pytest.raises(a.CaptureError,match='save_failed'):
        a.capture_pdf(fig)
    assert RendererPdf.draw_text is original
    assert 'get_tightbbox' not in fig.__dict__
    def recurse(*args,**kwargs): return a.capture_pdf(fig)
    monkeypatch.setattr(fig,'savefig',recurse)
    with pytest.raises(a.CaptureError,match='capture_reentry'):
        a.capture_pdf(fig)
    assert RendererPdf.draw_text is original


def test_save_warning_scope_and_non_bmp_capture():
    import warnings
    fig=figure();fig.text(.2,.4,'Missing𠀀')
    with warnings.catch_warnings(record=True) as outside:
        warnings.simplefilter('always')
        warnings.warn('outside save')
        c=api().capture_pdf(fig)
    assert any(str(w.message)=='outside save' for w in outside)
    assert any('131072' in w.message for w in c.warnings)
    assert all('outside save' not in w.message for w in c.warnings)
    assert len(c.warnings)==len(set(c.warnings))


def test_raster_images_and_mathtext_are_explicit_capture_issues():
    import numpy as np
    fig=figure();ax=fig.subplots();ax.imshow(np.zeros((2,2)))
    fig.text(.2,.4,'$x$');fig.text(.5,.4,'raster',rasterized=True)
    c=api().capture_pdf(fig)
    assert 'image_capture_pending' in c.capture_issues
    assert 'mathtext_capture_pending' in c.capture_issues
    assert 'rasterized_capture_pending' in c.capture_issues


@pytest.mark.parametrize('kwargs', [{'bbox_inches':'other'}, {'pad_inches':-1},
    {'max_events':0}, {'max_pdf_bytes':False}, {'pad_inches':float('nan')}])
def test_bad_options_are_rejected_before_drawing(kwargs):
    a=api()
    with pytest.raises(a.CaptureError,match='invalid_input'):
        a.capture_pdf(figure(),**kwargs)


def test_bounds_and_tex_preflight_fail_explicitly():
    a=api();fig=figure();fig.text(.2,.3,'abc')
    for kwargs,reason in [({'max_events':1},'event_limit'),({'max_pdf_bytes':30},'pdf_byte_limit')]:
        with pytest.raises(a.CaptureError,match=reason): a.capture_pdf(fig,**kwargs)
    fig.text(.5,.4,'tex',usetex=True)
    with pytest.raises(a.CaptureError,match='unsupported_tex'): a.capture_pdf(fig)
