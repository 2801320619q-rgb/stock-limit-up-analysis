"""
复盘核心模块
- 个股复盘档案（profile）
- 次日表现追踪（next-day tracking）
- 复盘日报（daily report）
- 热点演化时间线（trend timeline）
- 相似行情匹配（similar days）
- 关键数据卡片（stat card）
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from . import history as hist_mod
from . import api_client


# ══════════════════════════════════════════════════
# 工具：从分析内容中提取关键信息
# ══════════════════════════════════════════════════
def extract_main_logic(content):
    """从分析内容中提取「核心上涨逻辑」一句话"""
    if not content:
        return ""
    # 优先抓 ②市场主要核心上涨共识 段落
    m = re.search(r'市场主要核心上涨共识[】：:\s]*([^。\n]{8,120})', content)
    if m:
        return m.group(1).strip()
    m = re.search(r'核心.{0,4}上涨.{0,4}观点.{0,4}是?[\s:：]*([^。\n]{8,120})', content)
    if m:
        return m.group(1).strip()
    return ""


def extract_main_business(content):
    """从分析内容中提取主营业务一句话"""
    if not content:
        return ""
    m = re.search(r'核心业务[】：:\s]*([^。\n]{8,80})', content)
    if m:
        return m.group(1).strip()
    return ""


def extract_concepts(content):
    """从分析内容中提取概念标签（最多5个）"""
    if not content:
        return []
    concepts = set()
    # 已知概念关键词
    pattern = re.compile(
        r'(算力|算电协同|AI|人工智能|大模型|半导体|芯片|存储|光刻|HBM|CPO|'
        r'新能源|储能|光伏|风电|核电|绿电|氢能|'
        r'消费电子|苹果链|华为链|折叠屏|'
        r'医药|创新药|减肥药|GLP-1|脑机接口|'
        r'机器人|低空经济|无人驾驶|智能驾驶|'
        r'军工|国防|大飞机|商业航天|卫星|'
        r'金融|券商|银行|国资改革|央企|'
        r'数字货币|区块链|稳定币|'
        r'传感器|MCU|功率半导体)')
    for m in pattern.finditer(content):
        concepts.add(m.group(1))
        if len(concepts) >= 5:
            break
    return list(concepts)


# ══════════════════════════════════════════════════
# 1. 个股复盘档案
# ══════════════════════════════════════════════════
def build_stock_profile(stock_code):
    """
    构建一只股票的复盘档案
    返回 {
        "code", "name", "total_analyses",
        "records": [完整历史记录, ...],
        "logic_counter": [(逻辑, 次数), ...],
        "next_day_stats": {"count","win","avg_pct","records"},
        "linked_stocks_counter": [(代码, 次数), ...],
    }
    """
    profile = {
        "code":           stock_code,
        "name":           "",
        "total_analyses": 0,
        "records":        [],
        "logic_counter":  [],
        "next_day_stats": {"count": 0, "win": 0, "avg_pct": 0, "records": []},
        "linked_stocks":  [],
    }

    # 收集所有该股票的历史记录
    logic_words = Counter()
    next_day_results = []
    linked_counter   = Counter()

    for date_key in hist_mod.list_history_dates():
        for r in hist_mod.load_history(date_key):
            if r.get("code") == stock_code:
                r_copy = dict(r)
                r_copy["date"] = date_key
                profile["records"].append(r_copy)
                if not profile["name"]:
                    profile["name"] = r.get("name", "")

                # 提取逻辑关键词
                concepts = extract_concepts(r.get("content", ""))
                for c in concepts:
                    logic_words[c] += 1

                # 收集次日表现
                nd = r.get("next_day")
                if nd and isinstance(nd, dict) and nd.get("change_pct") is not None:
                    next_day_results.append({
                        "date":    date_key,
                        "next_dt": nd.get("date", ""),
                        "pct":     nd.get("change_pct", 0),
                    })

                # 提取联动标的
                codes = api_client.extract_linked_codes(r.get("content", ""))
                for c in codes:
                    linked_counter[c] += 1

    profile["total_analyses"] = len(profile["records"])
    profile["logic_counter"]  = logic_words.most_common(8)
    profile["linked_stocks"]  = linked_counter.most_common(10)

    # 次日表现统计
    if next_day_results:
        wins  = sum(1 for x in next_day_results if x["pct"] > 0)
        total = len(next_day_results)
        avg   = sum(x["pct"] for x in next_day_results) / total
        profile["next_day_stats"] = {
            "count":    total,
            "win":      wins,
            "win_rate": wins / total,
            "avg_pct":  round(avg, 2),
            "records":  next_day_results,
        }
    return profile


# ══════════════════════════════════════════════════
# 2. 次日表现追踪
# ══════════════════════════════════════════════════
def fetch_next_day_perf(stock_code, base_date_key):
    """
    抓取 base_date 之后下一个交易日的表现
    使用腾讯实时接口，返回 {"date","price","change_pct","captured_at"}
    
    注意：腾讯接口只能拿到当前实时数据，所以只能在【次日盘后】调用才有意义
    """
    data = api_client.fetch_change_pct([stock_code])
    if not data or stock_code not in data:
        return None
    info = data[stock_code]
    return {
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "price":       info["price"],
        "change_pct":  info["change_pct"],
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def batch_update_next_day(date_key, target_date_key=None, on_progress=None):
    """
    批量更新指定日期所有记录的次日表现
    target_date_key: 指定"次日"的日期，None 表示用今天
    on_progress(i, total, name): 进度回调
    返回 {"updated":N, "skipped":N, "failed":N}
    """
    records = hist_mod.load_history(date_key)
    updated, skipped, failed = 0, 0, 0
    target_dt = target_date_key or datetime.now().strftime("%Y%m%d")

    # 收集所有有效股票代码
    valid_records = [r for r in records
                     if r.get("code") and r.get("code") != "000000"]
    total = len(valid_records)

    # 批量查询（每次 30 个，太多腾讯接口会报错）
    BATCH_SIZE = 30
    for batch_start in range(0, total, BATCH_SIZE):
        batch = valid_records[batch_start:batch_start + BATCH_SIZE]
        codes = [r["code"] for r in batch]
        data = api_client.fetch_change_pct(codes)

        for i, r in enumerate(batch):
            real_i = batch_start + i + 1
            code = r["code"]
            if on_progress:
                on_progress(real_i, total, r.get("name", ""))

            # 已经有次日数据且日期匹配，跳过
            existing = r.get("next_day")
            if existing and existing.get("date", "").replace("-", "") == target_dt:
                skipped += 1
                continue

            if code in data:
                info = data[code]
                r["next_day"] = {
                    "date":        "{}-{}-{}".format(target_dt[:4], target_dt[4:6], target_dt[6:]),
                    "price":       info["price"],
                    "change_pct":  info["change_pct"],
                    "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                updated += 1
            else:
                failed += 1

    # 写回文件
    if updated > 0:
        hist_mod._save_day(date_key, records)

    return {"updated": updated, "skipped": skipped, "failed": failed}


# ══════════════════════════════════════════════════
# 3. 复盘日报
# ══════════════════════════════════════════════════
def generate_daily_report(date_key=None):
    """
    生成指定日期的复盘日报
    返回 dict（用于前端展示），不直接生成HTML
    """
    date_key = date_key or datetime.now().strftime("%Y%m%d")
    records  = hist_mod.load_history(date_key)
    if not records:
        return None

    # ── 基础统计 ──
    total = len(records)
    ok    = sum(1 for r in records if r.get("success"))
    fail  = total - ok

    # ── 主线提取 ──
    concept_counter = Counter()
    for r in records:
        for c in extract_concepts(r.get("content", "")):
            concept_counter[c] += 1
    top_concepts = concept_counter.most_common(10)

    # ── 明星股 ──
    stars_today = [r for r in records if r.get("starred")]

    # ── 联动汇总 ──
    linked_counter = Counter()
    for r in records:
        codes = api_client.extract_linked_codes(r.get("content", ""))
        for c in codes:
            linked_counter[c] += 1
    top_linked = linked_counter.most_common(15)

    # ── 次日表现汇总（如果有）──
    next_day_data = []
    for r in records:
        nd = r.get("next_day")
        if nd and nd.get("change_pct") is not None:
            next_day_data.append({
                "name":  r.get("name", ""),
                "code":  r.get("code", ""),
                "pct":   nd["change_pct"],
                "date":  nd.get("date", ""),
            })
    next_day_data.sort(key=lambda x: x["pct"], reverse=True)
    next_day_summary = None
    if next_day_data:
        wins = sum(1 for x in next_day_data if x["pct"] > 0)
        avg = sum(x["pct"] for x in next_day_data) / len(next_day_data)
        next_day_summary = {
            "count":    len(next_day_data),
            "win":      wins,
            "win_rate": wins / len(next_day_data),
            "avg_pct":  round(avg, 2),
            "best":     next_day_data[:5],
            "worst":    next_day_data[-5:][::-1],
        }

    return {
        "date":               date_key,
        "date_display":       "{}-{}-{}".format(date_key[:4], date_key[4:6], date_key[6:]),
        "total":              total,
        "ok":                 ok,
        "fail":               fail,
        "stars":              len(stars_today),
        "star_records":       [{"name":r.get("name",""), "code":r.get("code",""),
                                "note":r.get("note","")} for r in stars_today],
        "top_concepts":       top_concepts,
        "top_linked":         top_linked,
        "next_day_summary":   next_day_summary,
    }


# ══════════════════════════════════════════════════
# 4. 热点演化时间线
# ══════════════════════════════════════════════════
def build_concept_timeline(concept_name, days=180):
    """
    构建概念的演化时间线
    返回 [{"date","mention_count","stocks","stage"}, ...]
    stage: "首次" / "扩散" / "爆发" / "加速" / "高潮" / "延续" / "退潮"
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    raw = []
    for date_key in hist_mod.list_history_dates():
        if date_key < cutoff:
            continue
        records = hist_mod.load_history(date_key)
        hit = []
        for r in records:
            if concept_name in (r.get("content") or ""):
                hit.append({"name": r.get("name", ""), "code": r.get("code", "")})
        if hit:
            raw.append({
                "date":          date_key,
                "date_display":  "{}-{}-{}".format(date_key[:4], date_key[4:6], date_key[6:]),
                "mention_count": len(hit),
                "stocks":        hit,
            })
    # 时间正序
    raw.sort(key=lambda x: x["date"])

    # 给每个节点打阶段标签
    for i, node in enumerate(raw):
        count = node["mention_count"]
        prev_count = raw[i-1]["mention_count"] if i > 0 else 0
        next_count = raw[i+1]["mention_count"] if i < len(raw)-1 else 0

        if i == 0:
            stage = "🌱 首次"
        elif count > prev_count * 2:
            stage = "⚡ 爆发"
        elif count > prev_count * 1.3:
            stage = "📈 加速"
        elif count < prev_count * 0.5:
            stage = "📉 退潮"
        elif count >= max(x["mention_count"] for x in raw):
            stage = "🔥 高潮"
        elif count < prev_count:
            stage = "💤 衰退"
        else:
            stage = "🌊 延续"
        node["stage"] = stage

    return raw


# ══════════════════════════════════════════════════
# 5. 相似行情匹配
# ══════════════════════════════════════════════════
def find_similar_days(target_date_key=None, top_n=5):
    """
    根据"概念主线、涨停数、明星股"等特征找相似日子
    target_date_key: 与哪一天比较，None=今天
    返回 [{"date","similarity","main_concepts","total_count"}, ...]
    """
    target_date_key = target_date_key or datetime.now().strftime("%Y%m%d")
    target_records = hist_mod.load_history(target_date_key)
    if not target_records:
        return []

    # 目标日特征
    target_concepts = Counter()
    for r in target_records:
        for c in extract_concepts(r.get("content", "")):
            target_concepts[c] += 1
    target_top = set(c for c, _ in target_concepts.most_common(5))
    target_total = len(target_records)

    # 所有历史日特征
    candidates = []
    for date_key in hist_mod.list_history_dates():
        if date_key == target_date_key:
            continue
        records = hist_mod.load_history(date_key)
        if not records:
            continue
        day_concepts = Counter()
        for r in records:
            for c in extract_concepts(r.get("content", "")):
                day_concepts[c] += 1
        day_top = set(c for c, _ in day_concepts.most_common(5))
        if not day_top:
            continue

        # 相似度 = 概念主线重合度 + 规模相似度
        if target_top:
            overlap = len(target_top & day_top) / len(target_top | day_top)
        else:
            overlap = 0
        # 规模相似（1 - |差|/max）
        size_sim = 1 - abs(len(records) - target_total) / max(len(records), target_total)
        similarity = overlap * 0.7 + size_sim * 0.3

        candidates.append({
            "date":          date_key,
            "date_display":  "{}-{}-{}".format(date_key[:4], date_key[4:6], date_key[6:]),
            "similarity":    round(similarity * 100, 1),
            "main_concepts": list(day_top)[:5],
            "total_count":   len(records),
        })

    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:top_n]


# ══════════════════════════════════════════════════
# 内置可选标签
# ══════════════════════════════════════════════════
PRESET_TAGS = [
    ("✅ 已买入",    "buy"),
    ("❌ 错过",      "missed"),
    ("💎 强势龙头",  "leader"),
    ("🚫 慎入",      "avoid"),
    ("📌 重点观察",  "watch"),
    ("🔥 主升浪",    "uptrend"),
    ("⚠️ 高位",      "high"),
    ("🌱 启动初期",  "early"),
    ("💸 已止盈",    "took_profit"),
    ("📉 已止损",    "stopped_loss"),
]


def update_tags(date_key, record_id, tags):
    """更新指定记录的标签"""
    hist_mod.update_record(date_key, record_id, tags=tags)


def filter_by_tag(tag_value):
    """跨日期按标签过滤记录"""
    result = []
    for date_key in hist_mod.list_history_dates():
        for r in hist_mod.load_history(date_key):
            if tag_value in (r.get("tags") or []):
                r_copy = dict(r)
                r_copy["date"] = date_key
                result.append(r_copy)
    return result


# ══════════════════════════════════════════════════
# 6. 关键数据卡片（用于详情面板顶部）
# ══════════════════════════════════════════════════
def build_stat_card(stock_code, stock_name=""):
    """构建详情顶部的关键数据卡片"""
    profile = build_stock_profile(stock_code)
    card = {
        "code":           stock_code,
        "name":           profile["name"] or stock_name,
        "total":          profile["total_analyses"],
        "win_rate":       None,
        "avg_next_day":   None,
        "top_logics":     [c for c, _ in profile["logic_counter"][:3]],
        "linked_count":   len(profile["linked_stocks"]),
        "realtime":       None,
    }
    if profile["next_day_stats"]["count"] > 0:
        card["win_rate"]     = profile["next_day_stats"]["win_rate"]
        card["avg_next_day"] = profile["next_day_stats"]["avg_pct"]
        card["next_count"]   = profile["next_day_stats"]["count"]

    # 抓实时行情（如果代码有效）
    if stock_code and stock_code != "000000":
        try:
            data = api_client.fetch_change_pct([stock_code])
            if data and stock_code in data:
                card["realtime"] = data[stock_code]
        except Exception:
            pass
    return card
