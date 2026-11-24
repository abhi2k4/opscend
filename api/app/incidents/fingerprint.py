"""Fingerprints: a stable name for "this kind of failure", taken from its log lines.

Two failures get the same fingerprint when their headline error is the same once the
parts that change from run to run (ids, timestamps, line numbers, paths) are masked:

    Error: Missing required environment variable STRIPE_WEBHOOK_SECRET
    -> signature: "error: missing required environment variable stripe_webhook_secret"
    -> family:    "error: missing required environment variable <id>"

`signature` keeps names and quoted values, so it means "the same error". `family` masks
them as well, so it means "the same kind of error with a different value", such as a
different missing variable. Both are stored as short hashes.

Pure functions only: no database, no network. `memory.py` decides when to call them.
"""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

# Bump when the masking or the headline choice changes. It is part of every hash, so
# fingerprints from different versions never match by accident.
VERSION = "v1"
MAX_ERROR_TEXT = 500

# Lines that carry no message of their own: stack frames, code frames, carets, bare
# file locations, runtime banners and lone braces.
_NOISE = re.compile(
    r"""^\s*(?:
        at\s.*                            # JS stack frame
      | File\s".*                         # Python stack frame
      | [\^~|\s]+                         # caret or gutter line
      | >?\s*\d+\s*\|.*                   # code frame: "  23 | <code>"
      | \S+:\d+(?::\d+)?                  # bare path:line(:col)
      | \.{0,2}/\S*                       # bare path
      | Node\.js\sv\d.*                   # Node version banner
      | [{}\[\]()]+                       # lone braces
    )\s*$""",
    re.VERBOSE,
)
# Generic lines that only say "something failed". Used only when nothing better exists.
_WRAPPER = re.compile(
    r"ELIFECYCLE|Command failed with exit code|Command \".*\" exited with|Failed to compile"
    r"|Build failed because of|Deployment aborted|restarting \(attempt|Import trace",
    re.IGNORECASE,
)
# (pattern, points): the headline is the highest scoring line, the earliest on a tie.
_SCORES = (
    (re.compile(r"^\s*[\w.]*(?:Error|Exception)\b:"), 3),  # TypeError: ..., Error: ...
    (re.compile(r"\berror (?:TS|E)\d+\b|\bERR_[A-Z_]+\b|npm ERR!"), 3),
    (re.compile(r"^\s*(?:error|fatal|panic)\b[:\s]", re.IGNORECASE), 2),
    (re.compile(r"failed|timed out|refused|not found|denied|exit code", re.IGNORECASE), 1),
    (_WRAPPER, -4),
)

# Run to run noise, most specific first (a URL contains numbers, a UUID contains hex).
_MASKS = (
    (re.compile(r"\x1b\[[0-9;]*m"), ""),
    (
        re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
        "<ts>",
    ),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<ts>"),
    (
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
        "<uuid>",
    ),
    (re.compile(r"\bhttps?://\S+"), "<url>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b", re.I), "<hex>"),
    (re.compile(r"(?<![\w.])(?:[A-Za-z]:\\|\.{0,2}/)[\w./\\@-]+"), "<path>"),
    # A number on its own or with a unit ("300s", "512mb"). "bullmq_1", "TS2345" and
    # "v22" stay: they are part of a word.
    (re.compile(r"(?<![\w.])\d+(?:\.\d+)*(?:ms|s|m|h|kb|mb|gb)?(?!\w)", re.I), "<num>"),
)
# What `family` masks on top: the value that differs between two errors of one kind.
_FAMILY_MASKS = (
    (re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`"), "<str>"),
    (re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"), "<id>"),  # UPPER_SNAKE names
    (
        re.compile(r"\b(variable|module|column|property|package|table|function|key)\s+\S+", re.I),
        r"\1 <id>",
    ),
)
_TOKEN = re.compile(r"<\w+>|[a-z0-9_]+")


@dataclass(frozen=True)
class Fingerprint:
    signature: str  # hash: the same error
    family: str  # hash: the same kind of error
    error_text: str  # masked headline first, then up to 2 more signal lines


def _mask(text: str) -> str:
    for pattern, token in _MASKS:
        text = pattern.sub(token, text)
    return " ".join(text.split())


def _family(masked: str) -> str:
    for pattern, token in _FAMILY_MASKS:
        masked = pattern.sub(token, masked)
    return masked


def _hash(text: str) -> str:
    return hashlib.sha1(f"{VERSION}|{text}".encode()).hexdigest()[:16]  # noqa: S324


def _score(message: str) -> int:
    return sum(points for pattern, points in _SCORES if pattern.search(message))


def headline(lines: Iterable[tuple[str, str]]) -> str | None:
    """The line that names the failure, from `(level, message)` pairs in log order."""
    lines = [(level, message.strip()) for level, message in lines if message.strip()]
    # Error lines, else warnings, else the last few lines of a log that has no levels.
    pool = (
        [m for level, m in lines if level == "error"]
        or [m for level, m in lines if level == "warn"]
        or [m for _, m in lines[-5:]]
    )
    candidates = [m for m in pool if not _NOISE.match(m)]
    if not candidates:
        return None
    # max() keeps the first of equal scores, so the earliest line wins a tie.
    return max(candidates, key=_score)


def from_logs(lines: Iterable[tuple[str, str]]) -> Fingerprint | None:
    """Fingerprint a failed deploy from its log lines. None when they say nothing."""
    lines = list(lines)
    top = headline(lines)
    if top is None:
        return None
    masked = _mask(top)
    others = []
    for level, message in lines:
        if level == "error" and not _NOISE.match(message.strip()):
            line = _mask(message).lower()
            if line != masked.lower() and line not in others:
                others.append(line)
    error_text = "\n".join([masked.lower(), *others[:2]])[:MAX_ERROR_TEXT]
    return Fingerprint(
        signature=_hash(masked.lower()),
        family=_hash(_family(masked).lower()),
        error_text=error_text,
    )


def from_health_check(service_id: str, status_code: int | None) -> Fingerprint:
    """A failing health check has no log line: its status class names the failure.

    The service id is part of it, because "returns 503" on two different services says
    nothing about a shared cause.
    """
    kind = "no response" if status_code is None else f"http {status_code // 100}xx"
    text = f"health check failed: {kind}"
    digest = _hash(f"{service_id}|{text}")
    return Fingerprint(signature=digest, family=digest, error_text=text)


def _words(error_text: str) -> set[str]:
    # The headline only: the lines after it are often the platform's own boilerplate
    # ("Healthcheck failed! Deployment marked as FAILED"), shared by unrelated failures.
    # Mask tokens are left out too, since `<num>` appears in almost every error.
    first_line = error_text.split("\n", 1)[0].lower()
    return {token for token in _TOKEN.findall(first_line) if not token.startswith("<")}


def similarity(a: str, b: str) -> float:
    """Word overlap (Jaccard) of the headlines of two error texts, from 0 to 1."""
    words_a, words_b = _words(a), _words(b)
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)
