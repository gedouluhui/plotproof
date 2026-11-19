"""CA1 save-time PDF events. Not a full §2 source manifest or a checker.

Temporarily instruments Matplotlib's backend. Calls through this module are
serialized; unrelated concurrent Matplotlib use is not supported. Live Figures
are trusted Python objects: their custom draw methods execute as in savefig.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from math import isfinite
import threading
import warnings

from .capture_events import AppliedAlpha, CapturedPdf, DrawEvent, SourceArtist
from .evidence import SaveWarning
from .geometry import Rect

_LOCK = threading.Lock()
_LOCAL = threading.local()
_MAX_BYTES = 16 * 1024 * 1024
_MAX_EVENTS = 100_000
_MAX_VERTICES = 1_000_000


class CaptureError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__('Capture failed: ' + reason)


class _Output(BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise CaptureError('pdf_byte_limit')
        return super().write(data)


class _Hooks:
    def __init__(self):
        self.entries = []

    def set(self, target, name, value):
        owned = name in vars(target)
        previous = vars(target).get(name)
        self.entries.append((target, name, owned, previous))
        setattr(target, name, value)

    def restore(self):
        for target, name, owned, previous in reversed(self.entries):
            if owned:
                setattr(target, name, previous)
            else:
                delattr(target, name)


def _artists(fig):
    """One deterministic traversal for preflight and inventory, including Cells."""
    from matplotlib.table import Cell
    seen = set()
    pending = [fig]
    while pending:
        artist = pending.pop()
        if id(artist) in seen:
            continue
        seen.add(id(artist))
        if len(seen) > _MAX_EVENTS:
            raise CaptureError('source_limit')
        yield artist
        children = list(artist.get_children())
        if isinstance(artist, Cell):
            children.append(artist.get_text())
        pending.extend(reversed(children))


class _Recorder:
    def __init__(self, fig, output, max_events):
        from matplotlib.text import Text
        from matplotlib.patches import Patch
        self.fig, self.output, self.max_events = fig, output, max_events
        self.Text, self.Patch = Text, Patch
        self.ids = {}
        self.objects = []
        self.sources = []
        self.stack = []
        self.events = []
        self.issues = set()
        self.vertex_count = 0
        self.crop_calls = []
        self.hooks = _Hooks()

    def register(self, artist, owner=None):
        if not isinstance(artist, (self.Text, self.Patch)):
            return None
        key = id(artist)
        if key not in self.ids:
            if len(self.sources) >= _MAX_EVENTS:
                raise CaptureError('source_limit')
            uid = len(self.sources)
            self.ids[key] = uid
            self.objects.append(artist)
            color = None
            if isinstance(artist, self.Text):
                from matplotlib.colors import to_rgba
                color = float(to_rgba(artist.get_color())[3])
            elif isinstance(artist, self.Patch):
                color = float(artist.get_facecolor()[3])
            raw_alpha = artist.get_alpha()
            self.sources.append(SourceArtist(uid, type(artist).__name__,
                artist.get_text() if isinstance(artist,self.Text) else None,
                bool(artist.get_visible()), None if raw_alpha is None else float(raw_alpha), color, None, owner))
        # Coverage-affecting properties can change in saving-time callbacks.
        if artist.get_rasterized():
            self.issues.add('rasterized_capture_pending')
        if artist.get_path_effects():
            self.issues.add('path_effect_capture_pending')
        if artist.get_clip_path() is not None:
            self.issues.add('nonrectangular_clip_capture_pending')
        uid = self.ids[key]
        if owner is not None:
            self.sources[uid] = replace(self.sources[uid], owner_unit_id=owner)
        if isinstance(artist, self.Text):
            if artist.get_wrap(): self.issues.add('wrapped_text_capture_pending')
            # Saving-time callbacks can create/replace a bbox after inventory.
            patch = artist.get_bbox_patch()
            patch_id = self.register(patch, owner=uid) if patch is not None else None
            old_id = self.sources[uid].background_patch_id
            if old_id is not None and old_id != patch_id:
                self.sources[old_id] = replace(self.sources[old_id], owner_unit_id=None)
            self.sources[uid] = replace(self.sources[uid], background_patch_id=patch_id)
        return uid

    def inventory(self):
        for artist in _artists(self.fig):
            self.register(artist)

    def target(self, renderer):
        return getattr(getattr(renderer,'file',None),'fh',None) is self.output

    def belongs(self, artist):
        return id(artist) in self.ids or artist.get_figure(root=True) is self.fig

    def applied(self, gc, color, text=False):
        rgba = gc.get_rgb() if text else color
        component = float(rgba[3]) if rgba is not None and len(rgba)>3 else 1.0
        gc_alpha = float(gc.get_alpha())
        forced = bool(gc.get_forced_alpha())
        effective = gc_alpha if forced else component
        if not all(isfinite(v) and 0<=v<=1 for v in (component,gc_alpha,effective)):
            raise CaptureError('invalid_alpha')
        return AppliedAlpha(gc_alpha, forced, component, effective)

    def add(self, kind, renderer, gc, *, color=None, artist=None, box=None,
            text=None, size=None, angle=None, vertices=(), codes=None):
        if not self.target(renderer): return
        if len(self.events) >= self.max_events: raise CaptureError('event_limit')
        if artist is None and self.stack: artist = self.stack[-1]
        uid = self.register(artist) if artist is not None else None
        if uid is None: self.issues.add('unassociated_material_event')
        if box is not None and not isinstance(box, Rect):
            try: box = Rect(*map(float,box))
            except (ValueError,TypeError,OverflowError):
                box = None; self.issues.add('invalid_event_geometry')
        source = self.sources[uid] if uid is not None else None
        raw_alpha = None if artist is None else artist.get_alpha()
        raw_color = None
        if isinstance(artist,self.Text):
            from matplotlib.colors import to_rgba
            raw_color = float(to_rgba(artist.get_color())[3])
        elif isinstance(artist,self.Patch):
            raw_color = float(artist.get_facecolor()[3])
        self.events.append(DrawEvent(len(self.events),kind,uid,
            None if source is None else source.artist_class,box,self.applied(gc,color,text=kind=='text'),
            None if raw_alpha is None else float(raw_alpha),raw_color,text,size,angle,vertices,codes))

    def install(self):
        from matplotlib.backends.backend_pdf import RendererPdf
        original_text = self.Text.draw
        original_layout = self.Text._get_layout
        original_patch = self.Patch._draw_paths_with_artist_properties
        original_emit_text = RendererPdf.draw_text
        original_emit_path = RendererPdf.draw_path
        original_tight = self.fig.get_tightbbox

        def text_draw(artist, renderer):
            if not self.belongs(artist): return original_text(artist,renderer)
            if artist.get_usetex(): raise CaptureError('unsupported_tex')
            self.register(artist)
            self.stack.append(artist)
            try: return original_text(artist,renderer)
            finally: self.stack.pop()

        def layout(artist, renderer):
            # Axis title placement and table auto-sizing measure before Text.draw.
            if self.belongs(artist) and artist.get_usetex():
                raise CaptureError('unsupported_tex')
            return original_layout(artist, renderer)

        def patch_draw(artist, renderer, paths):
            if not self.belongs(artist): return original_patch(artist,renderer,paths)
            self.register(artist)
            self.stack.append(artist)
            try: return original_patch(artist,renderer,paths)
            finally: self.stack.pop()

        def emit_text(renderer,gc,x,y,s,prop,angle,ismath=False,mtext=None):
            if self.target(renderer):
                artist = mtext if isinstance(mtext,self.Text) else (self.stack[-1] if self.stack else None)
                if ismath: self.issues.add('mathtext_capture_pending')
                box = None
                if isinstance(artist,self.Text):
                    # Call the Text extent, not Annotation's union with its arrow.
                    box = self.Text.get_window_extent(artist,renderer).extents
                self.add('text',renderer,gc,artist=artist,box=box,text=s,
                         size=float(prop.get_size_in_points()),angle=float(angle))
            return original_emit_text(renderer,gc,x,y,s,prop,angle,ismath=ismath,mtext=mtext)

        def emit_path(renderer,gc,path,transform,rgbFace=None):
            if self.target(renderer) and rgbFace is not None:
                transformed = path.transformed(transform)
                count = len(transformed.vertices)
                if self.vertex_count + count > _MAX_VERTICES: raise CaptureError('vertex_limit')
                self.vertex_count += count
                vertices = tuple(tuple(map(float, point)) for point in transformed.vertices)
                if not all(isfinite(v) for point in vertices for v in point):
                    self.issues.add('invalid_event_geometry')
                codes = None if path.codes is None else tuple(map(int,path.codes))
                self.add('filled_path',renderer,gc,color=rgbFace,box=transformed.get_extents().extents,
                         vertices=vertices,codes=codes)
            return original_emit_path(renderer,gc,path,transform,rgbFace)

        def tight(renderer=None,*args,**kwargs):
            if any(isinstance(t,self.Text) and t.get_usetex() for t in _artists(self.fig)):
                raise CaptureError('unsupported_tex')
            box = original_tight(renderer,*args,**kwargs)
            if self.fig.canvas.is_saving():
                self.crop_calls.append(tuple(map(float,box.bounds)))
            return box

        self.hooks.set(self.Text,'draw',text_draw)
        self.hooks.set(self.Text,'_get_layout',layout)
        self.hooks.set(self.Patch,'_draw_paths_with_artist_properties',patch_draw)
        self.hooks.set(RendererPdf,'draw_text',emit_text)
        self.hooks.set(RendererPdf,'draw_path',emit_path)
        self.hooks.set(self.fig,'get_tightbbox',tight)
        for name, issue in (('draw_image','image_capture_pending'),('draw_markers','collection_capture_pending'),
                            ('draw_path_collection','collection_capture_pending'),('draw_quad_mesh','collection_capture_pending'),
                            ('draw_gouraud_triangles','gouraud_capture_pending'),('draw_tex','tex_capture_pending')):
            original = getattr(RendererPdf,name)
            def pending(renderer,*args,_original=original,_issue=issue,**kwargs):
                if self.target(renderer): self.issues.add(_issue)
                return _original(renderer,*args,**kwargs)
            self.hooks.set(RendererPdf,name,pending)


def capture_pdf(fig, *, bbox_inches=None, pad_inches=None, transparent=False,
                max_events=10_000, max_pdf_bytes=_MAX_BYTES) -> CapturedPdf:
    """Record a real PDF save and raw provenance without claiming full coverage."""
    if getattr(_LOCAL, 'active', False):
        raise CaptureError('capture_reentry')
    with _LOCK:
        _LOCAL.active = True
        try:
            return _capture_locked(fig, bbox_inches, pad_inches, transparent, max_events, max_pdf_bytes)
        finally:
            _LOCAL.active = False


def _capture_locked(fig, bbox_inches, pad_inches, transparent, max_events, max_pdf_bytes):
    import matplotlib as mpl
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.text import Text
    # Mutable canvas/DPI/rc state is inspected only after the preceding save
    # has restored it, including concurrent calls on the very same Figure.
    if (not isinstance(fig,Figure) or not isinstance(fig.canvas,FigureCanvasAgg)
            or mpl.__version__!='3.10.8'):
        raise CaptureError('unsupported_runtime')
    if bbox_inches not in (None,'tight') or type(transparent) is not bool:
        raise CaptureError('invalid_input')
    for value,limit in ((max_events,_MAX_EVENTS),(max_pdf_bytes,_MAX_BYTES)):
        if type(value) is not int or not 0<value<=limit: raise CaptureError('invalid_input')
    pad = mpl.rcParams['savefig.pad_inches'] if pad_inches is None else pad_inches
    if isinstance(pad,bool) or not isinstance(pad,(int,float)) or not isfinite(pad) or pad<0 or pad>10:
        raise CaptureError('invalid_input')
    dpi = float(fig.dpi)
    if not isfinite(dpi) or dpi<=0: raise CaptureError('invalid_input')
    if mpl.rcParams['pdf.use14corefonts']: raise CaptureError('unsupported_core_fonts')
    if any(isinstance(t,Text) and t.get_usetex() for t in _artists(fig)):
        raise CaptureError('unsupported_tex')
    output = _Output(max_pdf_bytes)
    recorder = _Recorder(fig,output,max_events)
    try:
        recorder.inventory()
        recorder.install()  # Guard metrics before even the Agg pre-draw.
        with warnings.catch_warnings(record=True):
            warnings.simplefilter('always')
            fig.canvas.draw()
            pre = tuple(map(float,fig.get_tightbbox(fig.canvas.get_renderer()).bounds)) if bbox_inches=='tight' else None
        recorder.inventory()  # Layout may have created additional source artists.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            with mpl.rc_context({'savefig.bbox':None}):
                fig.savefig(output,format='pdf',bbox_inches=bbox_inches,pad_inches=float(pad),transparent=transparent,
                    metadata={'CreationDate':None,'ModDate':None,'Creator':'PlotProof CA1 capture'})
        saved = None
        origin = (0.0,0.0)
        if bbox_inches=='tight':
            if len(recorder.crop_calls)!=1:
                recorder.issues.add('ambiguous_crop_origin');origin=None
            else:
                saved=recorder.crop_calls[0]
                if not all(isfinite(v) for v in saved) or saved[2]<=0 or saved[3]<=0:
                    recorder.issues.add('invalid_crop_origin');origin=None
                else: origin=((saved[0]-pad)*dpi,(saved[1]-pad)*dpi)
        data=output.getvalue()
        return CapturedPdf(data,sha256(data).hexdigest(),dpi,bbox_inches,float(pad),transparent,pre,saved,origin,
            tuple(recorder.sources),tuple(recorder.events),
            tuple(dict.fromkeys(SaveWarning(w.category.__name__,str(w.message)) for w in caught)),
            tuple(sorted(recorder.issues)),
            source_artists=tuple(recorder.objects))
    except CaptureError:
        raise
    except Exception:
        raise CaptureError('save_failed') from None
    finally:
        recorder.hooks.restore()
        output.close()
