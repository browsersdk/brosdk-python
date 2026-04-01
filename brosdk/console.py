"""
brosdk.console
==============

Windows 控制台输出修复工具。

解决 DLL 内部 printf/puts 在 Python 进程中无输出的问题。

原因分析
--------
Windows 上 DLL 与 Python 进程各自持有独立的 CRT 实例和 stdout 缓冲区，
DLL 的 printf 写入 DLL 自己的缓冲，Python 不会刷新它，导致输出丢失。

提供三种修复策略（推荐依次尝试）：

1. attach_console()        - 同步 Win32 标准句柄，最通用
2. redirect_crt_stdout()   - 直接同步 DLL 所用的 MSVCRT FILE*，最彻底
3. force_flush_crt()       - 每次操作后强制 flush，轻量级
"""

import ctypes
import os
import sys
import platform
from typing import Optional


def is_windows() -> bool:
    return platform.system() == "Windows"


# ── 方案 A：同步 Win32 标准句柄 ──────────────────────────────────────────────

def attach_console() -> bool:
    """
    将当前进程的 Win32 STD_OUTPUT_HANDLE / STD_ERROR_HANDLE 同步到 CRT。

    适用场景：
    - IDE、子进程、重定向管道中运行时 DLL printf 无输出

    原理：
    - 调用 kernel32.SetStdHandle 将正确的句柄写入进程标准句柄表
    - 调用 MSVCRT._open_osfhandle 将 Win32 句柄绑定到 CRT 文件描述符

    :return: True 表示修复成功，False 表示非 Windows 或失败
    """
    if not is_windows():
        return False

    try:
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE  = -12

        # 获取当前 Python 进程的 stdout 句柄
        stdout_handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

        if stdout_handle and stdout_handle != ctypes.c_void_p(-1).value:
            # 将 Win32 句柄注册到 CRT
            crt_fd = msvcrt.open_osfhandle(stdout_handle, os.O_WRONLY | os.O_TEXT)
            # 同步到文件描述符 1（stdout）
            os.dup2(crt_fd, 1)

        stderr_handle = kernel32.GetStdHandle(STD_ERROR_HANDLE)
        if stderr_handle and stderr_handle != ctypes.c_void_p(-1).value:
            crt_fd = msvcrt.open_osfhandle(stderr_handle, os.O_WRONLY | os.O_TEXT)
            os.dup2(crt_fd, 2)

        return True
    except Exception as e:
        print(f"[brosdk.console] attach_console failed: {e}", file=sys.stderr)
        return False


# ── 方案 B：直接重定向 MSVCRT 的 FILE* stdout ─────────────────────────────────

def redirect_crt_stdout() -> bool:
    """
    直接将 MSVCRT（DLL 所用的 CRT）的 FILE* stdout 重定向到当前终端。

    适用场景：
    - DLL 使用 MSVCRT（Visual C++ 运行时）内部 printf，与 Python 的 CRT 不同

    原理：
    - 打开 "CONOUT$"（Windows 控制台输出设备）
    - 用 freopen 替换 MSVCRT 的 stdout FILE*

    :return: True 表示修复成功
    """
    if not is_windows():
        return False

    try:
        msvcrt_dll = ctypes.CDLL("msvcrt.dll")

        # 获取 MSVCRT 内部的 FILE* stdout 指针
        # Windows 10+ 使用 __acrt_iob_func(0) 获取 stdin/stdout/stderr
        # 旧版本通过 _iob 数组
        stdout_ptr = None
        try:
            # 现代 Windows (VS2015+): __acrt_iob_func(index)
            # index: 0=stdin, 1=stdout, 2=stderr
            acrt_iob_func = msvcrt_dll.__acrt_iob_func
            acrt_iob_func.restype = ctypes.c_void_p
            acrt_iob_func.argtypes = [ctypes.c_uint]
            stdout_ptr = acrt_iob_func(1)  # 1 = stdout
        except AttributeError:
            pass

        if stdout_ptr is None:
            try:
                # 旧版本：直接访问 _iob[1]（每个 FILE 结构体大约 32 字节）
                iob = msvcrt_dll._iob
                stdout_ptr = ctypes.cast(iob, ctypes.c_void_p).value + 32
            except AttributeError:
                pass

        if stdout_ptr is None:
            return False

        # freopen("CONOUT$", "w", stdout_ptr)
        freopen = msvcrt_dll.freopen
        freopen.restype  = ctypes.c_void_p
        freopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]

        result = freopen(b"CONOUT$", b"w", ctypes.c_void_p(stdout_ptr))
        if result:
            # 设置为无缓冲
            setvbuf = msvcrt_dll.setvbuf
            setvbuf.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_size_t]
            setvbuf(result, None, 4, 0)  # _IONBF = 4
            return True

        return False
    except Exception as e:
        print(f"[brosdk.console] redirect_crt_stdout failed: {e}", file=sys.stderr)
        return False


# ── 方案 C：强制刷新 CRT 缓冲（轻量级） ──────────────────────────────────────

def force_flush_crt() -> None:
    """
    强制刷新 MSVCRT 的 stdout / stderr 缓冲区。

    适用场景：
    - 输出延迟（不是真的丢失），调用后终端才能看到之前的输出
    - 可在每次 SDK 调用之后调用

    用法::

        sdk.browser_open(...)
        brosdk.console.force_flush_crt()
    """
    if not is_windows():
        sys.stdout.flush()
        sys.stderr.flush()
        return

    try:
        msvcrt_dll = ctypes.CDLL("msvcrt.dll")
        msvcrt_dll.fflush(None)   # fflush(NULL) 刷新所有打开的流
    except Exception:
        pass

    sys.stdout.flush()
    sys.stderr.flush()


# ── 方案 D：AllocConsole（进程本身没有控制台时） ─────────────────────────────

def alloc_console() -> bool:
    """
    为当前进程申请一个新的控制台窗口（仅当进程没有控制台时有效）。

    适用场景：
    - pythonw.exe 或 GUI 程序（无控制台进程）运行时 DLL printf 无窗口

    注意：
    - 会弹出一个新的黑色命令行窗口
    - 通常在调试场景下使用，生产环境不推荐

    :return: True 表示申请成功或已有控制台
    """
    if not is_windows():
        return False

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ret = kernel32.AllocConsole()
        if ret:
            # 重新绑定 Python 的 sys.stdout/stderr 到新控制台
            sys.stdout = open("CONOUT$", "w")
            sys.stderr = open("CONOUT$", "w")
        return bool(ret)
    except Exception as e:
        print(f"[brosdk.console] alloc_console failed: {e}", file=sys.stderr)
        return False


# ── 自动修复（推荐入口） ──────────────────────────────────────────────────────

def fix_dll_console_output(verbose: bool = False) -> None:
    """
    自动修复 DLL 控制台输出问题（组合方案）。

    推荐在加载 DLL **之前** 调用一次。

    策略顺序：
    1. 先尝试 ``redirect_crt_stdout()``（直接同步 MSVCRT FILE*，最彻底）
    2. 再调用 ``attach_console()``（同步 Win32 句柄到 CRT fd）
    3. 最后 ``force_flush_crt()``（清空已有缓冲）

    :param verbose: 是否打印修复过程日志
    """
    if not is_windows():
        return

    if verbose:
        print("[brosdk.console] Applying DLL console output fix...", flush=True)

    ok1 = redirect_crt_stdout()
    ok2 = attach_console()
    force_flush_crt()

    if verbose:
        print(
            f"[brosdk.console] redirect_crt_stdout={ok1}, attach_console={ok2}",
            flush=True,
        )
