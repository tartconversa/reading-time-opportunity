#!/usr/bin/env python3
"""时间机会分析工具的命令行入口（薄封装）。

推荐以隔离模式运行，避免资料目录中的同名模块被误导入：

    python3 -I run_tool.py --materials materials --workdir workdir inspect

不带 -I 时也可运行，但处理不受信资料时请始终使用 -I。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeopp.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
