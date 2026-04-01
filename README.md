# brosdk-sdk-python

[![PyPI version](https://img.shields.io/pypi/v/brosdk-sdk)](https://pypi.org/project/brosdk-sdk/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)

Python 语言绑定库 + 交互式命令行 Demo。

通过 `ctypes` 动态加载平台 DLL/dylib，暴露安全、符合 Python 惯用法的 API。

## 安装

```bash
# 从 PyPI 安装（推荐）
pip install brosdk-sdk

# 从源码安装
git clone https://github.com/browsersdk/brosdk-sdk-python.git
cd brosdk-sdk-python
pip install .
```

## 项目结构

```
brosdk-sdk-python/
├── brosdk/
│   ├── __init__.py      # 公共 API 导出
│   ├── ffi.py           # 原始 C ctypes 绑定
│   ├── manager.py       # 高级安全封装 + 事件回调
│   ├── api.py           # REST API 客户端
│   └── console.py       # Windows DLL 控制台输出修复
├── libs/
│   ├── brosdk.dll       # Windows x64 原生库
│   └── brosdk.dylib     # macOS arm64 原生库
├── demo.py              # 交互式命令行 Demo
├── pyproject.toml       # 项目配置
├── requirements.txt     # 可选依赖
└── README.md
```

## 环境要求

- Python 3.8+
- 从 [github.com/browsersdk/brosdk-sdk/releases](https://github.com/browsersdk/brosdk-sdk/releases) 下载原生库并放置到 `libs/` 目录

## 快速开始

### 安装依赖（可选）

```bash
pip install -r requirements.txt
```

> 不安装也能运行，`requests` 会降级到内置 `urllib`，`colorama` 会降级为无色输出。

### 运行 Demo

```bash
# 交互式菜单
python demo.py

# 预填 API Key 直接进入
python demo.py --api-key YOUR_API_KEY

# 快速演示（自动执行所有步骤）
python demo.py --quick --api-key YOUR_API_KEY

# 使用已有环境跳过创建步骤
python demo.py --quick --api-key YOUR_API_KEY --env-id ENV_ID

# 开启详细日志
python demo.py --verbose
```

### Demo 使用流程

1. **选择 `1`** → 输入 API Key → 自动获取 userSig → 初始化 SDK（API Key 会自动记住）
2. **选择 `2`** → 查看环境列表（SDK 接口或 REST API）
3. **选择 `3`** → 选择内核版本（可选代理）→ 创建新环境
4. **选择 `4`** → 启动浏览器环境（有记住的环境 ID 时会询问是否复用）
5. **选择 `5`** → 关闭浏览器环境
6. **选择 `6`** → 查看 SDK 信息
7. **选择 `7`** → 更新动态库（从 GitHub Releases 自动下载）

> Demo 会自动记住最后一次使用的环境 ID 和 API Key，下次启动无需重复输入。

## 库使用方式

### 基础用法

```python
from brosdk import BrosdkManager

def on_event(event):
    print(f"SDK 事件: code={event.code}, data={event.data}")

sdk = BrosdkManager()
sdk.on_event(on_event)

# 加载原生库
sdk.load("libs/brosdk.dll")      # Windows
# sdk.load("libs/brosdk.dylib")  # macOS

# 初始化（user_sig 通过 REST API 获取）
sdk.init("your_user_sig", "/tmp/.brosdk", port=8080)

# 启动环境
import json
sdk.browser_open(json.dumps({
    "envs": [{"envId": "env-001", "args": ["--no-first-run"]}]
}))

# 关闭环境
sdk.browser_close("env-001")

sdk.shutdown()
```

### 使用上下文管理器

```python
from brosdk import BrosdkManager

with BrosdkManager("libs/brosdk.dll") as sdk:
    sdk.init("user_sig", "/tmp/.brosdk")
    sdk.browser_open('{"envs": [{"envId": "env-001"}]}')
    # SDK 会在 with 块结束时自动 shutdown
```

### REST API 客户端

```python
from brosdk.api import BrosdkApiClient

client = BrosdkApiClient(api_key="your-api-key")

# 获取 userSig
user_sig = client.get_user_sig()

# 创建环境
env = client.create_env(kernel_version="127", proxy="http://127.0.0.1:8080")
print(f"创建成功: {env.env_id}")

# 查询环境列表
result = client.page_env(page=1, page_size=20)
for e in result.list:
    print(f"{e.env_id}: {e.env_name} ({e.kernel_version})")

# 获取所有环境（自动翻页）
all_envs = client.list_all_envs()
```

### 监听 SDK 事件

```python
from brosdk import BrosdkManager, SdkEvent

sdk = BrosdkManager()

@sdk.on_event
def handle_event(event: SdkEvent):
    if event.is_ok():
        print(f"成功: {event.data}")
    else:
        data = event.data_json()  # 自动解析 JSON
        print(f"事件 code={event.code}: {data}")
```

> **注意**：`browser_open` 是异步操作，结果通过事件回调返回，不阻塞主线程。

## API 参考

### `BrosdkManager`

| 方法 | 说明 |
|------|------|
| `load(lib_path)` | 加载原生库，注册回调 |
| `init(user_sig, work_dir, port)` | 用凭据初始化 SDK |
| `sdk_info()` | 查询 SDK 运行时信息 |
| `browser_open(json_str)` | 启动浏览器环境（异步） |
| `browser_close(env_id)` | 关闭浏览器环境 |
| `token_update(token_json)` | 刷新访问令牌 |
| `env_create(config)` | 创建新环境 |
| `env_page(page, page_size)` | 分页查询环境列表 |
| `env_update(config)` | 更新环境配置 |
| `env_destroy(env_id)` | 销毁环境 |
| `shutdown()` | 优雅关闭 |
| `on_event(callback)` | 注册事件监听器 |
| `off_event(callback)` | 移除事件监听器 |

### `BrosdkApiClient`

| 方法 | 说明 |
|------|------|
| `get_user_sig(duration)` | API Key → userSig |
| `create_env(kernel_version, ...)` | 创建环境 |
| `page_env(page, page_size)` | 分页查询环境 |
| `list_all_envs(page_size)` | 获取所有环境（自动翻页） |

### `SdkEvent`

```python
@dataclass
class SdkEvent:
    code: int    # SDK 状态码
    data: str    # JSON 数据字符串

    def is_ok(self) -> bool: ...       # 是否成功
    def data_json(self) -> Any: ...    # 解析 data 为 Python 对象
```

## 构建

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 构建发布包
python -m build

# 上传到 PyPI
twine upload dist/*
```

## 特性

- **记住环境**：自动保存最后一次使用的环境 ID 和 API Key（`~/.brosdk-demo.json`）
- **动态库更新**：一键从 GitHub Releases 下载并安装最新版本动态库
- **跨平台**：支持 Windows（x64）、macOS（arm64）、Linux（x64）
- **零强制依赖**：核心库无第三方依赖，requests/colorama 为可选增强

## 协议

MIT
