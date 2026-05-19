"""
全局常量、路径、目录管理
所有输出文件统一放在 data/ 子目录，不污染主程序目录
"""
import os
from pathlib import Path

# ══════════════════════════════════════════════════
# 数据根目录（所有运行时数据都放这里）
#   🛡️ 锚定到项目根（main.py 所在目录），不依赖工作目录。
#     paths.py 在  <project_root>/stock_app/core/paths.py
#     parents[0] = core/，parents[1] = stock_app/，parents[2] = <project_root>
#   优先级：环境变量 STOCK_APP_DATA_DIR > 项目根/data
# ══════════════════════════════════════════════════
_ENV_DIR = os.environ.get("STOCK_APP_DATA_DIR", "").strip()
if _ENV_DIR:
    DATA_DIR = Path(_ENV_DIR).expanduser().resolve()
else:
    DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# 各类数据子目录
DIRS = {
    "config":   DATA_DIR / "config",        # 配置文件
    "output":   DATA_DIR / "output",        # 批量分析结果 Excel
    "backup":   DATA_DIR / "output" / "backup",  # 备份
    "history":  DATA_DIR / "history",       # 历史记录
    "reports":  DATA_DIR / "reports",       # HTML报告
    "exports":  DATA_DIR / "exports",       # 星标导出
    "logs":     DATA_DIR / "logs",          # 运行日志
    "temp":     DATA_DIR / "temp",          # 临时文件
    "market":   DATA_DIR / "market",
    "sector_snapshots": DATA_DIR / "sector_snapshots",  # 🆕 v9.7：板块+雷达每日快照
}

def ensure_dirs():
    """启动时调用，确保所有目录存在"""
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

# 各类具体文件路径
PATHS = {
    "config":     DIRS["config"]  / "config.json",
    "favorites":  DIRS["config"]  / "favorites.json",
    "stock_dict": DIRS["config"]  / "stock_dict.json",
    "settings":   DIRS["config"]  / "app_settings.json",
    "log":        DIRS["logs"]    / "app.log",
}

# 模块版本
VERSION = "2.0"

# ══════════════════════════════════════════════════
# 必填模块标记
# ══════════════════════════════════════════════════
REQUIRED_SECTIONS = [
    "核心业务",
    "市场主要核心上涨共识",
    "市场次要上涨共识",
    "同逻辑联动标的",
    "同逻辑标的板块事件共识",
]
