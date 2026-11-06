# audio2srt API 接口说明

把音频/视频转成 SRT 字幕的 HTTP 服务。核心转写链路参考桌面端项目
`/Users/liujiaming/PycharmProjects/audio2srt`，抽取其 ffmpeg 处理、Whisper 转写、
SRT 生成与输出命名规则，去掉 PySide6 界面与 QThread，改为 FastAPI + 后台任务队列。

- 服务版本：1.0.0
- API 前缀：`/api/v1`
- 交互式文档：启动后访问 `http://127.0.0.1:8000/docs`（Swagger UI）
- 开源协议：[MIT License](../../../LICENSE)（Copyright (c) 2026 jarming）

---

## 1. 目录结构

```
audio2srt_service/
├── main.py                        # 启动入口：python main.py
├── scripts/
│   ├── start.sh                   # 启动包装（pid 文件 + 可选复用外部 whisper 环境）
│   └── stop.sh                    # 按 data/server.pid 停止
├── app/
│   ├── main.py                    # FastAPI 应用入口、异常处理、生命周期
│   ├── api/
│   │   ├── transcriptions.py      # 上传/查询/下载接口
│   │   └── system.py              # 健康检查、配置、模型信息
│   ├── core/
│   │   ├── config.py              # 环境变量配置
│   │   ├── errors.py              # 错误码与统一异常
│   │   ├── ffmpeg.py              # ffmpeg/ffprobe 定位、音频归一化
│   │   └── formats.py             # 支持的音/视频扩展名
│   ├── schemas/
│   │   ├── task.py                # 任务模型与响应结构
│   │   └── system.py              # 系统接口响应结构
│   └── services/
│       ├── audio_extractor.py     # 格式校验 + 音频准备
│       ├── model_manager.py       # 模型路径/下载状态/单例缓存
│       ├── transcriber.py         # openai-whisper 封装
│       ├── srt_writer.py          # SRT 渲染、输出命名与占位
│       ├── task_store.py          # 内存索引 + JSON 落盘
│       └── pipeline.py            # 上传落盘、排队、后台执行
├── tests/                         # pytest 测试（29 个用例）
├── data/                          # 运行时数据（自动创建）
│   ├── uploads/                   # 上传文件（默认处理完即删除）
│   ├── srt/                       # 生成的 SRT
│   ├── tasks/                     # 任务元信息 JSON
│   └── tmp/                       # ffmpeg 临时 WAV
├── requirements.txt
```

---

## 2. 本地启动

### 2.1 安装依赖

```bash
cd /Users/liujiaming/PycharmProjects/audio2srt_service
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
# openai-whisper 会安装 torch，首次安装体积较大
```

### 2.2 准备 ffmpeg

查找优先级（与桌面端一致）：

1. 环境变量 `FFMPEG_PATH`
2. 项目内置 `assets/ffmpeg/{mac,win,linux}/ffmpeg`
3. 系统 `PATH`

```bash
# macOS
brew install ffmpeg
ffmpeg -version
```

本机验证时使用的是 `/opt/homebrew/bin/ffmpeg`（7.1.1）。

### 2.3 下载模型

模型默认放在 `~/.audio2srt/models`，服务**不会**在请求时自动下载（避免意外拉取
1.6–3 GB 文件）。手动下载：

```bash
mkdir -p ~/.audio2srt/models

# 极速版 large-v3-turbo (约 1.5 GB)
curl -L -o ~/.audio2srt/models/large-v3-turbo.pt \
  https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt

# 专业版 large-v3 (约 2.9 GB，按需)
curl -L -o ~/.audio2srt/models/large-v3.pt \
  https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt
```

### 2.4 启动服务

以根目录 `main.py` 为唯一入口：

```bash
cd /Users/liujiaming/PycharmProjects/audio2srt_service
source .venv/bin/activate
python main.py                  # 默认 http://127.0.0.1:8000
```

可选参数（均可用同名环境变量替代）：

| 参数 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--host` | `HOST` | `127.0.0.1` | 局域网访问用 `0.0.0.0` |
| `--port` | `PORT` | `8000` | 监听端口 |
| `--reload` | `AUDIO2SRT_RELOAD` | 关闭 | 开发热重载 |
| — | `AUDIO2SRT_LOG_LEVEL` | `info` | 日志级别 |

```bash
python main.py --host 0.0.0.0 --port 8123
PORT=8123 python main.py --reload
```

后台常驻启动与停止：

```bash
nohup python main.py --host 127.0.0.1 --port 8000 > data/server.log 2>&1 &
echo $! > data/server.pid

cat data/server.pid              # 查看 pid
kill $(cat data/server.pid)      # 停止
# 或使用脚本：scripts/stop.sh
```

`scripts/start.sh` 是等价包装：会自动写 `data/server.pid`，并在 `.venv` 缺少
`openai-whisper` 时尝试复用 `../audio2srt/.venv/.../site-packages`
（可用 `AUDIO2SRT_WHISPER_SITE` 指定），适合快速本地启动：

```bash
nohup scripts/start.sh > data/server.log 2>&1 &
scripts/stop.sh
```

本项目 `.venv` 已按 `requirements.txt` 安装齐依赖（`openai-whisper 20250625`
+ `torch 2.15.0`，约 984 MB），正常情况下无需复用外部环境。

### 2.5 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AUDIO2SRT_MODEL_DIR` | `~/.audio2srt/models` | `.pt` 模型目录 |
| `AUDIO2SRT_DATA_DIR` | `<项目根>/data` | 上传、SRT、任务元数据根目录 |
| `AUDIO2SRT_DEFAULT_MODEL` | `large-v3-turbo` | 请求未指定模型时使用 |
| `AUDIO2SRT_MAX_UPLOAD_MB` | `500` | 单文件大小上限 |
| `AUDIO2SRT_MAX_WORKERS` | `1` | 后台转写线程数（建议保持 1） |
| `AUDIO2SRT_MODEL_DEVICE` | 空（whisper 自动选择） | `cpu` / `cuda` |
| `AUDIO2SRT_KEEP_UPLOADS` | `false` | 是否保留已处理的上传文件 |
| `AUDIO2SRT_LOG_LEVEL` | `INFO` | 日志级别 |
| `FFMPEG_PATH` | 空 | 指定 ffmpeg 可执行文件 |
| `FFPROBE_PATH` | 空 | 指定 ffprobe（缺省时探测为可选能力） |

---

## 3. 设计取舍（相对桌面端）

| 主题 | 桌面端做法 | 服务端做法 | 原因 |
| --- | --- | --- | --- |
| 转写库 | `openai-whisper` | 保留 `openai-whisper` | 与参考项目一致；不用 faster-whisper |
| 模型档位 | `large-v3-turbo`=极速版、`large-v3`=专业版 | 保留映射，接口用模型名传参 | 语义清晰，便于文档与计费扩展 |
| 模型加载 | 模块级 `_model_cache` 字典，无锁 | `ModelManager` 单例 + 双重检查锁 + 每模型推理锁 | 并发请求下避免重复加载与模型实例竞争 |
| ffmpeg 定位 | ENV → 内置 → PATH；ENV 无效时静默回退 | 保留优先级；ENV 无效时直接报错 | 服务端要可观测，避免"以为用了指定版本" |
| 音频处理 | 仅视频用 ffmpeg 提取；音频直接交给 whisper | 所有输入统一转成 16 kHz 单声道 WAV | 输入一致、提前暴露坏文件、错误可归类 |
| 输出命名 | 与输入同名 `.srt`；重名加 6 位随机字符 | 沿用规则；只接受文件名，不接受路径 | 防止路径穿越/任意写文件；保留用户熟悉的命名体验 |
| 任务执行 | PySide6 `QThread` + Qt 信号 | FastAPI + 线程池 + 任务落盘 + 轮询 | 无 UI 依赖，可横向扩展为独立 worker |
| 配置 | `~/.audio2srt/config.json` | 环境变量 | 适合容器化/多环境部署 |
| 进度 | 回调在 `transcribe` 返回后才遍历段落，实际是"假进度" | 阶段式进度（见 6.1） | whisper 同步接口没有逐段回调，如实标注粒度 |
| 模型下载 | GUI 内置下载器 | 不提供下载接口，给出 curl 命令 | 避免服务端隐式拉取大文件；运维可控 |

另一处小改进：桌面端 SRT 毫秒是直接截断浮点，这里改为先四舍五入到毫秒再拆分，
避免 `1.999s` 这类值出现毫秒误差。

---

## 4. 接口总览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查（ffmpeg、模型目录、已加载模型、队列并发） |
| `GET` | `/api/v1/config` | 服务配置（路径、限制、支持的格式、模型档位） |
| `GET` | `/api/v1/models` | 模型清单（是否下载、是否已加载、大小、下载地址） |
| `POST` | `/api/v1/transcriptions` | 上传音/视频，创建异步转写任务（202） |
| `GET` | `/api/v1/transcriptions` | 列出最近任务 |
| `GET` | `/api/v1/transcriptions/{task_id}` | 查询任务状态与结果 |
| `GET` | `/api/v1/transcriptions/{task_id}/srt` | 下载 SRT（仅 completed 状态） |

所有业务错误统一返回：

```json
{
  "error": {
    "code": "MODEL_NOT_DOWNLOADED",
    "message": "模型 large-v3（专业版）未下载，请先下载到 /Users/liujiaming/.audio2srt/models",
    "details": { "...": "可选，按错误类型不同" }
  }
}
```

---

## 5. 接口详情

### 5.1 健康检查

`GET /health`

无参数。HTTP 200。`status` 为 `ok` 或 `degraded`（ffmpeg 缺失或没有任何已下载模型时
为 degraded；服务本身仍存活，因此不返回 5xx）。

```bash
curl -s http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "service_version": "1.0.0",
  "ffmpeg": {
    "ok": true,
    "path": "/opt/homebrew/bin/ffmpeg",
    "version": "ffmpeg version 7.1.1 Copyright (c) 2000-2025 the FFmpeg developers",
    "error": null
  },
  "model_dir": "/Users/liujiaming/.audio2srt/models",
  "downloaded_models": ["large-v3-turbo"],
  "loaded_models": ["large-v3-turbo"],
  "queue_workers": 1
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `ok` / `degraded` |
| `ffmpeg.ok` | bool | ffmpeg 是否可用 |
| `downloaded_models` | string[] | 模型目录中存在的模型 |
| `loaded_models` | string[] | 已加载进内存的模型（单例复用） |
| `queue_workers` | int | 后台转写并发数 |

### 5.2 配置查询

`GET /api/v1/config`

```bash
curl -s http://127.0.0.1:8000/api/v1/config
```

```json
{
  "api_version": "v1",
  "service_version": "1.0.0",
  "model_dir": "/Users/liujiaming/.audio2srt/models",
  "data_dir": "/Users/liujiaming/PycharmProjects/audio2srt_service/data",
  "srt_dir": "/Users/liujiaming/PycharmProjects/audio2srt_service/data/srt",
  "default_model": "large-v3-turbo",
  "model_device": null,
  "max_upload_mb": 500,
  "queue_workers": 1,
  "ffmpeg_path": "/opt/homebrew/bin/ffmpeg",
  "ffmpeg_version": "ffmpeg version 7.1.1 ...",
  "supported_audio_formats": [".aac", ".aif", ".aiff", ".amr", ".flac", ".m4a", ".m4b", ".mp3", ".mpga", ".ogg", ".opus", ".wav", ".webm", ".wma"],
  "supported_video_formats": [".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm", ".wmv"],
  "model_tiers": [
    {"name": "large-v3-turbo", "display_name": "极速版", "downloaded": true, "download_url": "https://..."},
    {"name": "large-v3", "display_name": "专业版", "downloaded": false, "download_url": "https://..."}
  ],
  "progress_semantics": "阶段式百分比: queued=0, extracting=5, transcribing=15, writing=95, completed=100；..."
}
```

### 5.3 模型信息

`GET /api/v1/models`

```bash
curl -s http://127.0.0.1:8000/api/v1/models
```

```json
{
  "model_dir": "/Users/liujiaming/.audio2srt/models",
  "models": [
    {
      "name": "large-v3-turbo",
      "display_name": "极速版",
      "downloaded": true,
      "loaded": true,
      "path": "/Users/liujiaming/.audio2srt/models/large-v3-turbo.pt",
      "size_bytes": 1617941637,
      "download_url": "https://openaipublic.azureedge.net/main/whisper/models/....pt"
    },
    {
      "name": "large-v3",
      "display_name": "专业版",
      "downloaded": false,
      "loaded": false,
      "path": "/Users/liujiaming/.audio2srt/models/large-v3.pt",
      "size_bytes": null,
      "download_url": "https://openaipublic.azureedge.net/main/whisper/models/....pt"
    }
  ]
}
```

`loaded=true` 表示模型已常驻内存，后续请求不会再触发 `whisper.load_model()`。

### 5.4 创建转写任务（核心接口）

`POST /api/v1/transcriptions`

`multipart/form-data`：

| 参数 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- |
| `file` | 是 | 文件 | 音频或视频，扩展名需在支持列表中 |
| `model` | 否 | string | `large-v3-turbo`（极速版，默认）或 `large-v3`（专业版） |
| `language` | 否 | string | `auto` 或留空=自动检测；也可传 `zh`/`en`/`ja` 等 |
| `output_filename` | 否 | string | 自定义 SRT 文件名，不含路径；可省略 `.srt` |

响应 `202 Accepted`：

```json
{
  "task_id": "6231c14790494610afca98db3e4f2577",
  "status": "queued",
  "model": "large-v3-turbo",
  "language": null,
  "original_filename": "test_speech.m4a",
  "output_filename": "test_speech.srt",
  "progress": 0,
  "audio_duration_seconds": null,
  "segment_count": null,
  "srt_size_bytes": null,
  "detected_language": null,
  "error": null,
  "download_url": null,
  "created_at": "2026-11-06T07:50:52.265431Z",
  "started_at": null,
  "finished_at": null
}
```

```bash
# 极速版 + 自动语言检测
curl -X POST http://127.0.0.1:8000/api/v1/transcriptions \
  -F "file=@test_speech.m4a" \
  -F "model=large-v3-turbo"

# 指定中文、自定义输出名
curl -X POST http://127.0.0.1:8000/api/v1/transcriptions \
  -F "file=@video_test.mp4" \
  -F "model=large-v3" \
  -F "language=zh" \
  -F "output_filename=会议记录"
```

说明：

- 提交时会先校验扩展名、模型是否已下载、ffmpeg 是否可用，任一不满足立即返回错误，
  不会白白接收大文件。
- 默认输出名取输入文件主名 + `.srt`；`data/srt` 下已有同名文件时自动追加 6 位随机字符，
  例如 `test_speech_jvh2ck.srt`（已实测）。
- 上传文件在任务结束后默认删除（`AUDIO2SRT_KEEP_UPLOADS=1` 可保留）。

### 5.5 查询任务

`GET /api/v1/transcriptions/{task_id}`

```bash
curl -s http://127.0.0.1:8000/api/v1/transcriptions/6231c14790494610afca98db3e4f2577
```

处理中：

```json
{
  "task_id": "6231c14790494610afca98db3e4f2577",
  "status": "transcribing",
  "progress": 15,
  "audio_duration_seconds": 6.641,
  "segment_count": null,
  "error": null,
  "download_url": null,
  "started_at": "2026-11-06T07:50:52.266507Z"
}
```

完成：

```json
{
  "task_id": "6231c14790494610afca98db3e4f2577",
  "status": "completed",
  "progress": 100,
  "audio_duration_seconds": 6.641,
  "segment_count": 1,
  "srt_size_bytes": 121,
  "detected_language": "zh",
  "error": null,
  "download_url": "/api/v1/transcriptions/6231c14790494610afca98db3e4f2577/srt",
  "finished_at": "2026-11-06T07:51:04.510098Z"
}
```

失败：

```json
{
  "status": "failed",
  "progress": 5,
  "error": {
    "code": "AUDIO_EXTRACTION_FAILED",
    "message": "ffmpeg 音频提取失败，文件可能已损坏或不是有效的音视频格式",
    "details": {"stderr": "..."}
  },
  "download_url": null
}
```

轮询建议：短音频 1–2 秒一次；长音频 5 秒一次，`status` 为 `completed` 或 `failed`
即可停止。任务元信息落盘在 `data/tasks/<task_id>.json`，服务重启后仍可查询。

### 5.6 列出任务

`GET /api/v1/transcriptions?limit=50`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `limit` | 50 | 1–200，按创建时间倒序 |

```bash
curl -s "http://127.0.0.1:8000/api/v1/transcriptions?limit=10"
```

### 5.7 下载 SRT

`GET /api/v1/transcriptions/{task_id}/srt`

```bash
curl -OJ http://127.0.0.1:8000/api/v1/transcriptions/6231c14790494610afca98db3e4f2577/srt
```

响应头：

```
HTTP/1.1 200 OK
content-type: application/x-subrip
content-disposition: attachment; filename="test_speech.srt"
content-length: 121
```

文件内容（真实转写结果，UTF-8）：

```
1
00:00:00,000 --> 00:00:06,520
这是一次端到端接口测试,用来验证音频转字幕服务是否正常工作。
```

任务未完成时返回 `409 TASK_NOT_COMPLETED`；文件被清理时返回 `410 OUTPUT_NOT_FOUND`。

---

## 6. 任务状态与异步方案

### 6.1 状态机

```
queued → extracting → transcribing → writing → completed
   └────────────── 任一阶段失败 ──────────────→ failed
```

进度为阶段式百分比：`queued=0`、`extracting=5`、`transcribing=15`、`writing=95`、
`completed=100`。openai-whisper 的 `transcribe()` 是同步阻塞调用，不暴露逐段回调
（桌面端看似有进度回调，实际是转写结束后才遍历段落），因此转写阶段进度停留在 15，
通过 `status` 与 `audio_duration_seconds` 让客户端自行估算。

### 6.2 为什么选"异步任务 + 轮询"而不是同步长请求

1. **耗时不可控**：本机 large-v3-turbo 处理 6.6 秒音频（含首次模型加载）约 12 秒；
   1 小时音频在 CPU 上通常是几十分钟量级，同步 HTTP 很容易触发网关/客户端超时。
2. **可观测**：任务持久化，客户端断线重连后仍能按 `task_id` 查询结果，不会丢结果。
3. **不阻塞事件循环**：转写跑在 `ThreadPoolExecutor` 中，FastAPI 的 async 事件循环
   继续处理健康检查、查询、下载等请求。
4. **部署简单**：单机不需要 Redis/Celery/RabbitMQ，零额外中间件。

代价与边界：任务只在当前进程内执行，进程重启会中断进行中的任务（启动时会把
遗留的非终态任务标记为 `SERVICE_INTERRUPTED`）；不能多副本共享队列。

扩展路径（当前未实现）：需要多副本/多机时，把 `pipeline` 的执行端替换为
Celery/RQ + Redis，`TaskStore` 换成 Redis/PostgreSQL，接口层保持不变。

### 6.3 并发控制

- 默认 `AUDIO2SRT_MAX_WORKERS=1`：whisper 是 CPU/GPU 密集型，单 worker 最稳，也避免
  同一模型实例被多线程同时推理。
- 即使调大 worker，`ModelManager` 仍按模型维度提供推理锁，保证同一模型串行推理。
- 模型实例进程内单例：同一模型的第二次请求直接复用已加载模型（实测第二个任务耗时
  从 ~12 秒降到 ~6 秒，正是音频本身的转写时间）。

---

## 7. 错误码与处理方式

| HTTP | code | 触发场景 | message 示例 |
| --- | --- | --- | --- |
| 400 | `UNKNOWN_MODEL` | `model` 不是支持档位 | `未知模型: large-v1，可选值: large-v3-turbo, large-v3` |
| 400 | `INVALID_OUTPUT_FILENAME` | 输出名含 `/`、`\`、为空或只有 `.srt` | `output_filename 只能是文件名，不能包含路径分隔符` |
| 404 | `TASK_NOT_FOUND` | task_id 不存在 | `任务不存在: xxx` |
| 409 | `MODEL_NOT_DOWNLOADED` | 模型 `.pt` 不存在（含下载中断） | `模型 large-v3（专业版）未下载，请先下载到 ...` |
| 409 | `TASK_NOT_COMPLETED` | 任务未完成就下载 SRT | `任务尚未完成，当前状态: transcribing` |
| 410 | `OUTPUT_NOT_FOUND` | SRT 文件已被清理 | `SRT 文件已不存在（可能被清理）` |
| 413 | `FILE_TOO_LARGE` | 超过 `AUDIO2SRT_MAX_UPLOAD_MB` | `文件超过大小限制 500 MB` |
| 415 | `UNSUPPORTED_FORMAT` | 扩展名不在白名单 | `不支持的文件格式: .txt` |
| 422 | `INVALID_REQUEST` | 缺少 `file`、空文件、表单校验失败 | `上传文件为空` |
| 422 | `AUDIO_EXTRACTION_FAILED` | ffmpeg 解码失败（损坏/伪装扩展名） | `ffmpeg 音频提取失败，文件可能已损坏...` |
| 500 | `MODEL_LOAD_FAILED` | 模型文件损坏、torch/whisper 导入失败 | `模型 large-v3-turbo 加载失败: ...` |
| 500 | `TRANSCRIPTION_FAILED` | 转写运行期异常、无可用推理设备等 | `转写失败: ...` |
| 500 | `SERVICE_INTERRUPTED` | 服务重启导致任务中断 | `服务重启，任务被中断，请重新提交` |
| 503 | `FFMPEG_NOT_FOUND` | 三处查找均失败 | `未找到 ffmpeg，请安装 ffmpeg 或设置 FFMPEG_PATH ...` |

注意：

- 转写类错误发生在后台任务里，HTTP 提交请求本身已返回 202，错误体现在
  `GET /{task_id}` 的 `status=failed` 与 `error` 字段。
- 未捕获异常统一返回 `500 INTERNAL_ERROR`（不含堆栈），详细堆栈写入服务日志。

---

## 8. 端到端验证记录（本机真实执行）

环境：macOS arm64，Python 3.12.10，ffmpeg 7.1.1（Homebrew），
模型 `large-v3-turbo.pt`（1.5 GB，已下载到 `~/.audio2srt/models`）。

> 说明：项目 `.venv` 已按 `requirements.txt` 安装齐依赖（`openai-whisper 20250625`
> + `torch 2.15.0`），服务直接使用项目 venv 启动，无需额外 `PYTHONPATH`。

### 8.1 音频上传 → 转写 → 下载

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8123

curl -X POST http://127.0.0.1:8123/api/v1/transcriptions \
  -F "file=@test_speech.m4a" -F "model=large-v3-turbo" -F "language=auto"
# 202, task_id=6231c14790494610afca98db3e4f2577, output_filename=test_speech.srt

curl http://127.0.0.1:8123/api/v1/transcriptions/6231c147...
# queued → transcribing(progress=15) → completed(progress=100)

curl -o result.srt http://127.0.0.1:8123/api/v1/transcriptions/6231c147.../srt
```

结果：`status=completed`，`segment_count=1`，`detected_language=zh`，
`audio_duration_seconds=6.641`，SRT 121 字节，内容正确：

```
1
00:00:00,000 --> 00:00:06,520
这是一次端到端接口测试,用来验证音频转字幕服务是否正常工作。
```

首次任务含模型加载，总耗时约 12.2 秒；模型常驻后同类任务约 6 秒。

### 8.2 视频上传 → 提取音频 → 转写

用同一段语音合成的 6.6 秒 MP4（320×240，带 AAC 音轨）上传：

- 任务 `2cab3909...`：`completed`，`audio_duration_seconds=6.595`，
  `detected_language=zh`，SRT 121 字节，耗时约 6.7 秒。

### 8.3 重名输出

预置 `test_speech.srt` 后再次上传 `test_speech.m4a`：

- `output_filename=test_speech_jvh2ck.srt`（自动追加 6 位随机字符），任务完成。

### 8.4 错误路径

| 场景 | 实际返回 |
| --- | --- |
| 上传 `notes.txt` | `415 UNSUPPORTED_FORMAT` |
| `model=large-v3`（未下载） | `409 MODEL_NOT_DOWNLOADED`，`details.download_url` 给出下载地址 |
| 伪造的 `corrupt.mp3` | 任务 `failed`，`error.code=AUDIO_EXTRACTION_FAILED`，`details.stderr` 含 ffmpeg 报错 |
| 查询不存在的 task_id | `404 TASK_NOT_FOUND` |
| 空文件 / 缺少 file 字段 | `422 INVALID_REQUEST` |

### 8.5 单元/接口测试

```bash
.venv/bin/python -m pytest tests -v
# 29 passed
```

覆盖：SRT 时间格式与渲染、命名冲突、非法输出名、上传校验、未知模型、
模型未下载、失败任务记录、未完成下载、列表接口、健康/配置/模型接口。

### 8.6 后台驻留运行实测

```bash
nohup .venv/bin/python main.py --host 127.0.0.1 --port 8000 > data/server.log 2>&1 &
echo $! > data/server.pid
# pid=52191，监听 127.0.0.1:8000
```

| 接口 | 实测结果 |
| --- | --- |
| `GET /health` | 200，`status=ok`，`ffmpeg.ok=true`，`downloaded_models=["large-v3-turbo"]` |
| `GET /api/v1/config` | 200，`default_model=large-v3-turbo`，`queue_workers=1`，`max_upload_mb=500` |
| `GET /api/v1/models` | 200，`large-v3-turbo`：`downloaded=true`、转写后 `loaded=true`；`large-v3`：`downloaded=false` |
| `POST /api/v1/transcriptions` | 202，`task_id=00ccfca939914027a07077da51cf6cc0`，`output_filename=test_speech_nm1hhf.srt` |
| `GET /api/v1/transcriptions/{id}` | `transcribing(progress=15)` → `completed(progress=100)`，`segment_count=1`，`srt_size_bytes=121`，`detected_language=zh`，总耗时约 13.3 秒（含模型加载） |
| `GET /api/v1/transcriptions/{id}/srt` | 200，`content-type: application/x-subrip`，`content-length: 121`，Attachment 文件名 `test_speech_nm1hhf.srt` |
| `GET /api/v1/transcriptions?limit=5` | 200，返回 5 条任务（含历史失败任务与错误详情） |
| `POST` 上传 `notes.txt` | 415，`UNSUPPORTED_FORMAT` |
| `POST` 指定 `model=large-v3` | 409，`MODEL_NOT_DOWNLOADED`，`details.download_url` 给出下载地址 |

SRT 实际内容：

```
1
00:00:00,000 --> 00:00:06,520
这是一次端到端接口测试,用来验证音频转字幕服务是否正常工作。
```

验证后服务仍在运行（`ps` 显示 pid 52191 持续存活，`/health` 返回 200）。


---

## 9. 已知限制与后续可选增强

1. **无鉴权/限流**：当前定位为内网服务。对外暴露前建议加 API Key、限流与 HTTPS。
2. **单进程任务队列**：不支持多副本共享；需要水平扩展时替换为 Celery/RQ + Redis。
3. **转写精细进度缺失**：受 openai-whisper 同步接口限制；若必须逐段进度，可改为
   ffmpeg 切片 + 分段转写再拼接（会牺牲少量上下文准确率）。
4. **不自动下载模型**：需运维提前放置 `.pt`；如需接口化，可增加异步"模型下载任务"。
5. **输出目录固定**：不接受任意输出路径（安全取舍）；如确需自定义目录，可增加
   白名单目录配置，而不是放开绝对路径。
6. **CPU 上 FP16 提示**：日志中的 `FP16 is not supported on CPU; using FP32 instead`
   是 whisper 的正常警告，不影响结果；有 CUDA 时可用 `AUDIO2SRT_MODEL_DEVICE=cuda`。

---

## 10. 开源协议

本项目基于 [MIT License](../../../LICENSE) 开源，Copyright (c) 2026 jarming。

你可以自由使用、修改、分发、商用，唯一要求是保留版权声明与许可声明。
项目按"现状"提供，不附带任何明示或暗示的担保。
