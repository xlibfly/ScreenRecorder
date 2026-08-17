#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快捷屏幕录制 - 命令行版（F9 开始/停止），复用 recorder 引擎。

用法:
    python screen_recorder.py
    python screen_recorder.py --region W H X Y
    python screen_recorder.py --fps 30 --codec x264
"""

import argparse
import sys
import time
from pathlib import Path

from recorder import Recorder, Settings, CODECS, find_ffmpeg

HOTKEY = "f9"


def parse_args():
    p = argparse.ArgumentParser(description="快捷屏幕录制工具 (F9 开始/停止)")
    p.add_argument("--region", nargs=4, type=int, metavar=("W", "H", "X", "Y"),
                   help="区域录制: 宽 高 左上角X 左上角Y")
    p.add_argument("--monitor", type=int, default=1, help="显示器编号 (默认 1 = 主屏)")
    p.add_argument("--fps", type=int, default=24, help="帧率 (默认 24)")
    p.add_argument("--codec", choices=list(CODECS), default="x265",
                   help="编码器: x265(默认,小体积) / x264(兼容) / av1(最小)")
    p.add_argument("--crf", type=int, default=None, help="质量系数，越小越清晰越大")
    p.add_argument("--no-audio", action="store_true", help="不录制系统声音")
    p.add_argument("--out", default=str(Path(__file__).parent / "recordings"),
                   help="输出目录")
    return p.parse_args()


def main():
    args = parse_args()

    if not find_ffmpeg():
        print("[错误] 未找到 ffmpeg，请安装并加入 PATH，或放到 C:\\ffmpeg\\bin")
        sys.exit(1)

    region = None
    if args.region:
        w, h, x, y = args.region
        region = {"left": x, "top": y, "width": w, "height": h}

    settings = Settings(fps=args.fps, codec=args.codec, crf=args.crf,
                        audio=not args.no_audio, monitor=args.monitor, out=args.out)

    def on_finish(r):
        if r.get("ok"):
            print(f"[完成] {r['path']}  {r['size_mb']:.1f} MB")
        else:
            print(f"[失败] {r.get('error')}")

    recorder = Recorder(settings, on_finish=on_finish)

    try:
        import keyboard
    except ImportError:
        print("[错误] 缺少依赖 keyboard，请先 pip install -r requirements.txt")
        sys.exit(1)

    keyboard.add_hotkey(HOTKEY, lambda: recorder.toggle(region))

    print("=" * 56)
    print("  快捷屏幕录制工具 (命令行版)")
    print(f"  热键: F9 开始/停止    Ctrl+C 退出")
    print(f"  输出: {args.out}")
    print("=" * 56)
    print("等待中，按 F9 开始录制...")

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n退出...")
    finally:
        recorder.stop()
        try:
            keyboard.unhook_all()
        except Exception:
            pass


if __name__ == "__main__":
    main()
