from pathlib import Path

from scripts import check_no_secrets
from scripts.check_no_secrets import scan_text


def test_secret_scan_rejects_assignments_but_allows_examples():
    assert scan_text("MISTRAL_API_KEY=actual-secret-value")
    assert scan_text("MISTRAL_API_KEY=") == []
    assert scan_text("MISTRAL_API_KEY=\nMISTRAL_MODEL=mistral-small-latest") == []


def test_fallback_file_discovery_excludes_local_environment(tmp_path, monkeypatch):
    local_environment = tmp_path / ".env.local"
    local_environment.write_text("MISTRAL_API_KEY=secret", encoding="utf-8")
    source = tmp_path / "app.py"
    source.write_text("print('safe')", encoding="utf-8")
    monkeypatch.setattr(check_no_secrets, "_git_tracked_files", lambda root: None)

    discovered = tuple(check_no_secrets._tracked_text_files(Path(tmp_path)))

    assert discovered == (source,)
