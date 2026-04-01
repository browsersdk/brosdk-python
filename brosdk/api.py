"""
brosdk.api
==========

REST API 客户端，对应 Rust commands.rs 中的 HTTP 操作。

封装 brosdk.com 的 REST API，提供：
- 用 API Key 换取 userSig
- 创建浏览器环境
- 分页查询环境列表

使用示例
--------
.. code-block:: python

    from brosdk.api import BrosdkApiClient

    client = BrosdkApiClient(api_key="your-api-key")

    # 获取 userSig
    user_sig = client.get_user_sig()

    # 创建环境
    env = client.create_env(kernel_version="127")
    print(f"创建成功: {env.env_id}")

    # 查询环境列表
    result = client.page_env(page=1, page_size=20)
    for env in result.list:
        print(f"{env.env_id}: {env.env_name}")
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    # 降级到 urllib
    import urllib.request
    import urllib.error
    import json as _json

logger = logging.getLogger(__name__)

# ── 端点常量 ─────────────────────────────────────────────────────────────────

BASE_URL         = "https://api.brosdk.com"
GET_USER_SIG_URL = f"{BASE_URL}/api/v2/browser/getUserSig"
CREATE_ENV_URL   = f"{BASE_URL}/api/v2/browser/create"
PAGE_ENV_URL     = f"{BASE_URL}/api/v2/browser/page"


# ── 数据模型 ─────────────────────────────────────────────────────────────────

@dataclass
class FingerConfig:
    """浏览器指纹配置。"""
    kernel:        str = "Chrome"
    kernelVersion: str = "127"
    system:        str = "All Windows"
    publicIp:      str = "127.0.0.1"

    def to_dict(self) -> dict:
        return {
            "kernel":        self.kernel,
            "kernelVersion": self.kernelVersion,
            "system":        self.system,
            "publicIp":      self.publicIp,
        }


@dataclass
class EnvInfo:
    """环境信息，从 API 响应中解析。"""
    env_id:         str
    env_name:       str
    kernel_version: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "EnvInfo":
        finger = d.get("finger") or {}
        return cls(
            env_id         = d.get("envId", ""),
            env_name       = d.get("envName", ""),
            kernel_version = finger.get("kernelVersion", ""),
        )


@dataclass
class PageEnvResult:
    """分页查询环境列表的结果。"""
    list:  List[EnvInfo]
    total: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "PageEnvResult":
        items = [EnvInfo.from_dict(item) for item in (d.get("list") or [])]
        return cls(list=items, total=d.get("total", 0))


# ── HTTP 工具 ─────────────────────────────────────────────────────────────────

def _do_post(url: str, headers: dict, body: dict) -> dict:
    """
    统一 HTTP POST：优先用 requests，降级到 urllib。

    :return: 解析后的响应 JSON 字典。
    :raises RuntimeError: 网络错误或非 2xx 响应。
    """
    import json

    if _HAS_REQUESTS:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()
    else:
        import urllib.request, urllib.error
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code}: {body_text}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e


# ── 客户端 ────────────────────────────────────────────────────────────────────

class BrosdkApiClient:
    """
    brosdk REST API 客户端。

    :param api_key:     API Key（Bearer 令牌）。
    :param customer_id: 客户 ID，默认 "default"。
    """

    def __init__(self, api_key: str, customer_id: str = "default") -> None:
        if not api_key:
            raise ValueError("api_key cannot be empty")
        self._api_key     = api_key
        self._customer_id = customer_id

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept":        "application/json",
            "Content-Type":  "application/json",
        }

    def _check_response(self, data: dict, operation: str) -> dict:
        """校验 API 响应码，非 200 时抛出异常。"""
        code = data.get("code", -1)
        msg  = data.get("msg", "unknown error")
        if code != 200:
            raise RuntimeError(f"{operation} failed: {msg} (code={code})")
        return data.get("data") or {}

    # ── 认证 ─────────────────────────────────────────────────────────────────

    def get_user_sig(self, duration: int = 2_592_000) -> str:
        """
        用 API Key 换取 userSig。

        :param duration: userSig 有效期（秒），默认 30 天。
        :return:         userSig 字符串。
        :raises RuntimeError: 请求失败或服务端返回错误。
        """
        body = {
            "customerId": self._customer_id,
            "duration":   duration,
        }
        logger.info("Fetching userSig from %s", GET_USER_SIG_URL)
        resp = _do_post(GET_USER_SIG_URL, self._headers, body)
        data = self._check_response(resp, "get_user_sig")
        user_sig = data.get("userSig", "")
        if not user_sig:
            raise RuntimeError("get_user_sig: response missing userSig field")
        logger.info("userSig obtained successfully")
        return user_sig

    # ── 环境管理 ─────────────────────────────────────────────────────────────

    def create_env(
        self,
        kernel_version: str = "127",
        env_name:       Optional[str] = None,
        device_name:    str = "brosdk-python-demo",
        proxy:          Optional[str] = None,
        system:         str = "All Windows",
        public_ip:      str = "127.0.0.1",
    ) -> EnvInfo:
        """
        创建新的浏览器环境。

        :param kernel_version: Chrome 内核版本号，如 "127"、"131"、"134"。
        :param env_name:       自定义环境名称，默认自动生成。
        :param device_name:    设备名称。
        :param proxy:          代理地址，如 ``"http://127.0.0.1:8080"``，None 表示不使用代理。
        :param system:         操作系统标识。
        :param public_ip:      公网 IP（指纹参数）。
        :return:               :class:`EnvInfo` 实例，包含 env_id 等信息。
        :raises RuntimeError:  请求失败时。
        """
        if env_name is None:
            env_name = f"env-{int(time.time())}"

        body: Dict[str, Any] = {
            "customerId": self._customer_id,
            "deviceName": device_name,
            "envName":    env_name,
            "finger": {
                "kernel":        "Chrome",
                "kernelVersion": kernel_version,
                "system":        system,
                "publicIp":      public_ip,
            },
        }
        if proxy:
            body["proxy"] = proxy

        logger.info("Creating env: %s", body)
        resp = _do_post(CREATE_ENV_URL, self._headers, body)
        data = self._check_response(resp, "create_env")
        env = EnvInfo(
            env_id   = data.get("envId", ""),
            env_name = data.get("envName", ""),
        )
        logger.info("Environment created: %s (%s)", env.env_name, env.env_id)
        return env

    def page_env(self, page: int = 1, page_size: int = 50) -> PageEnvResult:
        """
        分页查询环境列表。

        :param page:      页码，从 1 开始。
        :param page_size: 每页数量。
        :return:          :class:`PageEnvResult` 实例。
        :raises RuntimeError: 请求失败时。
        """
        body = {
            "customerId": self._customer_id,
            "page":       page,
            "page_size":  page_size,
        }
        logger.info("Fetching env list: page=%d, page_size=%d", page, page_size)
        resp = _do_post(PAGE_ENV_URL, self._headers, body)
        data = self._check_response(resp, "page_env")
        result = PageEnvResult.from_dict(data)
        logger.info("Fetched %d environments (total=%d)", len(result.list), result.total)
        return result

    def list_all_envs(self, page_size: int = 100) -> List[EnvInfo]:
        """
        获取所有环境（自动翻页）。

        :param page_size: 每页数量，默认 100。
        :return:          所有环境的列表。
        """
        all_envs: List[EnvInfo] = []
        page = 1
        while True:
            result = self.page_env(page=page, page_size=page_size)
            all_envs.extend(result.list)
            if len(all_envs) >= result.total or not result.list:
                break
            page += 1
        return all_envs
