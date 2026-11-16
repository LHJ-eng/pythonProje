#!/usr/bin/env python3
"""生成 APP_PASSWORD_HASH，避免在 .env 中保存明文密码。

用法：
    python -m app.set_password "你的密码"
然后把输出的 APP_PASSWORD_HASH=... 写入 .env，并删除 APP_PASSWORD。
"""

import getpass
import sys

from .auth import hash_password
from .config import PBKDF2_ITERATIONS


def main() -> None:
    password = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("输入访问密码：")
    if len(password) < 8:
        print("密码过短，建议至少 12 位。", file=sys.stderr)
    print(hash_password(password, iterations=PBKDF2_ITERATIONS))


if __name__ == "__main__":
    main()
