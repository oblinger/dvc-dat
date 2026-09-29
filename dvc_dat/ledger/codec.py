"""Values to row strings and back: every object says its own kind.

``str:<text>``, ``json:<sorted document>``, ``blob:sha256:<hex>`` for a
document past :data:`BLOB_BYTES`, and a ``Ref`` as ``dat:<name>``,
``art:<type>:<hash or name>`` or ``node:<subject>``. A row with no ``word:``
prefix, or one this module does not know, is ``ValueError``.
"""

from __future__ import annotations

import hashlib
import json as _json
from typing import Any, Callable, Optional, Tuple, Type

from ..core import Dat
from .ref import Ref
from .shelf import is_hash
from .types import ART_TYPES, Artifact, Node, canonical_json

#: A JSON document longer than this many bytes is spilled to the shelf as ``blob:`` (the row's index edge).
BLOB_BYTES = 2048

PREFIXES = ("str", "json", "blob", "dat", "art", "node")


def encode_value(value: Any) -> Tuple[str, Optional[bytes]]:
    """``(row string, blob bytes to put or None)`` for a value; ``ValueError`` for anything not a Value."""
    if isinstance(value, str):
        return "str:" + value, None
    if isinstance(value, (dict, list)):
        doc = canonical_json(value)
        data = doc.encode()
        if len(data) > BLOB_BYTES:
            return "blob:sha256:" + hashlib.sha256(data).hexdigest(), data
        return "json:" + doc, None
    if isinstance(value, Ref):
        if value.kind == "node":
            return "node:" + value.name, None
        if value.kind == "art":
            return f"art:{value.type.token}:{value.hash or value.name}", None
        return "dat:" + value.name, None
    raise ValueError(
        f"a ledger object is a str, a JSON dict or list, or a Ref; not {type(value).__name__} ({value!r}): "
        "say what it means (str(n), an ISO day)")


Fetch = Callable[[str], bytes]
Size = Callable[[str], Optional[int]]


def decode_text(text: Any, fetch: Optional[Fetch] = None, size: Optional[Size] = None) -> Any:
    """The Python value a row string encodes. ``fetch`` reads a blob's bytes; ``size`` fills an artifact's size."""
    if not isinstance(text, str):
        raise ValueError(f"a row's object is a str, not {type(text).__name__}")
    prefix, sep, rest = text.partition(":")
    if not sep or prefix not in PREFIXES:
        raise ValueError(f"row object {text[:60]!r} has no known prefix ({', '.join(p + ':' for p in PREFIXES)})")
    if prefix == "str":
        return rest
    if prefix == "json":
        try:
            return _json.loads(rest)
        except ValueError as e:
            raise ValueError(f"row object {text[:60]!r} is not JSON: {e}") from None
    if prefix == "blob":
        if not is_hash(rest):
            raise ValueError(f"row object {text[:60]!r}: a blob is blob:sha256:<hex>")
        if fetch is None:
            raise FileNotFoundError(f"{text}: no ledger to fetch the blob through")
        return _json.loads(fetch(rest).decode())
    if not rest:
        raise ValueError(f"row object {text!r} names nothing")
    if prefix == "node":
        return Ref(rest, type=Node)
    if prefix == "dat":
        return Ref(rest, type=Dat)
    token, sep, key = rest.partition(":")
    atype = ART_TYPES.get(token)
    if not sep or atype is None or not key:
        raise ValueError(f"row object {text[:60]!r}: an artifact is art:<type>:<hash>, type one of {sorted(ART_TYPES)}")
    return _art_ref(atype, key, size)


def _art_ref(atype: Type[Artifact], key: str, size: Optional[Size]) -> Ref:
    if key.startswith("sha256:"):
        if not is_hash(key):
            raise ValueError(f"art:{atype.token}:{key[:30]}…: malformed hash")
        return Ref(key, hash=key, type=atype, size=size(key) if size else None)
    return Ref(key, type=atype, size=size(key) if size else None)
