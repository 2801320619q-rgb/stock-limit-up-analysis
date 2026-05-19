"""
板块+雷达每日快照存储（v9.7）
- 路径：data/sector_snapshots/{YYYYMMDD}.json
- 每天后写覆盖前写（最后一次刷新生效）
- 单文件包含：
    saved_at: "YYYY-MM-DD HH:MM:SS"
    type:     "concept" / "industry"  (当前 sector 选项)
    sectors:  [{name, change_pct, main_inflow, leader_name, leader_pct, code, ...}, ...]
    stocks_by_sector: {sector_code: [stocks...]}     # 全量预拉取
    ladder_by_sector: {sector_code: ladder_dict}     # 各板块梯队
    radar:    [{name, code, price, change_pct, high, low}, ...]
"""
import os, json, tempfile, threading
from datetime import datetime
from pathlib import Path

from .paths import DIRS


_LOCK = threading.Lock()


def _snapshot_path(date_key):
    return DIRS["sector_snapshots"] / "{}.json".format(date_key)


def list_dates():
    """返回所有已有快照的日期，新→旧"""
    d = DIRS["sector_snapshots"]
    if not d.exists():
        return []
    files = [f[:-5] for f in os.listdir(d) if f.endswith(".json")]
    return sorted(files, reverse=True)


def today_key():
    return datetime.now().strftime("%Y%m%d")


def save_snapshot(payload, date_key=None):
    """
    原子写入。payload 必须可 JSON 序列化。
    若 date_key 为空 → 用今天的日期。同一天文件后写覆盖前写。
    """
    if date_key is None:
        date_key = today_key()
    payload = dict(payload)
    payload.setdefault("saved_at",
                       datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    p = _snapshot_path(date_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(p))
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise


def load_snapshot(date_key):
    """读取某天的快照，返回 dict 或 None"""
    p = _snapshot_path(date_key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_snapshot(date_key):
    p = _snapshot_path(date_key)
    if p.exists():
        p.unlink()


def format_date_label(date_key):
    """20260516 → '2026-05-16'"""
    if len(date_key) == 8:
        return "{}-{}-{}".format(date_key[:4], date_key[4:6], date_key[6:8])
    return date_key
