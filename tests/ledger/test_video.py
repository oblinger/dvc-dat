"""SVP 249: a video as a ledger value, sealed from a URL, a file or frames, stored as segments plus a manifest, and
read lazily: ``frame(n)`` fetches one segment, ``clip(a, b)`` the segments it covers, ``path()`` joins them once.

Every video here is a few seconds of synthetic frames made in the test (64x48 at 10 fps unless a test needs more);
the URL is a ``file://`` one read through ``fsspec``. ``SEGMENT_SECONDS`` is 1 so a few seconds make several segments.
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

from dvc_dat.ledger import Ledger, Video, register_values
from dvc_dat.ledger import backends as backends_mod
from dvc_dat.ledger import video as video_mod
from dvc_dat.ledger.codec import sha256

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None and not os.environ.get("CI"),
                                reason="ffmpeg is not on PATH (CI installs it)")

W, H, FPS = 64, 48, 10


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


def with_audio(path, seconds=3.5, *args, audio=("-c:a", "aac", "-b:a", "64k")):
    """``seconds`` of test picture and a 440 Hz tone muxed to ``path``, keyframes every 10 frames."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", str(seconds),
                    *(args or ("-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p")), *audio, str(path)], check=True)
    return path


def streams(path, kind):
    """The codec of each stream of ``kind`` (``v`` or ``a``) in ``path``, and its packets."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-count_packets", "-show_entries",
                          "stream=codec_name,nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True,
                         text=True, check=True).stdout
    return [(line.split(",")[0], int(line.split(",")[1])) for line in out.split()]


def duration(path, kind):
    """The seconds covered by the stream ``kind`` of ``path``, from its packets."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries",
                          "packet=pts_time,duration_time", "-of", "csv=p=0", str(path)], capture_output=True,
                         text=True, check=True).stdout
    rows = [line.split(",") for line in out.split()]
    return float(rows[-1][0]) + float(rows[-1][1]) - float(rows[0][0])


@pytest.fixture
def world(tmp_path, monkeypatch):
    """The ledger ``games``, splitting at every second."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.setattr(video_mod, "SEGMENT_SECONDS", 1)
    return Ledger(tmp_path / "games", create=True)


def saved(L, v, name="video/G1", **kw):
    v.seal(L, name=name, **kw)
    L._values.clear()
    return L.at().load(name)


# --- seal and load, by url, by path and by frames -------------------------------------------------------------

def test_a_video_from_frames_seals_and_loads_back(world):
    frames = pictures(25)
    back = saved(world, Video.from_frames(iter(frames), FPS))
    assert isinstance(back, Video) and back._info()["frames"] == 25
    got = list(back.iter())
    assert len(got) == 25 and all(close(a, b) for a, b in zip(got, frames))


def test_a_video_from_a_path_seals_and_loads_back(world, tmp_path):
    src = mpeg4(tmp_path / "src.mp4")
    back = saved(world, Video.from_path(src))
    assert back._info()["frames"] == 35 and close(back.frame(20), pictures(35)[20])


def test_a_video_from_a_url_seals_and_loads_back_with_the_hash_of_the_same_file(world, tmp_path):
    src = mpeg4(tmp_path / "src.mp4")
    by_url = Video.from_url(src.as_uri())
    back = saved(world, by_url)
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
    back = saved(world, Video.from_frames(iter(pictures(35)), FPS))
    info = back._info()
    assert [(s["file"], s["start"], s["frames"]) for s in info["segments"]] == [
        ("seg/00000.mp4", 0, 10), ("seg/00001.mp4", 10, 10), ("seg/00002.mp4", 20, 10), ("seg/00003.mp4", 30, 5)]
    assert {k: info[k] for k in ("codec", "pix_fmt", "width", "height", "fps", "frames", "segment_seconds",
                                 "audio")} == {
        "codec": "h264", "pix_fmt": "yuv420p", "width": W, "height": H, "fps": "10/1", "frames": 35,
        "segment_seconds": 1, "audio": []}
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
    src = mpeg4(tmp_path / "src.mp4")
    a = saved(world, Video.from_path(src), "video/a")
    files = sorted((world._store.art.root / "sha256").rglob("*"))
    b = saved(world, Video.from_url(src.as_uri()), "video/b")
    assert a.hash == b.hash and sorted((world._store.art.root / "sha256").rglob("*")) == files


# --- a seal keeps what it is given; convert is the one change ---------------------------------------------------

def test_a_seal_keeps_the_source_codec_and_splits_at_its_keyframes(world, tmp_path):
    src = mpeg4(tmp_path / "src.mp4")
    with warnings.catch_warnings():
        warnings.simplefilter("error")                   # nothing to say: there is no standard to miss
        back = saved(world, Video.from_path(src))
    info = back._info()
    assert (info["codec"], info["frames"]) == ("mpeg4", 35) and len(info["segments"]) > 1
    whole = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt",
                                          "rgb24", "pipe:1"], capture_output=True, check=True).stdout, np.uint8)
    got = np.stack(list(back.iter()))
    assert (got.ravel() == whole).all()                  # not re-encoded: the same pixels


def test_a_seal_takes_no_canonical(world, tmp_path):
    with pytest.raises(TypeError):
        Video.from_path(mpeg4(tmp_path / "src.mp4")).seal(world, name="video/a", canonical=False)


def test_a_video_read_from_its_path_seals_to_the_same_segments(world):
    """Packets are copied, so a video's own ``path()`` sealed again decodes to exactly the same pixels."""
    first = saved(world, Video.from_frames(iter(pictures(35)), FPS), "video/a")
    again = saved(world, Video.from_path(first.path()), "video/b")
    assert [s["frames"] for s in again._info()["segments"]] == [10, 10, 10, 5]
    assert all((x == y).all() for x, y in zip(first.iter(), again.iter()))


def test_a_stream_mp4_cannot_hold_goes_in_matroska_segments(world, tmp_path):
    """Any representation goes on a ledger: FFV1 and mu-law, the second refused by MP4, are kept in Matroska."""
    src = with_audio(tmp_path / "src.mkv", 2.5, "-c:v", "ffv1", "-pix_fmt", "yuv420p", audio=("-c:a", "pcm_mulaw"))
    back = saved(world, Video.from_path(src))
    info = back._info()
    assert (info["codec"], info["frames"], info["audio"][0]["codec"]) == ("ffv1", 25, "pcm_mulaw")
    assert {Path(s["file"]).suffix for s in info["segments"]} == {".mkv"} and len(info["segments"]) == 3
    p = back.path()
    assert p.suffix == ".mkv" and streams(p, "v") == [("ffv1", 25)] and streams(p, "a")[0][0] == "pcm_mulaw"
    assert back.frame(24).shape == (H, W, 3)


def test_the_audio_is_kept_by_the_seal_and_the_path(world, tmp_path):
    src = with_audio(tmp_path / "src.mp4")
    back = saved(world, Video.from_path(src))
    assert back._info()["audio"] == [{"codec": "aac", "channels": 1, "sample_rate": "44100"}]
    assert back._info()["frames"] == 35 and len(back._info()["segments"]) == 4
    assert streams(back.path(), "a") == streams(src, "a") and streams(back.path(), "v") == streams(src, "v")
    assert duration(back.path(), "a") == pytest.approx(duration(src, "a"), abs=0.05)
    assert duration(back.path(), "v") == pytest.approx(duration(src, "v"), abs=0.05)     # B-frames: no gap at a join


def video_timing(path):
    """The first video stream's frame count, average frame rate and duration, as ffprobe reads them."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets,avg_frame_rate,duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return int(s["nb_read_packets"]), s["avg_frame_rate"], s["duration"]


def test_the_joined_path_has_the_sources_frame_rate_and_duration(world, tmp_path):
    """SVP 249, 2026-11-11: G1's ``path()`` read 29.986 fps and 1.488 s more than its mp4 (30 fps), 328 segments.
    The concat join advanced each segment by its whole length, audio overhang included, and the first segment's
    timestamps start one B-frame delay late. A source shaped like a game's (30 fps H.264 with B-frames, 48 kHz AAC,
    keyframes every 31 frames, off the audio frame grid) joins back to the same frames, frame rate and duration."""
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "6",
                    "-c:v", "libx264", "-g", "31", "-bf", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
                    str(src)], check=True)
    back = saved(world, Video.from_path(src))
    assert len(back._info()["segments"]) == 6
    assert video_timing(back.path()) == video_timing(src) == (180, "30/1", "6.000000")


def test_every_audio_stream_is_kept(world, tmp_path):
    two = tmp_path / "two.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(with_audio(tmp_path / "src.mp4")), "-f", "lavfi", "-i",
                    "sine=frequency=880:sample_rate=22050:duration=3", "-map", "0", "-map", "1", "-c:v", "copy",
                    "-c:a", "aac", str(two)], check=True)
    back = saved(world, Video.from_path(two))
    assert len(back._info()["audio"]) == 2 and len(streams(back.path(), "a")) == 2


def test_a_clip_keeps_its_audio_and_its_frames_are_exact(world, tmp_path):
    back = saved(world, Video.from_path(with_audio(tmp_path / "src.mp4")))
    clip = back.clip(12, 27)                             # 1.5 s, across two segment boundaries
    p = clip.path()
    assert clip._info()["frames"] == 15 and clip._info()["codec"] == "h264"
    assert clip._info()["audio"][0]["codec"] == "aac" and duration(p, "a") == pytest.approx(1.5, abs=0.05)
    assert close(clip.frame(0), back.frame(12), tol=16) and close(clip.frame(14), back.frame(26), tol=16)
    again = saved(world, clip, "video/clip")
    assert again._info()["audio"] == clip._info()["audio"]


def test_a_clip_of_a_silent_video_is_silent(world):
    back = saved(world, Video.from_frames(iter(pictures(25)), FPS))
    assert back.clip(3, 13)._info()["audio"] == []


def test_convert_gives_a_new_unsealed_video_in_the_target_format(world, tmp_path):
    src = saved(world, Video.from_path(with_audio(tmp_path / "src.mp4")))
    before = src.hash
    out = src.convert("mpeg4", options=("-q:v", "2"))
    assert isinstance(out, Video) and out is not src and not out.sealed
    assert (out._info()["codec"], out._info()["audio"][0]["codec"]) == ("mpeg4", "aac")
    assert out._info()["frames"] == 35 and close(out.frame(30), src.frame(30), tol=16)
    back = saved(world, out, "video/mpeg4")
    assert back.hash != before and src.hash == before and src._info()["codec"] == "h264"


def test_convert_changes_the_pixel_format_the_rate_and_the_audio_codec(world, tmp_path):
    src = saved(world, Video.from_path(with_audio(tmp_path / "src.mp4")))
    out = src.convert("libx264", pix_fmt="yuv444p", fps=5, audio="pcm_mulaw")
    info = out._info()
    assert (info["codec"], info["pix_fmt"], info["fps"], info["audio"][0]["codec"]) == ("h264", "yuv444p", "5/1",
                                                                                      "pcm_mulaw")
    assert info["frames"] == pytest.approx(18, abs=1)
    assert {Path(s["file"]).suffix for s in info["segments"]} == {".mkv"}     # MP4 does not hold mu-law
    assert saved(world, out, "video/x")._info()["fps"] == "5/1"


def test_convert_takes_a_format_no_list_knows_and_says_when_ffmpeg_does_not(world, tmp_path):
    src = saved(world, Video.from_frames(iter(pictures(15)), FPS))
    assert src.convert("ffv1")._info()["codec"] == "ffv1"
    with pytest.raises(RuntimeError, match="Unknown encoder|nosuchencoder"):
        src.convert("nosuchencoder")._info()
    with pytest.raises(ValueError, match="codec"):
        src.convert("")


# --- lazy reads: frame(n), clip, path() ------------------------------------------------------------------------

class CountingRemote:
    """A folder-backed value store that records every blob fetched and its size."""

    def __init__(self, root):
        self.root, self.gets = Path(root), []

    def _p(self, h):
        return self.root / h

    def has(self, h):
        return self._p(h).exists()

    def push(self, path, h):
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self._p(h))

    def pull(self, h, path):
        self.gets.append(h)
        shutil.copyfile(self._p(h), path)


@pytest.fixture
def remote(world, tmp_path, monkeypatch):
    """``games`` keeps its values on a counting store; returns ``(ledger, the store)``."""
    monkeypatch.setattr(backends_mod, "_VALUES", dict(backends_mod._VALUES))
    monkeypatch.setattr(backends_mod, "_MADE", {})
    store = CountingRemote(tmp_path / "bucket")
    register_values("bucket", lambda uri: store)
    with world.transaction(by="t") as t:
        t.add("db", "db/values", "bucket://games")
    return world, store


def cold(L, name="video/G1"):
    """``name`` loaded by a reader whose art cache is empty."""
    shutil.rmtree(L._store.art.root)
    L._values.clear()
    return L.at().load(name)


def seal_on(L, frames):
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
    back = saved(world, Video.from_frames(iter(pictures(12)), FPS))
    with pytest.raises(IndexError):
        back.frame(12)
    with pytest.raises(IndexError):
        list(back.frames(5, 3))


def test_a_copy_to_another_ledger_carries_every_segment(world, tmp_path):
    v = Video.from_frames(iter(pictures(25)), FPS)
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
        v.seal(world, name="video/noise")
        _now, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < size / 4, (peak, size)
    assert world.at().load("video/noise")._info()["frames"] == 210


def test_frames_are_encoded_as_they_are_iterated_never_accumulated(world):
    """300 frames of 320x240 RGB, 69 MB in all, made one at a time: peak allocation stays a few frames."""
    made = []

    def stream():
        rng = np.random.default_rng(1)
        for i in range(300):
            made.append(i)
            yield rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)

    v = Video.from_frames(stream(), 30)
    tracemalloc.start()
    try:
        v.seal(world, name="video/stream")
        _now, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(made) == 300 and peak < 300 * 240 * 320 * 3 / 16, peak
