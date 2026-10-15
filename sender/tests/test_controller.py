"""SenderController: validation, secrets never reach the UI, URL warnings."""

import pytest

from church_sender import config, controller
from church_sender.audio import InputDevice
from church_sender.controller import SenderController, UserError

from test_config import kr  # noqa: F401  (in-memory keyring fixture)

DEVICES = [
    InputDevice(index=0, name="Dante Virtual Soundcard", hostapi="Core Audio", max_input_channels=16, default_samplerate=48000.0),
    InputDevice(index=1, name="Built-in Microphone", hostapi="Core Audio", max_input_channels=1, default_samplerate=48000.0),
]
TOKEN = "cs_0123456789abcdef0123456789abcdef_" + "s" * 40  # gitleaks:allow (fake test token)


@pytest.fixture
def ctl(tmp_path, monkeypatch, kr):  # noqa: F811
    monkeypatch.setattr(controller, "list_input_devices", lambda: list(DEVICES))
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    return SenderController(config.Config())


def test_initial_state_never_contains_the_token(ctl):
    ctl.save_settings({"server_url": "wss://audio.example.org/ingest/v1/stream", "token": TOKEN,
                       "device_key": "Core Audio::Dante Virtual Soundcard", "channel": 3, "sample_rate": 16000})
    state = ctl.initial_state()
    assert state["has_token"] is True
    assert TOKEN not in repr(state)
    assert state["config"]["device_key"] == "Core Audio::Dante Virtual Soundcard"
    assert state["config"]["channel"] == 3
    assert [d["channels"] for d in state["devices"]] == [16, 1]


def test_blank_token_keeps_the_saved_one(ctl):
    ctl.refresh_devices()
    ctl.save_settings({"server_url": "", "token": TOKEN})
    ctl.save_settings({"server_url": "", "token": ""})
    assert config.get_token() == TOKEN


@pytest.mark.parametrize(
    "data, message",
    [
        ({"server_url": "https://example.org"}, "wss://"),
        ({"server_url": "ws://audio.example.org/x"}, "local network"),
        ({"device_key": "Core Audio::Built-in Microphone", "channel": 2}, "1 input channel"),
        ({"sample_rate": 44100}, "sample rate"),
        ({"headers": {"Bad Name": "x"}}, "header"),
    ],
)
def test_invalid_settings_are_rejected_with_a_readable_message(ctl, data, message):
    ctl.refresh_devices()
    with pytest.raises(UserError) as e:
        ctl.save_settings(data)
    assert message.lower() in str(e.value).lower()


def test_url_warning_for_lan(ctl):
    assert "local network" in ctl.url_warning("ws://192.168.1.10:8082/ingest/v1/stream")
    assert ctl.url_warning("wss://audio.example.org/ingest/v1/stream") is None


def test_poll_when_idle(ctl):
    p = ctl.poll()
    assert p["status"]["state"] == "stopped" and p["levels"] is None and p["capturing"] is False
