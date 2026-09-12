"""Settings/env control which ModelProvider create_app wires up by default."""

import os

import pytest

from caseapi.ai.agentcore_provider import AgentCoreModelProvider
from caseapi.ai.fixed_provider import FixedModelProvider
from caseapi.config import Settings, load_settings
from caseapi.main import create_app


def test_load_settings_defaults_to_fixed_provider_with_no_agentcore_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        'CASEAPI_MODEL_PROVIDER',
        'CASEAPI_AGENTCORE_RUNTIME_ARN',
        'CASEAPI_AGENTCORE_REGION',
    ):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings()

    assert settings.model_provider == 'fixed'
    assert settings.agentcore_runtime_arn is None


def test_load_settings_reads_agentcore_config_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('CASEAPI_MODEL_PROVIDER', 'agentcore')
    monkeypatch.setenv(
        'CASEAPI_AGENTCORE_RUNTIME_ARN',
        'arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo',
    )
    monkeypatch.setenv('CASEAPI_AGENTCORE_REGION', 'us-west-2')

    settings = load_settings()

    assert settings.model_provider == 'agentcore'
    assert settings.agentcore_runtime_arn == (
        'arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo'
    )
    assert settings.agentcore_region == 'us-west-2'


def test_create_app_defaults_to_fixed_provider(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / 'db.sqlite', model_provider='fixed')

    app = create_app(settings)

    assert isinstance(app.state.model_provider, FixedModelProvider)


def test_create_app_wires_agentcore_provider_when_configured(tmp_path) -> None:
    settings = Settings(
        db_path=tmp_path / 'db.sqlite',
        model_provider='agentcore',
        agentcore_runtime_arn='arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo',
        agentcore_region='us-west-2',
    )

    app = create_app(settings)

    provider = app.state.model_provider
    assert isinstance(provider, AgentCoreModelProvider)
    assert provider.descriptor() == {
        'provider': 'agentcore',
        'model': 'arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo',
        'region': 'us-west-2',
    }


def test_create_app_fails_fast_when_agentcore_selected_without_runtime_arn(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / 'db.sqlite', model_provider='agentcore')

    with pytest.raises(ValueError, match='CASEAPI_AGENTCORE_RUNTIME_ARN'):
        create_app(settings)


def test_explicit_model_provider_argument_overrides_settings(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / 'db.sqlite', model_provider='agentcore')
    explicit_provider = FixedModelProvider()

    app = create_app(settings, model_provider=explicit_provider)

    assert app.state.model_provider is explicit_provider
