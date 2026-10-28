import asyncio
import os
import subprocess
import sys
import threading


class MirrorProcessManager:
    """Start/stopt mirror_node.main als kindproces van de beheerpagina-
    backend, puur voor ontwerp/test zonder fysieke node -- MIRROR_HEADLESS=1
    wordt altijd geforceerd. Zie
    docs/superpowers/specs/2026-08-27-mirror-node-inline-start-design.md."""

    def __init__(self, settings, ws_hub=None, loop=None, log_dir="./logs"):
        self._settings = settings
        self._ws_hub = ws_hub
        self._loop = loop
        self._log_dir = log_dir
        self._proc = None
        self._reader_thread = None
        # _wanted: is de node bewust gestart (en niet bewust gestopt)? Dan
        # herstart de watchdog 'm als hij onverwacht wegvalt -- op de avond
        # zelf staat er niemand naast om op Start te drukken.
        self._wanted = False
        self._lock = threading.Lock()
        self._watchdog_stop = threading.Event()

    def _running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        with self._lock:
            self._wanted = True
            return self._start_locked()

    def _start_locked(self):
        if self._running():
            return self.status()
        env = {
            **os.environ,
            "MIRROR_HEADLESS": "1",
            "MQTT_HOST": self._settings.mqtt_host,
            "MQTT_PORT": str(self._settings.mqtt_port),
            "MQTT_USER": self._settings.mqtt_user,
            "MQTT_PASS": self._settings.mqtt_pass,
            "BACKEND_URL": "http://localhost:8000",
            "LOG_DIR": self._log_dir,
        }
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "mirror_node.main"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()
        return self.status()

    def stop(self):
        with self._lock:
            self._wanted = False
            return self._stop_locked()

    def _stop_locked(self):
        if not self._running():
            return self.status()
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        return self.status()

    def ensure_running(self):
        """Herstart de node als hij gewenst is maar niet (meer) draait."""
        with self._lock:
            if self._wanted and not self._running():
                self._start_locked()

    def start_watchdog(self, interval=10):
        def _loop():
            while not self._watchdog_stop.wait(interval):
                self.ensure_running()

        threading.Thread(target=_loop, daemon=True).start()

    def stop_watchdog(self):
        self._watchdog_stop.set()

    def status(self):
        running = self._running()
        return {"running": running, "pid": self._proc.pid if running else None}

    def _read_output(self):
        for line in self._proc.stdout:
            self._broadcast(line.rstrip())

    def _broadcast(self, line):
        if self._ws_hub is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._ws_hub.broadcast({"type": "log", "topic": "process/mirror-node", "payload": line}),
            self._loop,
        )
