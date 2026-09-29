"""The classes a ``Ref.type`` holds: artifact types, and ``Node`` for a subject.

An artifact type is a class with an encoder (``source``) and a decoder
(``decode``); its ``token`` is the word between ``art:`` and the hash in a row
(``art:json:sha256:…``). Four ship here; a consumer adds its own by
subclassing :class:`Artifact` with a new ``token``, which registers it.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, ClassVar, Dict, Type, Union

Source = Union[bytes, Path]

#: Every artifact type by its token; a subclass with a ``token`` registers itself.
ART_TYPES: Dict[str, Type["Artifact"]] = {}


class Artifact:
    """An artifact type: how an object is written into the shelf and read back."""

    token: ClassVar[str] = ""

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        token = cls.__dict__.get("token", "")
        if token:
            if ":" in token:
                raise ValueError(f"an artifact token has no ':', not {token!r}")
            ART_TYPES[token] = cls

    @classmethod
    def source(cls, obj: Any) -> Source:
        """What the shelf stores for ``obj``: its bytes, or the path of a file or folder."""
        raise NotImplementedError

    @classmethod
    def decode(cls, payload: Path) -> Any:
        """The object, from the shelf's copy of it."""
        raise NotImplementedError


def _file(obj: Any, what: str) -> Path:
    if not isinstance(obj, Path):
        raise ValueError(f"a {what} artifact is saved from a file's Path, not {type(obj).__name__}")
    if not obj.is_file():
        raise FileNotFoundError(f"{obj}: a {what} artifact is a file")
    return obj


class json(Artifact):  # noqa: N801
    """A ``dict`` or ``list`` (or a ``.json`` file's Path); loads as the parsed document."""

    token = "json"

    @classmethod
    def source(cls, obj: Any) -> Source:
        if isinstance(obj, (dict, list)):
            return canonical_json(obj).encode()
        path = _file(obj, "json")
        try:
            _json.loads(path.read_text())
        except ValueError as e:
            raise ValueError(f"{path}: not a JSON document ({e})") from None
        return path

    @classmethod
    def decode(cls, payload: Path) -> Any:
        return _json.loads(payload.read_text())


class file(Artifact):  # noqa: N801
    """``bytes`` or a file's Path; loads as ``bytes``."""

    token = "file"

    @classmethod
    def source(cls, obj: Any) -> Source:
        if isinstance(obj, (bytes, bytearray)):
            return bytes(obj)
        return _file(obj, "file")

    @classmethod
    def decode(cls, payload: Path) -> Any:
        return payload.read_bytes()


class ckpt(Artifact):  # noqa: N801
    """A folder's Path (a checkpoint); loads as the stored folder's Path."""

    token = "ckpt"

    @classmethod
    def source(cls, obj: Any) -> Source:
        if not isinstance(obj, Path):
            raise ValueError(f"a ckpt artifact is saved from a folder's Path, not {type(obj).__name__}")
        if not obj.is_dir():
            raise FileNotFoundError(f"{obj}: a ckpt artifact is a folder")
        return obj

    @classmethod
    def decode(cls, payload: Path) -> Any:
        return payload


class video(Artifact):  # noqa: N801
    """A video file's Path; loads as the stored file's Path."""

    token = "video"

    @classmethod
    def source(cls, obj: Any) -> Source:
        return _file(obj, "video")

    @classmethod
    def decode(cls, payload: Path) -> Any:
        return payload


class Node:
    """The type of a ``Ref`` to a subject of the ledger itself (``node:<subject>``)."""


def canonical_json(obj: Any) -> str:
    """The one spelling of a document: sorted keys, no spaces, so equal documents are equal rows."""
    try:
        return _json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ValueError(f"not a JSON document: {e}") from None
