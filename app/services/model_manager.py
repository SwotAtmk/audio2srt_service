"""Whisper 模型管理：模型清单、下载状态、进程内单例缓存。

服务端最重要的点：模型只加载一次并常驻内存，避免每个请求都
``whisper.load_model()``（large-v3 加载一次就要数秒到数十秒）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import ApiError, ErrorCode


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display_name: str
    url: str


# 与桌面端保持一致的档位映射
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "large-v3-turbo": ModelSpec(
        name="large-v3-turbo",
        display_name="极速版",
        url=(
            "https://openaipublic.azureedge.net/main/whisper/models/"
            "aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt"
        ),
    ),
    "large-v3": ModelSpec(
        name="large-v3",
        display_name="专业版",
        url=(
            "https://openaipublic.azureedge.net/main/whisper/models/"
            "e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt"
        ),
    ),
}


class ModelManager:
    """模型路径解析 + 模型实例缓存（进程内单例）。"""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[str, Any] = {}
        self._load_lock = threading.Lock()
        self._inference_locks: dict[str, threading.Lock] = {}
        self._inference_lock_guard = threading.Lock()

    # ---- 元信息 ----
    @staticmethod
    def get_spec(model_name: str) -> ModelSpec:
        spec = MODEL_REGISTRY.get(model_name)
        if spec is None:
            raise ApiError(
                ErrorCode.UNKNOWN_MODEL,
                f"未知模型: {model_name}，可选值: {', '.join(MODEL_REGISTRY)}",
                details={"available_models": list(MODEL_REGISTRY)},
            )
        return spec

    def get_model_path(self, model_name: str) -> Path:
        self.get_spec(model_name)
        return self._settings.model_dir / f"{model_name}.pt"

    def is_downloaded(self, model_name: str) -> bool:
        path = self.get_model_path(model_name)
        return path.is_file() and path.stat().st_size > 0

    def is_loaded(self, model_name: str) -> bool:
        return model_name in self._cache

    def list_models(self) -> list[dict[str, Any]]:
        items = []
        for name, spec in MODEL_REGISTRY.items():
            path = self.get_model_path(name)
            downloaded = self.is_downloaded(name)
            items.append(
                {
                    "name": spec.name,
                    "display_name": spec.display_name,
                    "downloaded": downloaded,
                    "loaded": self.is_loaded(name),
                    "path": str(path),
                    "size_bytes": path.stat().st_size if downloaded else None,
                    "download_url": spec.url,
                }
            )
        return items

    # ---- 模型实例 ----
    def get_model(self, model_name: str) -> Any:
        """返回常驻内存的模型实例，未下载/加载失败时抛出明确错误。"""
        spec = self.get_spec(model_name)
        if not self.is_downloaded(model_name):
            raise ApiError(
                ErrorCode.MODEL_NOT_DOWNLOADED,
                f"模型 {model_name}（{spec.display_name}）未下载，请先下载到 {self._settings.model_dir}",
                details={
                    "model": model_name,
                    "expected_path": str(self.get_model_path(model_name)),
                    "download_url": spec.url,
                },
            )

        model = self._cache.get(model_name)
        if model is not None:
            return model

        with self._load_lock:
            # 双重检查，避免并发重复加载
            if model_name in self._cache:
                return self._cache[model_name]

            try:
                import whisper  # 延迟导入：未装 torch 时服务仍可启动做健康检查
            except Exception as exc:  # pragma: no cover - 环境依赖分支
                raise ApiError(
                    ErrorCode.MODEL_LOAD_FAILED,
                    "无法导入 openai-whisper，请确认已安装 openai-whisper 与 torch",
                    details={"error": str(exc)},
                ) from exc

            try:
                model = whisper.load_model(
                    str(self.get_model_path(model_name)),
                    device=self._settings.model_device,
                )
            except Exception as exc:
                raise ApiError(
                    ErrorCode.MODEL_LOAD_FAILED,
                    f"模型 {model_name} 加载失败: {exc}",
                    details={"model": model_name, "error": str(exc)},
                ) from exc

            self._cache[model_name] = model
            return model

    def inference_lock(self, model_name: str) -> threading.Lock:
        """openai-whisper 模型实例不是线程安全的，同一模型的推理需串行执行。"""
        with self._inference_lock_guard:
            if model_name not in self._inference_locks:
                self._inference_locks[model_name] = threading.Lock()
            return self._inference_locks[model_name]

    def clear_cache(self, model_name: str | None = None) -> None:
        with self._load_lock:
            if model_name is None:
                self._cache.clear()
            else:
                self._cache.pop(model_name, None)
