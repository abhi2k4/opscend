"""Remove secrets from provider text before it is sent to the model.

Build logs, diffs and commit messages regularly contain credentials: a printed env
var, a connection string, a committed `.env`. The model (Groq by default) is an
outside service, so `untrusted()` runs every piece of provider text through
`redact()` first. Only what the model sees changes; stored logs, the console and
report quotes (taken from the stored line) keep the original text.

The patterns are deliberately narrow. Variable names stay ("STRIPE_WEBHOOK_SECRET
is missing" is the evidence), and so does anything that is not a literal value,
such as `required("STRIPE_SECRET_KEY")`.
"""

import re

REDACTED = "[redacted]"

# Token formats that are secret wherever they appear.
KNOWN_TOKENS = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"  # AWS access key id
    r"|gh[pousr]_[A-Za-z0-9]{36,}"  # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"  # GitLab
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"  # Slack
    r"|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"  # Stripe secret / restricted keys
    r"|whsec_[A-Za-z0-9]{10,}"  # Stripe webhook secret
    r"|sk-[A-Za-z0-9_-]{20,}"  # OpenAI, Anthropic
    r"|gsk_[A-Za-z0-9]{20,}"  # Groq
    r"|AIza[0-9A-Za-z_-]{35}"  # Google API key
    r"|npm_[A-Za-z0-9]{36}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r")"
)

# -----BEGIN ... PRIVATE KEY----- up to its END line, or to the end of a cut-off block.
PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S
)

# scheme://user:password@host keeps the user and host, drops the password.
URL_PASSWORD = re.compile(r"\b([a-z][a-z0-9+.-]*://[^\s:/@]+):[^\s@/]+@", re.I)

# Authorization: Bearer <token>, Basic <base64>.
AUTH_HEADER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{16,}")

# NAME=value, NAME: value, "name": "value" where the name says it is a secret. The
# value must be a literal of 8+ characters that ends at whitespace, a quote, a comma
# or a semicolon, so a call such as `required("X")` or a short flag never matches.
# Placeholders stay: `API_KEY=undefined` is the evidence that the key is missing.
SECRET_ASSIGNMENT = re.compile(
    r"(?P<name>[A-Za-z0-9_.-]*(?:secret|token|passw(?:or)?d|pwd|api_?key|access_?key"
    r"|private_?key|credential|auth_?token)[A-Za-z0-9_.-]*)"
    r"(?P<sep>[\"']?\s*[:=]\s*[\"']?)"
    r"(?!(?:undefined|required|missing|\[redacted\])(?=[\"'\s,;]|$))"
    r"[A-Za-z0-9_\-./+=~!@#$%^&*]{8,}(?=[\"'\s,;]|$)",
    re.I | re.M,
)


def redact(text: str) -> str:
    """Return `text` with credentials replaced by `[redacted]`."""
    text = PRIVATE_KEY.sub(REDACTED, text)
    text = URL_PASSWORD.sub(rf"\1:{REDACTED}@", text)
    text = AUTH_HEADER.sub(rf"\1 {REDACTED}", text)
    text = SECRET_ASSIGNMENT.sub(rf"\g<name>\g<sep>{REDACTED}", text)
    return KNOWN_TOKENS.sub(REDACTED, text)
