"""
brosdk.ffi
==========

原始 C FFI 绑定，通过 ctypes 动态加载 brosdk.dll / brosdk.dylib。
直接对应 brosdk.h 中的函数签名。

SDK API 约定
-----------
- 所有字符串输入通过 (const char *data, size_t len) 传入 —— 无需 NUL 终止
- 带 out_data/out_len 的函数返回 SDK 分配的字符串，调用方必须通过 sdk_free 释放
- 返回码：通过 sdk_is_ok / sdk_is_error 等判断
"""

import ctypes
import os
import platform
import sys
from typing import Optional


# ── C 类型别名 ────────────────────────────────────────────────────────────────

c_int32  = ctypes.c_int32
c_size_t = ctypes.c_size_t
c_void_p = ctypes.c_void_p
c_char_p = ctypes.c_char_p
c_bool   = ctypes.c_bool

# sdk_handle_t = void*
SdkHandleT = ctypes.c_void_p

# sdk_result_cb_t: void(int32_t code, void *user_data, const char *data, size_t len)
SdkResultCbType = ctypes.CFUNCTYPE(
    None,           # return void
    c_int32,        # code
    c_void_p,       # user_data
    ctypes.c_char_p,  # data
    c_size_t,       # len
)

# sdk_cookies_storage_cb_t: void(const char *data, size_t len,
#                                char **new_data, size_t *new_len, void *user_data)
SdkCookiesStorageCbType = ctypes.CFUNCTYPE(
    None,
    ctypes.c_char_p,                   # data
    c_size_t,                          # len
    ctypes.POINTER(ctypes.c_char_p),   # new_data (char**)
    ctypes.POINTER(c_size_t),          # new_len
    c_void_p,                          # user_data
)


class BrosdkLib:
    """
    动态加载 brosdk 共享库，封装所有原始 C 函数符号。

    使用示例
    --------
    .. code-block:: python

        lib = BrosdkLib.load("libs/windows-x64/brosdk.dll")
        # ... 调用 lib.sdk_init(...)
        lib.sdk_shutdown()
    """

    def __init__(self, cdll: ctypes.CDLL) -> None:
        self._lib = cdll
        self._bind_symbols()

    # ── 工厂方法 ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str) -> "BrosdkLib":
        """加载指定路径的 brosdk 动态库。"""
        if not os.path.isabs(path):
            # 相对路径：相对于调用方的当前工作目录
            path = os.path.abspath(path)

        if not os.path.exists(path):
            raise FileNotFoundError(f"brosdk library not found: {path}")

        try:
            lib = ctypes.CDLL(path)
        except OSError as e:
            raise RuntimeError(f"Failed to load brosdk: {e}") from e

        return cls(lib)

    @classmethod
    def load_default(cls) -> "BrosdkLib":
        """根据当前平台自动选择默认路径加载库。"""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        system = platform.system()
        machine = platform.machine().lower()

        if system == "Windows":
            lib_path = os.path.join(base, "libs", "windows-x64", "brosdk.dll")
        elif system == "Darwin":
            lib_path = os.path.join(base, "libs", "macos-arm64", "brosdk.dylib")
        elif system == "Linux":
            lib_path = os.path.join(base, "libs", "linux-x64", "libbrosdk.so")
        else:
            raise RuntimeError(f"Unsupported platform: {system}")

        return cls.load(lib_path)

    # ── 符号绑定 ──────────────────────────────────────────────────────────────

    def _bind_symbols(self) -> None:
        """为所有导出符号设置 argtypes / restype，避免 ctypes 默认的 int 假设。"""
        lib = self._lib

        # ── 注册回调 ─────────────────────────────────────────────────────────
        lib.sdk_register_result_cb.argtypes = [SdkResultCbType, c_void_p]
        lib.sdk_register_result_cb.restype  = c_int32

        lib.sdk_register_cookies_storage_cb.argtypes = [SdkCookiesStorageCbType, c_void_p]
        lib.sdk_register_cookies_storage_cb.restype  = c_int32

        # ── 核心生命周期 ──────────────────────────────────────────────────────
        # int32_t sdk_init(sdk_handle_t *cpp_handle, const char *data, size_t len,
        #                  char **out_data, size_t *out_len)
        lib.sdk_init.argtypes = [
            ctypes.POINTER(SdkHandleT),   # cpp_handle
            ctypes.c_char_p,              # data
            c_size_t,                     # len
            ctypes.POINTER(ctypes.c_char_p),  # out_data
            ctypes.POINTER(c_size_t),     # out_len
        ]
        lib.sdk_init.restype = c_int32

        # int32_t sdk_info(char **out_data, size_t *out_len)
        lib.sdk_info.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(c_size_t),
        ]
        lib.sdk_info.restype = c_int32

        # int32_t sdk_shutdown(void)
        lib.sdk_shutdown.argtypes = []
        lib.sdk_shutdown.restype  = c_int32

        # ── 浏览器操作 ────────────────────────────────────────────────────────
        lib.sdk_browser_open.argtypes = [ctypes.c_char_p, c_size_t]
        lib.sdk_browser_open.restype  = c_int32

        lib.sdk_browser_close.argtypes = [ctypes.c_char_p, c_size_t]
        lib.sdk_browser_close.restype  = c_int32

        # ── 认证 ─────────────────────────────────────────────────────────────
        lib.sdk_token_update.argtypes = [ctypes.c_char_p, c_size_t]
        lib.sdk_token_update.restype  = c_int32

        # ── 环境管理 ─────────────────────────────────────────────────────────
        # int32_t sdk_env_create(const char *data, size_t len,
        #                        char **out_data, size_t *out_len)
        lib.sdk_env_create.argtypes = [
            ctypes.c_char_p,
            c_size_t,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(c_size_t),
        ]
        lib.sdk_env_create.restype = c_int32

        lib.sdk_env_page.argtypes = [
            ctypes.c_char_p,
            c_size_t,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(c_size_t),
        ]
        lib.sdk_env_page.restype = c_int32

        lib.sdk_env_update.argtypes = [
            ctypes.c_char_p,
            c_size_t,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(c_size_t),
        ]
        lib.sdk_env_update.restype = c_int32

        lib.sdk_env_destroy.argtypes = [
            ctypes.c_char_p,
            c_size_t,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(c_size_t),
        ]
        lib.sdk_env_destroy.restype = c_int32

        # ── 内存管理 ─────────────────────────────────────────────────────────
        lib.sdk_free.argtypes  = [c_void_p]
        lib.sdk_free.restype   = None

        lib.sdk_malloc.argtypes = [c_size_t]
        lib.sdk_malloc.restype  = c_void_p

        # ── 返回码分类 ────────────────────────────────────────────────────────
        lib.sdk_is_ok.argtypes    = [c_int32]
        lib.sdk_is_ok.restype     = c_bool

        lib.sdk_is_done.argtypes  = [c_int32]
        lib.sdk_is_done.restype   = c_bool

        lib.sdk_is_reqid.argtypes = [c_int32]
        lib.sdk_is_reqid.restype  = c_bool

        lib.sdk_is_error.argtypes = [c_int32]
        lib.sdk_is_error.restype  = c_bool

        lib.sdk_is_warn.argtypes  = [c_int32]
        lib.sdk_is_warn.restype   = c_bool

        lib.sdk_is_event.argtypes = [c_int32]
        lib.sdk_is_event.restype  = c_bool

        # ── 错误描述 ─────────────────────────────────────────────────────────
        lib.sdk_error_string.argtypes = [ctypes.c_int]
        lib.sdk_error_string.restype  = ctypes.c_char_p

        lib.sdk_error_name.argtypes = [ctypes.c_int]
        lib.sdk_error_name.restype  = ctypes.c_char_p

        lib.sdk_event_name.argtypes = [ctypes.c_int]
        lib.sdk_event_name.restype  = ctypes.c_char_p

    # ── 辅助工具 ─────────────────────────────────────────────────────────────

    def take_string(self, ptr: ctypes.c_char_p, length: int) -> str:
        """
        读取 SDK 分配的字符串并通过 sdk_free 释放它。

        :param ptr:    SDK 返回的 char* 指针（c_char_p 实例）
        :param length: 字节数
        :return:       解码后的 Python 字符串
        """
        if not ptr or length == 0:
            return ""
        try:
            raw = ctypes.string_at(ptr, length)
            return raw.decode("utf-8", errors="replace")
        finally:
            self._lib.sdk_free(ptr)

    def is_ok(self, code: int) -> bool:
        return bool(self._lib.sdk_is_ok(code))

    def is_done(self, code: int) -> bool:
        return bool(self._lib.sdk_is_done(code))

    def is_error(self, code: int) -> bool:
        return bool(self._lib.sdk_is_error(code))

    def is_warn(self, code: int) -> bool:
        return bool(self._lib.sdk_is_warn(code))

    def is_event(self, code: int) -> bool:
        return bool(self._lib.sdk_is_event(code))

    def is_reqid(self, code: int) -> bool:
        return bool(self._lib.sdk_is_reqid(code))

    def error_string(self, code: int) -> str:
        ptr = self._lib.sdk_error_string(code)
        if not ptr:
            return f"SDK error code {code}"
        return ptr.decode("utf-8", errors="replace")
