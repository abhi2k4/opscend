"""`make check-ai` matches the configured model against the server's model list."""

from app.investigator.check import is_served


def test_ollama_latest_tag_counts_as_the_plain_name():
    served = ["qwen3.5-2b-local:latest", "llama3:latest"]
    assert is_served("qwen3.5-2b-local", served)
    assert is_served("qwen3.5-2b-local:latest", served)


def test_other_tags_and_missing_models_are_not_served():
    served = ["qwen2.5:7b", "openai/gpt-oss-120b"]
    assert not is_served("qwen2.5", served)  # only :latest is implied
    assert not is_served("qwen2.5:14b", served)
    assert is_served("openai/gpt-oss-120b", served)
