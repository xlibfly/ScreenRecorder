#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快捷屏幕录制 - 可视化界面 (Tkinter)。入口：python app.py"""

import ctypes
import os
import queue
import sys
import threading
from pathlib import Path

# PyInstaller --noconsole 模式下 stdout/stderr 为 None，重定向避免 print 崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from recorder import Recorder, Settings, CODECS, find_ffmpeg

HOTKEY = "f9"


def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("快捷屏幕录制")
        self.root.resizable(False, False)

        self.msg_q = queue.Queue()
        self.region = None  # None => 全屏；dict => 自定义区域

        self.ffmpeg = find_ffmpeg()
        self.settings = Settings(out=str(Path(__file__).parent / "recordings"))
        self.recorder = Recorder(
            self.settings,
            ffmpeg=self.ffmpeg,
            on_finish=lambda r: self.msg_q.put(("finish", r)),
        )

        self._build_ui()
        self._register_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()

    # -- UI ---------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        # 标题
        ttk.Label(main, text="快捷屏幕录制", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")

        # 状态栏
        self.status_var = tk.StringVar(value="空闲")
        status_bar = ttk.Frame(main)
        status_bar.pack(fill="x", pady=(6, 8))
        self.status_dot = tk.Label(status_bar, text="●", fg="#999", font=("", 12))
        self.status_dot.pack(side="left")
        ttk.Label(status_bar, textvariable=self.status_var, font=("Microsoft YaHei UI", 10)).pack(side="left", padx=4)
        ttk.Label(status_bar, text=f"热键 {HOTKEY.upper()}", foreground="#888").pack(side="right")

        # 设置面板
        box = ttk.LabelFrame(main, text="录制设置", padding=10)
        box.pack(fill="x")

        # 帧率
        row = ttk.Frame(box)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="帧率", width=12).pack(side="left")
        self.fps_var = tk.StringVar(value="24")
        ttk.Combobox(row, textvariable=self.fps_var, width=8, state="readonly",
                     values=("10", "15", "20", "24", "30", "60")).pack(side="left")
        ttk.Label(row, text="fps", foreground="#888").pack(side="left", padx=6)

        # 编码器
        row = ttk.Frame(box)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="编码器", width=12).pack(side="left")
        self.codec_var = tk.StringVar(value="x265")
        cb = ttk.Combobox(row, textvariable=self.codec_var, width=26, state="readonly",
                          values=[f"{k} - {v['label']}" for k, v in CODECS.items()])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self._on_codec_change)

        # 质量 CRF
        row = ttk.Frame(box)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="质量 CRF", width=12).pack(side="left")
        self.crf_var = tk.StringVar(value=str(CODECS["x265"]["default_crf"]))
        ttk.Spinbox(row, from_=0, to=51, textvariable=self.crf_var, width=8).pack(side="left")
        ttk.Label(row, text="越小越清晰、文件越大", foreground="#888").pack(side="left", padx=6)

        # 系统声
        row = ttk.Frame(box)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="录制系统声", width=12).pack(side="left")
        self.audio_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, variable=self.audio_var).pack(side="left")

        # 输出目录
        row = ttk.Frame(box)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="输出目录", width=12).pack(side="left")
        self.out_var = tk.StringVar(value=self.settings.out)
        ttk.Entry(row, textvariable=self.out_var, width=32).pack(side="left")
        ttk.Button(row, text="浏览", width=6, command=self._browse_out).pack(side="left", padx=6)

        # 区域
        row = ttk.Frame(box)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="录制区域", width=12).pack(side="left")
        self.region_var = tk.IntVar(value=0)
        ttk.Radiobutton(row, text="全屏", variable=self.region_var, value=0,
                        command=self._on_region_change).pack(side="left")
        ttk.Radiobutton(row, text="自定义", variable=self.region_var, value=1,
                        command=self._on_region_change).pack(side="left", padx=8)
        self.select_btn = ttk.Button(row, text="框选区域", width=10, state="disabled",
                                     command=self._select_region)
        self.select_btn.pack(side="left", padx=6)
        self.region_label_var = tk.StringVar(value="未选择")
        ttk.Label(row, textvariable=self.region_label_var, foreground="#888").pack(side="left")

        # 控制按钮
        self.btn = tk.Button(main, text="开始录制 (F9)", font=("Microsoft YaHei UI", 12, "bold"),
                             bg="#e74c3c", fg="white", activebackground="#c0392b",
                             activeforeground="white", relief="flat", cursor="hand2",
                             padx=20, pady=8, command=self._toggle)
        self.btn.pack(fill="x", pady=(10, 4))

        # 结果提示
        self.result_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.result_var, foreground="#27ae60",
                  wraplength=380).pack(anchor="w")

        if not self.ffmpeg:
            self.result_var.set("警告：未找到 ffmpeg，请安装并加入 PATH")

    # -- 事件处理 ---------------------------------------------------------
    def _on_codec_change(self, _event=None):
        key = self.codec_var.get().split(" - ")[0]
        self.crf_var.set(str(CODECS[key]["default_crf"]))

    def _on_region_change(self):
        self.select_btn.configure(state="normal" if self.region_var.get() == 1 else "disabled")

    def _browse_out(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or str(Path.home()))
        if d:
            self.out_var.set(d)

    def _select_region(self):
        top = tk.Toplevel(self.root)
        top.attributes("-fullscreen", True)
        top.attributes("-alpha", 0.35)
        top.attributes("-topmost", True)
        top.configure(bg="black")
        canvas = tk.Canvas(top, cursor="cross", bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        st = {"start": None, "rect": None, "result": None}

        def on_press(e):
            st["start"] = (e.x, e.y)

        def on_drag(e):
            if st["start"] is None:
                return
            if st["rect"] is not None:
                canvas.delete(st["rect"])
            x0, y0 = st["start"]
            st["rect"] = canvas.create_rectangle(x0, y0, e.x, e.y, outline="red", width=2)

        def on_release(e):
            x0, y0 = st["start"]
            x1, y1 = e.x, e.y
            left, top = min(x0, x1), min(y0, y1)
            st["result"] = {"left": left, "top": top, "width": abs(x1 - x0), "height": abs(y1 - y0)}
            top.destroy()

        def on_cancel(_e):
            top.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        top.bind("<Escape>", on_cancel)
        top.focus_force()
        self.root.wait_window(top)

        r = st["result"]
        if r and r["width"] >= 2 and r["height"] >= 2:
            self.region = r
            self.region_label_var.set(f"{r['width']}x{r['height']} @ ({r['left']},{r['top']})")
        else:
            self.region_label_var.set("未选择")

    def _current_region(self):
        if self.region_var.get() == 1:
            return self.region
        return None

    def _toggle(self):
        if self.recorder.recording:
            self.recorder.stop()
        else:
            self._apply_settings()
            if self.region_var.get() == 1 and not self.region:
                messagebox.showwarning("提示", "请先点击「框选区域」选择要录制的区域")
                return
            self.recorder.start(self._current_region())

    def _apply_settings(self):
        try:
            self.settings.fps = int(self.fps_var.get())
            self.settings.crf = int(self.crf_var.get())
        except ValueError:
            messagebox.showerror("错误", "帧率 / CRF 必须是数字")
            return
        key = self.codec_var.get().split(" - ")[0]
        self.settings.codec = key
        self.settings.audio = self.audio_var.get()
        self.settings.out = self.out_var.get().strip() or self.settings.out

    def _register_hotkey(self):
        try:
            import keyboard
            keyboard.add_hotkey(HOTKEY, lambda: self.msg_q.put(("hotkey", None)))
        except Exception:
            self.result_var.set("提示：全局热键注册失败，仍可用按钮控制")

    # -- 主循环 -----------------------------------------------------------
    def _tick(self):
        try:
            while True:
                kind, data = self.msg_q.get_nowait()
                if kind == "hotkey":
                    self._toggle()
                elif kind == "finish":
                    self._show_result(data)
        except queue.Empty:
            pass

        if self.recorder.recording:
            el = self.recorder.elapsed()
            self.status_dot.configure(fg="#e74c3c")
            self.status_var.set(f"录制中  {self._fmt(el)}")
            self.btn.configure(text="停止录制 (F9)", bg="#27ae60", activebackground="#1e8449")
        else:
            self.status_dot.configure(fg="#999")
            self.status_var.set("空闲")
            self.btn.configure(text="开始录制 (F9)", bg="#e74c3c", activebackground="#c0392b")

        self.root.after(200, self._tick)

    def _show_result(self, r):
        if r.get("ok"):
            self.result_var.set(f"已保存：{r['path']}\n大小 {r['size_mb']:.1f} MB"
                                + ("（含系统声）" if r.get("audio") else ""))
        else:
            self.result_var.set(f"失败：{r.get('error')}")
            messagebox.showerror("录制失败", r.get("error", ""))

    @staticmethod
    def _fmt(sec):
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _on_close(self):
        self.recorder.stop()
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()


def main():
    set_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
