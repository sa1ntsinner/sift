import re

from steamsift import config, i18n
from steamsift.config import Profile, Settings


def test_settings_roundtrip_with_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    s = Settings(lang="ru", active="friend",
                 profiles={"main": Profile(steam_id="1", country="TR", budget=15.5),
                           "friend": Profile(steam_id="2", country="KZ", family=["3", "4"])})
    s.save()
    loaded = Settings.load()
    assert loaded.active == "friend" and loaded.lang == "ru"
    assert loaded.profiles["main"].budget == 15.5 and loaded.profiles["friend"].budget is None
    assert loaded.profiles["friend"].family == ["3", "4"]


def test_env_overrides_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    Settings(profiles={"main": Profile(steam_id="1", country="TR")}).save()
    monkeypatch.setenv("STEAM_COUNTRY", "kz")
    monkeypatch.setenv("STEAM_API_KEY", "abc")
    c = config.activate()
    assert c.country == "KZ" and c.steam_api_key == "abc" and c.steam_id == "1"


def test_secrets_fall_back_to_private_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "secrets.toml")
    assert config.set_secret("itad_api_key", "k1") == "file"
    assert config.get_secret("itad_api_key") == "k1" and config.secret_source("itad_api_key") == "file"
    config.set_secret("itad_api_key", "")
    assert config.get_secret("itad_api_key") == ""


def test_legacy_env_migration(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("STEAM_ID64=76561198012345678\nSTEAM_API_KEY=key1\nSTEAM_COUNTRY=tr\nSTEAM_BALANCE=15\n"
                   "ITAD_API_KEY=key2\n", encoding="utf-8")
    monkeypatch.setattr(config, "_legacy_env_files", lambda: [env])
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "secrets.toml")
    s = Settings()
    assert config.migrate_legacy(s)
    p = s.profiles["main"]
    assert (p.steam_id, p.country, p.budget) == ("76561198012345678", "TR", 15.0)
    assert config.get_secret("steam_api_key") == "key1" and config.get_secret("itad_api_key") == "key2"
    assert not env.exists() and (tmp_path / ".env.migrated").exists()


def test_every_russian_string_matches_english_placeholders():
    missing = set(i18n.EN) - set(i18n.RU)
    assert not missing, f"untranslated: {sorted(missing)}"
    for key, ru in i18n.RU.items():
        assert key in i18n.EN, key
        assert set(re.findall(r"{(\w+)}", ru)) == set(re.findall(r"{(\w+)}", i18n.EN[key])), key


def test_language_switch(monkeypatch):
    config.cfg.lang = "ru"
    assert i18n.t("v_was", n=90) == "было −90%"
    assert i18n.review_label("Very Positive") == "Очень положительные"
    config.cfg.lang = "en"
    assert i18n.t("v_was", n=90) == "was −90%"
