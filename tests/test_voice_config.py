import pytest

from alivia_edge.config import VoiceConfig
from alivia_edge.devices.catalog import DeviceCatalog, UnknownDeviceAction


def test_everything_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALIVIA_WS_PORT", "9000")
    monkeypatch.setenv("ALIVIA_WS_PATH", "/voz")
    monkeypatch.setenv("ALIVIA_EMERGENCY_WORDS", "ayuda, socorro")
    monkeypatch.setenv("ALIVIA_BACKEND_URL", "https://api.real.com")
    monkeypatch.setenv("EMERGENCY_PATH", "/v2/e")
    monkeypatch.setenv("EMERGENCY_API_TOKEN", "tok")
    monkeypatch.setenv("ALIVIA_CONFIRM_WINDOW_S", "12.5")
    cfg = VoiceConfig.from_env()
    assert (cfg.ws_port, cfg.ws_path, cfg.confirm_window_s) == (9000, "/voz", 12.5)
    assert cfg.emergency_words == ("ayuda", "socorro")
    assert not cfg.emergency_is_placeholder


def test_defaults_match_the_spec():
    cfg = VoiceConfig()
    assert (cfg.vad_end_ms, cfg.confirm_window_s, cfg.echo_tail_ms) == (700, 8.0, 300)
    assert (
        cfg.emergency_words == ("ayuda", "auxilio") and cfg.emergency_dedupe_s == 10.0
    )
    assert cfg.emergency_is_placeholder  # backend .example y token changeme


def test_catalog_discards_anything_not_in_the_table(tmp_path):
    catalog = DeviceCatalog()
    assert catalog.resolve("puerta", "open")[0].device_id == "door-01"
    for device, action in [
        ("garaje", "open"),
        ("puerta", "on"),
        ("luz_cuarto", "open"),
    ]:
        with pytest.raises(UnknownDeviceAction):
            catalog.resolve(device, action)
