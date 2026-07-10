#!/usr/bin/env python3
"""Single-owner audio orchestrator for the kitchen Raspberry Pi.

The daemon deliberately owns only its mpv process. Other players are stopped
through explicitly configured commands, so no process-name guessing is needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:  # grp is unavailable on Windows, which is useful for development tests.
    import grp
except ImportError:  # pragma: no cover - Linux always provides grp.
    grp = None


LOG = logging.getLogger("kuche_pi_audio")
SOCKET_PATH = "/run/kuche-pi-audio/control.sock"
KEY_ACTIONS = {
    "KEY_F13": {"action": "stop"},
    "KEY_F14": {"action": "play", "source": "tagesschau"},
    "KEY_F15": {"action": "play", "source": "dlf_kultur"},
    "KEY_F16": {"action": "labels"},
    "KEY_F17": {"action": "play", "source": "swr1"},
    "KEY_F18": {"action": "play", "source": "querfunk"},
    "KEY_F19": {"action": "play", "source": "rock_antenne"},
    "KEY_F20": {"action": "play", "source": "dlf"},
}


class ConfigurationError(ValueError):
    """Raised for a configuration that would be unsafe or unusable."""


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file:
        config = json.load(file)
    required = ("audio_device", "mpv_binary", "tagesschau_rss", "streams", "remote_sources")
    missing = [name for name in required if name not in config]
    if missing:
        raise ConfigurationError("Missing configuration keys: " + ", ".join(missing))
    if not isinstance(config["streams"], dict) or not config["streams"]:
        raise ConfigurationError("streams must be a non-empty object")
    if config.get("radio_timeout_seconds", 0) < 0:
        raise ConfigurationError("radio_timeout_seconds must not be negative")
    for name, stream in config["streams"].items():
        if not isinstance(stream, dict) or stream.get("kind") != "radio" or not stream.get("url"):
            raise ConfigurationError(f"Invalid radio stream: {name}")
    for name, remote in config["remote_sources"].items():
        commands = remote.get("stop_commands") if isinstance(remote, dict) else None
        if not isinstance(commands, list) or not all(isinstance(command, list) and command for command in commands):
            raise ConfigurationError(f"Invalid stop_commands for remote source: {name}")
    label_command = config.get("label_command", [])
    if not isinstance(label_command, list) or not all(isinstance(value, str) for value in label_command):
        raise ConfigurationError("label_command must be a list of program arguments")
    return config


def latest_tagesschau_url(feed_url: str) -> str:
    """Return the enclosure URL of the newest episode in the official RSS feed."""
    request = urllib.request.Request(feed_url, headers={"User-Agent": "kuche-pi-audio/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        root = ET.fromstring(response.read())
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "enclosure" and element.get("url"):
            return element.attrib["url"]
    raise RuntimeError("The Tagesschau RSS feed contains no playable enclosure")


class AudioOrchestrator:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.owner: str | None = None
        self.source: str | None = None
        self.deadline: float | None = None
        self.mpv: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.stopping = asyncio.Event()

    def state(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "source": self.source,
            "radio_stops_at": int(self.deadline) if self.deadline else None,
            "mpv_running": self.mpv is not None and self.mpv.returncode is None,
        }

    async def run_command(self, command: list[str]) -> None:
        LOG.info("Executing configured command: %s", command)
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=12)
            if process.returncode:
                LOG.warning("Command failed (%s): %s", process.returncode, command)
        except (FileNotFoundError, asyncio.TimeoutError) as error:
            LOG.warning("Could not execute %s: %s", command, error)

    async def stop_mpv(self) -> None:
        if self.mpv is None:
            return
        process, self.mpv = self.mpv, None
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def stop_remotes(self, except_source: str | None = None) -> None:
        for name, remote in self.config["remote_sources"].items():
            if name != except_source:
                for command in remote["stop_commands"]:
                    await self.run_command(command)

    async def stop_all(self) -> None:
        await self.stop_mpv()
        await self.stop_remotes()
        self.owner = self.source = self.deadline = None

    async def start_mpv(self, url: str, source: str, is_radio: bool) -> None:
        command = [
            self.config["mpv_binary"], "--no-video", "--really-quiet", "--no-terminal",
            "--ao=alsa", f"--audio-device={self.config['audio_device']}", "--idle=no", url,
        ]
        LOG.info("Starting button source %s", source)
        self.mpv = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        self.owner, self.source = "button", source
        self.deadline = time.time() + self.config.get("radio_timeout_seconds", 21600) if is_radio else None

    async def play(self, source: str) -> None:
        await self.stop_mpv()
        await self.stop_remotes()
        if source == "tagesschau":
            url = await asyncio.to_thread(latest_tagesschau_url, self.config["tagesschau_rss"])
            await self.start_mpv(url, source, False)
            return
        stream = self.config["streams"].get(source)
        if stream is None:
            raise ValueError(f"Unknown source: {source}")
        await self.start_mpv(stream["url"], source, stream["kind"] == "radio")

    async def remote_start(self, source: str) -> None:
        if source not in self.config["remote_sources"]:
            raise ValueError(f"Unknown remote source: {source}")
        await self.stop_mpv()
        await self.stop_remotes(except_source=source)
        self.owner, self.source, self.deadline = source, source, None

    async def labels(self) -> None:
        command = self.config.get("label_command", [])
        if not command:
            raise ValueError("label_command has not been configured")
        # No await: printing never participates in audio ownership.
        await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            # Leave output connected to systemd's journal so a failed printer
            # job can be diagnosed without ever affecting audio playback.
            start_new_session=True,
        )

    async def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        async with self.lock:
            if action == "status":
                return {"ok": True, "state": self.state()}
            try:
                if action == "stop":
                    await self.stop_all()
                elif action == "play":
                    await self.play(str(request["source"]))
                elif action == "remote-start":
                    await self.remote_start(str(request["source"]))
                elif action == "remote-stop":
                    source = str(request["source"])
                    if self.owner == source:
                        self.owner = self.source = self.deadline = None
                elif action == "labels":
                    await self.labels()
                else:
                    raise ValueError("Unknown action")
            except (KeyError, ValueError, RuntimeError, OSError) as error:
                LOG.warning("Request failed %s: %s", request, error)
                return {"ok": False, "error": str(error), "state": self.state()}
            return {"ok": True, "state": self.state()}

    async def control_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=3)
            response = await self.dispatch(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, asyncio.TimeoutError) as error:
            response = {"ok": False, "error": f"Invalid request: {error}"}
        writer.write((json.dumps(response) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def watch_timeout(self) -> None:
        while not self.stopping.is_set():
            await asyncio.sleep(5)
            async with self.lock:
                if self.mpv is not None and self.mpv.returncode is not None:
                    self.mpv = None
                    if self.owner == "button":
                        self.owner = self.source = self.deadline = None
                if self.owner == "button" and self.deadline and time.time() >= self.deadline:
                    LOG.info("Radio timeout reached")
                    await self.stop_mpv()
                    self.owner = self.source = self.deadline = None


def keyboard_worker(orchestrator: AudioOrchestrator, loop: asyncio.AbstractEventLoop) -> None:
    """Block in evdev on a helper thread and reconnect after unplug/replug."""
    try:
        from evdev import InputDevice, ecodes, list_devices
    except ImportError:
        LOG.error("python3-evdev is not installed; keyboard support disabled")
        return
    names = {getattr(ecodes, name): action for name, action in KEY_ACTIONS.items()}
    while not orchestrator.stopping.is_set():
        device = None
        try:
            for path in list_devices():
                candidate = InputDevice(path)
                if set(candidate.capabilities().get(ecodes.EV_KEY, [])).intersection(names):
                    device = candidate
                    break
                candidate.close()
            if device is None:
                time.sleep(3)
                continue
            LOG.info("Listening to keyboard %s (%s)", device.path, device.name)
            device.grab()
            for event in device.read_loop():
                if orchestrator.stopping.is_set():
                    break
                if event.type == ecodes.EV_KEY and event.value == 1 and event.code in names:
                    loop.call_soon_threadsafe(asyncio.create_task, orchestrator.dispatch(names[event.code]))
        except OSError as error:
            LOG.warning("Keyboard disconnected or unavailable: %s", error)
            time.sleep(2)
        finally:
            if device is not None:
                try:
                    device.ungrab()
                except OSError:
                    pass
                device.close()


async def run(config: dict[str, Any]) -> None:
    Path(SOCKET_PATH).unlink(missing_ok=True)
    orchestrator = AudioOrchestrator(config)
    server = await asyncio.start_unix_server(orchestrator.control_client, path=SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o660)
    try:
        if grp is None:
            raise KeyError
        os.chown(SOCKET_PATH, -1, grp.getgrnam("kuche-audio").gr_gid)
    except KeyError:
        LOG.warning("Group 'kuche-audio' does not exist; socket keeps service group")
    loop = asyncio.get_running_loop()
    threading.Thread(target=keyboard_worker, args=(orchestrator, loop), daemon=True).start()
    for number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(number, orchestrator.stopping.set)
    timeout_task = asyncio.create_task(orchestrator.watch_timeout())
    LOG.info("Audio button daemon ready")
    await orchestrator.stopping.wait()
    timeout_task.cancel()
    await orchestrator.stop_all()
    server.close()
    await server.wait_closed()
    Path(SOCKET_PATH).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/kuche-pi-audio/config.json")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    try:
        asyncio.run(run(load_config(arguments.config)))
    except ConfigurationError as error:
        LOG.critical("Invalid configuration: %s", error)
        sys.exit(2)


if __name__ == "__main__":
    main()
