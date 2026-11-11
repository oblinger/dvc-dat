"""``Video``: a video as a ledger value, a lazy handle over a source that is read only where an operation needs it
(SVP 249).

A ``Video`` holds a source, a URL (``gs://…``, ``https://…``, anything ``fsspec`` opens), a local file or frames in
memory, and its stored form is a folder of segments plus a manifest. Sealing never re-encodes a source: it splits
the file at its keyframes through one ``ffmpeg`` process, keeping the codec and the audio, and stores each segment
as a part, never holding the video whole in memory; a loaded ``Video`` reads its manifest alone, and ``frame``,
``frames``, ``clip``, ``path`` and ``iter`` fetch the segments they cover, once, into the local art store. Any
representation goes on any ledger, and changing one is an explicit ``convert``, which gives a new value (SVP 1557).

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
import weakref
from fractions import Fraction
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from .codec import canonical as canonical_json
from .value import Value

if TYPE_CHECKING:
    import numpy as np

    from .store import ArtStore, Part

#: The length a video is split at, in seconds: a split lands on the first keyframe at or after each multiple.
SEGMENT_SECONDS = 10
#: The file inside the stored folder that describes the video.
MANIFEST = "manifest.json"
#: The encoder settings where a video has no codec to keep (frames in memory, a clip), and of ``convert`` to H.264
#: with no options of its own, fixed so a source gives the same bytes on every machine with the same ``ffmpeg``
#: build: ``x264``'s output depends on its thread count, never on the cores it runs on.
_X264 = ("-preset", "medium", "-crf", "23", "-x264-params", "threads=8")
_ENCODE = ("-c:v", "libx264", *_X264, "-pix_fmt", "yuv420p")
#: Segment container options: each segment plays alone, no muxer version or time written into it. MP4 is fragmented,
#: ``delay_moov`` so a segment's edit list carries its B-frame delay: with ``empty_moov`` every segment's video runs
#: late of its audio by that delay and joined segments run long. A stream MP4 cannot hold goes in Matroska instead.
_SEGMENT_OUT = ("-fflags", "+bitexact", "-flags:v", "+bitexact", "-f", "segment", "-reset_timestamps", "1")
_FRAGMENTED = ("-segment_format", "mp4", "-segment_format_options",
               "movflags=+frag_keyframe+delay_moov+default_base_moof:fflags=+bitexact")
_MATROSKA = ("-segment_format", "matroska")
#: The block a URL source is read and spooled in.
_BLOCK = 1 << 20


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


def _audio(path: Path) -> List[Dict[str, Any]]:
    """The audio streams of ``path``: codec, channels and sample rate of each."""
    out = _run([_tool("ffprobe"), "-v", "error", "-select_streams", "a", "-show_entries",
                "stream=codec_name,channels,sample_rate", "-of", "json", str(path)], f"probing the audio of {path}")
    return [{"codec": a["codec_name"], "channels": a.get("channels"), "sample_rate": a.get("sample_rate")}
            for a in json.loads(out).get("streams") or []]


def _container(args: List[str]) -> str:
    """The segment file suffix for the ``ffmpeg`` input and stream arguments ``args``: ``.mp4`` when MP4 holds those
    streams, else ``.mkv``. Asked of ``ffmpeg`` by muxing one frame, so no list of codecs is kept here."""
    with tempfile.TemporaryDirectory(prefix="dvc-dat-video-") as d:
        done = subprocess.run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", *args, "-frames:v", "1",
                               "-f", "mp4", str(Path(d) / "try.mp4")], capture_output=True)
    return ".mp4" if done.returncode == 0 else ".mkv"


def _start(path: Path) -> Fraction:
    """The seconds at which the first video stream of ``path`` starts: its first presentation timestamp."""
    out = _run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=start_pts,time_base", "-of", "json", str(path)], f"probing the start of {path}")
    s = json.loads(out)["streams"][0]
    return int(s["start_pts"]) * _rate(s["time_base"])


def _us(seconds: Fraction) -> int:
    return round(seconds * 1_000_000)


def _time(us: int) -> str:
    """Microseconds as the seconds a concat listing reads."""
    return f"{'-' if us < 0 else ''}{abs(us) // 1_000_000}.{abs(us) % 1_000_000:06d}"


def _listing(parts: List[Tuple[Path, Fraction, Fraction, Fraction]], dest: Path) -> None:
    """An ``ffmpeg`` concat listing of ``parts``, each ``(path, video start, from, to)``: the file's own timestamps
    start at its video's start, and it covers ``[from, to)`` seconds of the joined video. Without the two the concat
    demuxer starts each file at its earliest stream and advances by its longest, so an audio packet running past
    a segment's last frame, or a first segment's B-frame delay, moves every later frame (SVP 249, 2026-11-11).
    The ends are rounded to microseconds, the listing's unit, never the lengths, so the rounding never adds up."""
    quote = chr(39) + chr(92) + chr(39) + chr(39)
    dest.write_text("".join(f"file '{str(p).replace(chr(39), quote)}'\ninpoint {_time(_us(start))}\n"
                            f"duration {_time(_us(b) - _us(a))}\n" for p, start, a, b in parts))


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
    segment length, the audio streams, and each segment's first frame, frame count and sha256) and
    ``seg/00000.mp4`` …, each starting on a keyframe and playing alone, so a frame's address is a segment and an
    offset. Segments are fragmented MP4, or Matroska (``.mkv``) for a stream MP4 cannot hold. The encoding is the
    folder's content manifest, ``{"files": {relpath: sha256}}`` in canonical JSON, a ``Dat``'s shape, so two videos
    with the same segments have one hash and a segment two videos share is stored once.

    **Sealing keeps what it is given** (SVP 1557). A source's packets are copied, video and every audio stream, and
    split at the keyframe at or after each ``SEGMENT_SECONDS``; nothing is decoded, on any ledger. Only frames in
    memory, which have no codec to keep, are encoded (H.264, yuv420p, constant rate). ``convert`` is the one way to
    change a video's representation.

    **The encoding rule** (deterministic and lossless, ``Value``). A ``Video``'s value is its stored segments and
    manifest, not the frames they decode to, and on that value both clauses hold: equal stored forms encode to the
    same bytes, and ``decode`` gives back a video whose encoding is those bytes. Sealing is not canonical: it keeps
    the source's bytes, so two files holding the same frames in different codecs or containers are different values;
    encoding frames gives the same bytes for the same frames only under the same ``ffmpeg`` and ``x264`` builds
    (the encoder settings are fixed, ``_X264``, and no muxer version or time is written). Each limit is an
    ``xfail(strict=True)`` in ``tests/ledger/test_value_encoding.py``.

    Subtitle and data streams are not kept. Inside a sandboxed function a ``Video`` that has to run ``ffmpeg`` is
    ``ConfinedProcess``.
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

    def _stage(self) -> Tuple[Path, Dict[str, str], Dict[str, Any]]:
        """The source converted to the stored form in a local folder: ``(folder, files, manifest)``. Done once and
        kept while the object lives (the save hardlinks the files into the art store)."""
        staged = self.__dict__.get("_staged")
        if staged is not None:
            return staged
        source = self.__dict__.get("_source")
        if source is None:
            raise ValueError(f"{self!r} has no source to convert")
        folder = Path(tempfile.mkdtemp(prefix="dvc-dat-video-"))
        weakref.finalize(self, shutil.rmtree, str(folder), True)
        self.__dict__["_staged"] = _convert(source, folder)
        return self.__dict__["_staged"]

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
        """Frames ``[a, b)`` and their audio as a new, unsealed ``Video``.

        Reading or sealing it fetches only the segments that cover them. The frames are encoded anew (H.264, yuv420p,
        frame-exact); the audio is copied, cut at the packets nearest the frames' times."""
        a, b = self._span(a, b)
        return Video(("clip", self, a, b))

    def convert(self, codec: str, *, pix_fmt: Optional[str] = None, fps: Any = None, audio: str = "copy",
                options: Iterable[str] = ()) -> "Video":
        """This video in another format, as a new, unsealed ``Video``; this one is untouched.

        ``codec`` is any video encoder ``ffmpeg`` has or a codec it can encode (``"h264"``, ``"libx265"``,
        ``"libvpx-vp9"``, ``"ffv1"``, ``"rawvideo"``); there is no list here, and one this ``ffmpeg`` lacks fails
        with its own message. ``pix_fmt`` keeps the source's when ``None``. ``fps`` gives a constant frame rate,
        dropping and repeating frames to reach it, and ``None`` keeps the source's timing. ``audio`` is ``"copy"`` or
        an audio encoder. ``options`` are more ``ffmpeg`` output arguments (``("-crf", "18")``), and H.264 given none
        takes ``_X264``. The conversion reads the whole video, when it is read or sealed, and a keyframe is forced
        every ``SEGMENT_SECONDS`` so its segments come out even."""
        if not isinstance(codec, str) or not codec:
            raise ValueError(f"convert takes the name of a video codec or encoder, not {codec!r}")
        return Video(("convert", self, codec, pix_fmt, _fps(fps) if fps is not None else None, audio,
                      tuple(options)))

    def _suffix(self) -> str:
        """The stored segments' file suffix."""
        return Path(self._info()["segments"][0]["file"]).suffix

    def _join(self, segments: List[int], dest: Path, maps: List[str], extra: Iterable[str] = ()) -> None:
        """The streams ``maps`` of ``segments`` (consecutive), joined without re-encoding into ``dest``, each frame at
        its place in the manifest's frame rate."""
        info = self._info()
        fps, segs = _rate(info["fps"]), info["segments"]
        base = int(segs[segments[0]]["start"])
        parts = []
        for i in segments:
            p, a = self._segment(i), int(segs[i]["start"]) - base
            parts.append((p, _start(p), Fraction(a) / fps, Fraction(a + int(segs[i]["frames"])) / fps))
        listing = dest.with_name(f"{dest.name}.list-{uuid.uuid4().hex[:8]}")
        try:
            _listing(parts, listing)
            _run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                  *extra, *maps, "-c", "copy", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                  *(["-movflags", "+faststart", "-f", "mp4"] if dest.suffix == ".mp4" else ["-f", "matroska"]),
                  str(dest)], f"joining the segments of {self!r}")
        finally:
            listing.unlink(missing_ok=True)

    def _audio_of(self, a: int, b: int, folder: Path) -> Optional[Path]:
        """The audio of frames ``[a, b)`` as a file in ``folder``, cut at packets; ``None`` for a silent video."""
        info = self._info()
        if not info.get("audio"):
            return None
        fps = _rate(info["fps"])
        covering = [(i, s) for i, s in enumerate(info["segments"])
                    if int(s["start"]) < b and int(s["start"]) + int(s["frames"]) > a]
        offset = Fraction(a - int(covering[0][1]["start"])) / fps
        dest = folder / f"audio{self._suffix()}"
        self._join([i for i, _s in covering], dest, ["-map", "0:a"],
                   ("-ss", f"{float(offset):.6f}", "-t", f"{float(Fraction(b - a) / fps):.6f}"))
        return dest

    def path(self) -> Path:
        """The whole video, audio included, as one local file: an MP4, or a Matroska file when the segments are.

        For a reader that needs a file. Its segments joined without re-encoding, once: under the art store's ``video/`` (a saved video) or beside
        the staged segments (an unsealed one)."""
        store = self.__dict__.get("_store")
        suffix = self._suffix()
        if store is None:
            dest = self._stage()[0] / f"video{suffix}"
        else:
            dest = store.dats.parent / "video" / f"{self.hash}{suffix}"
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"tmp-{uuid.uuid4().hex[:8]}-{dest.name}")
        try:
            self._join(list(range(len(self._info()["segments"]))), tmp, ["-map", "0:v:0", "-map", "0:a?"])
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest


def _rawvideo(first: Any, fps: Fraction) -> List[str]:
    """The ``ffmpeg`` input arguments of RGB frames on stdin, sized from ``first``, after checking it is a frame."""
    shape = getattr(first, "shape", None)
    if getattr(first, "dtype", None) is None or str(first.dtype) != "uint8" or shape is None or len(shape) != 3 \
            or shape[2] != 3:
        raise ValueError(f"a frame is a (height, width, 3) uint8 RGB array, not {type(first).__name__} {shape}")
    return ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{shape[1]}x{shape[0]}", "-r", _rational(fps), "-i", "pipe:0"]


def _convert(source: Tuple[Any, ...], folder: Path) -> Tuple[Path, Dict[str, str], Dict[str, Any]]:
    """Make the stored form of ``source`` in ``folder`` (``seg/*`` and ``manifest.json``) through one ``ffmpeg``
    process: a file's packets copied and split at its keyframes, frames encoded as they are iterated, a ``convert``
    encoded to its target. ``(folder, files, manifest)``."""
    from .store import file_sha

    (folder / "seg").mkdir(parents=True)
    kind = source[0]
    seconds = SEGMENT_SECONDS
    keys = ["-force_key_frames", f"expr:gte(t,n_forced*{seconds})"]
    feed: Optional[Iterator[Any]] = None
    first: Any = None
    if kind in ("frames", "clip"):
        if kind == "frames":
            frames, fps = source[1], source[2]
            audio, suffix = None, ".mp4"
        else:
            parent, a, b = source[1:]
            frames, fps = parent.frames(a, b), _rate(parent._info()["fps"])
            audio, suffix = parent._audio_of(a, b, folder), parent._suffix()
        feed = iter(frames)
        first = next(feed, None)
        if first is None:
            raise ValueError("a Video from frames needs at least one frame")
        streams = [*_rawvideo(first, fps), *(["-i", str(audio)] if audio is not None else []), "-map", "0:v:0",
                   *(["-map", "1:a", "-c:a", "copy"] if audio is not None else []), *_ENCODE,
                   "-fps_mode", "cfr", "-r", _rational(fps), *keys]
    else:
        if kind == "url":
            local = folder / "source"
            _spool(source[1], local)
        elif kind == "path":
            local = Path(source[1])
        else:
            local = source[1].path()
        probe = _probe(local)
        fps = _rate(probe.get("avg_frame_rate") or probe["r_frame_rate"])
        if fps <= 0:
            fps = _rate(probe["r_frame_rate"])
        streams = ["-i", str(local), "-map", "0:v:0", "-map", "0:a?"]
        if kind == "convert":
            _kind, _parent, codec, pix_fmt, target, sound, options = source
            fps = target if target is not None else fps
            streams += ["-c:v", codec, *(options or (_X264 if codec in ("h264", "libx264") else ())),
                        *(["-pix_fmt", pix_fmt] if pix_fmt else []),
                        *(["-fps_mode", "cfr", "-r", _rational(target)] if target is not None else []), *keys,
                        "-c:a", sound]
        else:
            streams += ["-c", "copy"]
        suffix = _container(streams)
    args = [_tool("ffmpeg"), *(["-nostdin"] if feed is None else []), "-v", "error", *streams, "-sn", "-dn",
            "-map_metadata", "-1", "-map_chapters", "-1", *_SEGMENT_OUT,
            *(_FRAGMENTED if suffix == ".mp4" else _MATROSKA), "-segment_time", str(seconds),
            str(folder / "seg" / f"%05d{suffix}")]
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
    for used in (folder / "source", folder / f"audio{suffix}"):
        used.unlink(missing_ok=True)
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
        "duration": float(Fraction(start) / fps), "segment_seconds": seconds, "audio": _audio(segs[0]),
        "segments": segments,
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
