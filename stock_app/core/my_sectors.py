"""
自定义板块管理
- 用户自建板块（如"我的半导体池"），每个板块包含一组股票
- 支持快速文本导入（粘贴股票名称或代码，自动识别）
- 持久化到 data/config/custom_sectors.json
- 一键拉取所有板块的最新行情
"""
import json
import re
from datetime import datetime
from pathlib import Path
from .paths import DIRS
from . import api_client


_FILE = None
def _file():
    global _FILE
    if _FILE is None:
        _FILE = Path(DIRS["config"]) / "custom_sectors.json"
    return _FILE


# ══════════════════════════════════════════════════
# 数据访问
# ══════════════════════════════════════════════════
def _load_all():
    p = _file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_all(data):
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_sectors():
    """列出所有自定义板块名"""
    return sorted(_load_all().keys())


def get_sector(name):
    """获取板块详情 {'name','stocks':[{name,code}],'created','updated','note'}"""
    data = _load_all()
    return data.get(name)


def get_all_with_quotes():
    """所有板块 + 最新行情快照（用于显示）"""
    data = _load_all()
    return data


def create_sector(name, stocks=None, note=""):
    """新建板块"""
    name = (name or "").strip()
    if not name:
        return False, "板块名不能为空"
    data = _load_all()
    if name in data:
        return False, "板块「{}」已存在".format(name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data[name] = {
        "name":    name,
        "stocks":  stocks or [],
        "note":    note or "",
        "created": now,
        "updated": now,
        "quotes":  {},   # {code: {price, change_pct, time}} 缓存最新行情
    }
    _save_all(data)
    return True, "已创建"


def delete_sector(name):
    data = _load_all()
    if name in data:
        del data[name]
        _save_all(data)
        return True
    return False


def rename_sector(old_name, new_name):
    if not new_name.strip():
        return False, "新名称不能为空"
    data = _load_all()
    if old_name not in data:
        return False, "原板块不存在"
    if new_name in data and new_name != old_name:
        return False, "新名称已存在"
    data[new_name] = data.pop(old_name)
    data[new_name]['name'] = new_name
    data[new_name]['updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_all(data)
    return True, "已重命名"


def add_stocks(sector_name, stocks):
    """向板块中追加股票，自动去重"""
    data = _load_all()
    if sector_name not in data:
        return False, "板块不存在", 0
    existing = {s['code']: s for s in data[sector_name]['stocks']}
    added = 0
    for s in stocks:
        code = s.get('code', '').strip()
        if not code or code in existing:
            continue
        existing[code] = {'name': s.get('name', ''), 'code': code}
        added += 1
    data[sector_name]['stocks'] = list(existing.values())
    data[sector_name]['updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_all(data)
    return True, "新增 {} 只".format(added), added


def remove_stocks(sector_name, codes):
    """从板块中移除股票"""
    data = _load_all()
    if sector_name not in data:
        return False, 0
    before = len(data[sector_name]['stocks'])
    data[sector_name]['stocks'] = [s for s in data[sector_name]['stocks']
                                    if s['code'] not in set(codes)]
    after = len(data[sector_name]['stocks'])
    data[sector_name]['updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_all(data)
    return True, before - after


def update_note(sector_name, note):
    data = _load_all()
    if sector_name not in data:
        return False
    data[sector_name]['note'] = note
    data[sector_name]['updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_all(data)
    return True


# ══════════════════════════════════════════════════
# 快速文本导入
# ══════════════════════════════════════════════════
def parse_smart(text, name_lookup=None):
    """
    智能解析：从一行文本中同时识别 板块名 + 股票列表
    支持格式：
      半导体：寒武纪 海光信息 000001 002230
      半导体: 九方科技、万象股份、九安科技
      新能源 | 比亚迪 宁德时代
    返回 {"sector_name": str or None, "stocks": [...]}
    """
    if not text:
        return {"sector_name": None, "stocks": []}

    sector_name = None
    body = text

    # 找冒号（中英文都支持）/ 竖线 作为分隔
    m = re.match(r'^\s*([^\s：:|]{1,10})\s*[：:|]\s*(.+)$', text.strip())
    if m:
        prefix = m.group(1).strip()
        # 板块名必须是 2~10 个中文/字母
        if 2 <= len(prefix) <= 10 and re.match(r'^[\u4e00-\u9fa5A-Za-z0-9]+$', prefix):
            # 但不能本身就是 6 位代码
            if not re.match(r'^\d{6}$', prefix):
                sector_name = prefix
                body = m.group(2)

    stocks = parse_import_text(body, name_lookup=name_lookup)
    return {"sector_name": sector_name, "stocks": stocks}


def parse_import_text(text, name_lookup=None):
    """
    解析用户粘贴的文本，提取股票
    支持格式：
      半导体：寒武纪、海光信息、000001、002230
      寒武纪 688256
      603019,中科曙光
      688256 寒武纪 涨停理由
    返回 [{name, code}, ...]
    name_lookup: 名称→代码字典（用于通过名称反查代码）
    """
    if not text:
        return []
    # 整理分隔符
    text = re.sub(r'[，、；\|/]', ' ', text)
    text = re.sub(r'[：:]', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    # 找所有 6 位数字 -> 当作代码
    # 找所有 2~6 中文字符 -> 当作名称
    results = []
    seen_codes = set()

    # 优先匹配代码
    for m in re.finditer(r'(?<!\d)(\d{6})(?!\d)', text):
        code = m.group(1)
        if code in seen_codes:
            continue
        seen_codes.add(code)
        # 尝试就近找名称
        start = max(0, m.start() - 10)
        end   = min(len(text), m.end() + 10)
        near  = text[start:end]
        name_m = re.search(r'([\u4e00-\u9fa5A-Za-z]{2,8}股份|[\u4e00-\u9fa5]{2,6})', near)
        name  = name_m.group(1) if name_m else ""
        results.append({"name": name, "code": code})

    # 再匹配纯名称（用 lookup 查代码）
    if name_lookup:
        for m in re.finditer(r'[\u4e00-\u9fa5A-Za-z]{2,8}', text):
            n = m.group(0)
            if n in name_lookup:
                code = name_lookup[n]
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                results.append({"name": n, "code": code})

    return results


# ══════════════════════════════════════════════════
# 行情更新
# ══════════════════════════════════════════════════
def refresh_quotes(sector_name=None):
    """
    刷新行情快照
    sector_name=None 时刷新全部板块
    返回 {成功更新的板块名: 行情数}
    """
    data = _load_all()
    targets = [sector_name] if sector_name else list(data.keys())
    result = {}
    for name in targets:
        if name not in data:
            continue
        codes = [s['code'] for s in data[name]['stocks'] if s.get('code')]
        if not codes:
            data[name]['quotes'] = {}
            result[name] = 0
            continue
        # 调腾讯接口
        quotes = api_client.fetch_change_pct(codes)
        if isinstance(quotes, dict):
            data[name]['quotes'] = quotes
            data[name]['last_refresh'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result[name] = len(quotes)
        else:
            result[name] = 0
    _save_all(data)
    return result


def get_sector_stats(sector_name):
    """获取板块统计：涨家数 / 跌家数 / 平均涨幅 / 涨停数"""
    sector = get_sector(sector_name)
    if not sector:
        return None
    quotes = sector.get('quotes', {})
    stocks = sector['stocks']
    if not quotes:
        return {"total": len(stocks), "up": 0, "down": 0, "flat": 0,
                "limit_up": 0, "avg_pct": 0, "best": None, "worst": None}

    up, down, flat, lu = 0, 0, 0, 0
    pcts = []
    best  = None
    worst = None
    for s in stocks:
        code = s['code']
        if code not in quotes:
            continue
        q = quotes[code]
        chg = q.get('change_pct', 0)
        pcts.append(chg)
        if chg >= 9.7:
            lu += 1
        if chg > 0:
            up += 1
        elif chg < 0:
            down += 1
        else:
            flat += 1
        if best is None or chg > best['chg']:
            best = {"name": s.get('name') or q.get('name', ''),
                    "code": code, "chg": chg}
        if worst is None or chg < worst['chg']:
            worst = {"name": s.get('name') or q.get('name', ''),
                     "code": code, "chg": chg}

    return {
        "total":    len(stocks),
        "up":       up,
        "down":     down,
        "flat":     flat,
        "limit_up": lu,
        "avg_pct":  round(sum(pcts) / len(pcts), 2) if pcts else 0,
        "best":     best,
        "worst":    worst,
    }
