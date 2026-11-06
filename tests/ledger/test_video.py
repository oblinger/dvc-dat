"""SVP 249: a video as a ledger value, sealed from a URL, a file or frames, stored as segments plus a manifest, and
read lazily: ``frame(n)`` fetches one segment, ``clip(a, b)`` the segments it covers, ``path()`` joins them once.

Every video here is a few seconds of synthetic frames made in the test (64x48 at 10 fps unless a test needs more);
the URL is a ``file://`` one read through ``fsspec``. The ledger's standard is a row on a root ledger of the test's
own, with ``seg=1s`` so a few seconds make several segments.
"""

import io
import json
import os
import shutil
import subprocess
import tracemalloc
import warnings
from pathlib import Path

import numpy as np
import pytest

from dvc_dat.ledger import Ledger, Video, ledgers, register_store
from dvc_dat.ledger import remote as remote_mod
from dvc_dat.ledger import video as video_mod
from dvc_dat.ledger.codec import sha256
from dvc_dat.ledger.video import DEFAULT_STANDARD, STANDARD, Standard

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None and not os.environ.get("CI"),
                                reason="ffmpeg is not on PATH (CI installs it)")

W, H, FPS = 64, 48, 10
ONE_SECOND = "h264 yuv420p cfr seg=1s"


def pictures(n, seed=0, w=W, h=H):
    """``n`` frames, each a flat grey whose level follows its index with a white square whose place follows the index
    and ``seed``, so every frame differs and a lossy codec keeps them close."""
    out = []
    for i in range(n):
        f = np.full((h, w, 3), (i * 7) % 200, np.uint8)
        x, y = (i * 3 + seed * 11) % (w - 8), (i * 2 + seed * 5) % (h - 8)
        f[y:y + 8, x:x + 8] = 255
        out.append(f)
    return out


def encode_file(path, frames, *args, fps=FPS):
    """``frames`` written to ``path`` by ffmpeg with the codec arguments ``args``."""
    h, w = frames[0].shape[:2]
    raw = b"".join(f.tobytes() for f in frames)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                    "-r", str(fps), "-i", "pipe:0", *args, str(path)], input=raw, check=True)
    return path


def mpeg4(path, n=35, **kw):
    """A source not in the standard: MPEG-4 part 2 in an MP4, keyframes wherever its encoder put them."""
    return encode_file(path, pictures(n, **kw), "-c:v", "mpeg4", "-q:v", "2")


def close(a, b, tol=12):
    """Two frames within a lossy codec's error of each other (mean absolute difference)."""
    return a.shape == b.shape and float(np.abs(a.astype(int) - b.astype(int)).mean()) < tol


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A root ledger (``.datconfig.yaml``: ``root: root``) and the ledger ``games`` beside it, no standard yet."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.setattr(video_mod, "_WARNED", set())
    (tmp_path / ".datconfig.yaml").write_text("root: root\n")
    Ledger(tmp_path / "root", create=True)
    return Ledger(tmp_path / "games", create=True)


def declare(standard, name="games"):
    """Root's row naming ledger ``name``'s video standard."""
    with ledgers.root.transaction(by="t") as t:
        t.add(f"ledger/{name}", STANDARD, standard)


def saved(L, v, name="video/G1", **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v.seal(L, name=name, **kw)
    L._values.clear()
    return L.at().load(name)


# --- seal and load, by url, by path and by frames -------------------------------------------------------------

def test_a_video_from_frames_seals_and_loads_back(world):
    declare(ONE_SECOND)
    frames = pictures(25)
    back = saved(world, Video.from_frames(iter(frames), FPS))
    assert isinstance(back, Video) and back._info()["frames"] == 25
    got = list(back.iter())
    assert len(got) == 25 and all(close(a, b) for a, b in zip(got, frames))


def test_a_video_from_a_path_seals_and_loads_back(world, tmp_path):
    declare(ONE_SECOND)
    src = mpeg4(tmp_path / "src.mp4")
    back = saved(world, Video.from_path(src))
    assert back._info()["frames"] == 35 and close(back.frame(20), pictures(35)[20])


def test_a_video_from_a_url_seals_and_loads_back_with_the_hash_of_the_same_file(world, tmp_path):
    declare(ONE_SECOND)
    src = mpeg4(tmp_path / "src.mp4")
    by_url = Video.from_url(src.as_uri())
    back = saved(world, by_url)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        by_path = Video.from_path(src)
        by_path.seal(world, name="video/G2")
    assert by_url.hash == by_path.hash == back.hash
    assert close(back.frame(3), pictures(35)[3])


def test_a_url_needs_its_scheme_and_a_path_must_be_a_file(tmp_path):
    with pytest.raises(ValueError, match="scheme"):
        Video.from_url(str(tmp_path / "x.mp4"))
    with pytest.raises(FileNotFoundError):
        Video.from_path(tmp_path / "absent.mp4")


def test_a_frame_is_an_rgb_uint8_array_and_every_frame_one_size(world):
    v = Video.from_frames(iter([np.zeros((H, W, 3), np.uint8), np.zeros((H, W + 2, 3), np.uint8)]), FPS)
    with pytest.raises(ValueError, match="every frame"):
        v.hash
    with pytest.raises(ValueError, match="uint8"):
        Video.from_frames(iter([np.zeros((H, W), np.uint8)]), FPS).hash


# --- segments plus manifest -----------------------------------------------------------------------------------

def test_the_stored_form_is_segments_of_the_standard_length_and_a_manifest(world):
    declare(ONE_SECOND)
    back = saved(world, Video.from_frames(iter(pictures(35)), FPS))
    info = back._info()
    assert [(s["file"], s["start"], s["frames"]) for s in info["segments"]] == [
        ("seg/00000.mp4", 0, 10), ("seg/00001.mp4", 10, 10), ("seg/00002.mp4", 20, 10), ("seg/00003.mp4", 30, 5)]
    assert {k: info[k] for k in ("codec", "pix_fmt", "width", "height", "fps", "frames", "segment_seconds",
                                 "standard")} == {
        "codec": "h264", "pix_fmt": "yuv420p", "width": W, "height": H, "fps": "10/1", "frames": 35,
        "segment_seconds": 1, "standard": ONE_SECOND}
    assert info["duration"] == 3.5
    files = json.loads(io.BytesIO(_encoded(back)).read())["files"]
    assert sorted(files) == ["manifest.json", *(s["file"] for s in info["segments"])]
    art = world._store.art
    for seg in info["segments"]:
        assert files[seg["file"]] == seg["sha256"] and art.exists(seg["sha256"])
        p = art.path(seg["sha256"])
        assert sha256(p.read_bytes()) == seg["sha256"]
        first = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "packet=flags", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout
        assert first.splitlines()[0].startswith("K"), seg["file"]           # each segment starts on a keyframe
    assert back.hash == sha256(_encoded(back))


def _encoded(v):
    out = io.BytesIO()
    v.encode(out)
    return out.getvalue()


def test_the_same_video_under_two_names_stores_each_segment_once(world, tmp_path):
    declare(ONE_SECOND)
    src = mpeg4(tmp_path / "src.mp4")
    a = saved(world, Video.from_path(src), "video/a")
    files = sorted((world._store.art.root / "sha256").rglob("*"))
    b = saved(world, Video.from_url(src.as_uri()), "video/b")
    assert a.hash == b.hash and sorted((world._store.art.root / "sha256").rglob("*")) == files


# --- the ledger/video standard row, read at seal ----------------------------------------------------------------

def test_the_standard_row_on_root_transcodes_the_source_to_it(world, tmp_path):
    declare(ONE_SECOND)
    back = saved(world, Video.from_path(mpeg4(tmp_path / "src.mp4")))
    assert (back._info()["codec"], back._info()["standard"], len(back._info()["segments"])) == ("h264", ONE_SECOND, 4)


def test_canonical_false_keeps_the_source_codec_and_splits_at_its_keyframes(world, tmp_path):
    declare(ONE_SECOND)
    back = saved(world, Video.from_path(mpeg4(tmp_path / "src.mp4")), canonical=False)
    info = back._info()
    assert (info["codec"], info["standard"], info["frames"]) == ("mpeg4", None, 35)
    assert close(back.frame(34), pictures(35)[34], tol=4)


def test_a_ledger_with_no_row_seals_as_canonical_false_and_says_so_once(world, tmp_path):
    src = mpeg4(tmp_path / "src.mp4")
    with warnings.catch_warnings(record=True) as said:
        warnings.simplefilter("always")
        Video.from_path(src).seal(world, name="video/a")
        Video.from_path(src).seal(world, name="video/b")
    texts = [str(w.message) for w in said if "ledger/video" in str(w.message)]
    assert len(texts) == 1 and "ledger/games" in texts[0] and "canonical=False" in texts[0]
    assert world.at().load("video/b")._info()["codec"] == "mpeg4"


def test_a_source_already_in_the_standard_is_split_without_re_encoding(world):
    """A video's own ``path()`` is in its standard, keyframes at every boundary: sealed again, its packets are
    copied, so every frame decodes to exactly the same pixels (a transcode would move them) in the same segments."""
    declare(ONE_SECOND)
    first = saved(world, Video.from_frames(iter(pictures(35)), FPS), "video/a")
    again = saved(world, Video.from_path(first.path()), "video/b")
    assert [s["frames"] for s in again._info()["segments"]] == [10, 10, 10, 5]
    assert again._info()["standard"] == ONE_SECOND
    assert all((x == y).all() for x, y in zip(first.iter(), again.iter()))


def test_a_standard_row_that_does_not_parse_is_refused(world, tmp_path):
    declare("h265 yuv420p cfr seg=10s")
    with pytest.raises(ValueError, match="video standard"):
        Video.from_path(mpeg4(tmp_path / "src.mp4")).seal(world, name="video/a")
    assert Standard(DEFAULT_STANDARD).seconds == 10


def test_v_seal_reads_no_ledger_and_its_save_keeps_its_bytes(world, tmp_path):
    declare(ONE_SECOND)
    v = Video.from_path(mpeg4(tmp_path / "src.mp4"))
    h = v.seal()
    v.seal(world, name="video/a")
    assert world.at().load("video/a").hash == h and world.at().load("video/a")._info()["codec"] == "mpeg4"


# --- lazy reads: frame(n), clip, path() ------------------------------------------------------------------------

class CountingRemote:
    """A folder-backed value store that records every blob fetched and its size."""

    def __init__(self, root):
        self.root, self.gets = Path(root), []

    def _p(self, h):
        return self.root / h

    def exists(self, h):
        return self._p(h).exists()

    def put_path(self, path, h):
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self._p(h))

    def get_to(self, h, dest):
        self.gets.append(h)
        shutil.copyfile(self._p(h), dest)


@pytest.fixture
def remote(world, tmp_path, monkeypatch):
    """``games`` keeps its values on a counting store; returns ``(ledger, the store)``."""
    monkeypatch.setattr(remote_mod, "STORES", {})
    monkeypatch.setattr(remote_mod, "_REMOTES", {})
    monkeypatch.setattr(remote_mod, "probe", lambda: None)
    store = CountingRemote(tmp_path / "bucket")
    register_store("bucket", lambda ledger: store)
    with world.transaction(by="t") as t:
        t.add("db", "db/store", "bucket")
    declare(ONE_SECOND)
    return world, store


def cold(L, name="video/G1"):
    """``name`` loaded by a reader whose art cache is empty."""
    shutil.rmtree(L._store.art.root)
    L._values.clear()
    return L.at().load(name)


def seal_on(L, frames):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = Video.from_frames(iter(frames), FPS)
        v.seal(L, name="video/G1")
    return v


def test_a_load_reads_the_manifest_and_no_segment(remote):
    L, store = remote
    v = seal_on(L, pictures(35))
    files = json.loads(_encoded(v))["files"]
    cold(L)
    assert store.gets == [v.hash, files["manifest.json"]]


def test_frame_n_fetches_one_segment_not_the_video(remote):
    L, store = remote
    frames = pictures(35)
    v = seal_on(L, frames)
    segs = [s["sha256"] for s in v._info()["segments"]]
    back = cold(L)
    store.gets.clear()
    assert close(back.frame(23), frames[23])
    assert store.gets == [segs[2]]
    sizes = {h: (store.root / h).stat().st_size for h in segs}
    fetched = sum(sizes[h] for h in store.gets)
    assert fetched < sum(sizes.values()) / 2, (fetched, sizes)
    back.frame(25)
    assert store.gets == [segs[2]]                    # fetched once, then read from the art store


def test_clip_fetches_and_materializes_only_its_frames(remote):
    L, store = remote
    frames = pictures(35)
    v = seal_on(L, frames)
    segs = [s["sha256"] for s in v._info()["segments"]]
    back = cold(L)
    store.gets.clear()
    clip = back.clip(12, 18)
    p = clip.path()
    assert store.gets == [segs[1]]
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    assert int(out.stdout.strip()) == 6
    assert close(Video.from_path(p).frame(0), frames[12], tol=16)


def test_path_joins_the_segments_into_one_file_once(remote):
    L, store = remote
    frames = pictures(35)
    v = seal_on(L, frames)
    back = cold(L)
    store.gets.clear()
    p = back.path()
    assert p.is_file() and len(store.gets) == 4 and back.path() == p and len(store.gets) == 4
    whole = Video.from_path(p)
    assert whole._info()["frames"] == 35 and close(whole.frame(31), frames[31])


def test_frames_outside_the_video_are_index_error(world):
    declare(ONE_SECOND)
    back = saved(world, Video.from_frames(iter(pictures(12)), FPS))
    with pytest.raises(IndexError):
        back.frame(12)
    with pytest.raises(IndexError):
        list(back.frames(5, 3))


def test_a_copy_to_another_ledger_carries_every_segment(world, tmp_path):
    declare(ONE_SECOND)
    v = Video.from_frames(iter(pictures(25)), FPS)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v.seal(world, name="video/G1")
    hashes = set(Video._stored_hashes(world._store.art, v.hash))
    assert hashes == {s["sha256"] for s in v._info()["segments"]} | {json.loads(_encoded(v))["files"]["manifest.json"]}


# --- never whole in memory ----------------------------------------------------------------------------------------

def test_a_seal_from_a_url_holds_no_more_than_a_block(world, tmp_path):
    """A 7-second 320x240 noise video (several MB, far over a block): peak Python allocation while it is spooled,
    split and sealed stays under a quarter of its size."""
    src = tmp_path / "noise.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30,"
                    "noise=alls=60:allf=t", "-t", "7", "-c:v", "libx264", "-qp", "4", "-pix_fmt", "yuv420p",
                    str(src)], check=True)
    size = src.stat().st_size
    assert size > 4 * (1 << 20), size
    v = Video.from_url(src.as_uri())
    tracemalloc.start()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            v.seal(world, name="video/noise")
        _now, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < size / 4, (peak, size)
    assert world.at().load("video/noise")._info()["frames"] == 210


def test_frames_are_encoded_as_they_are_iterated_never_accumulated(world):
    """300 frames of 320x240 RGB, 69 MB in all, made one at a time: peak allocation stays a few frames."""
    declare(ONE_SECOND)
    made = []

    def stream():
        rng = np.random.default_rng(1)
        for i in range(300):
            made.append(i)
            yield rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)

    v = Video.from_frames(stream(), 30)
    tracemalloc.start()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            v.seal(world, name="video/stream")
        _now, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(made) == 300 and peak < 300 * 240 * 320 * 3 / 16, peak
