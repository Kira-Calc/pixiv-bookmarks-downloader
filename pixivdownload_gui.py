#!/usr/bin/env python3
"""Tkinter GUI wrapper for pixivdownload.py / download_all.py.

Features:
- UID + output directory inputs persisted to ~/.pixiv_bookmarks_downloader.json
- AI filter / full scan checkboxes
- Progress bar (parses "[i/N] Downloading ..." lines from stdout)
- Scrolling log area
- No extra dependencies (stdlib only)
"""

import json
import os
import re
import sys
import threading
import subprocess
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FILTERED_SCRIPT = os.path.join(SCRIPT_DIR, "pixivdownload.py")
ALL_SCRIPT = os.path.join(SCRIPT_DIR, "download_all.py")
CONFIG_PATH = os.path.expanduser("~/.pixiv_bookmarks_downloader.json")
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Pictures/pixiv_bookmarks")

# Progress line: "[12/345] Downloading 12345678 (3p) - title..."
PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]\s+Downloading\s+(\d+)")
# Actual download count after dedup: "Already downloaded: X, remaining: N"
TOTAL_RE = re.compile(r"remaining:\s+(\d+)")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class PixivDownloaderGUI:
    def __init__(self, root):
        self.root = root
        root.title("Pixiv 收藏夹下载器")
        root.geometry("760x600")

        self.proc = None
        self.reader_thread = None
        self.msg_queue = queue.Queue()
        self.total = 0
        self.current = 0
        self.success = 0
        self.failed = 0

        cfg = load_config()
        self.uid_var = tk.StringVar(value=cfg.get("uid", ""))
        self.outdir_var = tk.StringVar(value=cfg.get("output_dir", DEFAULT_OUTPUT_DIR))
        self.filter_var = tk.BooleanVar(value=cfg.get("filter_ai", True))
        self.full_scan_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.root.after(100, self._drain_queue)

    def _build_ui(self):
        # ---- config row 1: UID ----
        cfg_frame = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        cfg_frame.pack(fill=tk.X)

        ttk.Label(cfg_frame, text="Pixiv UID:", width=12).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(cfg_frame, textvariable=self.uid_var, width=20).grid(
            row=0, column=1, sticky=tk.W, padx=(0, 8)
        )
        ttk.Label(
            cfg_frame,
            text="（登录 Pixiv 后访问个人主页，URL 中的数字即为 UID）",
            foreground="gray",
        ).grid(row=0, column=2, sticky=tk.W)

        # ---- config row 2: output dir ----
        ttk.Label(cfg_frame, text="保存路径:", width=12).grid(
            row=1, column=0, sticky=tk.W, pady=(6, 0)
        )
        ttk.Entry(cfg_frame, textvariable=self.outdir_var, width=50).grid(
            row=1, column=1, columnspan=2, sticky=tk.EW, padx=(0, 8), pady=(6, 0)
        )
        ttk.Button(cfg_frame, text="浏览…", command=self._browse_outdir).grid(
            row=1, column=3, sticky=tk.W, pady=(6, 0)
        )
        cfg_frame.columnconfigure(2, weight=1)

        # ---- control row: checkboxes + start/stop ----
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Checkbutton(
            top, text="过滤 AI 生成作品", variable=self.filter_var
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            top, text="完整扫描（补漏）", variable=self.full_scan_var
        ).pack(side=tk.LEFT, padx=(10, 0))

        self.start_btn = ttk.Button(top, text="开始下载", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=10)
        self.stop_btn = ttk.Button(
            top, text="停止", command=self.stop, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT)

        # Progress bar
        prog_frame = ttk.Frame(self.root, padding=(10, 0))
        prog_frame.pack(fill=tk.X)
        self.progress = ttk.Progressbar(
            prog_frame, mode="determinate", length=400
        )
        self.progress.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self.progress_label = ttk.Label(prog_frame, text="0 / 0", width=16)
        self.progress_label.pack(side=tk.LEFT, padx=(10, 0))

        # Status line
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 5)).pack(
            anchor=tk.W
        )

        # Log area
        log_frame = ttk.Frame(self.root, padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log = scrolledtext.ScrolledText(
            log_frame, height=18, state=tk.DISABLED, font=("Menlo", 11)
        )
        self.log.pack(fill=tk.BOTH, expand=True)

    # ---- control ----

    def _browse_outdir(self):
        initial = self.outdir_var.get() or DEFAULT_OUTPUT_DIR
        if not os.path.isdir(initial):
            initial = os.path.expanduser("~")
        chosen = filedialog.askdirectory(initialdir=initial, title="选择保存路径")
        if chosen:
            self.outdir_var.set(chosen)

    def _persist_config(self):
        save_config({
            "uid": self.uid_var.get().strip(),
            "output_dir": self.outdir_var.get().strip(),
            "filter_ai": bool(self.filter_var.get()),
        })

    def start(self):
        uid = self.uid_var.get().strip()
        outdir = self.outdir_var.get().strip()
        if not uid.isdigit():
            messagebox.showerror("配置错误", "请输入有效的 Pixiv UID（纯数字）")
            return
        if not outdir:
            messagebox.showerror("配置错误", "请选择保存路径")
            return
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("配置错误", f"无法创建保存路径：{e}")
            return

        self._persist_config()

        script = FILTERED_SCRIPT if self.filter_var.get() else ALL_SCRIPT
        if not os.path.exists(script):
            self._log(f"错误：找不到 {script}\n")
            return

        self.total = 0
        self.current = 0
        self.success = 0
        self.failed = 0
        self.progress["value"] = 0
        self.progress["maximum"] = 100
        self.progress_label.config(text="0 / 0")
        self._log(f"\n=== 启动 {os.path.basename(script)} (UID={uid}) ===\n")
        self.status_var.set("运行中...")

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        cmd = [sys.executable, "-u", script]
        if self.full_scan_var.get():
            cmd.append("--full")

        env = os.environ.copy()
        env["PIXIV_UID"] = uid
        env["PIXIV_OUTPUT_DIR"] = outdir

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.status_var.set("已停止")
            self._log("\n[用户中止]\n")

    # ---- IO ----

    def _read_output(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self.msg_queue.put(("line", line))
        self.proc.wait()
        self.msg_queue.put(("done", self.proc.returncode))

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "line":
                    self._handle_line(payload)
                elif kind == "done":
                    self._handle_done(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _handle_line(self, line: str):
        self._log(line)

        m = TOTAL_RE.search(line)
        if m:
            self.total = int(m.group(1))
            self.progress["maximum"] = max(self.total, 1)
            self.progress_label.config(text=f"0 / {self.total}")

        m = PROGRESS_RE.search(line)
        if m:
            self.current = int(m.group(1))
            page_total = int(m.group(2))
            if self.total == 0:
                self.total = page_total
                self.progress["maximum"] = page_total
            self.progress["value"] = self.current
            self.progress_label.config(text=f"{self.current} / {self.total}")
            self.status_var.set(f"下载中：{m.group(3)}")

        if "OK (" in line:
            self.success += 1
        elif line.strip().endswith("FAILED"):
            self.failed += 1

    def _handle_done(self, returncode: int):
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set(
            f"完成 — 成功 {self.success}，失败 {self.failed}（退出码 {returncode}）"
        )
        self._log(f"\n=== 进程结束，退出码 {returncode} ===\n")

    def _log(self, text: str):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    PixivDownloaderGUI(root)
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    root.focus_force()
    # macOS: 用自身 pid 让 NSRunningApplication 把窗口拉到最前
    if sys.platform == "darwin":
        try:
            subprocess.Popen([
                "osascript", "-e",
                f'tell application "System Events" to set frontmost of '
                f'(first process whose unix id is {os.getpid()}) to true',
            ])
        except Exception:
            pass
    root.mainloop()


if __name__ == "__main__":
    import traceback
    crash_log = os.path.join(SCRIPT_DIR, "gui_crash.log")
    try:
        with open(crash_log, "a") as f:
            f.write(f"\n==== START {__import__('datetime').datetime.now()} ====\n")
            f.write(f"sys.executable: {sys.executable}\n")
            f.write(f"sys.version: {sys.version}\n")
            f.write(f"cwd: {os.getcwd()}\n")
            f.flush()
        main()
        with open(crash_log, "a") as f:
            f.write(f"==== mainloop exited cleanly {__import__('datetime').datetime.now()} ====\n")
    except Exception:
        with open(crash_log, "a") as f:
            f.write("==== EXCEPTION ====\n")
            traceback.print_exc(file=f)
            f.write(f"==== END {__import__('datetime').datetime.now()} ====\n")
        raise
