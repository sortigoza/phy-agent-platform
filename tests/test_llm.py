import anthropic
from anthropic.lib.credentials import CredentialsFile

from phy.llm import credential_source


def test_ant_auth_login_profile_is_reported_with_its_name_and_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))
    client = anthropic.Anthropic(credentials=CredentialsFile(profile="work"))
    source = credential_source(client)
    assert "ant auth login" in source
    assert "'work'" in source
    assert str(tmp_path / "anthropic") in source


def test_api_key_wins_and_is_named():
    assert credential_source(anthropic.Anthropic(api_key="sk-ant-x")) == "ANTHROPIC_API_KEY"
