#!/usr/bin/env python3
"""Tkinter GUI wrapper for pixivdownload.py / download_all.py.

Features:
- Start / Stop buttons
- AI filter checkbox (switches between the two backend scripts)
- Progress bar (parses "[i/N] Downloading ..." lines from stdout)
- Scrolling log area
- No extra dependencies (stdlib only)
"""

import os
import re
import sys
import threading
import subprocess
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FILTERED_SCRIPT = os.path.join(SCRIPT_DIR, "pixivdownload.py")
ALL_SCRIPT = os.path.join(SCRIPT_DIR, "download_all.py")

# Progress line: "[12/345] Downloading 12345678 (3p) - title..."
PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]\s+Downloading\s+(\d+)")
# Actual download count after dedup: "Already downloaded: X, remaining: N"
TOTAL_RE = re.compile(r"remaining:\s+(\d+)")


class PixivDownloaderGUI:
    def __init__(self, root):
        self.root = root
        root.title("Pixiv 收藏夹下载器")
        root.geometry("720x520")

        self.proc = None
        self.reader_thread = None
        self.msg_queue = queue.Queue()
        self.total = 0
        self.current = 0
        self.success = 0
        self.failed = 0

        self._build_ui()
        self.root.after(100, self._drain_queue)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        self.filter_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text="过滤 AI 生成作品", variable=self.filter_var
        ).pack(side=tk.LEFT)

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

    def start(self):
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
        self._log(f"\n=== 启动 {os.path.basename(script)} ===\n")
        self.status_var.set("运行中...")

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        # Line-buffered subprocess
        self.proc = subprocess.Popen(
            [sys.executable, "-u", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
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
    root.mainloop()


if __name__ == "__main__":
    main()
