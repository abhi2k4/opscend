"""Secrets are removed from provider text before it reaches the model; evidence is not."""

import pytest

from app.evals.cases import CASES
from app.investigator.redact import REDACTED, redact
from app.investigator.tools import untrusted


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        ("STRIPE_SECRET_KEY=sk_live_51Hx9aBcDeFgHiJkLmN", "sk_live_51Hx9aBcDeFgHiJkLmN"),
        ("export GITHUB_TOKEN=ghp_" + "a1B2" * 9, "ghp_" + "a1B2" * 9),
        ("aws_access_key_id = AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("GROQ_API_KEY: gsk_0123456789abcdefghijKLMN", "gsk_0123456789abcdefghijKLMN"),
        ('{"password": "hunter2-but-longer"}', "hunter2-but-longer"),
        ("DB_PASSWORD='Tr0ub4dor&3xyz'", "Tr0ub4dor&3xyz"),
        ("connecting to postgres://app:s3cr3tpw@db.internal:5432/app", "s3cr3tpw"),
        ("Authorization: Bearer abcdefghijklmnop0123456789", "abcdefghijklmnop0123456789"),
        (
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
            "eyJhbGciOiJIUzI1NiJ9",
        ),
        ("whsec_abcdefghijklmnop leaked in a log", "whsec_abcdefghijklmnop"),
    ],
)
def test_secrets_are_redacted(line, secret):
    out = redact(line)
    assert secret not in out
    assert REDACTED in out


def test_connection_string_keeps_user_and_host():
    out = redact("DATABASE_URL=postgres://app:s3cr3tpw@db.internal:5432/app")
    assert out == f"DATABASE_URL=postgres://app:{REDACTED}@db.internal:5432/app"


def test_private_key_block_is_removed_even_when_cut_off():
    full = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----\nnext"
    assert redact(full) == f"{REDACTED}\nnext"
    assert redact("-----BEGIN PRIVATE KEY-----\nMIIEow\nabc") == REDACTED


@pytest.mark.parametrize(
    "line",
    [
        "Error: Missing required environment variable STRIPE_WEBHOOK_SECRET",
        '+  STRIPE_WEBHOOK_SECRET: required("STRIPE_WEBHOOK_SECRET"),',
        "+const stripe = new Stripe(env.STRIPE_SECRET_KEY);",
        'error: password authentication failed for user "storefront"',
        "API_KEY=undefined",
        "Unexpected token. Did you mean `{'}'}` or `&rbrace;`?",
        "max_tokens: 4000",
        "(author: Jordan Reyes)",
    ],
)
def test_evidence_and_names_are_kept(line):
    assert redact(line) == line


def test_eval_evidence_survives_redaction():
    """Every term an eval case scores on is still visible to the model after redaction."""
    for case in CASES:
        scenario = case.scenario
        raw = "\n".join(
            [text for _, _, text in (*scenario.build_logs, *scenario.runtime_logs)]
            + [spec.patch for spec in scenario.files]
            + [scenario.commit_message]
        )
        terms = [*case.evidence, *(term for group in case.mentions for term in group)]
        redacted = redact(raw)
        for term in terms:
            if term in raw:
                assert term in redacted, f"{case.id}: redaction hid '{term}'"


def test_untrusted_redacts_before_wrapping():
    out = untrusted("build logs", "using key sk_test_abcdefghijklmnop")
    assert "sk_test_abcdefghijklmnop" not in out
    assert out.startswith('<untrusted_data source="build logs">') and REDACTED in out
