"""Row objects to tagged strings and back.

The third position of a row is stored as one of three tagged strings:

``str:<text>``
    a ``str``.
``json:<canonical document>``
    a ``dict`` or ``list``.
``ref:<dotted class>:<hex sha256>[:<subject>]``
    a sealed value: the class that decodes it and the hash of its bytes; the
    subject is an optional hint, written only on a row ``add`` made from a
    ``Ref``. In ``db/value``, typed preds, ``db/keys`` and dependencies it is
    omitted, so a dependency is its bytes, not its entry.
``spill:<str|json>:<hex sha256>:<size>``
    a ``str`` or JSON object too large for the row (``spill``): the sha256 and byte size of its
    ``str:``/``json:`` text, whose bytes are in the art store under that hash.

A bare ``int``, ``float``, ``bool`` or ``None`` is refused by ``add``.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any, Optional, Tuple

_HEX = re.compile(r"^[0-9a-f]{64}$")


def canonical(doc: Any, *, strict: bool = False) -> str:
    """One text per JSON document: sorted keys, compact, unicode kept. ``strict``: a stored document, where
    a NaN or an infinity is not JSON (``ValueError``) -- it would not read back."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=not strict)


def sha256(data: bytes) -> str:
    """The hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


class HashSink(io.RawIOBase):
    """A write-only, forward-only binary stream that hashes and counts what passes through it:
    ``hash`` (hex sha256) and ``size`` read what was written so far. A subclass also writes the bytes
    somewhere (``store.FileSink``). ``seek`` is refused: an encoder that seeks back would make the digest
    wrong."""

    def __init__(self) -> None:
        super().__init__()
        self._digest = hashlib.sha256()
        self._size = 0

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def seek(self, offset: int, whence: int = 0) -> int:
        raise io.UnsupportedOperation(f"{type(self).__name__} is forward-only: an encoder writes its bytes once, "
                                      "in order, and never seeks")

    def tell(self) -> int:
        return self._size

    def write(self, b: Any) -> int:
        if self.closed:
            raise ValueError(f"write to a closed {type(self).__name__}")
        view = memoryview(b).cast("B")
        self._digest.update(view)
        self._out(view)
        self._size += len(view)
        return len(view)

    def _out(self, view: memoryview) -> None:
        """Where the bytes go besides the digest: nowhere, here."""

    @property
    def hash(self) -> str:
        """The hex sha256 of everything written."""
        return self._digest.hexdigest()

    @property
    def size(self) -> int:
        """How many bytes were written."""
        return self._size


def hash_sink() -> HashSink:
    """A sink backed by nothing: what a value's ``hash`` and a repeat check encode into."""
    return HashSink()


def hash_text(text: str, n: int = 64) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def is_hash(s: str) -> bool:
    return bool(_HEX.match(s))


def ref_text(cls: str, h: str, subject: Optional[str] = None) -> str:
    return f"ref:{cls}:{h}" + (f":{subject}" if subject else "")


def parse_ref(text: str) -> Tuple[str, str, Optional[str]]:
    """``(class, hash, subject or None)`` of a ``ref:`` string."""
    body = text[4:]
    cls, sep, rest = body.partition(":")
    h, sep2, subj = rest.partition(":")
    if not sep or not is_hash(h):
        raise ValueError(f"row object {text[:80]!r}: a ref is ref:<class>:<sha256 hex>[:<subject>]")
    return cls, h, (subj or None)


def strip_hint(text: str) -> str:
    """A ``ref:`` text without its subject hint: what a dependency, a key or a where clause compares."""
    if not text.startswith("ref:"):
        return text
    cls, h, _s = parse_ref(text)
    return ref_text(cls, h)


def tag(text: str) -> str:
    return text.partition(":")[0]


def is_spill(text: str) -> bool:
    return text.startswith("spill:")


def spill_text(text: str) -> str:
    """The ``spill:`` reference to a ``str:``/``json:`` text: its tag, the sha256 and byte size of its UTF-8."""
    data = text.encode("utf-8")
    return f"spill:{tag(text)}:{sha256(data)}:{len(data)}"


def parse_spill(text: str) -> Tuple[str, str, int]:
    """``(tag, hash, size)`` of a ``spill:`` text."""
    _s, t, rest = text.split(":", 2)
    h, _, size = rest.partition(":")
    if t not in ("str", "json") or not is_hash(h) or not size.isdigit():
        raise ValueError(f"row object {text[:80]!r}: a spill is spill:<str|json>:<sha256 hex>:<size>")
    return t, h, int(size)


def tag_of(text: str) -> str:
    """The tag of the object a stored text holds: a spill's own (``str`` or ``json``), else its tag."""
    return text.split(":", 2)[1] if is_spill(text) else tag(text)


def same(a: str, b: str) -> bool:
    """Do two stored texts hold the same object: equal, or one a ``spill:`` of the other (sizes compared first,
    so a plain text is hashed only when its size is the spill's)."""
    if a == b:
        return True
    if is_spill(a) == is_spill(b):
        return False
    s, p = (a, b) if is_spill(a) else (b, a)
    if p.startswith("ref:"):
        return False
    size = int(s.rpartition(":")[2])
    data = p.encode("utf-8")
    return len(data) == size and s == f"spill:{tag(p)}:{sha256(data)}:{size}"


def encode_plain(obj: Any) -> Optional[str]:
    """The tagged string of a ``str`` or JSON document; ``None`` when ``obj`` is neither."""
    if isinstance(obj, str):
        return "str:" + obj
    if isinstance(obj, (dict, list)):
        try:
            return "json:" + canonical(obj, strict=True)
        except (TypeError, ValueError) as e:
            raise TypeError(f"not a JSON document: {e}") from None
    return None


def refuse_scalar(obj: Any) -> None:
    if obj is None or isinstance(obj, (bool, int, float)):
        raise TypeError(f"a ledger object is a str, a JSON dict or list, or a Ref; not {type(obj).__name__} "
                        f"({obj!r}): a number is its string, say {str(obj)!r}")


def show(text: str) -> str:
    """A stored object as one line of text: a str as is, JSON canonical, a ref or a spill as its tag text."""
    t, _, rest = text.partition(":")
    return text if t in ("ref", "spill") else rest


#: ``dotted_get``'s marker for "no default given".
NO_DEFAULT: Any = object()


def dotted_get(source: Any, keys: Any, default_value: Any = NO_DEFAULT) -> Any:
    """The value at a dotted key path (``"dat.do"``, or a list of keys) in a dict tree (``Dat.get``'s walk).

    A missing key, or a value that is ``None``, returns ``default_value``, and is ``KeyError`` when none is
    given; a non-dict on the path is ``ValueError``."""
    d = source
    if isinstance(keys, str):
        keys = keys.split(".")
    result = None
    for k in keys:
        if d is None:
            break
        if not isinstance(d, dict):
            raise ValueError(f"GET: Expected dict value for {k!r} not {d!r}")
        d = d.get(k)
    else:
        result = d
    if result is not None:
        return result
    if default_value is NO_DEFAULT:
        raise KeyError(f"GET: Key {keys} not found in {source!r}")
    return default_value


def dotted_set(source: Any, keys: Any, value: Any) -> None:
    """Set ``value`` at a dotted key path in a dict tree, creating missing levels as dicts (``Dat.set``'s walk);
    a non-dict on the path is ``ValueError``."""
    assert source is not None, "set method requires a non None dict"
    assert len(keys) > 0, "set method requires at least one key"
    if isinstance(keys, str):
        keys = keys.split(".")
    for k in keys[:-1]:
        if not isinstance(source, dict):
            raise ValueError(f"Expected dict value for {k!r} not {source!r}")
        sub = source.get(k)
        if sub is None:
            sub = source[k] = {}
        source = sub
    if not isinstance(source, dict):
        raise ValueError(f"Expected dict value for {keys[-1]!r} not {source!r}")
    source[keys[-1]] = value
