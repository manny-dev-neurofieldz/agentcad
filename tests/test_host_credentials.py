"""Where a host's address and credentials come from, and the refusals around them.

Environment first, then the user file, then the host's defaults; a file other users can reach is
refused with the command that fixes it; nothing a message says is a credential.
"""

import os
import stat

import pytest

from agentcad.hosts import HostConfigError, credentials
from agentcad.hosts.credentials import HostSettings, env_name, load_settings, normalize_url

SECRET = "hunter2-file-secret-Q8"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty agentcad config folder under XDG_CONFIG_HOME, and no host variables in the environment."""
    for key in [k for k in os.environ if k.startswith("AGENTCAD_PRUSALINK_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    folder = tmp_path / "xdg" / "agentcad"
    folder.mkdir(parents=True)
    return folder


def _write(folder, text, mode=0o600):
    path = folder / "hosts.toml"
    path.write_text(text)
    path.chmod(mode)
    return path


def test_each_value_comes_from_the_environment_then_the_file_then_the_default(home, monkeypatch):
    path = _write(home, f'[prusalink]\nurl = "192.0.2.10:8080"\npassword = "{SECRET}"\nstorage = "sdcard"\ntimeout = 4\n')
    assert credentials.config_path() == path                                       # beside printers.toml, under XDG_CONFIG_HOME
    got = load_settings("prusalink", defaults={"user": "maker"})
    assert (got.url, got.user, got.password, got.storage, got.timeout) == ("http://192.0.2.10:8080", "maker", SECRET, "sdcard", 4.0)
    assert str(path) in got.source
    monkeypatch.setenv(env_name("prusalink", "password"), "from-the-environment")
    monkeypatch.setenv(env_name("prusalink", "user"), "operator")
    monkeypatch.setenv(env_name("prusalink", "TIMEOUT"), "2.5")
    got = load_settings("prusalink", defaults={"user": "maker"})
    assert (got.user, got.password, got.timeout, got.url) == ("operator", "from-the-environment", 2.5, "http://192.0.2.10:8080")
    assert "environment" in got.source and str(path) in got.source
    assert env_name("my host", "url") == "AGENTCAD_MY_HOST_URL"


def test_missing_values_are_named_with_where_to_set_them_and_never_with_values(home, monkeypatch):
    with pytest.raises(HostConfigError) as caught:
        load_settings("prusalink", defaults={"user": "maker"})
    text = str(caught.value)
    assert "AGENTCAD_PRUSALINK_URL" in text and "AGENTCAD_PRUSALINK_PASSWORD" in text and "hosts.toml" in text
    assert "no user" not in text                                                    # the default covers it
    _write(home, f'[prusalink]\nurl = "192.0.2.10"\n')
    with pytest.raises(HostConfigError, match="no password: set AGENTCAD_PRUSALINK_PASSWORD or add `password = ...` under"):
        load_settings("prusalink", defaults={"user": "maker"})
    monkeypatch.setenv(env_name("prusalink", "password"), "")                      # an empty variable is not a value
    with pytest.raises(HostConfigError, match="no password"):
        load_settings("prusalink", defaults={"user": "maker"})


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660, 0o620, 0o666, 0o777, 0o601, 0o610])
def test_a_file_other_users_can_reach_is_refused_and_the_message_gives_the_fix(home, monkeypatch, mode):
    path = _write(home, f'[prusalink]\nurl = "192.0.2.10"\npassword = "{SECRET}"\n', mode)
    with pytest.raises(HostConfigError) as caught:
        load_settings("prusalink", defaults={"user": "maker"})
    text = str(caught.value)
    assert str(path) in text and f"mode {mode:04o}" in text and f"chmod 600 {path}" in text and SECRET not in text
    monkeypatch.setenv(env_name("prusalink", "url"), "192.0.2.10")                  # supplying every value does not hide it
    monkeypatch.setenv(env_name("prusalink", "password"), "x")
    with pytest.raises(HostConfigError, match="chmod 600"):
        load_settings("prusalink", defaults={"user": "maker"})
    path.chmod(0o600)
    assert load_settings("prusalink", defaults={"user": "maker"}).url == "http://192.0.2.10"


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_a_private_file_is_read(home, mode):
    _write(home, f'[prusalink]\nurl = "192.0.2.10"\npassword = "{SECRET}"\n', mode)
    assert load_settings("prusalink", defaults={"user": "maker"}).password == SECRET
    assert stat.S_IMODE(os.stat(credentials.config_path()).st_mode) == mode


def test_a_bad_file_is_named_without_its_contents(home):
    _write(home, f'[prusalink]\nurl = "192.0.2.10"\npasword = "{SECRET}"\n')
    with pytest.raises(HostConfigError, match=r"unknown setting\(s\) in \[prusalink\]: pasword") as caught:
        load_settings("prusalink", defaults={"user": "maker"})
    assert SECRET not in str(caught.value)
    _write(home, f'[prusalink\nurl = "{SECRET}"\n')
    with pytest.raises(HostConfigError, match="cannot parse") as caught:
        load_settings("prusalink", defaults={"user": "maker"})
    assert SECRET not in str(caught.value)
    _write(home, 'prusalink = "not a table"\n')
    with pytest.raises(HostConfigError, match=r"\[prusalink\] must be a table"):
        load_settings("prusalink", defaults={"user": "maker"})
    _write(home, '[prusalink]\nurl = "192.0.2.10"\npassword = 12345\n')
    with pytest.raises(HostConfigError, match="password must be text"):
        load_settings("prusalink", defaults={"user": "maker"})
    _write(home, '[prusalink]\nurl = "192.0.2.10"\npassword = "x"\ntimeout = -1\n')
    with pytest.raises(HostConfigError, match="timeout must be a positive number"):
        load_settings("prusalink", defaults={"user": "maker"})


@pytest.mark.parametrize("raw,expected", [
    ("192.0.2.5", "http://192.0.2.5"), ("printer.local", "http://printer.local"),
    ("https://h.example:8443/pre/", "https://h.example:8443/pre"), ("HTTP://H.example/", "HTTP://H.example")])
def test_a_host_url_is_normalised(raw, expected):
    assert normalize_url(raw).lower() == expected.lower()


@pytest.mark.parametrize("raw", ["http://maker:hunter2@192.0.2.5", "http://:hunter2@192.0.2.5", "ftp://192.0.2.5",
                                 "http://192.0.2.5:notaport", "http://192.0.2.5/?key=hunter2", "http://192.0.2.5/a b", "", "http://"])
def test_a_host_url_with_credentials_or_junk_is_refused_without_repeating_it(raw):
    with pytest.raises(HostConfigError) as caught:
        normalize_url(raw)
    assert "hunter2" not in str(caught.value)


def test_settings_show_neither_the_user_nor_the_password():
    s = HostSettings(url="http://192.0.2.5", user="operator-77", password=SECRET, source="environment")
    for text in (repr(s), str(s), f"{s}", "%s" % (s,), repr([s])):
        assert "operator-77" not in text and SECRET not in text and "***" in text
    assert "operator-77" not in str(s.public()) and SECRET not in str(s.public()) and s.public()["url"] == "http://192.0.2.5"


def test_an_unreadable_file_a_missing_toml_reader_and_a_missing_file_are_named(home, monkeypatch):
    path = _write(home, '[prusalink]\nurl = "192.0.2.10"\npassword = "x"\n')
    with monkeypatch.context() as patched:                                           # not undo(): that would undo the fixture's too
        patched.setattr("agentcad.config.tomllib", None)
        with pytest.raises(HostConfigError, match="no TOML reader.*AGENTCAD_PRUSALINK_PASSWORD"):
            load_settings("prusalink", defaults={"user": "maker"})
    if os.geteuid() != 0:                                                            # root reads anything
        path.chmod(0)
        with pytest.raises(HostConfigError, match="cannot read"):
            load_settings("prusalink", defaults={"user": "maker"})
        path.chmod(0o600)
    with pytest.raises(HostConfigError, match="cannot read"):
        credentials.check_private(home / "absent.toml")
