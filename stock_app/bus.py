"""
全局事件总线 + 共享状态
让各 Tab 之间能互相通信（如 API 改了 → Key 状态卡刷新）
"""
import threading
from collections import defaultdict


class EventBus:
    """简单的发布/订阅事件总线"""
    def __init__(self):
        self._subs = defaultdict(list)
        self._lock = threading.Lock()

    def on(self, event_name, callback):
        with self._lock:
            self._subs[event_name].append(callback)

    def emit(self, event_name, *args, **kwargs):
        with self._lock:
            handlers = list(self._subs.get(event_name, []))
        for h in handlers:
            try:
                h(*args, **kwargs)
            except Exception:
                import traceback
                traceback.print_exc()


# 全局唯一事件总线
bus = EventBus()


# ══════════════════════════════════════════════════
# 事件名常量（集中管理，避免拼写错误）
# ══════════════════════════════════════════════════
class Events:
    API_KEYS_CHANGED   = "api_keys_changed"     # API Keys 列表变化
    THEME_CHANGED      = "theme_changed"         # 主题切换
    PROMPT_CHANGED     = "prompt_changed"        # 提示词修改
    SETTINGS_CHANGED   = "settings_changed"      # 全局设置变化
    HISTORY_UPDATED    = "history_updated"       # 历史记录新增/删除
    FAVORITES_UPDATED  = "favorites_updated"     # 自选股变化
    BATCH_STARTED      = "batch_started"         # 批量分析开始
    BATCH_COMPLETED    = "batch_completed"       # 批量分析完成
    REQUEST_BATCH_RUN  = "request_batch_run"     # 请求启动批量分析 (stocks, source)


# ══════════════════════════════════════════════════
# 全局共享状态（运行时数据）
# ══════════════════════════════════════════════════
class AppState:
    def __init__(self):
        # 应用级 lock 和事件
        self.save_lock = threading.Lock()
        self.shutdown  = threading.Event()
        self.paused    = threading.Event()

        # UI 队列：从工作线程发到主线程
        import queue
        self.log_queue = queue.Queue()
        self.ui_queue  = queue.Queue()

        # 运行时状态
        self.running        = False
        self.failed_stocks  = []
        self.last_batch_df  = None
        self.last_output    = None

        # 当前选中的输入文件
        self.input_file     = None


state = AppState()
