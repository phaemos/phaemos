import pytest


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    # tests never write the real boot counter file
    monkeypatch.setenv("PHAEMOS_STATE_DIR", str(tmp_path / "state"))
