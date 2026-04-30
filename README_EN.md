# BroSDK Python SDK

English | [简体中文](README.md)

[![PyPI version](https://img.shields.io/pypi/v/brosdk)](https://pypi.org/project/brosdk/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

`brosdk-python` is the Python binding and command-line demo for BroSDK. It dynamically loads the BroSDK native library through `ctypes` and exposes Python APIs for browser environment creation, environment listing, browser launch and close, token updates, SDK information, and asynchronous event callbacks.

It is suitable for automation scripts, testing platforms, data collection consoles, AI Agent toolchains, and business systems that need to manage independent browser environments from Python services.

## Core Capabilities

- Load BroSDK native libraries on Windows, macOS, and Linux.
- Initialize the SDK with `userSig`, a working directory, and a local service port.
- Create, query, update, and destroy browser environments.
- Launch and close browser instances for specified environments.
- Listen to SDK asynchronous events for browser launch results, errors, and status notifications.
- Use the REST API client to exchange an API Key for `userSig`, create environments, and query environments by page.
- Provide an interactive demo for quickly verifying API Key, core versions, and environment launch flow.

## Installation

```bash
pip install brosdk
```

Install from source:

```bash
git clone https://github.com/browsersdk/brosdk-python.git
cd brosdk-python
pip install .
```

Install optional development dependencies:

```bash
pip install -e ".[dev]"
```

## Requirements

| Item | Requirement |
|------|-------------|
| Python | 3.8+ |
| Native library | `brosdk.dll`, `brosdk.dylib`, or the Linux dynamic library |
| Authentication | BroSDK API Key or a valid `userSig` |

Native libraries can be downloaded from [brosdk releases](https://github.com/browsersdk/brosdk/releases) and placed under `libs/` or another path defined by your application.

## Quick Start

### Run The Interactive Demo

```bash
python demo.py
```

Common options:

```bash
python demo.py --api-key YOUR_API_KEY
python demo.py --quick --api-key YOUR_API_KEY
python demo.py --quick --api-key YOUR_API_KEY --env-id ENV_ID
python demo.py --verbose
```

Demo flow:

1. Enter an API Key, exchange it for `userSig`, and initialize the SDK.
2. Query the environment list or create a new environment by selecting a core version.
3. Launch the browser environment. The first launch may download the browser core.
4. Close the environment and inspect SDK information or callback events.

The demo stores the last used API Key and environment ID in `~/.brosdk-demo.json` for quicker debugging next time. Use secure credential management in production.

### Use In Code

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

Use a context manager:

```python
from brosdk import BrosdkManager

with BrosdkManager("libs/brosdk.dll") as sdk:
    sdk.init("your_user_sig", "./workDir", port=8080)
    sdk.browser_open('{"envs": [{"envId": "env-001"}]}')
```

## REST API Client

`BrosdkApiClient` accesses BroSDK server APIs. A common use case is exchanging an API Key for `userSig`, or creating and querying environments before SDK initialization.

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

## API Overview

### `BrosdkManager`

| Method | Description |
|--------|-------------|
| `load(lib_path)` | Load the native dynamic library and register callbacks |
| `init(user_sig, work_dir, port)` | Initialize the SDK |
| `sdk_info()` | Query SDK runtime information |
| `browser_open(json_str)` | Launch a browser environment; result is returned by event callback |
| `browser_close(env_id)` | Close a browser environment |
| `token_update(token_json)` | Refresh access token |
| `env_create(config)` | Create a browser environment |
| `env_page(page, page_size)` | Query environments by page |
| `env_update(config)` | Update environment configuration |
| `env_destroy(env_id)` | Destroy an environment |
| `shutdown()` | Shut down the SDK and release resources |
| `on_event(callback)` | Register an event listener |
| `off_event(callback)` | Remove an event listener |

### `BrosdkApiClient`

| Method | Description |
|--------|-------------|
| `get_user_sig(duration)` | Get `userSig` with API Key |
| `create_env(kernel_version, ...)` | Create a browser environment |
| `page_env(page, page_size)` | Query environments by page |
| `list_all_envs(page_size)` | Fetch all environments with automatic paging |

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

APIs such as `browser_open` may be asynchronous. The synchronous return value only indicates whether the request was submitted successfully; the final result should be handled through SDK event callbacks.

## Directory Layout

```text
brosdk-python/
├── brosdk/
│   ├── __init__.py      # Public API exports
│   ├── ffi.py           # Raw C binding through ctypes
│   ├── manager.py       # High-level wrapper and event callbacks
│   ├── api.py           # REST API client
│   └── console.py       # Windows console output handling
├── libs/                # Native library directory
├── demo.py              # Interactive command-line demo
├── pyproject.toml       # Python package configuration
├── requirements.txt     # Optional runtime dependencies
└── README.md
```

## Related Repositories

| Repository | Description |
|------------|-------------|
| [brosdk](https://github.com/browsersdk/brosdk) | Native C/C++ SDK |
| [brosdk-core](https://github.com/browsersdk/brosdk-core) | Browser core versions and platform support |
| [brosdk-docs](https://github.com/browsersdk/brosdk-docs) | Official documentation and API reference |
| [browser-demo](https://github.com/browsersdk/browser-demo) | Full server-side and desktop client example |

## Development

```bash
pip install -e ".[dev]"
pytest
python -m build
```

Before publishing, verify that:

- API Key, token, and environment ID examples are placeholders.
- The native library for the target platform is available locally.
- Asynchronous events from `browser_open` can be received correctly.

## License

MIT
