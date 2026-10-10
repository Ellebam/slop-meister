"""The retro port derives durable spill state from HOME, never from a run folder."""


def test_retro_spill_uses_durable_home_instead_of_a_disposable_run_root(tmp_path, monkeypatch):
    """The port no longer derives durable spill state from a disposable run root."""
    from slopmeister.vault.runtime import retro

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("RETRO_SPILL_DIR", raising=False)
    assert retro.spill_dir() == tmp_path / ".local/state/slopmeister/retro-spill"
