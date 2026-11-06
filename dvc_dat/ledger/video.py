"""``Video``: a video as a ledger value, a lazy handle over a source that is read only where an operation needs it
(SVP 249).

A ``Video`` holds a source, a URL (``gs://…``, ``https://…``, anything ``fsspec`` opens), a local file or frames in
memory, and its stored form is a folder of segments plus a manifest. Sealing converts the source through one
``ffmpeg`` process into segments of fixed length and stores each one as a part, never holding the video whole in
memory; a loaded ``Video`` reads its manifest alone, and ``frame``, ``frames``, ``clip``, ``path`` and ``iter``
fetch the segments they cover, once, into the local art store.

The stored form a ledger wants is declared on the root ledger, one row per ledger, the shape of
``ledger/lifetime``: ``(ledger/<name>, ledger/video, "h264 yuv420p cfr seg=10s")``. A ``Video`` sealed onto that
ledger is transcoded to it, unless the source already is in it (then it is split without re-encoding), or unless
sealed with ``canonical=False``, which keeps the source's codec and only splits at its keyframes.

``ffmpeg`` and ``ffprobe`` must be on ``PATH`` to seal or read one; a URL source needs ``fsspec`` (the ``video``
extra) and the filesystem package its scheme names (``gcsfs`` for ``gs://``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
import warnings
import weakref
from fractions import Fraction
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from .codec import canonical as canonical_json
from .value import Value

if TYPE_CHECKING:
    import numpy as np

    from .store import ArtStore, Part

#: The root ledger's row naming a ledger's video standard: ``(ledger/<name>, ledger/video, "<standard>")``.
STANDARD = "ledger/video"
#: The standard a video is encoded to when there is no source codec to keep (frames in memory) and no ledger row.
DEFAULT_STANDARD = "h264 yuv420p cfr seg=10s"
#: The file inside the stored folder that describes the video.
MANIFEST = "manifest.json"
#: The encoder settings of a transcode, fixed so a source gives the same bytes on every machine with the same
#: ``ffmpeg`` build: ``x264``'s output depends on its thread count, never on the cores it runs on.
_X264 = ("-preset", "medium", "-crf", "23", "-x264-params", "threads=8")
#: Segment container: fragmented MP4, each segment playable alone, no muxer version or time written into it.
_SEGMENT_OUT = ("-fflags", "+bitexact", "-flags:v", "+bitexact", "-f", "segment", "-reset_timestamps", "1",
                "-segment_format", "mp4", "-segment_format_options",
                "movflags=+frag_keyframe+empty_moov+default_base_moof:fflags=+bitexact")
#: The block a URL source is read and spooled in.
_BLOCK = 1 << 20

_WARNED: set = set()


class Standard:
    """A parsed video standard, the text of a ``ledger/video`` row: ``"<codec> <pix_fmt> cfr seg=<n>s"``.

    The codec is ``h264`` (encoded by ``libx264``); ``pix_fmt`` any pixel format ``ffmpeg`` names; ``cfr`` a constant
    frame rate (the source's average); ``seg=<n>s`` the segment length in whole seconds. Any other word is
    ``ValueError``."""

    CODECS = {"h264": "libx264"}

    def __init__(self, text: str) -> None:
        words = text.split() if isinstance(text, str) else []
        if len(words) != 4 or words[0] not in self.CODECS or words[2] != "cfr" or not words[3].startswith("seg=") \
                or not words[3].endswith("s") or not words[3][4:-1].isdigit() or int(words[3][4:-1]) < 1:
            raise ValueError(f"a video standard is '<codec> <pix_fmt> cfr seg=<seconds>s' with codec "
                             f"{'|'.join(self.CODECS)}, such as {DEFAULT_STANDARD!r}; not {text!r}")
        self.text = " ".join(words)
        self.codec, self.pix_fmt, self.seconds = words[0], words[1], int(words[3][4:-1])


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise FileNotFoundError(f"{name} is not on PATH: a Video is sealed and read through ffmpeg and ffprobe")
    return found


def _run(args: List[str], what: str) -> str:
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"{what}: {Path(args[0]).name} exited {done.returncode}: {done.stderr.strip()[-2000:]}")
    return done.stdout


def _probe(path: Path) -> Dict[str, Any]:
    """The first video stream of ``path``: codec, pixel format, size and frame rates."""
    out = _run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=codec_name,pix_fmt,width,height,r_frame_rate,avg_frame_rate", "-of", "json", str(path)],
               f"probing {path}")
    streams = json.loads(out).get("streams") or []
    if not streams:
        raise ValueError(f"{path}: no video stream")
    return streams[0]


def _count(path: Path) -> int:
    """The frames of ``path``'s first video stream, counted by its packets (nothing decoded)."""
    out = _run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                "stream=nb_read_packets", "-of", "csv=p=0", str(path)], f"counting frames of {path}")
    return int(out.strip().split(",")[0])


def _keyframes_at_boundaries(path: Path, seconds: int) -> bool:
    """Does every segment boundary of a ``seconds`` split land on a keyframe: is the first frame at or after each
    multiple of ``seconds`` a keyframe? (What a transcode to the standard forces.)"""
    out = _run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                "-of", "csv=p=0", str(path)], f"reading the keyframes of {path}")
    frames: List[Tuple[float, bool]] = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and parts[0] not in ("", "N/A"):
            frames.append((float(parts[0]), "K" in parts[1]))
    frames.sort()
    if not frames or not frames[0][1]:
        return False
    k = 1
    for t, key in frames:
        if t >= k * seconds:
            if not key:
                return False
            while t >= k * seconds:
                k += 1
    return True


def _rate(text: str) -> Fraction:
    num, _, den = str(text).partition("/")
    return Fraction(int(num), int(den or 1))


def _fps(value: Any) -> Fraction:
    """A frame rate from a number, a ``Fraction`` or ``"30000/1001"``; positive."""
    if isinstance(value, Fraction):
        f = value
    elif isinstance(value, str) and "/" in value:
        f = _rate(value)
    elif isinstance(value, float):
        f = Fraction(repr(value))
    else:
        f = Fraction(value)
    if f <= 0:
        raise ValueError(f"fps is positive, not {value!r}")
    return f


def _rational(f: Fraction) -> str:
    return f"{f.numerator}/{f.denominator}"


def _spool(url: str, dest: Path) -> None:
    """Copy the bytes at ``url`` to ``dest`` in 1 MiB blocks, never whole: an MP4 whose index sits at its end
    cannot be read by ``ffmpeg`` from a pipe, so a URL is spooled to a file first."""
    try:
        import fsspec
    except ImportError:
        raise ImportError("a Video from a URL reads it through fsspec: install dvc_dat[video]") from None
    with fsspec.open(url, "rb") as src, open(dest, "wb") as out:
        for block in iter(lambda: src.read(_BLOCK), b""):
            out.write(block)


class Video(Value):
    """A video: a handle over a source, stored as segments plus a manifest, read lazily (SVP 249).

    Made from a source with ``Video.from_url``, ``Video.from_path`` or ``Video.from_frames``; loaded from a ledger
    as any value (``rev.load(name)``), and then it holds only its manifest. ``frame(n)``, ``frames(a, b)``,
    ``iter()``, ``clip(a, b)`` and ``path()`` fetch the segments they cover, once, into the local art store. A frame
    is a ``numpy`` array, ``(height, width, 3)`` ``uint8``, RGB.

    **Stored form.** A folder: ``manifest.json`` (codec, pixel format, size, frame rate, frame count, duration,
    segment length, the standard, and each segment's first frame, frame count and sha256) and ``seg/00000.mp4`` …,
    each a fragmented MP4 that starts on a keyframe and plays alone, so a frame's address is a segment and an
    offset. The encoding is the folder's content manifest, ``{"files": {relpath: sha256}}`` in canonical JSON, a
    ``Dat``'s shape, so two videos with the same segments have one hash and a segment two videos share is stored
    once.

    **Sealing.** ``seal`` takes ``canonical`` besides what every value's takes. Sealed onto a ledger whose root
    declares a standard (``(ledger/<name>, ledger/video, "h264 yuv420p cfr seg=10s")``), the source is transcoded
    to it, or split without re-encoding when it is already in it; ``canonical=False``, or a ledger with no row
    (said once per ledger), keeps the source's codec and splits it at its keyframes near every 10 s. Frames in
    memory have no codec to keep and are always encoded, to the ledger's standard or ``DEFAULT_STANDARD``.
    ``v.seal()`` and a ``v.hash`` before a save read no ledger, so they convert with ``canonical=False``.

    **The encoding rule** (deterministic and lossless, ``Value``). A ``Video``'s value is its stored segments and
    manifest, not the frames they decode to, and on that value both clauses hold: equal stored forms encode to the
    same bytes, and ``decode`` gives back a video whose encoding is those bytes. Converting a source is not
    canonical: ``canonical=False`` keeps the source's bytes, so two files holding the same frames in different
    codecs or containers are different values; a transcode is lossy and gives the same bytes for the same frames
    only under the same ``ffmpeg`` and ``x264`` builds (the encoder settings are fixed, ``_X264``, and no muxer
    version or time is written). Each limit is an ``xfail(strict=True)`` in ``tests/ledger/test_value_encoding.py``.

    Audio is not kept. Inside a sandboxed function a ``Video`` that has to run ``ffmpeg`` is ``ConfinedProcess``.
    """

    def __init__(self, source: Tuple[Any, ...], *, name: Optional[str] = None) -> None:
        """A video over ``source``; made by ``from_url``, ``from_path``, ``from_frames`` or a load, not directly."""
        self.__dict__["_source"] = source
        super().__init__(name=name)

    @classmethod
    def from_url(cls, url: str, *, name: Optional[str] = None) -> "Video":
        """A video whose source is the file at ``url`` (``gs://…``, ``https://…``, any scheme ``fsspec`` opens).

        Read only when sealed or hashed, in blocks: spooled to a local temporary file, never held in memory."""
        if not isinstance(url, str) or "://" not in url:
            raise ValueError(f"a URL names its scheme (gs://bucket/game.mp4), not {url!r}; a local file is "
                             "Video.from_path")
        return cls(("url", url), name=name)

    @classmethod
    def from_path(cls, path: Union[str, Path], *, name: Optional[str] = None) -> "Video":
        """A video whose source is the local file ``path``; ``FileNotFoundError`` when it is not a file."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"{p}: a Video's source file")
        return cls(("path", p), name=name)

    @classmethod
    def from_frames(cls, frames: Iterable["np.ndarray"], fps: Any, *, name: Optional[str] = None) -> "Video":
        """A video of ``frames``, each a ``(height, width, 3)`` ``uint8`` RGB array, all one size, at ``fps``.

        Encoded as it is iterated, when sealed or hashed; the frames are never accumulated, so the iterable is
        read once."""
        return cls(("frames", frames, _fps(fps)), name=name)

    # --- sealing -------------------------------------------------------------------------------------------

    def seal(self, to: Any = True, *, canonical: bool = True, **kwargs: Any) -> str:  # type: ignore[override]
        """``Value.seal``, converting the source to the ledger's standard first (see the class).

        ``canonical=False`` keeps the source's codec and only splits it at its keyframes; a ledger whose root
        declares no ``ledger/video`` standard seals that way too, said once per ledger. ``to=True`` (``v.seal()``)
        reads no ledger and converts as ``canonical=False``."""
        if not self.sealed and self.__dict__.get("_files") is None:
            self.__dict__["_mode"] = self._standard_for(to) if canonical else None
        return super().seal(to, **kwargs)

    @staticmethod
    def _standard_for(to: Any) -> Optional[str]:
        """The standard the root ledger declares for the ledger ``to`` seals onto; ``None`` with no ledger, or no
        row (warned once per ledger)."""
        from .errors import LedgerError
        from .ledger import ROOT, Ledger
        from .txn import Transaction

        ledger = to._ledger if isinstance(to, Transaction) else to if isinstance(to, Ledger) else None
        if ledger is None:
            return None
        name = ledger._store.name
        why = None
        try:
            from .named import ledgers

            words = ledgers[ROOT].at().all(f"ledger/{name}", STANDARD)
        except (LedgerError, KeyError) as e:             # root does not open: no row can be read
            words, why = [], f"the root ledger does not open ({e})"
        if len(words) > 1:
            raise ValueError(f"root declares more than one video standard for ledger {name}: "
                             f"{', '.join(repr(w) for w in words)}")
        if words:
            return Standard(str(words[0])).text
        if name not in _WARNED:
            _WARNED.add(name)
            why = why or f"root declares no (ledger/{name}, {STANDARD}, ...) row"
            warnings.warn(f"ledger {name}: {why}; a Video sealed onto it keeps its source codec (canonical=False)",
                          stacklevel=4)
        return None

    def _stage(self) -> Tuple[Path, Dict[str, str], Dict[str, Any]]:
        """The source converted to the stored form in a local folder: ``(folder, files, manifest)``. Done once per
        mode and kept while the object lives (the save hardlinks the files into the art store)."""
        mode = self.__dict__.get("_mode")
        staged = self.__dict__.get("_staged")
        if staged is not None and staged[0] == mode:
            return staged[1]
        source = self.__dict__.get("_source")
        if source is None:
            raise ValueError(f"{self!r} has no source to convert")
        if source[0] == "frames" and staged is not None:
            raise ValueError("a Video's frames are read once: it was converted without a ledger's standard (a hash "
                             "or v.seal() before the save), and cannot be converted again to another")
        folder = Path(tempfile.mkdtemp(prefix="dvc-dat-video-"))
        weakref.finalize(self, shutil.rmtree, str(folder), True)
        result = _convert(source, Standard(mode) if mode is not None else None, folder)
        self.__dict__["_staged"] = (mode, result)
        return result

    def _files_now(self) -> Dict[str, str]:
        stored = self.__dict__.get("_files")
        return stored if stored is not None else self._stage()[1]

    def _info(self) -> Dict[str, Any]:
        """The manifest: what ``manifest.json`` holds."""
        info = self.__dict__.get("_manifest")
        return info if info is not None else self._stage()[2]

    def encode(self, out: IO[bytes]) -> None:
        """Write the stored folder's content manifest, ``{"files": {relpath: sha256}}``, canonical JSON.

        Unsealed, the source is converted first (once); the segments and ``manifest.json`` are ``_parts``."""
        out.write(canonical_json({"files": self._files_now()}).encode())

    @classmethod
    def decode(cls, src: IO[bytes], store: "ArtStore") -> "Video":
        """The video the content manifest read from ``src`` names: ``manifest.json`` is read, no segment is."""
        files = json.load(src)["files"]
        fetch = getattr(store._scope, "fetch", None)          # the value's store, for a later miss
        with store.fetching(fetch), store.open(files[MANIFEST]) as f:
            info = json.load(f)
        v = cls(None)  # type: ignore[arg-type]
        v.__dict__.update(_files=files, _manifest=info, _store=store, _fetch=fetch)
        return v

    def _parts(self) -> List[Tuple[str, Path]]:
        if self.__dict__.get("_files") is not None:
            return []
        folder, files, _info = self._stage()
        seen: Dict[str, Path] = {}
        for rel, h in sorted(files.items()):
            seen.setdefault(h, folder / rel)
        return list(seen.items())

    @classmethod
    def _stored_hashes(cls, store: "ArtStore", h: str) -> List[str]:
        """The segments and ``manifest.json`` of the video stored under ``h``."""
        with store.open(h) as src:
            return list(dict.fromkeys(json.load(src)["files"].values()))

    def _seal_bytes(self, size: int) -> int:
        folder, files, _info = self._stage()
        return sum((folder / rel).stat().st_size for rel in files)

    def _after_seal(self, store: "ArtStore", name: Optional[str] = None) -> None:
        """Saved: read from the art store from now on, as a load would."""
        files = self._files_now()
        self.__dict__.update(_files=files, _manifest=self._info(), _store=store,
                             _fetch=getattr(store._scope, "fetch", None))

    # --- reading -------------------------------------------------------------------------------------------

    def _segment(self, i: int) -> Path:
        """Segment ``i`` as a local file: staged, or fetched once into the art store."""
        rel = self._info()["segments"][i]["file"]
        store = self.__dict__.get("_store")
        if store is None:
            return self._stage()[0] / rel
        with store.fetching(self.__dict__.get("_fetch")):
            return store._have(self._files_now()[rel])

    def _span(self, a: int, b: int) -> Tuple[int, int]:
        n = int(self._info()["frames"])
        if not (isinstance(a, int) and isinstance(b, int)) or not 0 <= a <= b <= n:
            raise IndexError(f"frames [{a}, {b}) of a video of {n}")
        return a, b

    def frames(self, a: int, b: int) -> Iterator["np.ndarray"]:
        """Frames ``[a, b)``, decoded one at a time from the segments that cover them, each fetched once."""
        import numpy as np

        a, b = self._span(a, b)
        info = self._info()
        size = int(info["width"]) * int(info["height"]) * 3
        shape = (int(info["height"]), int(info["width"]), 3)
        for i, seg in enumerate(info["segments"]):
            lo, hi = int(seg["start"]), int(seg["start"]) + int(seg["frames"])
            if hi <= a or lo >= b:
                continue
            first, last = max(a, lo) - lo, min(b, hi) - lo
            proc = subprocess.Popen(
                [_tool("ffmpeg"), "-nostdin", "-v", "error", "-i", str(self._segment(i)), "-map", "0:v:0",
                 "-vf", f"select=gte(n\\,{first})", "-fps_mode", "passthrough", "-frames:v", str(last - first),
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            assert proc.stdout is not None
            try:
                for _ in range(last - first):
                    data = proc.stdout.read(size)
                    if len(data) != size:
                        raise RuntimeError(f"segment {seg['file']} decoded short of frame {lo + first + _}")
                    yield np.frombuffer(data, np.uint8).reshape(shape)
            finally:
                proc.stdout.close()
                proc.kill()
                proc.wait()

    def frame(self, n: int) -> "np.ndarray":
        """Frame ``n``: the one segment holding it fetched, nothing else."""
        return next(self.frames(n, n + 1))

    def iter(self) -> Iterator["np.ndarray"]:
        """Every frame in order, a segment fetched as it is reached."""
        return self.frames(0, int(self._info()["frames"]))

    def clip(self, a: int, b: int) -> "Video":
        """Frames ``[a, b)`` as a new, unsealed ``Video``.

        Reading or sealing it fetches only the segments that cover them; it is encoded anew, to this video's
        standard (else ``DEFAULT_STANDARD``)."""
        a, b = self._span(a, b)
        info = self._info()
        v = Video(("frames", self.frames(a, b), _rate(info["fps"])))
        v.__dict__["_mode"] = info.get("standard") or DEFAULT_STANDARD
        return v

    def path(self) -> Path:
        """The whole video as one local MP4 file, for a reader that needs a file.

        Its segments joined without re-encoding, once: under the art store's ``video/`` (a saved video) or beside
        the staged segments (an unsealed one)."""
        store = self.__dict__.get("_store")
        n = len(self._info()["segments"])
        if store is None:
            folder = self._stage()[0]
            dest = folder / "video.mp4"
        else:
            dest = store.dats.parent / "video" / f"{self.hash}.mp4"
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.tmp-{uuid.uuid4().hex[:8]}")
        listing = dest.with_name(f"{dest.name}.list-{uuid.uuid4().hex[:8]}")
        try:
            listing.write_text("".join(f"file '{str(self._segment(i)).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                                       for i in range(n)))
            _run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                  "-map", "0:v:0", "-c", "copy", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                  "-movflags", "+faststart", "-f", "mp4", str(tmp)], f"joining the segments of {self!r}")
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
            listing.unlink(missing_ok=True)
        return dest


def _convert(source: Tuple[Any, ...], standard: Optional[Standard], folder: Path) -> Tuple[Path, Dict[str, str],
                                                                                         Dict[str, Any]]:
    """Convert ``source`` into ``folder`` (``seg/*.mp4`` and ``manifest.json``) through one ``ffmpeg`` process:
    transcoded to ``standard``, split without re-encoding when the source is in it already, or with no
    ``standard`` split at the source's keyframes. ``(folder, files, manifest)``."""
    from .store import file_sha

    (folder / "seg").mkdir(parents=True)
    kind = source[0]
    feed: Optional[Iterator[Any]] = None
    first: Any = None
    if kind == "frames":
        _kind, frames, fps = source
        feed = iter(frames)
        first = next(feed, None)
        if first is None:
            raise ValueError("a Video from frames needs at least one frame")
        shape = getattr(first, "shape", None)
        if getattr(first, "dtype", None) is None or str(first.dtype) != "uint8" or shape is None or len(shape) != 3 \
                or shape[2] != 3:
            raise ValueError(f"a frame is a (height, width, 3) uint8 RGB array, not {type(first).__name__} "
                             f"{shape}")
        height, width = int(shape[0]), int(shape[1])
        standard = standard or Standard(DEFAULT_STANDARD)
        inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", _rational(fps),
                  "-i", "pipe:0"]
        copy = False
    else:
        if kind == "url":
            local = folder / "source"
            _spool(source[1], local)
        else:
            local = Path(source[1])
        probe = _probe(local)
        fps = _rate(probe.get("avg_frame_rate") or probe["r_frame_rate"])
        if fps <= 0:
            fps = _rate(probe["r_frame_rate"])
        inputs = ["-i", str(local)]
        copy = standard is None or (
            probe["codec_name"] == standard.codec and probe.get("pix_fmt") == standard.pix_fmt
            and _rate(probe["r_frame_rate"]) == _rate(probe["avg_frame_rate"])
            and _keyframes_at_boundaries(local, standard.seconds))
    seconds = standard.seconds if standard is not None else Standard(DEFAULT_STANDARD).seconds
    if copy:
        codec_args = ["-c", "copy"]
    else:
        assert standard is not None
        codec_args = ["-c:v", Standard.CODECS[standard.codec], *_X264, "-pix_fmt", standard.pix_fmt,
                      "-fps_mode", "cfr", "-r", _rational(fps),
                      "-force_key_frames", f"expr:gte(t,n_forced*{seconds})"]
    args = [_tool("ffmpeg"), *(["-nostdin"] if feed is None else []), "-v", "error", *inputs,
            "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1", *codec_args,
            *_SEGMENT_OUT, "-segment_time", str(seconds), str(folder / "seg" / "%05d.mp4")]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE if feed is not None else subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=err)
        try:
            if feed is not None:
                assert proc.stdin is not None
                try:
                    proc.stdin.write(_frame_bytes(first, first.shape))
                    for frame in feed:
                        proc.stdin.write(_frame_bytes(frame, first.shape))
                finally:
                    proc.stdin.close()
            code = proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        if code != 0:
            err.seek(0)
            raise RuntimeError(f"ffmpeg exited {code} converting the video: {err.read().decode(errors='replace')[-2000:]}")
    if kind == "url":
        (folder / "source").unlink()
    segs = sorted((folder / "seg").iterdir())
    if not segs:
        raise ValueError("the source holds no video frames")
    segments, start = [], 0
    files: Dict[str, str] = {}
    for p in segs:
        rel = f"seg/{p.name}"
        n, h = _count(p), file_sha(p)
        segments.append({"file": rel, "start": start, "frames": n, "sha256": h})
        files[rel] = h
        start += n
    head = _probe(segs[0])
    manifest = {
        "codec": head["codec_name"], "pix_fmt": head.get("pix_fmt"), "width": int(head["width"]),
        "height": int(head["height"]), "fps": _rational(fps), "frames": start,
        "duration": float(Fraction(start) / fps), "segment_seconds": seconds,
        "standard": standard.text if standard is not None else None, "segments": segments,
    }
    (folder / MANIFEST).write_text(canonical_json(manifest, strict=True))
    files[MANIFEST] = file_sha(folder / MANIFEST)
    return folder, files, manifest


def _frame_bytes(frame: Any, shape: Tuple[int, ...]) -> bytes:
    import numpy as np

    a = np.asarray(frame)
    if a.shape != tuple(shape) or a.dtype != np.uint8:
        raise ValueError(f"every frame is {tuple(shape)} uint8, as the first; not {a.dtype} {a.shape}")
    return np.ascontiguousarray(a).tobytes()
