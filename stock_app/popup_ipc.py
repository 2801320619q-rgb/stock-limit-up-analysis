"""
浮窗 IPC 通道（v9.9.4）
- 主程序写信号 → 浮窗子进程轮询读 → 触发刷新
- 信号文件：data/popup/signal.json
- 不用 socket / pipe（Windows 兼容性更好、调试更容易）
- 信号包含一个递增 seq，浮窗用 seq 判断是否是新信号
"""
import os, json, time, tempfile, threading
from pathlib import Path


def _signal_path(base_dir):
    """base_dir 是项目 data/ 目录"""
    return Path(base_dir) / "popup" / "signal.json"


# ════════════════════════════════════════════════
# 主程序侧：写信号
# ════════════════════════════════════════════════
class SignalWriter:
    """主程序用：每次写一个新信号通知浮窗"""
    _lock = threading.Lock()
    _seq  = 0

    def __init__(self, base_dir):
        self.path = _signal_path(base_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, action, **kwargs):
        """
        发送一个信号。action 可以是：
          - 'show'       {code, name}      无视模式直接刷新浮窗（如右键"在浮窗查看"）
          - 'follow'     {code, name}      🔁 v9.9.4 语义变更：
                                            "主程序点击/选中股票"通知。
                                            浮窗根据 📍 主程序联动 / 📤 推送同花顺
                                            两个开关独立消费（可同时启用）；
                                            同花顺监听走浮窗内部 watcher，与本信号无关。
          - 'push'       {code, name}      显式让浮窗推送给同花顺（无视开关）
          - 'set_follow' {on: bool}        旧 API：on=True 等价于
                                            set_modes(follow=True,push=False,main_link=False)
          - 'set_modes'  {follow: bool,
                          push:   bool,
                          main_link: bool} 🆕 v9.9.4：三参版本；老调用方只传
                                            follow/push 也兼容（main_link 不变）。
          - 'ping'                          心跳
          - 'shutdown'                      请求浮窗优雅退出
        """
        with SignalWriter._lock:
            SignalWriter._seq += 1
            payload = {
                "seq":     SignalWriter._seq,
                "ts":      time.time(),
                "action":  action,
                "data":    kwargs,
            }
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".tmp_", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(tmp, str(self.path))
            except Exception:
                try: os.unlink(tmp)
                except OSError: pass


# ════════════════════════════════════════════════
# 浮窗侧：轮询读信号
# ════════════════════════════════════════════════
class SignalReader:
    """浮窗子进程用：周期轮询，发现新 seq 就触发回调"""

    def __init__(self, base_dir):
        self.path = _signal_path(base_dir)
        self._last_seq = -1

    def poll(self):
        """
        返回一个新信号 dict 或 None。
        无文件 / 无新信号 → None
        """
        try:
            if not self.path.exists(): return None
            data = json.loads(self.path.read_text(encoding="utf-8"))
            seq = data.get("seq", -1)
            if seq <= self._last_seq:
                return None
            self._last_seq = seq
            return data
        except Exception:
            return None


def find_data_dir():
    """
    定位项目 data 目录。
    - 通过环境变量 STOCK_APP_DATA_DIR（主程序拉起子进程时传入）
    - 否则用相对路径（兼容直接运行）
    """
    env = os.environ.get("STOCK_APP_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # 默认：脚本所在目录的上一层 / data
    return Path(__file__).resolve().parent.parent / "data"
