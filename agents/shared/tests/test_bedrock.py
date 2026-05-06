"""Unit tests for `agents.shared.bedrock.build_model`."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def fake_bedrock_model():
    """Patch strands.models.BedrockModel so we don't make a boto session."""
    import shared.bedrock as mod
    with patch.object(mod, "BedrockModel") as mock_cls:
        mock_cls.return_value = MagicMock(spec=["inference_config"])
        yield mock_cls


def test_guardrail_env_attached(monkeypatch, fake_bedrock_model):
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "gr-x")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7")
    import shared.bedrock as mod
    mod.build_model()
    kwargs = fake_bedrock_model.call_args.kwargs
    assert kwargs["guardrail_id"] == "gr-x"
    assert kwargs["guardrail_version"] == "DRAFT"
    assert kwargs["guardrail_trace"] == "enabled"


def test_missing_guardrail_id_raises(monkeypatch, fake_bedrock_model):
    monkeypatch.delenv("BEDROCK_GUARDRAIL_ID", raising=False)
    monkeypatch.delenv("SDLC_ALLOW_MISSING_GUARDRAIL", raising=False)
    import shared.bedrock as mod
    with pytest.raises(RuntimeError, match="BEDROCK_GUARDRAIL_ID"):
        mod.build_model()
    fake_bedrock_model.assert_not_called()


def test_missing_guardrail_id_escape_hatch(monkeypatch, fake_bedrock_model, caplog):
    monkeypatch.delenv("BEDROCK_GUARDRAIL_ID", raising=False)
    monkeypatch.setenv("SDLC_ALLOW_MISSING_GUARDRAIL", "1")
    import shared.bedrock as mod
    with caplog.at_level("WARNING"):
        mod.build_model()
    kwargs = fake_bedrock_model.call_args.kwargs
    assert "guardrail_id" not in kwargs
    assert any("SDLC_ALLOW_MISSING_GUARDRAIL" in rec.message for rec in caplog.records)


def test_extra_kwargs_forwarded(monkeypatch, fake_bedrock_model):
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "gr-x")
    import shared.bedrock as mod
    mod.build_model(max_tokens=16000)
    assert fake_bedrock_model.call_args.kwargs["max_tokens"] == 16000
