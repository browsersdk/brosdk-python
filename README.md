# BroSDK Python SDK

[English](README_EN.md) | 简体中文

[![PyPI version](https://img.shields.io/pypi/v/brosdk)](https://pypi.org/project/brosdk/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

`brosdk-python` 是 BroSDK 的 Python 语言绑定和命令行 Demo。它通过 `ctypes` 动态加载 BroSDK 原生动态库，将浏览器环境创建、环境列表、浏览器启动/关闭、Token 更新、SDK 信息查询和异步事件回调封装为 Python API。

适用于自动化脚本、测试平台、数据采集控制台、AI Agent 工具链，以及需要在 Python 服务中管理独立浏览器环境的业务系统。

## 核心能力

- 加载 Windows / macOS / Linux 平台的 BroSDK 原生动态库。
- 使用 `userSig` 初始化 SDK，并指定工作目录和本地服务端口。
- 创建、查询、更新、销毁浏览器环境。
- 启动和关闭指定环境的浏览器实例。
- 监听 SDK 异步事件，处理浏览器启动结果、错误和状态通知。
- 使用 REST API 客户端通过 API Key 获取 `userSig`、创建环境和分页查询环境。
- 提供交互式 Demo，便于快速验证 API Key、内核版本和环境启动流程。

## 安装

```bash
pip install brosdk
```

从源码安装：

```bash
git clone https://github.com/browsersdk/brosdk-python.git
cd brosdk-python
pip install .
```

安装可选开发依赖：

```bash
pip install -e ".[dev]"
```

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.8+ |
| 原生库 | `brosdk.dll`、`brosdk.dylib` 或 Linux 对应动态库 |
| 认证 | BroSDK API Key 或可用的 `userSig` |

原生库可从 [brosdk releases](https://github.com/browsersdk/brosdk/releases) 获取，并放置到 `libs/` 或业务系统约定的位置。

## 快速开始

### 运行交互式 Demo

```bash
python demo.py
```

常用参数：

```bash
python demo.py --api-key YOUR_API_KEY
python demo.py --quick --api-key YOUR_API_KEY
python demo.py --quick --api-key YOUR_API_KEY --env-id ENV_ID
python demo.py --verbose
```

Demo 流程：

1. 输入 API Key，自动换取 `userSig` 并初始化 SDK。
2. 查询环境列表或选择内核版本创建新环境。
3. 启动浏览器环境，首次启动时可能触发内核下载。
4. 关闭环境并查看 SDK 信息或事件回调。

Demo 会将最近使用的 API Key 和环境 ID 保存到 `~/.brosdk-demo.json`，用于下次快速调试。生产环境请使用安全的密钥管理方式。

### 在代码中使用

```python
import json
from brosdk import BrosdkManager


def handle_event(event):
    print(f"SDK event: code={event.code}, data={event.data}")


sdk = BrosdkManager()
sdk.on_event(handle_event)

sdk.load("libs/brosdk.dll")      # Windows
# sdk.load("libs/brosdk.dylib")  # macOS

sdk.init("your_user_sig", "./workDir", port=8080)

sdk.browser_open(json.dumps({
    "envs": [
        {
            "envId": "env-001",
            "args": ["--no-first-run"]
        }
    ]
}))

sdk.browser_close("env-001")
sdk.shutdown()
```

使用上下文管理器：

```python
from brosdk import BrosdkManager

with BrosdkManager("libs/brosdk.dll") as sdk:
    sdk.init("your_user_sig", "./workDir", port=8080)
    sdk.browser_open('{"envs": [{"envId": "env-001"}]}')
```

## REST API 客户端

`BrosdkApiClient` 用于访问 BroSDK 服务端接口，常见场景是用 API Key 换取 `userSig`，或在初始化 SDK 前创建和查询环境。

```python
from brosdk.api import BrosdkApiClient

client = BrosdkApiClient(api_key="your-api-key")

user_sig = client.get_user_sig()

env = client.create_env(kernel_version="127", proxy="http://127.0.0.1:8080")
print(env.env_id)

page = client.page_env(page=1, page_size=20)
for item in page.list:
    print(item.env_id, item.env_name, item.kernel_version)
```

## API 概览

### `BrosdkManager`

| 方法 | 说明 |
|------|------|
| `load(lib_path)` | 加载原生动态库并注册回调 |
| `init(user_sig, work_dir, port)` | 初始化 SDK |
| `sdk_info()` | 查询 SDK 运行时信息 |
| `browser_open(json_str)` | 启动浏览器环境，结果通过事件返回 |
| `browser_close(env_id)` | 关闭浏览器环境 |
| `token_update(token_json)` | 刷新访问令牌 |
| `env_create(config)` | 创建浏览器环境 |
| `env_page(page, page_size)` | 分页查询环境 |
| `env_update(config)` | 更新环境配置 |
| `env_destroy(env_id)` | 销毁环境 |
| `shutdown()` | 关闭 SDK 并释放资源 |
| `on_event(callback)` | 注册事件监听器 |
| `off_event(callback)` | 移除事件监听器 |

### `BrosdkApiClient`

| 方法 | 说明 |
|------|------|
| `get_user_sig(duration)` | 使用 API Key 获取 `userSig` |
| `create_env(kernel_version, ...)` | 创建浏览器环境 |
| `page_env(page, page_size)` | 分页查询环境 |
| `list_all_envs(page_size)` | 自动翻页获取所有环境 |

### `SdkEvent`

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class SdkEvent:
    code: int
    data: str

    def is_ok(self) -> bool: ...
    def data_json(self) -> Any: ...
```

`browser_open` 等接口可能是异步操作，同步返回值只表示请求是否提交成功，最终结果应以 SDK 事件回调为准。

## 项目结构

```text
brosdk-python/
├── brosdk/
│   ├── __init__.py      # 公共 API 导出
│   ├── ffi.py           # ctypes 原始 C 绑定
│   ├── manager.py       # 高级封装和事件回调
│   ├── api.py           # REST API 客户端
│   └── console.py       # Windows 控制台输出处理
├── libs/                # 原生动态库放置目录
├── demo.py              # 交互式命令行 Demo
├── pyproject.toml       # Python 包配置
├── requirements.txt     # 可选运行依赖
└── README.md
```

## 与 BroSDK 生态的关系

| 仓库 | 说明 |
|------|------|
| [brosdk](https://github.com/browsersdk/brosdk) | 原生 C/C++ SDK |
| [brosdk-core](https://github.com/browsersdk/brosdk-core) | 浏览器内核版本和平台支持 |
| [brosdk-docs](https://github.com/browsersdk/brosdk-docs) | 官方文档和 API 参考 |
| [browser-demo](https://github.com/browsersdk/browser-demo) | 完整服务端和桌面客户端示例 |

## 开发

```bash
pip install -e ".[dev]"
pytest
python -m build
```

发布前建议确认：

- 示例中的 API Key、Token 和环境 ID 均为占位符。
- 本地已放置目标平台原生动态库。
- `browser_open` 的异步事件可以被正常接收。

## License

MIT
