from .base import BaseTab
from .batch_tab import BatchTab
from .single_tab import SingleTab
# RadarTab 类保留（其逻辑已合并到 SectorTab，但保留 import 以兼容旧引用）
from .radar_tab import RadarTab
from .sector_tab import SectorTab
from .my_sectors_tab import MySectorsTab
from .replay_tab import ReplayTab
from .history_tab import HistoryTab
from .api_tab import ApiTab
from .prompt_tab import PromptTab
from .settings_tab import SettingsTab


# Tab 注册表（顺序即显示顺序）
# v9.7：涨停雷达已合并到「板块分析」Tab 的子选项卡里，
#       主 Tab 列表不再单独显示。
ALL_TABS = [
    ("  📊  批量分析  ", BatchTab),
    ("  🔍  单股搜索  ", SingleTab),
    ("  🗂️  我的板块  ", MySectorsTab),
    ("  🎯  复盘中心  ", ReplayTab),
    ("  🏭  板块分析  ", SectorTab),
    ("  📜  历史记录  ", HistoryTab),
    ("  🔑  API管理   ", ApiTab),
    ("  📝  提示词     ", PromptTab),
    ("  ⚙️  设置       ", SettingsTab),
]
