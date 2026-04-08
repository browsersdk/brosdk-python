#!/usr/bin/env python3
"""
Brosdk SDK Python Demo
======================

交互式命令行演示，功能对应 Rust Tauri Demo 的完整使用流程：

  1. 填写 API Key → 初始化 SDK
  2. 查看/选择环境列表
  3. 创建新环境
  4. 启动 / 关闭浏览器环境
  5. 更新动态库（从 GitHub Releases 下载）

特性：
  - 记住最后一次使用的环境 ID 和 API Key（持久化到 ~/.brosdk-demo.json）
  - 支持从 GitHub Releases 自动下载并安装最新版本动态库
  - 下载进度条显示

用法
----
    python demo.py                     # 交互式菜单
    python demo.py --api-key <KEY>     # 预填 API Key 直接运行
    python demo.py --help              # 帮助信息
"""

import argparse
import json
import logging
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from typing import Optional

# 颜色输出支持（Windows 需要额外处理）
try:
    import colorama
    colorama.init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


# ── 颜色工具 ──────────────────────────────────────────────────────────────────

def _color(text: str, code: str) -> str:
    if not _HAS_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def green(s: str)  -> str: return _color(s, "32")
def red(s: str)    -> str: return _color(s, "31")
def yellow(s: str) -> str: return _color(s, "33")
def cyan(s: str)   -> str: return _color(s, "36")
def bold(s: str)   -> str: return _color(s, "1")
def dim(s: str)    -> str: return _color(s, "2")


# ── 日志输出 ──────────────────────────────────────────────────────────────────

def log_ok(msg: str)   -> None: print(f"  {green('✓')} {msg}")
def log_err(msg: str)  -> None: print(f"  {red('✗')} {msg}")
def log_info(msg: str) -> None: print(f"  {cyan('·')} {msg}")
def log_warn(msg: str) -> None: print(f"  {yellow('!')} {msg}")


def _ts() -> str:
    return time.strftime("%H:%M:%S")


# ── 持久化配置（记住最后环境 ID / API Key） ────────────────────────────────

_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".brosdk-demo.json")


def _load_config() -> dict:
    """加载持久化配置文件。"""
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(cfg: dict) -> None:
    """保存持久化配置文件。"""
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 默认库路径 ────────────────────────────────────────────────────────────────

def _default_lib_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()
    if system == "Windows":
        return os.path.join(base, "libs", "windows-x64", "brosdk.dll")
    elif system == "Darwin":
        return os.path.join(base, "libs", "macos-arm64", "brosdk.dylib")
    else:
        return os.path.join(base, "libs", "linux-x64", "libbrosdk.so")


# ── Lib 更新下载 ─────────────────────────────────────────────────────────────

_GITHUB_RELEASES_API = "https://api.github.com/repos/browsersdk/brosdk/releases/latest"

# 平台 → asset 文件名模板（{version} 占位）
_PLATFORM_ASSET = {
    ("Windows",  "AMD64"): "brosdk-{version}-windows-x64.zip",
    ("Darwin",   "ARM64"): "brosdk-{version}-darwin-arm64.tar.gz",
    ("Darwin",   "x86_64"): "brosdk-{version}-darwin-arm64.tar.gz",
    ("Linux",    "x86_64"): "brosdk-{version}-linux-x64.tar.gz",
}


def _detect_platform_asset() -> str:
    """检测当前平台对应的 asset 文件名模板。"""
    system = platform.system()
    machine = platform.machine()
    key = (system, machine)
    if key in _PLATFORM_ASSET:
        return _PLATFORM_ASSET[key]
    # 回退
    if system == "Windows":
        return "brosdk-{version}-windows-x64.zip"
    elif system == "Darwin":
        return "brosdk-{version}-darwin-arm64.tar.gz"
    return "brosdk-{version}-linux-x64.tar.gz"


def _extract_zip(zip_path: str, dest_dir: str) -> None:
    """解压 zip 文件到目标目录。"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _extract_tar(tar_path: str, dest_dir: str) -> None:
    """解压 tar.gz 文件到目标目录。"""
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest_dir)


def step_update_lib(lib_path_hint: str = "") -> bool:
    """
    从 GitHub Releases 下载最新版本的 brosdk 动态库。

    :param lib_path_hint: 当前使用的 lib 路径，用于推断 libs/ 目录位置。
    :return: 是否成功更新。
    """
    print()
    print(bold("═══ 更新 brosdk 动态库 ═══"))

    # 1. 获取最新版本信息
    asset_template = _detect_platform_asset()
    log_info("正在查询最新版本...")
    try:
        req = urllib.request.Request(_GITHUB_RELEASES_API)
        req.add_header("User-Agent", "brosdk-python-demo")
        req.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_err(f"获取 Release 信息失败: {e}")
        return False

    tag = release.get("tag_name", "")
    version = tag.lstrip("v")
    log_info(f"最新版本: {tag}")

    if not version:
        log_err("无法解析版本号")
        return False

    # 2. 找到匹配当前平台的 asset
    asset_name = asset_template.format(version=version)
    asset_url = None
    for a in release.get("assets", []):
        if a.get("name", "") == asset_name:
            asset_url = a.get("browser_download_url", "")
            break

    if not asset_url:
        log_err(f"未找到适配当前平台的资产: {asset_name}")
        log_info("可用资产:")
        for a in release.get("assets", []):
            print(f"    - {a.get('name', '')}")
        return False

    log_info(f"下载: {asset_name}")

    # 3. 确定 libs/ 目录
    project_dir = os.path.dirname(os.path.abspath(__file__))
    libs_dir = os.path.join(project_dir, "libs")
    os.makedirs(libs_dir, exist_ok=True)

    # 4. 下载到临时文件
    tmp_dir = tempfile.mkdtemp(prefix="brosdk-update-")
    try:
        tmp_file = os.path.join(tmp_dir, asset_name)
        log_info("正在下载...")
        try:
            urllib.request.urlretrieve(asset_url, tmp_file, reporthook=_download_progress)
        except Exception as e:
            log_err(f"下载失败: {e}")
            return False
        print()  # 进度条后换行

        # 5. 解压
        log_info("正在解压...")
        extract_dir = os.path.join(tmp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)

        if asset_name.endswith(".zip"):
            _extract_zip(tmp_file, extract_dir)
        else:
            _extract_tar(tmp_file, extract_dir)

        # 6. 找到解压后的动态库文件并复制到 libs/ 对应子目录
        lib_patterns = ["brosdk.dll", "brosdk.dylib", "libbrosdk.so"]
        found_libs = []
        for root, _dirs, files in os.walk(extract_dir):
            for fname in files:
                if fname in lib_patterns:
                    found_libs.append(os.path.join(root, fname))

        if not found_libs:
            log_err("解压后未找到动态库文件")
            return False

        for lib_file in found_libs:
            fname = os.path.basename(lib_file)
            # 推断平台子目录
            if fname == "brosdk.dll":
                subdir = "windows-x64"
            elif fname == "brosdk.dylib":
                subdir = "macos-arm64"
            else:
                subdir = "linux-x64"
            target_dir = os.path.join(libs_dir, subdir)
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, fname)
            shutil.copy2(lib_file, target)
            log_ok(f"已安装: {os.path.relpath(target, project_dir)}")

        log_ok(f"动态库已更新到 {version}")
        return True

    except Exception as e:
        log_err(f"更新失败: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _download_progress(block_num: int, block_size: int, total_size: int) -> None:
    """下载进度回调。"""
    if total_size <= 0:
        return
    downloaded = block_num * block_size
    pct = min(downloaded * 100 // total_size, 100)
    mb_down = downloaded / (1024 * 1024)
    mb_total = total_size / (1024 * 1024)
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stdout.write(f"\r  下载中: [{bar}] {pct}% ({mb_down:.1f}/{mb_total:.1f} MB)")
    sys.stdout.flush()


# ── 主演示类 ──────────────────────────────────────────────────────────────────

class BrosdkDemo:
    """交互式演示控制器。"""

    def __init__(self, api_key: str = "", lib_path: str = "") -> None:
        self.api_key  = api_key
        self.lib_path = lib_path or _default_lib_path()

        self.sdk: Optional[object]      = None   # BrosdkManager 实例
        self.api_client: Optional[object] = None  # BrosdkApiClient 实例
        self.sdk_ready = False
        self.env_list: list = []

        # 事件队列（异步回调写入，主线程打印）
        self._event_lock = threading.Lock()
        self._pending_events: list = []

        # 从持久化配置恢复
        cfg = _load_config()
        self.last_env_id: str = cfg.get("last_env_id", "")
        if not self.api_key:
            self.api_key = cfg.get("api_key", "")

    # ── 持久化 ────────────────────────────────────────────────────────────────

    def _save_env(self, env_id: str) -> None:
        """记住最后一次使用的环境 ID。"""
        self.last_env_id = env_id
        cfg = _load_config()
        cfg["last_env_id"] = env_id
        _save_config(cfg)

    def _save_api_key(self, key: str) -> None:
        """记住 API Key。"""
        cfg = _load_config()
        cfg["api_key"] = key
        _save_config(cfg)

    # ── 事件处理 ──────────────────────────────────────────────────────────────

    def _on_sdk_event(self, event) -> None:
        with self._event_lock:
            self._pending_events.append(event)

    def _flush_events(self) -> None:
        with self._event_lock:
            events, self._pending_events = self._pending_events, []
        for event in events:
            try:
                data_obj = event.data_json()
                data_str = json.dumps(data_obj, ensure_ascii=False) if isinstance(data_obj, dict) else str(data_obj)
            except Exception:
                data_str = event.data
            print(f"\n  {cyan('[SDK事件]')} code={event.code}  data={data_str}")

    # ── 初始化 ────────────────────────────────────────────────────────────────

    def step_init_sdk(self) -> bool:
        """步骤 1：用 API Key 换取 userSig，初始化 SDK。"""
        from brosdk.manager import BrosdkManager
        from brosdk.api import BrosdkApiClient

        print()
        print(bold("═══ 步骤 1：初始化 SDK ═══"))

        # 获取 API Key
        if not self.api_key:
            try:
                self.api_key = input(f"  请输入 API Key {dim('[必填]')}: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return False

        if not self.api_key:
            log_err("API Key 不能为空")
            return False

        # 持久化 API Key
        self._save_api_key(self.api_key)

        # 创建 API 客户端
        self.api_client = BrosdkApiClient(api_key=self.api_key)

        # 换取 userSig
        log_info(f"正在从服务端获取 userSig...")
        try:
            user_sig = self.api_client.get_user_sig()
            log_ok(f"userSig 获取成功")
        except Exception as e:
            log_err(f"获取 userSig 失败: {e}")
            return False

        # 加载并初始化 SDK
        log_info(f"正在加载动态库: {self.lib_path}")

        sdk = BrosdkManager()
        sdk.on_event(self._on_sdk_event)

        try:
            sdk.load(self.lib_path)
            log_ok("动态库加载成功")
        except (FileNotFoundError, RuntimeError) as e:
            log_warn(f"加载动态库失败: {e}")
            log_warn("进入模拟模式（不调用原生 SDK，仅演示 REST API 功能）")
            self.sdk = None
            self.sdk_ready = True
            return True

        # 确保工作目录存在
        work_dir = os.path.join(tempfile.gettempdir(), ".brosdk")
        os.makedirs(work_dir, exist_ok=True)

        log_info(f"正在初始化 SDK，工作目录: {work_dir}")
        try:
            result = sdk.init(user_sig, work_dir, port=8080)
            log_ok(f"SDK 初始化成功: {result}")
        except RuntimeError as e:
            log_err(f"SDK 初始化失败: {e}")
            return False

        self.sdk = sdk
        self.sdk_ready = True

        # 显示 SDK 信息
        try:
            info_str = sdk.sdk_info()
            info = json.loads(info_str)
            log_info(f"SDK 信息: " + "  ".join(f"{k}={v}" for k, v in info.items()))
        except Exception:
            pass

        return True

    # ── 环境列表 ──────────────────────────────────────────────────────────────

    def step_list_envs(self) -> None:
        """步骤 2：查询并展示环境列表。"""
        print()
        print(bold("═══ 步骤 2：环境列表 ═══"))

        if not self.sdk_ready:
            log_err("SDK 未初始化，请先执行步骤 1")
            return

        # 优先用 SDK 接口，降级用 REST API
        if self.sdk is not None:
            log_info("通过 SDK 接口查询环境列表...")
            try:
                result = self.sdk.env_page(page=1, page_size=50)
                envs_raw = result.get("list") or result.get("data", {}).get("list") or []
                self.env_list = envs_raw
                self._print_env_table(envs_raw)
                return
            except Exception as e:
                log_warn(f"SDK 接口失败: {e}，降级使用 REST API")

        # 使用 REST API
        if self.api_client is None:
            log_err("API 客户端未初始化")
            return

        log_info("通过 REST API 查询环境列表...")
        try:
            result = self.api_client.page_env(page=1, page_size=50)
            self.env_list = result.list
            self._print_env_table_api(result.list, result.total)
        except Exception as e:
            log_err(f"查询环境列表失败: {e}")

    def _print_env_table(self, envs: list) -> None:
        if not envs:
            log_info("暂无环境")
            return

        print(f"\n  {'#':<4}{'环境 ID':<28}{'环境名称':<20}{'内核版本':<12}")
        print(f"  {'─'*4}{'─'*28}{'─'*20}{'─'*12}")
        for i, env in enumerate(envs, 1):
            if isinstance(env, dict):
                eid  = env.get("envId", "")
                name = env.get("envName", "")
                kv   = (env.get("finger") or {}).get("kernelVersion", "")
            else:
                eid, name, kv = str(env), "", ""
            print(f"  {i:<4}{cyan(eid):<37}{name:<20}{dim(kv)}")
        print()

    def _print_env_table_api(self, envs: list, total: int) -> None:
        if not envs:
            log_info(f"暂无环境（total={total}）")
            return

        print(f"\n  {'#':<4}{'环境 ID':<28}{'环境名称':<20}{'内核版本':<12}")
        print(f"  {'─'*4}{'─'*28}{'─'*20}{'─'*12}")
        for i, env in enumerate(envs, 1):
            print(f"  {i:<4}{cyan(env.env_id):<37}{env.env_name:<20}{dim(env.kernel_version)}")
        print(f"\n  共 {total} 个环境，当前显示 {len(envs)} 个\n")

    # ── 创建环境 ──────────────────────────────────────────────────────────────

    def step_create_env(self) -> Optional[str]:
        """步骤 3：创建新的浏览器环境，返回 envId。"""
        print()
        print(bold("═══ 步骤 3：创建环境 ═══"))

        if not self.sdk_ready:
            log_err("SDK 未初始化，请先执行步骤 1")
            return None

        # 选择内核版本
        versions = ["127", "131", "134", "138", "140", "141"]
        print(f"  可用内核版本: {', '.join(f'Chrome {v}' for v in versions)}")
        try:
            kv_input = input(f"  请输入内核版本 {dim('[默认 127]')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        kernel_version = kv_input if kv_input in versions else "127"

        # 代理（可选）
        try:
            proxy = input(f"  代理地址 {dim('[可选，如 http://127.0.0.1:8080]')}: ").strip() or None
        except (EOFError, KeyboardInterrupt):
            proxy = None

        # 优先用 SDK 接口
        if self.sdk is not None:
            log_info(f"通过 SDK 创建环境 (Chrome {kernel_version})...")
            import time as _t
            config = {
                "customerId": "default",
                "deviceName": "brosdk-python-demo",
                "envName":    f"env-{int(_t.time())}",
                "finger": {
                    "kernel":        "Chrome",
                    "kernelVersion": kernel_version,
                    "system":        "All Windows",
                    "publicIp":      "127.0.0.1",
                },
            }
            if proxy:
                config["proxy"] = proxy
            try:
                result = self.sdk.env_create(config)
                # 兼容 SDK 返回格式（可能包裹在 data 中）
                data = result.get("data") or result
                env_id = data.get("envId", "")
                env_name = data.get("envName", "")
                if env_id:
                    log_ok(f"环境创建成功: {env_name} ({env_id})")
                    return env_id
                else:
                    log_warn(f"SDK 返回: {result}")
            except Exception as e:
                log_warn(f"SDK 接口失败: {e}，降级使用 REST API")

        # 降级用 REST API
        if self.api_client is None:
            log_err("API 客户端未初始化")
            return None

        log_info(f"通过 REST API 创建环境 (Chrome {kernel_version})...")
        try:
            env = self.api_client.create_env(
                kernel_version=kernel_version,
                proxy=proxy,
            )
            log_ok(f"环境创建成功: {env.env_name} ({env.env_id})")
            return env.env_id
        except Exception as e:
            log_err(f"创建环境失败: {e}")
            return None

    # ── 启动/关闭环境 ─────────────────────────────────────────────────────────

    def step_start_env(self, env_id: str) -> None:
        """步骤 4：启动浏览器环境。"""
        print()
        print(bold("═══ 步骤 4：启动环境 ═══"))

        if not self.sdk_ready:
            log_err("SDK 未初始化，请先执行步骤 1")
            return

        if self.sdk is None:
            log_warn("模拟模式：不执行实际启动")
            return

        config = json.dumps({
            "envs": [{
                "envId": env_id,
                "args":  ["--no-first-run", "--no-default-browser-check"],
            }]
        })
        log_info(f"正在启动环境: {env_id}")
        try:
            self.sdk.browser_open(config)
            log_ok(f"启动请求已发送，等待 SDK 事件回调...")
            # 等待一段时间，接收异步事件
            for _ in range(6):
                time.sleep(0.5)
                self._flush_events()
        except RuntimeError as e:
            log_err(f"启动失败: {e}")

    def step_stop_env(self, env_id: str) -> None:
        """步骤 5：关闭浏览器环境。"""
        print()
        print(bold("═══ 步骤 5：关闭环境 ═══"))

        if not self.sdk_ready:
            log_err("SDK 未初始化")
            return

        if self.sdk is None:
            log_warn("模拟模式：不执行实际关闭")
            return

        log_info(f"正在关闭环境: {env_id}")
        try:
            self.sdk.browser_close(env_id)
            log_ok(f"环境 {env_id} 已关闭")
        except RuntimeError as e:
            log_err(f"关闭失败: {e}")

    # ── 交互式菜单 ────────────────────────────────────────────────────────────

    def _get_env_id(self) -> str:
        """提示用户输入或从列表中选择环境 ID。"""
        if self.env_list:
            print()
            self._print_env_table(self.env_list) if isinstance(self.env_list[0], dict) \
                else self._print_env_table_api(self.env_list, len(self.env_list))
            try:
                choice = input(f"  输入序号选择，或直接输入环境 ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                return ""
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(self.env_list):
                    env = self.env_list[idx]
                    if isinstance(env, dict):
                        return env.get("envId", "")
                    return env.env_id
            return choice
        else:
            try:
                return input("  请输入环境 ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                return ""

    def run_interactive(self) -> None:
        """启动交互式主菜单。"""
        print()
        print(bold(cyan("╔══════════════════════════════════════╗")))
        print(bold(cyan("║       Brosdk SDK Python Demo         ║")))
        print(bold(cyan("╚══════════════════════════════════════╝")))
        if self.last_env_id:
            print(f"  {dim('上次使用的环境:')} {cyan(self.last_env_id)}")
        print()

        current_env_id = self.last_env_id

        while True:
            self._flush_events()
            print()
            status = green("已就绪") if self.sdk_ready else red("未初始化")
            env_hint = f"  当前环境: {cyan(current_env_id)}" if current_env_id else ""
            print(f"  SDK 状态: {status}{env_hint}")
            print()
            print(f"  {bold('1.')} 初始化 SDK (API Key → userSig → init)")
            print(f"  {bold('2.')} 查询环境列表")
            print(f"  {bold('3.')} 创建新环境")
            print(f"  {bold('4.')} 启动浏览器环境")
            print(f"  {bold('5.')} 关闭浏览器环境")
            print(f"  {bold('6.')} 查看 SDK 信息")
            print(f"  {bold('7.')} 更新动态库 {dim('(从 GitHub Releases 下载)')}")
            print(f"  {bold('q.')} 退出")
            print()

            try:
                choice = input(f"  {bold('请选择操作')} [1-7/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if choice == "1":
                self.step_init_sdk()

            elif choice == "2":
                self.step_list_envs()

            elif choice == "3":
                env_id = self.step_create_env()
                if env_id:
                    current_env_id = env_id
                    self._save_env(env_id)

            elif choice == "4":
                if not current_env_id:
                    current_env_id = self._get_env_id()
                else:
                    # 有记住的环境 ID，询问是否使用
                    print()
                    try:
                        ans = input(f"  使用上次环境 {cyan(current_env_id)}？{dim('[Y/n]')}: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print()
                        continue
                    if ans in ("n", "no"):
                        picked = self._get_env_id()
                        if picked:
                            current_env_id = picked
                if current_env_id:
                    self._save_env(current_env_id)
                    self.step_start_env(current_env_id)

            elif choice == "5":
                if not current_env_id:
                    current_env_id = self._get_env_id()
                else:
                    print()
                    try:
                        ans = input(f"  使用上次环境 {cyan(current_env_id)}？{dim('[Y/n]')}: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print()
                        continue
                    if ans in ("n", "no"):
                        picked = self._get_env_id()
                        if picked:
                            current_env_id = picked
                if current_env_id:
                    self.step_stop_env(current_env_id)

            elif choice == "6":
                if self.sdk is None:
                    log_warn("SDK 未加载")
                else:
                    try:
                        info = json.loads(self.sdk.sdk_info())
                        print()
                        print("  SDK 信息:")
                        for k, v in info.items():
                            print(f"    {dim(k)}: {v}")
                    except Exception as e:
                        log_err(f"获取失败: {e}")

            elif choice == "7":
                step_update_lib(self.lib_path)

            elif choice in ("q", "quit", "exit"):
                break

            else:
                log_warn("无效选择，请输入 1-7 或 q")

        # 退出时关闭 SDK
        print()
        if self.sdk is not None:
            log_info("正在关闭 SDK...")
            try:
                self.sdk.shutdown()
                log_ok("SDK 已关闭")
            except Exception as e:
                log_warn(f"关闭 SDK 时出错: {e}")
        print(cyan("再见！"))
        print()

    def run_quick(self, env_id: Optional[str] = None) -> None:
        """
        快速演示模式（非交互）：
        依次执行 初始化 → 列表 → [创建] → 启动 → 等待 → 关闭
        """
        print()
        print(bold(cyan("── Brosdk SDK Python Quick Demo ──")))
        print()

        if not self.step_init_sdk():
            sys.exit(1)

        self.step_list_envs()

        if not env_id:
            env_id = self.step_create_env()

        if env_id:
            self.step_start_env(env_id)
            log_info("等待 3 秒后关闭环境...")
            for _ in range(6):
                time.sleep(0.5)
                self._flush_events()
            self.step_stop_env(env_id)

        if self.sdk is not None:
            try:
                self.sdk.shutdown()
            except Exception:
                pass


# ── 命令行入口 ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Brosdk SDK Python Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python demo.py                           # 交互式菜单
  python demo.py --api-key YOUR_API_KEY    # 预填 API Key
  python demo.py --quick                   # 快速演示（自动执行所有步骤）
  python demo.py --quick --env-id ENV_ID   # 快速演示，使用指定环境
  python demo.py --verbose                 # 开启详细日志
        """,
    )
    parser.add_argument("--api-key",  default="", help="API Key (Bearer 令牌)")
    parser.add_argument("--lib-path", default="", help="动态库路径（默认根据平台自动选择）")
    parser.add_argument("--env-id",   default="", help="环境 ID（快速模式跳过创建步骤）")
    parser.add_argument("--quick",    action="store_true", help="快速演示模式（非交互）")
    parser.add_argument("--verbose",  action="store_true", help="开启详细日志")

    args = parser.parse_args()

    # 日志级别
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    demo = BrosdkDemo(
        api_key  = args.api_key,
        lib_path = args.lib_path,
    )

    if args.quick:
        demo.run_quick(env_id=args.env_id or None)
    else:
        demo.run_interactive()


if __name__ == "__main__":
    main()
