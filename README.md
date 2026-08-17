# ScreenRecorder 快捷屏幕录制

一个本地屏幕录制小工具：全局热键 `F9` 一键开始/停止，输出 **H.265 小体积 mp4**，可选录制系统声音。

## 功能

- 全局热键 `F9` 开始 / 停止，录制期间再按一次即停止
- 默认 H.265 (HEVC) 编码，体积约为 H.264 的一半；可选 H.264 / AV1
- 系统声音录制（WASAPI 环回，无需开启"立体声混音"）
- 全屏或自定义区域录制（鼠标框选）
- 可视化界面（Tkinter）与命令行两种用法
- 录制结果自动存入 `recordings/`，文件名带时间戳

## 快速开始

### 方式一：直接运行 exe（无需安装 Python）

1. 确保系统已安装 [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) 并加入 PATH（或放到 `C:\ffmpeg\bin`）
2. 双击 `ScreenRecorder.exe`
3. 按 `F9` 开始 / 停止，或点击界面按钮

> exe 需自行打包生成，见下方「打包」一节。

### 方式二：从源码运行（命令行版）

```bash
pip install -r requirements.txt
python screen_recorder.py            # 全屏，F9 开始/停止
python screen_recorder.py --region W H X Y   # 指定区域
```

### 方式三：从源码运行（界面版）

```bash
pip install -r requirements.txt
python app.py
```

## 界面设置

| 选项 | 说明 |
|------|------|
| 帧率 | 10 / 15 / 20 / 24 / 30 / 60，默认 24 |
| 编码器 | H.265（小体积）/ H.264（兼容性好）/ AV1（最小） |
| 质量 CRF | 越小越清晰、文件越大，默认随编码器自动调整 |
| 录制系统声 | 开启后同步录制系统播放的声音 |
| 输出目录 | 录制文件保存位置 |
| 录制区域 | 全屏 / 自定义（鼠标框选） |

## 命令行参数（`screen_recorder.py`）

```
--region W H X Y   区域录制：宽 高 左上角X 左上角Y
--monitor N        显示器编号（默认 1 = 主屏）
--fps N            帧率（默认 24）
--codec {x265,x264,av1}   编码器
--crf N            质量系数，越小越清晰越大
--no-audio         不录制系统声音
--out DIR          输出目录
```

## 打包为 exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name ScreenRecorder app.py
```

生成文件在 `dist\ScreenRecorder.exe`。

## 依赖

- Python 3.9+
- [ffmpeg](https://www.gyan.dev/ffmpeg/builds/)（需包含 `libx265` / `libx264` / `libsvtav1`）
- Python 包：`mss`、`soundcard`、`keyboard`、`numpy`（见 `requirements.txt`）

## 文件结构

```
ScreenRecorder/
├── app.py               # 可视化界面入口
├── recorder.py          # 录制核心引擎（抓屏 + 系统声 + ffmpeg 编码）
├── screen_recorder.py   # 命令行入口
├── requirements.txt     # Python 依赖
├── run.bat              # 一键启动命令行版
└── ScreenRecorder.spec  # PyInstaller 打包配置
```
