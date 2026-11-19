"""Additional actual-save controls: target identity, resource and hook isolation."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from matplotlib.artist import Artist
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import RendererPdf
from matplotlib.figure import Figure
from matplotlib.table import Table
from matplotlib.text import Text
import matplotlib as mpl
import pytest

from test_capture import api, figure


def test_another_pdf_saved_during_draw_cannot_contaminate_target_events():
    class NestedSave(Artist):
        def draw(self, renderer):
            other=figure();other.text(.2,.2,'NOT-TARGET')
            other.savefig(BytesIO(),format='pdf')
    fig=figure();fig.text(.2,.4,'TARGET');fig.add_artist(NestedSave())
    c=api().capture_pdf(fig)
    assert [e.text for e in c.events if e.kind=='text']==['TARGET']
    assert 'NOT-TARGET' not in {s.text for s in c.sources}


def test_concurrent_calls_through_adapter_are_serialized_and_do_not_leak():
    a=api()
    originals=(Text.draw,RendererPdf.draw_text,RendererPdf.draw_path)
    # Build figures before the concurrent region: unrelated Matplotlib calls
    # are not protected by the adapter lock and are deliberately not promised.
    figures=[]
    for word in ('Alpha','Bravo','Charlie'):
        f=figure();f.text(.2,.4,word);figures.append(f)
    with ThreadPoolExecutor(max_workers=3) as executor:
        captures=list(executor.map(a.capture_pdf,figures))
    assert [[e.text for e in c.events if e.kind=='text'] for c in captures]==[['Alpha'],['Bravo'],['Charlie']]
    assert (Text.draw,RendererPdf.draw_text,RendererPdf.draw_path)==originals


def test_table_cell_text_is_in_inventory_and_has_emitted_identity():
    fig=figure();ax=fig.subplots();ax.set_axis_off()
    table=Table(ax,bbox=[.1,.1,.5,.5]);table.add_cell(0,0,1,1,text='Cell text')
    ax.add_table(table)
    c=api().capture_pdf(fig)
    s=next(s for s in c.sources if s.text=='Cell text')
    assert any(e.kind=='text' and e.source_object_id==s.source_object_id for e in c.events)


def test_annotated_text_box_excludes_arrow_union():
    fig=figure();ax=fig.subplots()
    ann=ax.annotate('label',xy=(.8,.8),xytext=(.2,.2),arrowprops={'arrowstyle':'->'})
    c=api().capture_pdf(fig)
    e=next(e for e in c.events if e.text=='label')
    # The far arrow would make a ~130pt wide box; the actual text is much narrower.
    assert 10<e.bbox_pdf.x1-e.bbox_pdf.x0<50


def test_failed_native_emit_restores_class_and_instance_hooks(monkeypatch):
    a=api();fig=figure();fig.text(.2,.3,'failure')
    def bad_emit(*args,**kwargs):raise RuntimeError('actual native emit failure')
    original=(Text.draw,RendererPdf.draw_path)
    monkeypatch.setattr(RendererPdf,'draw_text',bad_emit)
    with pytest.raises(a.CaptureError,match='save_failed'):a.capture_pdf(fig,bbox_inches='tight')
    assert RendererPdf.draw_text is bad_emit
    assert (Text.draw,RendererPdf.draw_path)==original
    assert 'get_tightbbox' not in fig.__dict__ and fig.dpi==100


def test_original_instance_tight_override_is_restored():
    fig=figure();fig.text(.2,.3,'original')
    original=fig.get_tightbbox;fig.get_tightbbox=original
    c=api().capture_pdf(fig,bbox_inches='tight')
    assert fig.__dict__['get_tightbbox'] is original and c.origin_display is not None


def test_table_cell_tex_is_rejected_before_any_process_can_start(monkeypatch):
    import subprocess
    a=api();fig=figure();ax=fig.subplots()
    table=ax.table(cellText=[['unsafe-tex']],loc='center')
    table[0,0].get_text().set_usetex(True)
    attempts=[]
    def deny_process(*args,**kwargs):
        attempts.append(args)
        raise AssertionError('TeX must be rejected before process launch')
    monkeypatch.setattr(subprocess,'Popen',deny_process)
    with pytest.raises(a.CaptureError,match='unsupported_tex'):a.capture_pdf(fig)
    assert attempts==[]


def test_saving_time_background_gets_new_identity_and_raw_alpha():
    fig=figure();text=fig.text(.2,.4,'Dynamic')
    def add_background(event):
        if fig.canvas.is_saving() and text.get_bbox_patch() is None:
            text.set_bbox({'facecolor':'black','alpha':.6})
    connection=fig.canvas.mpl_connect('draw_event',add_background)
    try:c=api().capture_pdf(fig,bbox_inches='tight')
    finally:fig.canvas.mpl_disconnect(connection)
    source=next(s for s in c.sources if s.text=='Dynamic')
    assert source.background_patch_id is not None
    patch=next(s for s in c.sources if s.source_object_id==source.background_patch_id)
    event=next(e for e in c.events if e.source_object_id==patch.source_object_id)
    text_event=next(e for e in c.events if e.text=='Dynamic')
    assert event.kind=='filled_path' and event.artist_class=='FancyBboxPatch'
    assert event.raw_artist_alpha==.6 and event.alpha.effective==.6
    assert event.sequence<text_event.sequence and patch.owner_unit_id==source.source_object_id


def test_saving_callback_cannot_enable_tex_after_preflight(monkeypatch):
    import subprocess
    a=api();fig=figure();text=fig.text(.2,.4,'DynamicTeX')
    attempts=[]
    def enable(event):
        if fig.canvas.is_saving():text.set_usetex(True)
    connection=fig.canvas.mpl_connect('draw_event',enable)
    def deny(*args,**kwargs):
        attempts.append(args);raise AssertionError('dynamic TeX attempted launch')
    monkeypatch.setattr(subprocess,'Popen',deny)
    try:
        with pytest.raises(a.CaptureError,match='unsupported_tex'):a.capture_pdf(fig,bbox_inches='tight')
        assert attempts==[]
    finally:fig.canvas.mpl_disconnect(connection)


def test_draw_event_raw_alpha_is_current_not_inventory_snapshot():
    fig=figure();text=fig.text(.2,.4,'ChangedAlpha',color=(0,0,0,.8))
    def change(event):
        if fig.canvas.is_saving():text.set_alpha(.3)
    connection=fig.canvas.mpl_connect('draw_event',change)
    try:c=api().capture_pdf(fig,bbox_inches='tight')
    finally:fig.canvas.mpl_disconnect(connection)
    event=next(e for e in c.events if e.text=='ChangedAlpha')
    assert event.raw_artist_alpha==.3 and event.raw_color_alpha==.8
    assert event.alpha.effective==.3


def test_same_figure_waits_for_active_capture_before_runtime_validation(monkeypatch):
    import threading
    a=api();fig=figure();fig.text(.2,.4,'Shared')
    ready=threading.Event();release=threading.Event();second_started=threading.Event()
    native=RendererPdf.draw_text
    def hold(renderer,*args,**kwargs):
        ready.set()
        assert release.wait(5),'test control was not released'
        return native(renderer,*args,**kwargs)
    monkeypatch.setattr(RendererPdf,'draw_text',hold)
    def second_capture():
        second_started.set()
        return a.capture_pdf(fig)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first=executor.submit(a.capture_pdf,fig)
        try:
            assert ready.wait(5)
            second=executor.submit(second_capture)
            assert second_started.wait(5)
            # A premature failure must be observed while the first draw is held;
            # waiting here is the explicit concurrency control, not a product delay.
            try:
                second.result(timeout=.2)
            except TimeoutError:
                pass
        finally:release.set()
        captures=(first.result(timeout=5),second.result(timeout=5))
    assert all([e.text for e in c.events if e.kind=='text']==['Shared'] for c in captures)


@pytest.mark.parametrize('location', ['title','cell','pre_tight'])
def test_tex_guard_precedes_all_layout_measurements(monkeypatch,location):
    import subprocess
    a=api();fig=figure('constrained' if location!='pre_tight' else None);ax=fig.subplots()
    if location=='cell':text=ax.table(cellText=[['TeX metric guard cell']],loc='center')[0,0].get_text()
    elif location=='title':text=ax.set_title('TeX metric guard title')
    else:text=fig.text(.2,.4,'TeX metric guard pre crop')
    attempts=[]
    def enable(event):
        if fig.canvas.is_saving() or location=='pre_tight':text.set_usetex(True)
    token=fig.canvas.mpl_connect('draw_event',enable)
    def deny(*args,**kwargs):
        attempts.append(args);raise AssertionError('text metrics launched TeX')
    monkeypatch.setattr(subprocess,'Popen',deny)
    try:
        with pytest.raises(a.CaptureError,match='unsupported_tex'):
            a.capture_pdf(fig,bbox_inches='tight' if location=='pre_tight' else None)
        assert attempts==[]
    finally:fig.canvas.mpl_disconnect(token)


@pytest.mark.parametrize('feature,issue', [
    ('effects','path_effect_capture_pending'),('clip','nonrectangular_clip_capture_pending')])
def test_dynamic_coverage_features_cannot_be_silently_accepted(feature,issue):
    from matplotlib.patheffects import Normal
    from matplotlib.patches import Circle
    fig=figure();text=fig.text(.2,.4,'dynamic feature')
    def change(event):
        if fig.canvas.is_saving():
            if feature=='effects':text.set_path_effects([Normal()])
            else:
                text.set_clip_on(True);text.set_clip_path(Circle((.3,.4),.1,transform=fig.transFigure))
    token=fig.canvas.mpl_connect('draw_event',change)
    try:c=api().capture_pdf(fig,bbox_inches='tight')
    finally:fig.canvas.mpl_disconnect(token)
    assert issue in c.capture_issues


def test_capture_resolves_none_without_ambient_tight_setting():
    fig=figure();fig.text(.2,.3,'plain')
    with mpl.rc_context({'savefig.bbox':'tight'}):
        c=api().capture_pdf(fig,bbox_inches=None)
        assert c.origin_display==(0,0) and c.save_tight_bbox_inches is None
        assert mpl.rcParams['savefig.bbox']=='tight'
