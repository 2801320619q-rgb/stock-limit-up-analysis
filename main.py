"""
涨停复盘分析工具 · v2.0 · 模块化版本

启动入口
所有数据存储在 data/ 子目录，不污染主程序目录
"""
import sys
from pathlib import Path

# 确保可以从主目录运行
sys.path.insert(0, str(Path(__file__).parent))

from stock_app import App


if __name__ == "__main__":
    App().run()
