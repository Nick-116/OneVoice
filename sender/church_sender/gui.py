"""Tkinter GUI. The asyncio client runs in a background thread; the GUI polls its state with ``after()``."""

from __future__ import annotations

import logging
import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import APP_NAME, __version__, autostart
from .audio import SUPPORTED_RATES, AudioCapture, InputDevice, Levels, list_input_devices
from .client import STATE_LABELS, LinkState, SenderClient, validate_server_url
from .config import Config, get_extra_headers, get_token, save_config, set_extra_headers, set_token, validate_header
from .logsetup import add_handler
from .runner import ClientThread, build_client_settings, connected_for

log = logging.getLogger(__name__)

METER_MIN_DB = -60.0
STATE_COLORS = {
    LinkState.STOPPED: ("#666666", "white"),
    LinkState.CONNECTING: ("#c98a00", "white"),
    LinkState.RETRY_WAIT: ("#b03a2e", "white"),
    LinkState.STANDBY: ("#2e6db0", "white"),
    LinkState.LIVE: ("#1e8e3e", "white"),
    LinkState.REVOKED: ("#7b1fa2", "white"),
}


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


class HeadersDialog(tk.Toplevel):
    """Edit extra HTTP headers (e.g. Pangolin access-token headers). Values are masked."""

    def __init__(self, parent: tk.Misc, headers: dict[str, str]) -> None:
        super().__init__(parent)
        self.title("Extra HTTP headers")
        self.transient(parent)
        self.result: dict[str, str] | None = None
        self.rows: list[tuple[tk.StringVar, tk.StringVar, ttk.Frame]] = []
        ttk.Label(self, text="Sent with the WebSocket handshake. Values are stored in the system keychain.").pack(padx=10, pady=(10, 4), anchor="w")
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=10)
        ttk.Label(hdr, text="Name", width=28).pack(side="left")
        ttk.Label(hdr, text="Value").pack(side="left")
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=10)
        for name, value in headers.items():
            self._add_row(name, value)
        if not headers:
            self._add_row()
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="Add header", command=self._add_row).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=self._ok).pack(side="right", padx=6)
        self.grab_set()

    def _add_row(self, name: str = "", value: str = "") -> None:
        nv, vv = tk.StringVar(value=name), tk.StringVar(value=value)
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=2)
        ttk.Entry(row, textvariable=nv, width=28).pack(side="left")
        ttk.Entry(row, textvariable=vv, width=36, show="•").pack(side="left", padx=4)
        entry = (nv, vv, row)
        ttk.Button(row, text="Remove", command=lambda: self._remove(entry)).pack(side="left")
        self.rows.append(entry)

    def _remove(self, entry) -> None:
        entry[2].destroy()
        self.rows.remove(entry)

    def _ok(self) -> None:
        headers: dict[str, str] = {}
        try:
            for nv, vv, _ in self.rows:
                name, value = nv.get().strip(), vv.get().strip()
                if not name and not value:
                    continue
                validate_header(name, value)
                headers[name] = value
        except ValueError as e:
            messagebox.showerror("Invalid header", str(e), parent=self)
            return
        self.result = headers
        self.destroy()


class SenderApp:
    def __init__(self, root: tk.Tk, cfg: Config) -> None:
        self.root = root
        self.cfg = cfg
        self.devices: list[InputDevice] = []
        self.capture: AudioCapture | None = None
        self.client: SenderClient | None = None
        self.thread: ClientThread | None = None
        self.testing = False
        self.clip_until = 0.0
        self.peak_hold = (METER_MIN_DB, 0.0)
        self.headers = get_extra_headers(cfg)
        self.log_queue: queue.Queue[str] = queue.Queue()
        add_handler(_QueueHandler(self.log_queue))

        root.title(f"{APP_NAME} {__version__}")
        root.minsize(820, 600)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self.refresh_devices(initial=True)
        self._update_url_warning()
        self.root.after(100, self._tick_meter)
        self.root.after(300, self._tick_status)
        if cfg.auto_start_stream and get_token() and cfg.server_url and cfg.device_name:
            self.root.after(800, self.start_streaming)

    # ------------------------------------------------------------ layout

    def _build(self) -> None:
        pad = dict(padx=6, pady=3)
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)

        # Settings ---------------------------------------------------
        st = ttk.LabelFrame(main, text="Settings", padding=8)
        st.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        st.columnconfigure(1, weight=1)
        r = 0
        ttk.Label(st, text="Server URL").grid(row=r, column=0, sticky="w", **pad)
        self.url_var = tk.StringVar(value=self.cfg.server_url)
        self.url_var.trace_add("write", lambda *_: self._update_url_warning())
        self.url_entry = ttk.Entry(st, textvariable=self.url_var, width=44)
        self.url_entry.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        r += 1
        self.url_warning = ttk.Label(st, text="", foreground="#c25e00", wraplength=380)
        self.url_warning.grid(row=r, column=1, columnspan=2, sticky="w", padx=6)
        r += 1
        ttk.Label(st, text="Sender token").grid(row=r, column=0, sticky="w", **pad)
        self.token_var = tk.StringVar(value=get_token())
        self.token_entry = ttk.Entry(st, textvariable=self.token_var, show="•", width=36)
        self.token_entry.grid(row=r, column=1, sticky="ew", **pad)
        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(st, text="Show", variable=self.show_token,
                        command=lambda: self.token_entry.configure(show="" if self.show_token.get() else "•")).grid(row=r, column=2, **pad)
        r += 1
        ttk.Label(st, text="Extra headers").grid(row=r, column=0, sticky="w", **pad)
        self.headers_label = ttk.Label(st, text="")
        self.headers_label.grid(row=r, column=1, sticky="w", **pad)
        self.headers_btn = ttk.Button(st, text="Edit…", command=self.edit_headers)
        self.headers_btn.grid(row=r, column=2, **pad)
        self._update_headers_label()
        r += 1
        ttk.Separator(st).grid(row=r, column=0, columnspan=3, sticky="ew", pady=6)
        r += 1
        ttk.Label(st, text="Input device").grid(row=r, column=0, sticky="w", **pad)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(st, textvariable=self.device_var, state="readonly", width=44)
        self.device_combo.grid(row=r, column=1, sticky="ew", **pad)
        self.device_combo.bind("<<ComboboxSelected>>", lambda e: self._on_device_change())
        self.refresh_btn = ttk.Button(st, text="Refresh", command=self.refresh_devices)
        self.refresh_btn.grid(row=r, column=2, **pad)
        r += 1
        ttk.Label(st, text="Input channel").grid(row=r, column=0, sticky="w", **pad)
        self.channel_var = tk.StringVar(value=str(self.cfg.channel))
        self.channel_combo = ttk.Combobox(st, textvariable=self.channel_var, state="readonly", width=8)
        self.channel_combo.grid(row=r, column=1, sticky="w", **pad)
        self.channel_combo.bind("<<ComboboxSelected>>", lambda e: self._restart_test_if_running())
        r += 1
        ttk.Label(st, text="Send sample rate").grid(row=r, column=0, sticky="w", **pad)
        self.rate_var = tk.StringVar(value=str(self.cfg.sample_rate))
        self.rate_combo = ttk.Combobox(st, textvariable=self.rate_var, state="readonly", width=8, values=[str(x) for x in SUPPORTED_RATES])
        self.rate_combo.grid(row=r, column=1, sticky="w", **pad)
        r += 1
        ttk.Label(st, text="Input gain").grid(row=r, column=0, sticky="w", **pad)
        gf = ttk.Frame(st)
        gf.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self.gain_var = tk.DoubleVar(value=self.cfg.gain_db)
        self.gain_label = ttk.Label(gf, width=8)
        ttk.Scale(gf, from_=-20, to=20, variable=self.gain_var, command=lambda v: self._on_gain()).pack(side="left", fill="x", expand=True)
        self.gain_label.pack(side="left", padx=4)
        ttk.Button(gf, text="0 dB", width=5, command=lambda: (self.gain_var.set(0.0), self._on_gain())).pack(side="left")
        self._on_gain()
        r += 1
        self.autostream_var = tk.BooleanVar(value=self.cfg.auto_start_stream)
        ttk.Checkbutton(st, text="Start streaming automatically when the app opens", variable=self.autostream_var).grid(row=r, column=0, columnspan=3, sticky="w", **pad)
        r += 1
        self.login_var = tk.BooleanVar(value=autostart.is_enabled() if autostart.is_supported() else False)
        cb = ttk.Checkbutton(st, text="Launch at login", variable=self.login_var, command=self.toggle_launch_at_login)
        cb.grid(row=r, column=0, columnspan=3, sticky="w", **pad)
        if not autostart.is_supported():
            cb.state(["disabled"])
        r += 1
        ttk.Button(st, text="Save settings", command=self.save_settings).grid(row=r, column=0, columnspan=3, sticky="e", **pad)

        # Status -----------------------------------------------------
        sf = ttk.LabelFrame(main, text="Connection", padding=8)
        sf.grid(row=0, column=1, sticky="nsew")
        sf.columnconfigure(1, weight=1)
        self.state_label = tk.Label(sf, text="Disconnected", font=("TkDefaultFont", 20, "bold"), bg="#666666", fg="white", pady=10)
        self.state_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.status_vars: dict[str, tk.StringVar] = {}
        for i, (key, title) in enumerate([("campus", "Campus"), ("since", "Connected for"), ("bytes", "Data sent"),
                                          ("reconnects", "Reconnects"), ("error", "Last error"), ("warning", "Warning")], start=1):
            ttk.Label(sf, text=title).grid(row=i, column=0, sticky="nw", padx=4, pady=1)
            var = tk.StringVar(value="—")
            fg = "#b03a2e" if key == "error" else ("#c25e00" if key == "warning" else "")
            lbl = ttk.Label(sf, textvariable=var, wraplength=330, **({"foreground": fg} if fg else {}))
            lbl.grid(row=i, column=1, sticky="w", padx=4, pady=1)
            self.status_vars[key] = var
        self.stream_btn = ttk.Button(sf, text="Start streaming", command=self.toggle_streaming)
        self.stream_btn.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        # Meter ------------------------------------------------------
        mf = ttk.LabelFrame(main, text="Input level", padding=8)
        mf.grid(row=1, column=1, sticky="nsew", pady=(8, 0))
        mf.columnconfigure(0, weight=1)
        self.meter = tk.Canvas(mf, height=28, bg="#1b1b1b", highlightthickness=0)
        self.meter.grid(row=0, column=0, sticky="ew")
        self.clip_label = tk.Label(mf, text="CLIP", width=5, bg="#3a3a3a", fg="#777777", font=("TkDefaultFont", 10, "bold"))
        self.clip_label.grid(row=0, column=1, padx=(6, 0))
        self.level_text = ttk.Label(mf, text="RMS — dBFS   Peak — dBFS")
        self.level_text.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.test_btn = ttk.Button(mf, text="Test input", command=self.toggle_test)
        self.test_btn.grid(row=1, column=1, pady=(4, 0))

        # Log --------------------------------------------------------
        lf = ttk.LabelFrame(main, text="Log", padding=4)
        lf.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.log_text = tk.Text(lf, height=9, state="disabled", wrap="none", font=("TkFixedFont", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)
        self.settings_widgets = [self.url_entry, self.token_entry, self.headers_btn, self.device_combo, self.refresh_btn,
                                 self.channel_combo, self.rate_combo]

    # ------------------------------------------------------------ settings helpers

    def _update_url_warning(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            self.url_warning.configure(text="")
            return
        try:
            warning = validate_server_url(url)
            self.url_warning.configure(text=f"⚠ {warning}" if warning else "", foreground="#c25e00")
        except ValueError as e:
            self.url_warning.configure(text=str(e), foreground="#b03a2e")

    def _update_headers_label(self) -> None:
        n = len(self.headers)
        self.headers_label.configure(text=f"{n} header{'s' if n != 1 else ''}" if n else "none")

    def _on_gain(self) -> None:
        g = round(float(self.gain_var.get()) * 2) / 2
        self.gain_label.configure(text=f"{g:+.1f} dB")
        if self.client is not None:
            self.client.set_gain_db(g)

    def refresh_devices(self, initial: bool = False) -> None:
        try:
            self.devices = list_input_devices()
        except Exception as e:
            self.devices = []
            log.error("cannot list audio devices: %s", e)
        self.device_combo.configure(values=[d.label for d in self.devices])
        name, api = (self.cfg.device_name, self.cfg.device_hostapi) if initial else self._selected_device_key()
        match = next((d for d in self.devices if d.name == name and d.hostapi == api), None) or next((d for d in self.devices if d.name == name), None)
        if match is not None:
            self.device_combo.current(self.devices.index(match))
        elif self.devices and not name:
            self.device_combo.current(0)
        else:
            self.device_var.set("")
            if name:
                log.warning("saved input device '%s' not found", name)
        self._on_device_change(keep_channel=True)

    def _selected_device(self) -> InputDevice | None:
        i = self.device_combo.current()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def _selected_device_key(self) -> tuple[str, str]:
        d = self._selected_device()
        return (d.name, d.hostapi) if d else (self.cfg.device_name, self.cfg.device_hostapi)

    def _on_device_change(self, keep_channel: bool = False) -> None:
        d = self._selected_device()
        n = d.max_input_channels if d else 1
        self.channel_combo.configure(values=[str(i) for i in range(1, n + 1)])
        try:
            ch = int(self.channel_var.get())
        except ValueError:
            ch = 1
        self.channel_var.set(str(ch if keep_channel and 1 <= ch <= n else min(max(ch, 1), n)))
        self._restart_test_if_running()

    def _collect_config(self) -> Config:
        d = self._selected_device()
        cfg = Config(
            server_url=self.url_var.get().strip(),
            device_name=d.name if d else self.cfg.device_name,
            device_hostapi=d.hostapi if d else self.cfg.device_hostapi,
            channel=int(self.channel_var.get() or 1),
            sample_rate=int(self.rate_var.get() or 16000),
            gain_db=round(float(self.gain_var.get()) * 2) / 2,
            auto_start_stream=bool(self.autostream_var.get()),
            launch_at_login=bool(self.login_var.get()),
            extra_header_names=list(self.cfg.extra_header_names),
        )
        return cfg.normalise()

    def save_settings(self, quiet: bool = False) -> bool:
        cfg = self._collect_config()
        try:
            if cfg.server_url:
                validate_server_url(cfg.server_url)
            set_token(self.token_var.get())
            set_extra_headers(cfg, self.headers)
            save_config(cfg)
        except Exception as e:
            messagebox.showerror("Could not save settings", str(e))
            return False
        self.cfg = cfg
        log.info("settings saved")
        return True

    def edit_headers(self) -> None:
        dlg = HeadersDialog(self.root, dict(self.headers))
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.headers = dlg.result
            self._update_headers_label()

    def toggle_launch_at_login(self) -> None:
        want = bool(self.login_var.get())
        try:
            autostart.set_enabled(want)
        except Exception as e:
            self.login_var.set(not want)
            messagebox.showerror("Launch at login", f"Could not update login item: {e}")
            return
        self.cfg.launch_at_login = want
        try:
            save_config(self._collect_config())
        except Exception:
            log.exception("could not save config")

    # ------------------------------------------------------------ audio

    def _open_capture(self) -> AudioCapture | None:
        d = self._selected_device()
        if d is None:
            messagebox.showerror("No input device", "Select an input device first.")
            return None
        try:
            cap = AudioCapture(d, int(self.channel_var.get() or 1))
            cap.start()
            return cap
        except Exception as e:
            log.error("cannot open input: %s", e)
            messagebox.showerror("Cannot open input", f"{d.name}: {e}")
            return None

    def _close_capture(self) -> None:
        if self.capture is not None:
            self.capture.stop()
            self.capture = None

    def toggle_test(self) -> None:
        if self.testing:
            self.testing = False
            if self.client is None:
                self._close_capture()
            self.test_btn.configure(text="Test input")
            return
        if self.client is not None:
            return  # meter already live while streaming
        self.capture = self._open_capture()
        if self.capture is not None:
            self.testing = True
            self.test_btn.configure(text="Stop test")

    def _restart_test_if_running(self) -> None:
        if self.testing and self.client is None:
            self._close_capture()
            self.capture = self._open_capture()
            if self.capture is None:
                self.testing = False
                self.test_btn.configure(text="Test input")

    # ------------------------------------------------------------ streaming

    def toggle_streaming(self) -> None:
        if self.client is not None:
            self.stop_streaming()
        else:
            self.start_streaming()

    def start_streaming(self) -> None:
        if self.client is not None:
            return
        if not self.save_settings(quiet=True):
            return
        try:
            settings = build_client_settings(self.cfg, token=self.token_var.get().strip(), headers=dict(self.headers))
        except ValueError as e:
            messagebox.showerror("Cannot start", str(e))
            return
        self.testing = False
        self.test_btn.configure(text="Test input")
        self._close_capture()
        self.capture = self._open_capture()
        if self.capture is None:
            return
        self.client = SenderClient(settings, self.capture)
        self.thread = ClientThread(self.client)
        self.thread.start()
        self.stream_btn.configure(text="Stop streaming")
        self.test_btn.state(["disabled"])
        for w in self.settings_widgets:
            w.state(["disabled"])
        log.info("streaming started")

    def stop_streaming(self) -> None:
        if self.thread is not None:
            self.thread.stop()
        self.thread = None
        self.client = None
        self._close_capture()
        self.stream_btn.configure(text="Start streaming")
        self.test_btn.state(["!disabled"])
        for w in self.settings_widgets:
            w.state(["!disabled"])
        for w in (self.device_combo, self.channel_combo, self.rate_combo):
            w.state(["readonly"])
        log.info("streaming stopped")

    # ------------------------------------------------------------ periodic updates

    def _tick_meter(self) -> None:
        try:
            levels = self.capture.meter.read(float(self.gain_var.get())) if self.capture is not None else None
            self._draw_meter(levels, active=self.capture is not None)
        finally:
            self.root.after(50, self._tick_meter)

    def _draw_meter(self, lv: Levels | None, active: bool) -> None:
        c = self.meter
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 20)
        c.delete("all")

        def x_for(db: float) -> float:
            return w * (min(0.0, max(METER_MIN_DB, db)) - METER_MIN_DB) / -METER_MIN_DB

        for db in range(-60, 1, 6):
            x = x_for(db)
            c.create_line(x, h - 5, x, h, fill="#555555")
        now = time.monotonic()
        if lv is not None:
            rms_x = x_for(lv.rms_db)
            color = "#2ecc71" if lv.rms_db < -18 else ("#f1c40f" if lv.rms_db < -6 else "#e74c3c")
            c.create_rectangle(0, 3, rms_x, h - 6, fill=color, width=0)
            if lv.peak_db >= self.peak_hold[0] or now > self.peak_hold[1]:
                self.peak_hold = (lv.peak_db, now + 1.5)
            if lv.clipped:
                self.clip_until = now + 2.0
            self.level_text.configure(text=f"RMS {lv.rms_db:6.1f} dBFS   Peak {lv.peak_db:6.1f} dBFS"
                                      + ("   (digital silence — check Dante subscription)" if lv.peak_db <= -119 else ""))
        elif not active:
            self.level_text.configure(text="RMS — dBFS   Peak — dBFS")
            self.peak_hold = (METER_MIN_DB, 0.0)
        if active and self.peak_hold[0] > METER_MIN_DB:
            px = x_for(self.peak_hold[0])
            c.create_line(px, 2, px, h - 5, fill="white", width=2)
        clipping = now < self.clip_until
        self.clip_label.configure(bg="#e74c3c" if clipping else "#3a3a3a", fg="white" if clipping else "#777777")

    def _tick_status(self) -> None:
        try:
            self._drain_log()
            self._update_status()
        finally:
            self.root.after(250, self._tick_status)

    def _update_status(self) -> None:
        client = self.client
        if client is None:
            self.state_label.configure(text=STATE_LABELS[LinkState.STOPPED], bg=STATE_COLORS[LinkState.STOPPED][0])
            self.status_vars["since"].set("—")
            return
        s = client.snapshot()
        text = s.label
        if s.state == LinkState.LIVE:
            text = "Connected – LIVE (forwarding to captions)"
        elif s.state == LinkState.STANDBY:
            text = "Connected – standby (not live)"
        elif s.state == LinkState.RETRY_WAIT and s.retry_at:
            text = f"Disconnected – retry in {max(0, int(s.retry_at - time.time()))} s"
        bg, fg = STATE_COLORS[s.state]
        self.state_label.configure(text=text, bg=bg, fg=fg)
        self.status_vars["campus"].set(s.campus or "—")
        self.status_vars["since"].set(connected_for(s.connected_since))
        self.status_vars["bytes"].set(f"{s.bytes_sent / 1e6:.2f} MB ({s.frames_sent} frames)")
        self.status_vars["reconnects"].set(str(s.reconnects))
        self.status_vars["error"].set(s.last_error or "—")
        warn = s.warning or ""
        if s.dropped_seconds:
            warn = (warn + "; " if warn else "") + f"{s.dropped_seconds:.1f} s of old audio dropped"
        self.status_vars["warning"].set(warn or "—")
        if s.state == LinkState.REVOKED and self.thread is not None and not self.thread.is_alive():
            self.stop_streaming()
            self.state_label.configure(text="This sender was revoked", bg=STATE_COLORS[LinkState.REVOKED][0])
            messagebox.showerror("Sender revoked", "This sender was revoked. Create a new sender token in the admin dashboard.")

    def _drain_log(self) -> None:
        lines = []
        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", "\n".join(lines) + "\n")
        excess = int(t.index("end-1c").split(".")[0]) - 500
        if excess > 0:
            t.delete("1.0", f"{excess + 1}.0")
        t.configure(state="disabled")
        t.see("end")

    def on_close(self) -> None:
        try:
            self.stop_streaming() if self.client is not None else self._close_capture()
        finally:
            self.root.destroy()


def run_gui(cfg: Config, minimized: bool = False) -> int:
    root = tk.Tk()
    SenderApp(root, cfg)
    if minimized:
        root.iconify()
    root.mainloop()
    return 0
