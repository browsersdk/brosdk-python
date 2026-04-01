"""
brosdk.manager
==============

高级安全封装层，对应 Rust 的 manager.rs。

提供线程安全的单例 SDK 管理器，将原始 C 回调转换为 Python 可订阅的事件。

使用示例
--------
.. code-block:: python

    from brosdk.manager import BrosdkManager

    def on_event(event):
        print(f"SDK 事件: code={event.code}, data={event.data}")

    sdk = BrosdkManager()
    sdk.on_event(on_event)
    sdk.load("libs/windows-x64/brosdk.dll")
    sdk.init("user_sig", "/tmp/.brosdk", 8080)

    sdk.browser_open('{"envs": [{"envId": "env-001", "args": ["--no-first-run"]}]}')
    # 等待事件回调...
    sdk.browser_close("env-001")
    sdk.shutdown()
"""

import ctypes
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Any

from .ffi import BrosdkLib, SdkResultCbType, SdkCookiesStorageCbType, c_size_t

logger = logging.getLogger(__name__)


@dataclass
class SdkEvent:
    """SDK 异步回调事件，对应 Rust 的 SdkEvent 结构体。"""
    code: int
    data: str

    def is_ok(self) -> bool:
        return self.code == 0 or (200 <= self.code < 300)

    def data_json(self) -> Any:
        """将 data 字段解析为 Python 对象，失败则返回原始字符串。"""
        try:
            return json.loads(self.data)
        except (json.JSONDecodeError, TypeError):
            return self.data


EventCallback = Callable[[SdkEvent], None]


class BrosdkManager:
    """
    线程安全的 brosdk SDK 管理器（单例风格，但允许多实例）。

    :param lib_path: 可在构造时或 :meth:`load` 时传入动态库路径。
    """

    def __init__(self, lib_path: Optional[str] = None) -> None:
        self._lib: Optional[BrosdkLib] = None
        self._lock = threading.Lock()
        self._event_callbacks: List[EventCallback] = []

        # 持有 ctypes 回调对象的引用，防止被 GC 回收
        self._result_cb_ref: Optional[Any] = None
        self._cookies_cb_ref: Optional[Any] = None

        if lib_path:
            self.load(lib_path)

    # ── 事件订阅 ──────────────────────────────────────────────────────────────

    def on_event(self, callback: EventCallback) -> None:
        """
        注册 SDK 异步事件监听器。

        :param callback: 接收 :class:`SdkEvent` 的可调用对象。
        """
        with self._lock:
            self._event_callbacks.append(callback)

    def off_event(self, callback: EventCallback) -> None:
        """移除已注册的事件监听器。"""
        with self._lock:
            try:
                self._event_callbacks.remove(callback)
            except ValueError:
                pass

    # ── 内部回调实现 ──────────────────────────────────────────────────────────

    def _make_result_callback(self) -> Any:
        """构造 C 结果回调，持有 self 弱引用以避免循环引用。"""
        import weakref
        weak_self = weakref.ref(self)

        def _cb(code: int, user_data: int, data: ctypes.c_char_p, length: int) -> None:
            manager = weak_self()
            if manager is None:
                return

            payload = ""
            if data and length > 0:
                try:
                    raw = ctypes.string_at(data, length)
                    payload = raw.decode("utf-8", errors="replace")
                except Exception:
                    payload = ""

            logger.debug("brosdk callback: code=%d, len=%d", code, length)
            logger.debug("brosdk callback data: %s", payload)

            event = SdkEvent(code=code, data=payload)
            callbacks = list(manager._event_callbacks)  # 快照，避免持锁调用
            for cb in callbacks:
                try:
                    cb(event)
                except Exception as exc:
                    logger.exception("SDK event callback raised: %s", exc)

        return SdkResultCbType(_cb)

    def _make_cookies_callback(self) -> Any:
        """构造 cookies/storage 透传回调，使用 SDK 分配器保证内存安全。"""
        import weakref
        weak_self = weakref.ref(self)

        def _cb(
            data: ctypes.c_char_p,
            length: int,
            new_data_ptr: ctypes.POINTER(ctypes.c_char_p),
            new_len_ptr: ctypes.POINTER(c_size_t),
            user_data: int,
        ) -> None:
            manager = weak_self()
            if manager is None or manager._lib is None:
                return
            if not data or length == 0:
                return

            # 必须用 sdk_malloc 分配，SDK 后续会用 sdk_free 释放
            buf = manager._lib._lib.sdk_malloc(length)
            if not buf:
                return
            ctypes.memmove(buf, data, length)
            new_data_ptr[0] = ctypes.cast(buf, ctypes.c_char_p)
            new_len_ptr[0]  = length

        return SdkCookiesStorageCbType(_cb)

    # ── 核心 API ──────────────────────────────────────────────────────────────

    def load(self, lib_path: str) -> None:
        """
        加载原生动态库并注册回调。

        :param lib_path: 平台 DLL/dylib 路径。
        :raises RuntimeError: 如果库已加载或加载失败。
        """
        with self._lock:
            if self._lib is not None:
                raise RuntimeError("SDK library already loaded")

            lib = BrosdkLib.load(lib_path)
            self._lib = lib

            # 构造并保存回调对象（防止 GC）
            self._result_cb_ref  = self._make_result_callback()
            self._cookies_cb_ref = self._make_cookies_callback()

            # 注册结果回调
            rc = lib._lib.sdk_register_result_cb(self._result_cb_ref, None)
            if lib.is_error(rc):
                logger.warning("sdk_register_result_cb returned %d: %s", rc, lib.error_string(rc))

            # 注册 cookies/storage 回调
            rc = lib._lib.sdk_register_cookies_storage_cb(self._cookies_cb_ref, None)
            if lib.is_error(rc):
                logger.warning("sdk_register_cookies_storage_cb returned %d", rc)

            logger.info("brosdk loaded from %s", lib_path)

    def _require_lib(self) -> BrosdkLib:
        lib = self._lib
        if lib is None:
            raise RuntimeError("SDK not loaded — call load() first")
        return lib

    def init(self, user_sig: str, work_dir: str, port: int = 8080) -> str:
        """
        用凭据初始化 SDK。

        :param user_sig: 通过 REST API 用 API Key 换取的 userSig。
        :param work_dir: SDK 工作目录（需确保存在）。
        :param port:     SDK 监听端口，默认 8080。
        :return:         SDK 返回的 JSON 字符串。
        :raises RuntimeError: 初始化失败时。
        """
        lib = self._require_lib()

        init_data = json.dumps({
            "userSig": user_sig,
            "workDir": work_dir,
            "port": port,
        }, ensure_ascii=False)

        data_bytes = init_data.encode("utf-8")

        handle     = ctypes.c_void_p(None)
        out_data   = ctypes.c_char_p(None)
        out_len    = c_size_t(0)

        code = lib._lib.sdk_init(
            ctypes.byref(handle),
            data_bytes,
            len(data_bytes),
            ctypes.byref(out_data),
            ctypes.byref(out_len),
        )

        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"SDK init error (code={code}): {err}")

        result = lib.take_string(out_data, out_len.value)
        result = result or "{}"
        logger.info("brosdk initialized, port=%d, result=%s", port, result)
        return result

    def sdk_info(self) -> str:
        """
        查询 SDK 运行时信息（版本、状态等）。

        :return: JSON 字符串，如 ``{"version":"1.2.3","state":"ready"}``。
        """
        lib = self._require_lib()

        out_data = ctypes.c_char_p(None)
        out_len  = c_size_t(0)

        code = lib._lib.sdk_info(ctypes.byref(out_data), ctypes.byref(out_len))

        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"sdk_info error (code={code}): {err}")

        result = lib.take_string(out_data, out_len.value)
        result = result or "{}"
        logger.info("sdk_info result: %s", result)
        return result

    def browser_open(self, json_str: str) -> None:
        """
        启动浏览器环境（异步，结果通过事件回调返回）。

        :param json_str: 请求 JSON，格式：
                         ``{"envs": [{"envId": "...", "args": [...]}]}``
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()

        logger.info("browser_open request: %s", json_str)
        data_bytes = json_str.encode("utf-8")

        code = lib._lib.sdk_browser_open(data_bytes, len(data_bytes))

        is_ok    = lib.is_ok(code)
        is_done  = lib.is_done(code)
        is_error = lib.is_error(code)
        is_reqid = lib.is_reqid(code)
        logger.info(
            "browser_open code=%d ok=%s done=%s error=%s reqid=%s",
            code, is_ok, is_done, is_error, is_reqid,
        )

        if is_error:
            err = lib.error_string(code)
            raise RuntimeError(f"browser_open error (code={code}): {err}")

    def browser_close(self, env_id: str) -> None:
        """
        关闭浏览器环境。

        :param env_id: 要关闭的环境 ID。
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()

        config = json.dumps({"envs": [env_id]}, ensure_ascii=False)
        logger.info("browser_close request: %s", config)

        data_bytes = config.encode("utf-8")
        code = lib._lib.sdk_browser_close(data_bytes, len(data_bytes))

        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"browser_close error (code={code}): {err}")

    def token_update(self, token_json: str) -> None:
        """
        刷新访问令牌。

        :param token_json: 令牌 JSON 字符串。
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()
        data_bytes = token_json.encode("utf-8")
        code = lib._lib.sdk_token_update(data_bytes, len(data_bytes))
        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"token_update error (code={code}): {err}")

    def env_create(self, config: dict) -> dict:
        """
        创建新的浏览器环境。

        :param config: 环境配置字典，如::

                {
                    "customerId": "default",
                    "envName": "my-env",
                    "finger": {"kernelVersion": "127"},
                }

        :return: 创建结果字典，包含 ``envId``、``envName`` 等字段。
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()

        config_str = json.dumps(config, ensure_ascii=False)
        data_bytes = config_str.encode("utf-8")

        out_data = ctypes.c_char_p(None)
        out_len  = c_size_t(0)

        code = lib._lib.sdk_env_create(
            data_bytes,
            len(data_bytes),
            ctypes.byref(out_data),
            ctypes.byref(out_len),
        )

        result_str = lib.take_string(out_data, out_len.value)

        if lib.is_error(code):
            err = lib.error_string(code)
            detail = f" | result: {result_str}" if result_str else ""
            raise RuntimeError(f"env_create error (code={code}): {err}{detail}")

        result_str = result_str or "{}"
        logger.info("env_create result: %s", result_str)
        return json.loads(result_str)

    def env_page(self, page: int = 1, page_size: int = 50) -> dict:
        """
        分页查询环境列表。

        :param page:      页码，从 1 开始。
        :param page_size: 每页数量。
        :return: 查询结果字典，包含 ``list``（环境列表）和 ``total`` 字段。
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()

        query = json.dumps({"page": page, "pageSize": page_size}, ensure_ascii=False)
        data_bytes = query.encode("utf-8")

        out_data = ctypes.c_char_p(None)
        out_len  = c_size_t(0)

        code = lib._lib.sdk_env_page(
            data_bytes,
            len(data_bytes),
            ctypes.byref(out_data),
            ctypes.byref(out_len),
        )

        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"env_page error (code={code}): {err}")

        result_str = lib.take_string(out_data, out_len.value)
        result_str = result_str or "{}"
        logger.info("env_page result: %s", result_str)
        return json.loads(result_str)

    def env_update(self, config: dict) -> dict:
        """
        更新浏览器环境配置。

        :param config: 更新配置字典，需包含 ``envId``。
        :return: 更新结果字典。
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()

        config_str = json.dumps(config, ensure_ascii=False)
        data_bytes = config_str.encode("utf-8")

        out_data = ctypes.c_char_p(None)
        out_len  = c_size_t(0)

        code = lib._lib.sdk_env_update(
            data_bytes,
            len(data_bytes),
            ctypes.byref(out_data),
            ctypes.byref(out_len),
        )

        result_str = lib.take_string(out_data, out_len.value)

        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"env_update error (code={code}): {err}")

        result_str = result_str or "{}"
        return json.loads(result_str)

    def env_destroy(self, env_id: str) -> dict:
        """
        销毁（删除）浏览器环境。

        :param env_id: 要销毁的环境 ID。
        :return: 操作结果字典。
        :raises RuntimeError: SDK 返回错误码时。
        """
        lib = self._require_lib()

        config = json.dumps({"envId": env_id}, ensure_ascii=False)
        data_bytes = config.encode("utf-8")

        out_data = ctypes.c_char_p(None)
        out_len  = c_size_t(0)

        code = lib._lib.sdk_env_destroy(
            data_bytes,
            len(data_bytes),
            ctypes.byref(out_data),
            ctypes.byref(out_len),
        )

        result_str = lib.take_string(out_data, out_len.value)

        if lib.is_error(code):
            err = lib.error_string(code)
            raise RuntimeError(f"env_destroy error (code={code}): {err}")

        result_str = result_str or "{}"
        return json.loads(result_str)

    def shutdown(self) -> None:
        """
        优雅关闭 SDK。

        :raises RuntimeError: 关闭失败时。
        """
        lib = self._require_lib()
        code = lib._lib.sdk_shutdown()
        if lib.is_error(code):
            raise RuntimeError(f"SDK shutdown error: code={code}")
        logger.info("brosdk shutdown complete")

    # ── 上下文管理器支持 ──────────────────────────────────────────────────────

    def __enter__(self) -> "BrosdkManager":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._lib is not None:
            try:
                self.shutdown()
            except Exception as exc:
                logger.warning("Error during SDK shutdown: %s", exc)
