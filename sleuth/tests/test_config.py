from sleuth.config import Config


def test_memory_seconds():
    assert Config(day_seconds=120, memory_days=2).memory_seconds == 240


def test_from_env_overrides(monkeypatch):
    monkeypatch.delenv("SLEUTH_CONTEX_URL", raising=False)
    monkeypatch.setenv("SLEUTH_POPULATION", "7")
    monkeypatch.setenv("CONTEX_MCP_URL", "http://example:9/mcp")
    cfg = Config.from_env()
    assert cfg.population == 7
    assert cfg.contex_url == "http://example:9/mcp"


def test_match_margin_default_and_override(monkeypatch):
    monkeypatch.delenv("SLEUTH_CONTEX_URL", raising=False)
    assert Config().match_margin == 0.015
    monkeypatch.setenv("SLEUTH_MATCH_MARGIN", "0.05")
    assert Config.from_env().match_margin == 0.05


def test_old_threshold_fields_are_gone():
    assert not hasattr(Config(), "threshold") and not hasattr(Config(), "judge_threshold")


def test_each_run_gets_its_own_session(monkeypatch):
    monkeypatch.delenv("SLEUTH_SESSION", raising=False)
    assert Config.from_env().session != Config.from_env().session
    monkeypatch.setenv("SLEUTH_SESSION", "replay")
    assert Config.from_env().session == "replay"


def test_price_overrides(monkeypatch):
    monkeypatch.setenv("SLEUTH_JEV_INPUT_PER_MTOK", "0.1")
    monkeypatch.setenv("SLEUTH_HAIKU_OUTPUT_PER_MTOK", "4")
    cfg = Config.from_env()
    assert (cfg.jev_input_per_mtok, cfg.haiku_output_per_mtok, cfg.haiku_input_per_mtok) == (0.1, 4.0, 0.1)


def test_listen_lasts_twenty_seconds_by_default():
    assert Config().listen_seconds == 20.0


def test_the_address_is_the_web_host_and_railways_port_when_set(monkeypatch):
    monkeypatch.setenv("PORT", "4321")
    assert Config(web_host="0.0.0.0").address() == ("0.0.0.0", 4321)
    monkeypatch.delenv("PORT")
    assert Config().address() == ("127.0.0.1", 8765)
    monkeypatch.setenv("SLEUTH_WEB_HOST", "0.0.0.0")
    assert Config.from_env().address() == ("0.0.0.0", 8765)


def test_data_dir_defaults_to_the_working_directory_and_reads_the_environment(monkeypatch):
    assert Config().data_dir == ""
    monkeypatch.setenv("SLEUTH_DATA_DIR", "/data")
    assert Config.from_env().data_dir == "/data"
