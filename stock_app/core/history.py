"""
历史记录管理
- 按日期分文件存储
- 支持单条删除、批量删除、清空当日
- 支持加星标和备注
- 支持星标记录批量导出
- 🆕 支持结构化存储涨停类别(category)
- 🛡️ 原子写入 + 模块级锁：防止崩溃丢数据 / 并发写覆盖
"""
import os, json, re, tempfile, threading
from datetime import datetime
from pathlib import Path

from .paths import DIRS, ensure_dirs


# 模块级写锁：所有写历史的入口都串行化
_HIST_LOCK = threading.RLock()


def _hist_path(date_key):
    return DIRS["history"] / "{}.json".format(date_key)


# ══════════════════════════════════════════════════
# 基础读写
# ══════════════════════════════════════════════════
def save_history(stock_name, stock_code, content, success=True, category=""):
    """
    保存一条新记录，返回记录ID（用于后续删除/更新）
    🆕 增加 category 参数，结构化存储涨停类别
    """
    ensure_dirs()
    with _HIST_LOCK:
        date_key = datetime.now().strftime("%Y%m%d")
        records = _load_day(date_key)
        record_id = "{}_{}".format(
            datetime.now().strftime("%H%M%S%f")[:-3], stock_code)
        records.append({
            "id":       record_id,
            "time":     datetime.now().strftime("%H:%M:%S"),
            "name":     stock_name,
            "code":     stock_code,
            "success":  success,
            "content":  content,
            "starred":  False,
            "note":     "",
            "tags":     [],         # 用户自定义标签：买入/错过/龙头/慎入...
            "today":    None,       # 当日表现
            "next_day": None,       # 次日表现
            "score":    None,       # 用户评价
            "category": category,   # 🆕 涨停类别/细分标签（结构化存储，不再只混在content里）
        })
        _save_day(date_key, records)
        return record_id


def _load_day(date_key):
    path = _hist_path(date_key)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        # 向后兼容：为旧记录补字段
        for r in records:
            r.setdefault("starred", False)
            r.setdefault("note", "")
            r.setdefault("tags", [])
            r.setdefault("today", None)
            r.setdefault("next_day", None)
            r.setdefault("score", None)
            r.setdefault("id", "{}_{}".format(r.get("time","").replace(":",""), r.get("code","")))
            r.setdefault("category", "")  # 🆕 兼容旧数据
        return records
    except Exception:
        return []


def _save_day(date_key, records):
    """
    原子写入：先写临时文件，再 os.replace 原子覆盖。
    崩溃/断电时要么是旧版本完整，要么是新版本完整，不会出现半残文件。
    """
    path = _hist_path(date_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))   # 原子操作（POSIX 与 Windows 上都是）
    except Exception:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise


def list_history_dates():
    """返回所有日期 ['20260513', ...]，新→旧"""
    if not DIRS["history"].exists():
        return []
    files = [f[:-5] for f in os.listdir(DIRS["history"]) if f.endswith(".json")]
    return sorted(files, reverse=True)


def load_history(date_key):
    return _load_day(date_key)


# ══════════════════════════════════════════════════
# 搜索
# ══════════════════════════════════════════════════
def search_history(keyword):
    results = []
    for date_key in list_history_dates():
        for rec in _load_day(date_key):
            if (keyword in rec.get("name", "") or
                keyword in rec.get("code", "") or
                keyword in rec.get("content", "") or
                keyword in rec.get("note", "")):
                rec_copy = dict(rec)
                rec_copy["date"] = date_key
                results.append(rec_copy)
    return results


def find_by_code(code):
    """
    🆕 v9.5：按股票代码精确查所有历史记录，按日期+时间倒序返回。
    用于股票详情浮窗。
    """
    if not code: return []
    code6 = str(code).zfill(6)
    results = []
    for date_key in list_history_dates():    # 已经是新→旧
        for rec in _load_day(date_key):
            if str(rec.get("code","")).zfill(6) == code6:
                rec_copy = dict(rec)
                rec_copy["date"] = date_key
                results.append(rec_copy)
    # 同一天内按 time 倒序（time 是 HH:MM:SS）
    results.sort(key=lambda r: (r.get("date",""), r.get("time","")), reverse=True)
    return results


# ══════════════════════════════════════════════════
# 🆕 v9.6：股票代码 → 历史条数索引（用于"有历史则标 📊"）
# ══════════════════════════════════════════════════
_CODE_COUNT_LOCK = threading.Lock()
_CODE_COUNT_CACHE = None     # {code6: count}
_CODE_COUNT_FILES_SIG = None # 用文件名+mtime 元组判断是否要重建

def _history_files_signature():
    """所有 history JSON 文件的 (name, mtime) 集合，用于判断索引是否过期"""
    if not DIRS["history"].exists():
        return ()
    sig = []
    try:
        for f in os.listdir(DIRS["history"]):
            if not f.endswith(".json"): continue
            try:
                mt = (DIRS["history"] / f).stat().st_mtime
            except OSError:
                mt = 0
            sig.append((f, mt))
    except OSError:
        return ()
    return tuple(sorted(sig))

def get_code_count_index(force=False):
    """
    返回 {code6: 历史条数}。
    带 mtime 缓存：history 文件未变化时直接复用，避免每次刷新都全扫。
    """
    global _CODE_COUNT_CACHE, _CODE_COUNT_FILES_SIG
    with _CODE_COUNT_LOCK:
        sig = _history_files_signature()
        if not force and _CODE_COUNT_CACHE is not None and sig == _CODE_COUNT_FILES_SIG:
            return _CODE_COUNT_CACHE
        # 重建
        from collections import Counter
        counter = Counter()
        for date_key in list_history_dates():
            for rec in _load_day(date_key):
                code = str(rec.get("code","")).zfill(6)
                if code and code != "000000":
                    counter[code] += 1
        _CODE_COUNT_CACHE = dict(counter)
        _CODE_COUNT_FILES_SIG = sig
        return _CODE_COUNT_CACHE

def has_history(code):
    """快速判断某代码是否有历史记录"""
    if not code: return False
    return str(code).zfill(6) in get_code_count_index()

def history_marker(code, fmt="emoji"):
    """
    返回历史标记。fmt:
      - 'emoji':  '📊' 或 ''
      - 'count':  '📊3' 或 ''
      - 'paren':  ' 📊' 或 ''（前置空格，便于直接拼接）
    """
    n = get_code_count_index().get(str(code).zfill(6), 0)
    if n <= 0: return ""
    if fmt == 'count': return "📊{}".format(n)
    if fmt == 'paren': return " 📊"
    return "📊"


# ══════════════════════════════════════════════════
# 删除
# ══════════════════════════════════════════════════
def delete_record(date_key, record_id):
    with _HIST_LOCK:
        records = _load_day(date_key)
        records = [r for r in records if r.get("id") != record_id]
        _save_day(date_key, records)


def delete_records(date_key, record_ids):
    with _HIST_LOCK:
        records = _load_day(date_key)
        record_ids = set(record_ids)
        records = [r for r in records if r.get("id") not in record_ids]
        _save_day(date_key, records)


def clear_day(date_key):
    with _HIST_LOCK:
        path = _hist_path(date_key)
        if path.exists():
            path.unlink()


def clear_all():
    with _HIST_LOCK:
        for date_key in list_history_dates():
            clear_day(date_key)


# ══════════════════════════════════════════════════
# 星标 & 备注 & 更新
# ══════════════════════════════════════════════════
def update_record(date_key, record_id, **kwargs):
    """更新指定字段（starred, note, category 等）"""
    with _HIST_LOCK:
        records = _load_day(date_key)
        for r in records:
            if r.get("id") == record_id:
                r.update(kwargs)
        _save_day(date_key, records)


def toggle_star(date_key, record_id):
    with _HIST_LOCK:
        records = _load_day(date_key)
        for r in records:
            if r.get("id") == record_id:
                r["starred"] = not r.get("starred", False)
                _save_day(date_key, records)
                return r["starred"]
    return False


def set_note(date_key, record_id, note):
    update_record(date_key, record_id, note=note)


# ══════════════════════════════════════════════════
# 星标记录导出
# ══════════════════════════════════════════════════
def list_all_starred():
    starred = []
    for date_key in list_history_dates():
        for rec in _load_day(date_key):
            if rec.get("starred"):
                r = dict(rec)
                r["date"] = date_key
                starred.append(r)
    return starred


def export_starred_to_excel():
    import pandas as pd
    starred = list_all_starred()
    if not starred:
        return None
    rows = []
    for r in starred:
        rows.append({
            "日期":     r.get("date",""),
            "时间":     r.get("time",""),
            "股票名称": r.get("name",""),
            "股票代码": r.get("code",""),
            "细分标签": r.get("category",""),  # 🆕 导出也带上
            "备注":     r.get("note",""),
            "状态":     "成功" if r.get("success") else "失败",
            "分析内容": r.get("content",""),
        })
    df = pd.DataFrame(rows)
    fn = DIRS["exports"] / "星标记录_{}.xlsx".format(
        datetime.now().strftime("%Y%m%d_%H%M%S"))
    df.to_excel(fn, index=False)
    return str(fn)


def export_starred_to_html():
    starred = list_all_starred()
    if not starred:
        return None
    from .reports import export_html_report
    records = []
    for r in starred:
        title_extra = ""
        if r.get("note"):
            title_extra = " · 📝 " + r["note"]
        records.append({
            "name":    r.get("name","") + title_extra,
            "code":    r.get("code",""),
            "content": r.get("content",""),
            "success": r.get("success", True),
        })
    return export_html_report(records, title="⭐ 星标记录汇总",
                               subdir="exports")