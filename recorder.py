#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""屏幕录制核心引擎（无 GUI 依赖，供 CLI 与 GUI 复用）。

负责：屏幕采集 (mss)、系统声环回 (soundcard/WASAPI)、ffmpeg 编码与混流。
对外接口：Recorder 类。
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

# Windows: 防止在 GUI (--noconsole) 下启动 ffmpeg 时弹出黑色命令行窗口
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

CODECS = {
    "x265": {
        "label": "H.265 / HEVC（小体积）",
        "args": ["-c:v", "libx265", "-preset", "medium", "-crf", "28", "-tag:v", "hvc1",
                 "-x265-params", "log-level=error"],
        "default_crf": 28,
    },
    "x264": {
        "label": "H.264 / AVC（兼容性好）",
        "args": ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"],
        "default_crf": 23,
    },
    "av1": {
        "label": "AV1（体积最小）",
        "args": ["-c:v", "libsvtav1", "-preset", "6", "-crf", "32"],
        "default_crf": 32,
    },
}


@dataclass
class Settings:
    fps: int = 24
    codec: str = "x265"
    crf: int = None          # None => 使用编码器默认值
    audio: bool = True       # 是否录制系统声音
    monitor: int = 1         # 全屏时的显示器编号
    out: str = field(default_factory=lambda: str(Path(__file__).parent / "recordings"))


def _log(msg):
    if sys.stdout is None:
        return
    try:
        print(msg)
    except Exception:
        pass


def find_ffmpeg():
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg\bin\ffmpeg.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def get_loopback_mic():
    """通过 WASAPI loopback 获取系统声音采集设备，无需开启立体声混音。"""
    try:
        import soundcard as sc
        spk = sc.default_speaker()
        return sc.get_microphone(id=str(spk.name), include_loopback=True)
    except Exception:
        pass
    try:
        import soundcard as sc
        mics = sc.all_microphones(include_loopback=True)
        if mics:
            return mics[0]
    except Exception:
        pass
    return None


class Recorder:
    """线程安全的录制器。start/stop/toggle 可被任意线程调用。"""

    def __init__(self, settings: Settings, ffmpeg: str = None, on_finish=None):
        self.settings = settings
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self.on_finish = on_finish  # 回调 result dict
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self._recording = False
        self.start_time = None
        self.video_thread = None
        self.audio_thread = None
        self.proc = None
        self.mic = None
        self.sct = None
        self.tmp_video = None
        self.tmp_audio = None

    # -- 状态 -------------------------------------------------------------
    @property
    def recording(self):
        return self._recording

    def elapsed(self):
        if not self._recording or self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    # -- 控制 -------------------------------------------------------------
    def toggle(self, region=None):
        with self.lock:
            if self._recording:
                self.stop()
            else:
                self.start(region)

    def start(self, region=None):
        with self.lock:
            if self._recording:
                return
            self._start(region)

    def stop(self):
        with self.lock:
            if not self._recording:
                return
            self._stop()

    # -- 内部 -------------------------------------------------------------
    def _start(self, region):
        if not self.ffmpeg:
            self._emit({"ok": False, "error": "未找到 ffmpeg，请安装并加入 PATH"})
            return

        try:
            import mss
        except ImportError:
            self._emit({"ok": False, "error": "缺少依赖 mss，请安装 requirements.txt"})
            return

        try:
            self.sct = mss.MSS()
        except AttributeError:
            self.sct = mss.mss()

        if region is None:
            idx = self.settings.monitor
            if idx >= len(self.sct.monitors):
                self.sct.close()
                self.sct = None
                self._emit({"ok": False, "error": f"显示器 {idx} 不存在"})
                return
            region = self.sct.monitors[idx]

        w, h = region["width"], region["height"]
        if w <= 0 or h <= 0:
            self.sct.close()
            self.sct = None
            self._emit({"ok": False, "error": "录制区域无效"})
            return
        self.region = region

        self.stop_event.clear()
        tmpdir = tempfile.gettempdir()
        tag = f"sr_{os.getpid()}_{int(time.time() * 1000)}"
        self.tmp_video = os.path.join(tmpdir, tag + ".mp4")
        self.tmp_audio = os.path.join(tmpdir, tag + ".wav")

        codec = CODECS[self.settings.codec]
        crf = self.settings.crf if self.settings.crf is not None else codec["default_crf"]

        cmd = [
            self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgra",
            "-s", f"{w}x{h}", "-r", str(self.settings.fps), "-i", "-",
            "-an",
        ] + list(codec["args"])
        for i, a in enumerate(cmd):
            if a == "-crf":
                cmd[i + 1] = str(crf)
        cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", self.tmp_video]

        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         creationflags=_CREATE_NO_WINDOW)
        except Exception as e:
            self.sct.close()
            self.sct = None
            self._emit({"ok": False, "error": f"无法启动 ffmpeg: {e}"})
            return

        self.mic = get_loopback_mic() if self.settings.audio else None
        self.start_time = time.time()
        self._recording = True
        self.video_thread = threading.Thread(target=self._capture_video, daemon=True)
        self.audio_thread = threading.Thread(target=self._capture_audio, daemon=True)
        self.video_thread.start()
        self.audio_thread.start()
        _log(f"[录制中] {w}x{h} @ {self.settings.fps}fps, {self.settings.codec}/crf{crf}")

    def _stop(self):
        self._recording = False
        self.stop_event.set()
        if self.video_thread:
            self.video_thread.join(timeout=10)
        if self.audio_thread:
            self.audio_thread.join(timeout=10)
        self._finalize()

    def _capture_video(self):
        interval = 1.0 / self.settings.fps
        try:
            while not self.stop_event.is_set():
                t0 = time.perf_counter()
                try:
                    shot = self.sct.grab(self.region)
                    self.proc.stdin.write(shot.raw)
                except (BrokenPipeError, OSError):
                    break
                elapsed = time.perf_counter() - t0
                time.sleep(max(0.0, interval - elapsed))
        finally:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=15)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    def _capture_audio(self):
        if self.mic is None:
            return
        frames = []
        try:
            with self.mic.recorder(samplerate=48000, channels=2) as rec:
                while not self.stop_event.is_set():
                    frames.append(rec.record(numframes=480))
        except Exception:
            pass
        if not frames:
            return
        try:
            audio = np.concatenate(frames, axis=0)
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            with wave.open(self.tmp_audio, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                wf.writeframes(pcm.tobytes())
        except Exception:
            pass

    def _finalize(self):
        try:
            if self.sct:
                self.sct.close()
        except Exception:
            pass
        self.sct = None

        outdir = Path(self.settings.out)
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._emit({"ok": False, "error": f"无法创建输出目录: {e}"})
            return

        final = outdir / ("rec_{}.mp4".format(datetime.now().strftime("%Y%m%d_%H%M%S")))

        has_video = os.path.isfile(self.tmp_video) and os.path.getsize(self.tmp_video) > 0
        has_audio = os.path.isfile(self.tmp_audio) and os.path.getsize(self.tmp_audio) > 0

        if not has_video:
            self._emit({"ok": False, "error": "未捕获到视频帧，已放弃本次录制"})
            self._cleanup_tmp()
            return

        if has_audio:
            cmd = [
                self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                "-i", self.tmp_video, "-i", self.tmp_audio,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(final),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=_CREATE_NO_WINDOW)
            if r.returncode != 0:
                _log(f"[警告] 混流失败，仅保留视频: {r.stderr.strip()}")
                shutil.move(self.tmp_video, str(final))
        else:
            shutil.move(self.tmp_video, str(final))

        size_mb = os.path.getsize(final) / (1024 * 1024)
        _log(f"[完成] {final}  {size_mb:.1f} MB")
        self._emit({"ok": True, "path": str(final), "size_mb": size_mb, "audio": has_audio})
        self._cleanup_tmp()

    def _cleanup_tmp(self):
        for tmp in (self.tmp_video, self.tmp_audio):
            try:
                if tmp and os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _emit(self, result):
        if self.on_finish:
            try:
                self.on_finish(result)
            except Exception:
                pass
