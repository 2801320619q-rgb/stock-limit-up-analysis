"""
板块效应分析核心模块
- 板块强度评分
- 龙头梯队识别（龙一/龙二/龙三/补涨/退潮）
- 历史板块表现对比
"""
import re
from collections import Counter
from datetime import datetime, timedelta
from . import history as hist_mod


# ══════════════════════════════════════════════════
# 板块强度评分（0-100）
# ══════════════════════════════════════════════════
def calc_sector_strength(sector_info, stocks):
    """
    综合多维度算出板块强度评分
    sector_info: 板块基础信息（fetch_sectors 返回项）
    stocks:      板块成份股列表（fetch_sector_stocks 返回值）

    评分公式：
      涨停股数量      权重 35%  (>=10只满分)
      板块涨幅        权重 25%  (>=8% 满分)
      涨家数比例      权重 20%  (>=80% 满分)
      主力净流入(亿)  权重 20%  (>=20亿满分)
    """
    if not stocks or not isinstance(stocks, list):
        return 0, {}

    # 1. 涨停股数量（含一字板）
    limit_up_count = sum(1 for s in stocks if s.get("status") in ("一字板", "涨停"))
    score_lu = min(limit_up_count / 10.0 * 35, 35)

    # 2. 板块涨幅
    pct = sector_info.get("change_pct", 0)
    score_pct = min(max(pct, 0) / 8.0 * 25, 25)

    # 3. 涨家数比例
    up = sum(1 for s in stocks if s.get("change_pct", 0) > 0)
    ratio = up / len(stocks) if stocks else 0
    score_ratio = min(ratio / 0.8 * 20, 20)

    # 4. 主力净流入
    inflow_yi = sector_info.get("main_inflow", 0) / 1e8
    score_in = min(max(inflow_yi, 0) / 20.0 * 20, 20)

    total = round(score_lu + score_pct + score_ratio + score_in, 1)
    breakdown = {
        "limit_up":      (round(score_lu, 1),    "涨停股 {} 只".format(limit_up_count)),
        "change_pct":    (round(score_pct, 1),   "板块涨幅 {:+.2f}%".format(pct)),
        "up_ratio":      (round(score_ratio, 1), "涨家数 {}/{} ({:.0%})".format(up, len(stocks), ratio)),
        "main_inflow":   (round(score_in, 1),    "主力净流入 {:+.2f} 亿".format(inflow_yi)),
    }
    return total, breakdown


# ══════════════════════════════════════════════════
# 龙头梯队识别
# ══════════════════════════════════════════════════
def identify_ladder(stocks):
    """
    给定板块成份股，识别龙头梯队
    返回 {
        "leaders":   [龙一, 龙二, 龙三, ...] - 涨停（含一字板）
        "follow":    [补涨股] - 涨幅 5%~10%，未涨停
        "broken":    [炸板股]
        "fading":    [冲高回落]
        "other_up":  [其他上涨]
        "down":      [下跌]
    }
    每个元素是 stock dict + 额外字段 rank
    """
    result = {
        "leaders":  [],   # 涨停/一字板
        "follow":   [],   # 补涨
        "broken":   [],   # 炸板
        "fading":   [],   # 冲高回落
        "other_up": [],   # 其他上涨
        "down":     [],   # 下跌
    }
    for s in stocks:
        st = s.get("status", "")
        chg = s.get("change_pct", 0)
        if st in ("一字板", "涨停"):
            result["leaders"].append(s)
        elif st == "炸板":
            result["broken"].append(s)
        elif st == "冲高回落":
            result["fading"].append(s)
        elif chg >= 5:
            result["follow"].append(s)
        elif chg > 0:
            result["other_up"].append(s)
        else:
            result["down"].append(s)

    # 涨停股排序：一字板优先 > 涨幅高的优先 > 成交额大的优先
    result["leaders"].sort(key=lambda s: (
        0 if s.get("status") == "一字板" else 1,
        -s.get("change_pct", 0),
        -s.get("amount", 0),
    ))
    # 给龙一龙二龙三标 rank
    for i, s in enumerate(result["leaders"][:5]):
        s["rank"] = i + 1
        s["rank_label"] = ["🥇 龙一", "🥈 龙二", "🥉 龙三", "  龙四", "  龙五"][i]

    # 补涨按涨幅降序
    result["follow"].sort(key=lambda s: -s.get("change_pct", 0))
    result["broken"].sort(key=lambda s: -s.get("high_pct", 0))
    result["fading"].sort(key=lambda s: -s.get("high_pct", 0))

    return result


# ══════════════════════════════════════════════════
# 历史板块表现回看
# ══════════════════════════════════════════════════
def search_sector_in_history(sector_name, days=180):
    """
    在本地历史 JSON 里搜索某个板块的过去表现
    返回 [{"date","mention_count","stocks":[{name,code}],"avg_pct":...}, ...]
    
    sector_name: 板块名（如 "AI算力"、"算电协同"）
    days:       回看天数
    """
    # 把板块名打散成关键词集合，单字关键词去掉以免误匹配
    base_kws = set()
    base_kws.add(sector_name)
    # 也加入板块名拆分后的关键词
    for kw in re.split(r'[/+、与和]', sector_name):
        kw = kw.strip()
        if len(kw) >= 2:
            base_kws.add(kw)

    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    by_date = {}
    for date_key in hist_mod.list_history_dates():
        if date_key < cutoff_date:
            continue
        records = hist_mod.load_history(date_key)
        hit_stocks = []
        for r in records:
            content = r.get("content", "") or ""
            if any(kw in content for kw in base_kws):
                hit_stocks.append({
                    "name": r.get("name", ""),
                    "code": r.get("code", ""),
                    "id":   r.get("id", ""),
                })
        if hit_stocks:
            by_date[date_key] = hit_stocks

    # 转成列表，新→旧
    result = []
    for date_key in sorted(by_date.keys(), reverse=True):
        stocks = by_date[date_key]
        result.append({
            "date":          date_key,
            "date_display":  "{}-{}-{}".format(date_key[:4], date_key[4:6], date_key[6:]),
            "mention_count": len(stocks),
            "stocks":        stocks,
        })
    return result


# ══════════════════════════════════════════════════
# 提取板块关键词（用于热度统计）
# ══════════════════════════════════════════════════
KEYWORD_PATTERN = re.compile(
    r'(算力|算电协同|AI[算力大模型]*|人工智能|大模型|半导体|芯片|存储|光刻|'
    r'新能源|储能|光伏|风电|核电|绿电|氢能|'
    r'消费电子|苹果|华为|果链|折叠屏|'
    r'医药|创新药|减肥药|GLP-1|脑机接口|'
    r'机器人|低空经济|无人驾驶|智能驾驶|'
    r'军工|国防|大飞机|商业航天|卫星|'
    r'金融|券商|银行|保险|国资改革|国企改革|央企|'
    r'地产|建材|消费|食品|白酒|养殖|'
    r'数字货币|区块链|稳定币|跨境支付|'
    r'CPO|HBM|铜连接|液冷|温控|'
    r'传感器|MCU|功率半导体|第三代半导体)'
)

def extract_top_concepts(date_key, top_n=15):
    """从指定日期所有历史记录中提取出现频率最高的概念关键词"""
    records = hist_mod.load_history(date_key)
    counter = Counter()
    for r in records:
        content = r.get("content", "") or ""
        # 每条记录里同一关键词只计 1 次，避免单只股票内重复
        seen = set()
        for m in KEYWORD_PATTERN.finditer(content):
            kw = m.group(1)
            if kw not in seen:
                seen.add(kw)
                counter[kw] += 1
    return counter.most_common(top_n)
