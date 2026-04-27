"""
Unit tests for oscal.oscal_support.

These tests focus on API behavior and compatibility wrappers without
performing network updates.
"""

import oscal.oscal_support as support_mod
from oscal.oscal_support import OSCALSupport, OSCAL_support


class _FakeDB:
    def __init__(self):
        self.query_calls = 0

    def query(self, _sql):
        self.query_calls += 1
        return [{"model": "catalog"}, {"model": "profile"}]


class _FakeResourcePath:
    def __init__(self):
        self.name = ""
        self.read_text_calls = 0
        self.read_bytes_calls = 0

    def joinpath(self, name):
        self.name = name
        return self

    def read_text(self, encoding="utf-8"):
        _ = encoding
        self.read_text_calls += 1
        return f"text:{self.name}"

    def read_bytes(self):
        self.read_bytes_calls += 1
        return f"bytes:{self.name}".encode("utf-8")


def test_class_alias_preserved():
    assert OSCAL_support is OSCALSupport


def test_configure_support_accepts_pythonic_aliases(monkeypatch):
    monkeypatch.setattr(support_mod, "support", None)
    captured = {}

    class DummySupport:
        def __init__(self, support_file, db_init_mode="auto"):
            captured["support_file"] = support_file
            captured["db_init_mode"] = db_init_mode
            self.ready = True
            self.db_state = "populated"

    monkeypatch.setattr(support_mod, "OSCALSupport", DummySupport)

    obj = support_mod.configure_support(db_path="/tmp/test.db", init_mode="create")

    assert isinstance(obj, DummySupport)
    assert captured["support_file"] == "/tmp/test.db"
    assert captured["db_init_mode"] == "create"


def test_setup_support_wrapper_calls_configure_support(monkeypatch):
    sentinel = object()
    captured = {}

    def fake_configure_support(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(support_mod, "configure_support", fake_configure_support)

    result = support_mod.setup_support("/tmp/support.db", "extract")

    assert result is sentinel
    assert captured == {
        "support_file": "/tmp/support.db",
        "db_init_mode": "extract",
    }


def test_get_support_uses_singleton(monkeypatch):
    sentinel = object()
    calls = {"count": 0}

    def fake_configure_support():
        calls["count"] += 1
        return sentinel

    monkeypatch.setattr(support_mod, "support", None)
    monkeypatch.setattr(support_mod, "configure_support", fake_configure_support)

    first = support_mod.get_support()
    second = support_mod.get_support()

    assert first is sentinel
    assert second is sentinel
    assert calls["count"] == 1


def test_wrapper_asset_delegates_to_get_asset():
    obj = OSCALSupport.__new__(OSCALSupport)

    def fake_get_asset(version, model, asset_type):
        return f"{version}:{model}:{asset_type}"

    obj.get_asset = fake_get_asset

    assert obj.asset("v1.2.3", "catalog", "xml-schema") == "v1.2.3:catalog:xml-schema"


def test_wrapper_model_methods_delegate():
    obj = OSCALSupport.__new__(OSCALSupport)

    def fake_list_models(version="all"):
        if version == "v1.0.0":
            return ["catalog"]
        return ["profile"]

    obj.list_models = fake_list_models

    assert obj.enumerate_models("v1.0.0") == ["catalog"]
    assert obj.is_model_valid("catalog", "v1.0.0") is True
    assert obj.is_valid_model("profile", "all") is True


def test_get_latest_version_wrapper_delegates():
    obj = OSCALSupport.__new__(OSCALSupport)
    obj.latest_version = lambda: "v1.0.9"

    assert obj.get_latest_version() == "v1.0.9"


def test_list_models_uses_cache_per_version():
    obj = OSCALSupport.__new__(OSCALSupport)
    obj.versions = {"v1.0.0": {}}
    obj._cache = {}
    obj.db = _FakeDB()

    first = obj.list_models("v1.0.0")
    second = obj.list_models("v1.0.0")

    assert first == ["catalog", "profile"]
    assert second == ["catalog", "profile"]
    assert obj.db.query_calls == 1


def test_load_file_as_bytes_overrides_binary(monkeypatch):
    obj = OSCALSupport.__new__(OSCALSupport)
    obj._cache = {}

    fake_path = _FakeResourcePath()
    monkeypatch.setattr(support_mod.resources, "files", lambda _pkg: fake_path)

    content = obj.load_file("catalog.xml", binary=False, as_bytes=True)

    assert isinstance(content, bytes)
    assert content == b"bytes:catalog.xml"
    assert fake_path.read_bytes_calls == 1
    assert fake_path.read_text_calls == 0


def test_update_respects_fetch_alias_over_mode():
    obj = OSCALSupport.__new__(OSCALSupport)
    events = []

    obj._OSCALSupport__status_messages = lambda *args, **kwargs: None
    obj._OSCALSupport__clear_oscal_versions = lambda: events.append("clear_all") or True
    obj._OSCALSupport__clear_oscal_version = lambda version: events.append(("clear_one", version)) or True
    obj._OSCALSupport__get_oscal_versions = lambda fetch: events.append(("get", fetch)) or True
    obj._OSCALSupport__load_versions = lambda: events.append("load") or True

    result = obj.update(mode="all", fetch="new")

    assert result is True
    assert "clear_all" not in events
    assert ("get", "new") in events
