"""Row objects to tagged strings and back.

The third position of a row is stored as one of three tagged strings:

``str:<text>``
    a ``str``.
``json:<canonical document>``
    a ``dict`` or ``list``.
``ref:<dotted class>:<hex sha256>[:<subject>]``
    a sealed value: the class that decodes it and the hash of its bytes; the
    subject is an optional hint, written only on a row ``add`` made from a
    ``Ref`` (A28). In ``db/value``, typed preds, ``db/keys`` and dependencies it is
    omitted, so a dependency is its bytes, not its entry (A21).

A bare ``int``, ``float``, ``bool`` or ``None`` is refused by ``add`` (Q5 (A)).
"""

from __future__ import annotations

import hashlib
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
                        f"({obj!r}): a number is its string (Q5), say {str(obj)!r}")


def show(text: str) -> str:
    """A stored object as one line of text: a str as is, JSON canonical, a ref as its tag text."""
    t, _, rest = text.partition(":")
    return text if t == "ref" else rest
