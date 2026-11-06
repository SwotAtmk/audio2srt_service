# audio2srt_service

把音频/视频转换成 SRT 字幕的 HTTP 服务。转写基于 **openai-whisper**，
用 FastAPI 提供上传、异步任务、状态查询与 SRT 下载接口。

本仓库的实现参考了桌面端项目 `audio2srt` 的核心链路（ffmpeg 处理、Whisper 转写、
SRT 生成、模型档位与输出命名），去掉了 PySide6 界面与 Qt 线程，改成适合服务端部署的分层结构。

- 技术栈：Python 3.12 / FastAPI / uvicorn / openai-whisper / ffmpeg
- 默认地址：`http://127.0.0.1:8000`，Swagger 文档：`/docs`

## 核心能力

- **音频与视频统一处理**：mp3、wav、m4a、flac、mp4、mov、mkv 等格式统一经 ffmpeg
  转成 16 kHz 单声道 WAV 后送 Whisper。
- **两个模型档位**：`large-v3-turbo`（极速版，默认）、`large-v3`（专业版）。
- **模型单例复用**：模型加载一次后常驻内存，避免每个请求重复加载；同时按模型维度
  加推理锁，保证并发请求下的安全。
- **异步任务 + 轮询**：上传立即返回 `task_id`（202），转写在后台线程池执行，
  长音频不会撑爆 HTTP 超时；任务元信息落盘，重启后仍可查询。
- **SRT 命名规则**：默认用输入文件名 + `.srt`；重名时自动追加 6 位随机字符。
- **统一错误码**：不支持格式、ffmpeg 缺失、模型未下载、转写失败等都有明确
  HTTP 状态码与 `error.code`。
- **健康检查与配置查询**：`/health`、`/api/v1/config`、`/api/v1/models`。

## 目录结构

```
audio2srt_service/
├── main.py                        # 启动入口：python main.py
├── scripts/
│   ├── start.sh                   # 启动包装（写 pid 文件，可选复用外部 whisper 环境）
│   └── stop.sh                    # 按 data/server.pid 停止服务
├── app/
│   ├── main.py                    # FastAPI 应用、异常处理、生命周期
│   ├── api/
│   │   ├── transcriptions.py      # 上传 / 查询 / 下载
│   │   └── system.py              # 健康检查 / 配置 / 模型信息
│   ├── core/
│   │   ├── config.py              # 环境变量配置
│   │   ├── errors.py              # 错误码与统一异常
│   │   ├── ffmpeg.py              # ffmpeg 定位与音频归一化
│   │   └── formats.py             # 支持的扩展名
│   ├── schemas/
│   │   ├── task.py                # 任务模型与响应
│   │   └── system.py              # 系统接口响应
│   └── services/
│       ├── pipeline.py            # 上传落盘、排队、后台执行
│       ├── model_manager.py       # 模型路径 / 单例缓存 / 推理锁
│       ├── transcriber.py         # openai-whisper 封装
│       ├── audio_extractor.py     # 格式校验与音频准备
│       ├── srt_writer.py          # SRT 渲染与输出命名
│       └── task_store.py          # 内存索引 + JSON 落盘
├── tests/                         # pytest 测试
├── data/                          # 运行时数据（自动创建，已 gitignore）
├── requirements.txt
├── LICENSE
└── README.md
```

完整的接口参数、请求/响应示例、错误码表与设计取舍见
[接口文档](2026-11-06/audio2srt-api/outputs/audio2srt-api.md)。

## 快速开始

### 1. 环境要求

- Python 3.11+（本项目在 3.12 上验证）
- ffmpeg（macOS: `brew install ffmpeg`；Ubuntu: `sudo apt install ffmpeg`）
- 至少一个 Whisper 模型文件（见第 3 步）

### 2. 安装依赖

```bash
cd audio2srt_service
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

`openai-whisper` 会一并安装 torch，首次安装体积较大（本机 venv 约 1 GB）。

### 3. 准备模型

模型默认放在 `~/.audio2srt/models`，服务不会自动下载：

```bash
mkdir -p ~/.audio2srt/models

# 极速版 large-v3-turbo（约 1.5 GB）
curl -L -o ~/.audio2srt/models/large-v3-turbo.pt \
  https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt
```

专业版 `large-v3`（约 2.9 GB）按需下载，地址见接口文档 2.3 节。

### 4. 启动

```bash
python main.py
# 浏览器打开 http://127.0.0.1:8000/docs
```

后台常驻：

```bash
nohup python main.py --host 127.0.0.1 --port 8000 > data/server.log 2>&1 &
echo $! > data/server.pid

kill $(cat data/server.pid)    # 停止
# 或：scripts/stop.sh
```

### 启动参数与环境变量

| 参数 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--host` | `HOST` | `127.0.0.1` | 监听地址，局域网访问用 `0.0.0.0` |
| `--port` | `PORT` | `8000` | 监听端口 |
| `--reload` | `AUDIO2SRT_RELOAD` | 关闭 | 开发热重载 |
| — | `AUDIO2SRT_LOG_LEVEL` | `info` | 日志级别 |
| — | `AUDIO2SRT_MODEL_DIR` | `~/.audio2srt/models` | 模型目录 |
| — | `AUDIO2SRT_DATA_DIR` | `<项目根>/data` | 运行时数据目录 |
| — | `AUDIO2SRT_DEFAULT_MODEL` | `large-v3-turbo` | 默认模型 |
| — | `AUDIO2SRT_MAX_UPLOAD_MB` | `500` | 上传大小上限 |
| — | `AUDIO2SRT_MAX_WORKERS` | `1` | 后台转写并发数 |
| — | `AUDIO2SRT_MODEL_DEVICE` | 自动 | `cpu` / `cuda` |
| — | `AUDIO2SRT_KEEP_UPLOADS` | `false` | 是否保留上传文件 |
| — | `FFMPEG_PATH` | 自动查找 | 指定 ffmpeg 可执行文件 |
| — | `FFPROBE_PATH` | 自动查找 | 指定 ffprobe |

ffmpeg 查找优先级：`FFMPEG_PATH` → 项目内置 `assets/ffmpeg/{mac,win,linux}` → 系统 `PATH`。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查（ffmpeg、模型目录、已加载模型） |
| `GET` | `/api/v1/config` | 服务配置与支持的格式 |
| `GET` | `/api/v1/models` | 模型下载/加载状态 |
| `POST` | `/api/v1/transcriptions` | 上传音/视频创建转写任务（202） |
| `GET` | `/api/v1/transcriptions` | 任务列表 |
| `GET` | `/api/v1/transcriptions/{task_id}` | 查询状态与结果 |
| `GET` | `/api/v1/transcriptions/{task_id}/srt` | 下载 SRT |

最小调用示例：

```bash
# 创建任务
curl -X POST http://127.0.0.1:8000/api/v1/transcriptions \
  -F "file=@demo.mp3" \
  -F "model=large-v3-turbo"

# 查询（task_id 来自上一步响应）
curl http://127.0.0.1:8000/api/v1/transcriptions/<task_id>

# 下载
curl -OJ http://127.0.0.1:8000/api/v1/transcriptions/<task_id>/srt
```

- 任务状态：`queued → extracting → transcribing → writing → completed / failed`
- 进度为阶段式（`0/5/15/95/100`）：openai-whisper 不提供转写中的细粒度回调
- 详细参数、响应示例与错误码：[接口文档](2026-11-06/audio2srt-api/outputs/audio2srt-api.md)

## 测试

```bash
pytest tests -v
```

测试覆盖 SRT 渲染与命名、上传校验、模型未下载、失败任务记录、下载状态等；
默认用替身实现，不需要真实模型即可运行。

## 常见问题

**Q: 启动报 `FFMPEG_NOT_FOUND`？**
安装 ffmpeg 或设置 `FFMPEG_PATH`；`/health` 会显示当前使用的 ffmpeg 路径与版本。

**Q: 上传返回 409 `MODEL_NOT_DOWNLOADED`？**
对应模型文件不在模型目录中，按第 3 步下载到 `~/.audio2srt/models`。

**Q: 上传返回 415 `UNSUPPORTED_FORMAT`？**
仅接受白名单扩展名，完整列表见 `/api/v1/config` 的
`supported_audio_formats` / `supported_video_formats`。

**Q: 为什么转写进度一直停在 15？**
openai-whisper 的 `transcribe()` 是同步阻塞调用，没有逐段进度回调；服务用阶段式进度，
转写期间不会变化，完成后直接到 100。长音频请用轮询并适当放宽间隔。

**Q: 第一次转写特别慢？**
首次请求包含模型加载（large-v3-turbo 约数秒到十几秒）。模型加载后会常驻内存，
`/api/v1/models` 的 `loaded=true` 表示已复用。

**Q: 日志出现 `FP16 is not supported on CPU; using FP32 instead`？**
这是 whisper 在 CPU 上的正常提示，不影响结果；有 GPU 时可设置 `AUDIO2SRT_MODEL_DEVICE=cuda`。

**Q: 想让局域网其他机器访问？**
`python main.py --host 0.0.0.0`，并确认防火墙放行对应端口。当前服务没有鉴权，
对外暴露前请自行加 API Key / 反向代理与 HTTPS。

**Q: 任务执行到一半服务重启了怎么办？**
启动时会把未完成任务标记为 `failed`（`error.code=SERVICE_INTERRUPTED`），重新提交即可。
需要多副本/高可用时，应把线程池执行端替换为 Celery/RQ + Redis。

## 开源协议

本项目基于 [MIT License](LICENSE) 开源，Copyright (c) 2026 jarming。
