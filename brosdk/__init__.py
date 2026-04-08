"""
brosdk-python
=================

Python 语言绑定库，动态加载平台 DLL/dylib 并暴露安全、符合 Python 惯用法的 API。

快速开始
--------

.. code-block:: python

    from brosdk import BrosdkManager

    sdk = BrosdkManager()
    sdk.load("libs/windows-x64/brosdk.dll")
    sdk.init("your_user_sig", "/path/to/work_dir", 8080)

    sdk.browser_open('{"envs": [{"envId": "env-001"}]}')
    sdk.browser_close("env-001")
    sdk.shutdown()
"""

from .manager import BrosdkManager, SdkEvent
from .ffi import BrosdkLib

__version__ = "1.0.0"
__all__ = [
    "BrosdkManager", "SdkEvent", "BrosdkLib",
]
