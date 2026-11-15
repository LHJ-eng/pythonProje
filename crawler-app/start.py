"""本地启动入口：在 PyCharm 中右键本文件 → Run 即可启动。

也可以直接命令行运行： python start.py
"""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
