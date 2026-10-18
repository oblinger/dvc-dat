"""Row objects to tagged strings and back, and the Q5 text form of a key.

The third position of a row is stored as one of three tagged strings:

``str:<text>``
    a ``str``.
``json:<canonical document>``
    a ``dict`` or ``list``.
``ref:<class>:<hash>[:<subject>]``
    an artifact: the dotted name of the ``Value`` class that decodes it and
    the ``sha256:<hex>`` of its bytes; ``<subject>`` names the subject the
    value lives on when that is not the row's own subject (a pointer to a
    sealed subject, or a ``Ref`` to another subject). Class and hash may be
    empty for a ``Ref`` to a subject with no value.

A bare ``int``, ``float``, ``bool`` or ``None`` is refused (Q5 (A)).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Tuple

HASH_LEN = len("sha256:") + 64


def canonical(doc: Any) -> str:
    """One text per JSON document: sorted keys, no spaces."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def short(text: str, n: int = 16) -> str:
    """The first ``n`` hex digits of the sha256 of ``text``: the hash part of a derived subject."""
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def ref_text(cls: Optional[str], hash: Optional[str], subject: Optional[str]) -> str:
    out = f"ref:{cls or ''}:{hash or ''}"
    return out + (":" + subject if subject else "")


def parse_ref(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """``(class, hash, subject)`` of a ``ref:`` string; each may be ``None``."""
    body = text[len("ref:"):]
    cls, sep, rest = body.partition(":")
    if not sep:
        raise ValueError(f"row object {text[:60]!r}: a ref is ref:<class>:<hash>[:<subject>]")
    h: Optional[str] = None
    if rest.startswith("sha256:"):
        h, rest = rest[:HASH_LEN], rest[HASH_LEN:]
    if rest and not rest.startswith(":"):
        raise ValueError(f"row object {text[:60]!r}: malformed ref")
    return (cls or None), h, (rest[1:] or None)


def check_scalar(obj: Any) -> None:
    if obj is None or isinstance(obj, (bool, int, float)):
        raise ValueError(
            f"a ledger object is a str, a JSON dict or list, or a Value/Ref; not {type(obj).__name__} "
            f"({obj!r}): a number is its string (Q5), say str({obj!r})")


def encode_plain(obj: Any) -> Optional[str]:
    """The tagged string of a ``str`` or JSON document, or ``None`` when ``obj`` is neither."""
    if isinstance(obj, str):
        return "str:" + obj
    if isinstance(obj, (dict, list)):
        try:
            return "json:" + canonical(obj)
        except (TypeError, ValueError) as e:
            raise ValueError(f"not a JSON document: {e}") from None
    return None


def key_text(v: Any) -> str:
    """Q5 (A): a key or index value as text. ``str`` as is; a number or bool as its JSON text."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    raise TypeError(f"a key is a str, int, float, bool or Ref, not {type(v).__name__} ({v!r})")
