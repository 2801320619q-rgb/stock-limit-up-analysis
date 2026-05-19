"""
细分标签关联度分析
- 🌟 极简提取模式：只提取【细分标签】和【涨停逻辑】，拒绝宽泛概念污染
- 基于历史记录提取标签，挖掘关联关系
- 输出：共现矩阵、关联度评分、共现股票、连带逻辑推理

v9.2 改进：
- normalize_tag：统一规范化（全角/半角/空格/尾缀清理）
- 单一数据源：以 record.category 为权威，content 仅 fallback
- build_cooccurrence 支持指定回溯天数
- 别名表 aliases.json：把"锂电"→"锂电池"这种映射做成可维护
- 标签管理：list / rename / merge / delete 全套 API
"""
import re, json, threading
from collections import defaultdict, Counter
from pathlib import Path

from . import history as hist_mod
from . import api_client


# ══════════════════════════════════════════════════
# 规范化（A2）
# ══════════════════════════════════════════════════
# 常见冗余尾缀：在标签末尾出现且去掉后剩余 ≥2 字时移除
_TRIM_SUFFIXES = (
    "产业链", "概念股", "概念", "板块", "题材", "主线", "方向", "标的", "龙头")
# 全角 → 半角的映射（常见的几个）
_FULLWIDTH_MAP = str.maketrans({
    "（": "(", "）": ")", "，": ",", "、": ",", "／": "/", "｜": "|",
    "：": ":", "；": ";", "　": " ",
})


def normalize_tag(s):
    """
    规范化单个标签字符串。返回规范化后的字符串，或 "" 表示该标签应被丢弃。
    规则：
      1. 全角→半角，去前后空白
      2. 去掉括号及其内容： "锂电池(正极)" → "锂电池"
      3. 去掉常见尾缀： "锂电池产业链" → "锂电池"
      4. 长度限制：2 ≤ len ≤ 20
    """
    if not s:
        return ""
    t = str(s).translate(_FULLWIDTH_MAP).strip()
    # 去括号内容（中英文都已经转成半角了）
    t = re.sub(r"\([^)]*\)", "", t).strip()
    # 去末尾常见冗余尾缀，但保留至少 2 字
    for suf in _TRIM_SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 2:
            t = t[: -len(suf)]
            break
    t = t.strip(" -_,.;:|/+、")
    if not (2 <= len(t) <= 20):
        return ""
    return t


# 标签别名表（C1）：把"锂电"统一为"锂电池"这种映射做成可维护文件
# 路径：data/config/tag_aliases.json，格式 { "锂电": "锂电池", "光伏概念": "光伏" }
_ALIAS_LOCK = threading.Lock()
_ALIAS_CACHE = None
_ALIAS_MTIME = 0


def _alias_path():
    from .paths import DIRS
    return Path(DIRS["config"]) / "tag_aliases.json"


def load_aliases():
    """读取别名表（带 mtime 缓存）"""
    global _ALIAS_CACHE, _ALIAS_MTIME
    p = _alias_path()
    try:
        mt = p.stat().st_mtime if p.exists() else 0
    except OSError:
        mt = 0
    with _ALIAS_LOCK:
        if _ALIAS_CACHE is not None and mt == _ALIAS_MTIME:
            return _ALIAS_CACHE
        if not p.exists():
            _ALIAS_CACHE, _ALIAS_MTIME = {}, 0
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        _ALIAS_CACHE, _ALIAS_MTIME = data, mt
        return data


def save_aliases(mapping):
    """保存别名表（原子写）"""
    import os, tempfile
    p = _alias_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, str(p))
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    with _ALIAS_LOCK:
        global _ALIAS_CACHE, _ALIAS_MTIME
        _ALIAS_CACHE = dict(mapping)
        try: _ALIAS_MTIME = p.stat().st_mtime
        except OSError: _ALIAS_MTIME = 0


def canonical(tag):
    """规范化 + 查别名表 → 最终标签名"""
    n = normalize_tag(tag)
    if not n: return ""
    aliases = load_aliases()
    # 一层重定向；如果别名也指向另一个别名，最多再跳一次
    seen = {n}
    cur = n
    for _ in range(2):
        nxt = aliases.get(cur)
        if not nxt or nxt in seen: break
        cur = normalize_tag(nxt) or cur
        seen.add(cur)
    return cur


# ══════════════════════════════════════════════════
# 标签提取（A3：单一数据源 — category 优先，content 仅 fallback）
# ══════════════════════════════════════════════════
_CONTENT_PATTERNS = [
    re.compile(r'【细分标签】\s*[：:]?\s*([^\n]+)'),
    re.compile(r'【涨停逻辑】\s*[：:]?\s*([^\n]+)'),
    re.compile(r'细分标签\s*[：:]?\s*([^\n]+)'),
    re.compile(r'涨停逻辑\s*[：:]?\s*([^\n]+)'),
]
_TAG_SEP = re.compile(r'[+、，,\s/|]+')


def _split_and_canon(s):
    """切分一行文本里的多个标签词，每个走 canonical()"""
    out = set()
    for part in _TAG_SEP.split(s or ""):
        c = canonical(part)
        if c:
            out.add(c)
    return out


def extract_tags_from_content(content, record=None):
    """
    🌟 A3 单一数据源原则：
      record.category 不空 → 只用 category（用户/批量是权威输入）
      record.category 空   → 退而求其次，从 content 的【细分标签】行扫
    所有标签都过 canonical() 规范化 + 走别名表
    """
    # 优先级 1：结构化 category
    if record:
        cat = (record.get("category") or "").strip()
        if cat:
            return _split_and_canon(cat)

    # 优先级 2：fallback —— content 里的【细分标签】行
    tags = set()
    text = content or ""
    for pat in _CONTENT_PATTERNS:
        m = pat.search(text)
        if m:
            tags |= _split_and_canon(m.group(1))
    return tags


# ══════════════════════════════════════════════════
# 全局共现矩阵（A1：可指定回溯天数）
# ══════════════════════════════════════════════════
def build_cooccurrence(days=7, min_freq=1):
    """
    扫描最近 days 天的历史，构建标签频次/共现矩阵/标签→记录索引。
    days=None 或 days<=0 表示扫全部历史。
    """
    tag_freq    = Counter()
    cooccur     = Counter()
    tag_records = defaultdict(list)

    dates = hist_mod.list_history_dates()
    if not dates:
        return {}, {}, {}
    if days is None or days <= 0:
        target_dates = dates
    else:
        target_dates = dates[:int(days)]

    for date_key in target_dates:
        records = hist_mod.load_history(date_key)
        for r in records:
            tags = extract_tags_from_content(r.get('content', ''), record=r)
            if not tags:
                continue
            for t in tags:
                tag_freq[t] += 1
                tag_records[t].append({
                    "date": date_key,
                    "name": r.get('name', ''),
                    "code": r.get('code', ''),
                    "id":   r.get('id', ''),
                })
            tags_list = sorted(tags)
            for i in range(len(tags_list)):
                for j in range(i+1, len(tags_list)):
                    key = (tags_list[i], tags_list[j])
                    cooccur[key] += 1

    filtered_tags = {t for t, c in tag_freq.items() if c >= min_freq}
    tag_freq    = {t: c for t, c in tag_freq.items() if t in filtered_tags}
    cooccur     = {k: v for k, v in cooccur.items()
                    if k[0] in filtered_tags and k[1] in filtered_tags}
    tag_records = {t: r for t, r in tag_records.items() if t in filtered_tags}
    return tag_freq, cooccur, tag_records


# ══════════════════════════════════════════════════
# 标签管理 API（B1）
# ══════════════════════════════════════════════════
def list_all_tags(days=None):
    """
    全局标签清单。返回 [{tag, freq, first_date, last_date, codes_n}, ...]
    days=None / 0 → 全部历史
    """
    dates = hist_mod.list_history_dates()
    if not dates: return []
    if days and days > 0:
        dates = dates[:int(days)]

    freq        = Counter()
    first_date  = {}
    last_date   = {}
    codes_set   = defaultdict(set)
    for d in dates:
        for r in hist_mod.load_history(d):
            tags = extract_tags_from_content(r.get('content', ''), record=r)
            for t in tags:
                freq[t] += 1
                code = r.get('code', '')
                if code: codes_set[t].add(code)
                if t not in first_date or d < first_date[t]:
                    first_date[t] = d
                if t not in last_date  or d > last_date[t]:
                    last_date[t]  = d

    out = []
    for t, f in freq.items():
        out.append({
            "tag":        t,
            "freq":       f,
            "first_date": first_date.get(t, ""),
            "last_date":  last_date.get(t, ""),
            "codes_n":    len(codes_set[t]),
        })
    out.sort(key=lambda x: (-x['freq'], x['tag']))
    return out


def _rewrite_category_field(old, new, dry_run=False):
    """
    在所有历史记录的 category 字段里，把 token=old 替换为 token=new（或删除）。
    new="" 表示删除该 token。
    返回 (changed_record_count, affected_dates)
    会调用 hist_mod 的更新接口，受其原子写 + 锁保护。
    """
    changed = 0
    dates_touched = []
    for d in hist_mod.list_history_dates():
        records = hist_mod.load_history(d)
        any_change = False
        for r in records:
            cat = r.get("category", "") or ""
            if not cat: continue
            parts = [p for p in _TAG_SEP.split(cat) if p.strip()]
            # 用 canonical 比对，避免大小写/空格差异错过
            new_parts = []
            hit = False
            for p in parts:
                if canonical(p) == old:
                    hit = True
                    if new:
                        new_parts.append(new)
                    # else: 删除 → 不加入
                else:
                    new_parts.append(p)
            if not hit:
                continue
            # 去重保持顺序
            seen, dedup = set(), []
            for p in new_parts:
                key = canonical(p)
                if key and key not in seen:
                    seen.add(key); dedup.append(p)
            new_cat = "+".join(dedup)
            if new_cat != cat:
                if not dry_run:
                    hist_mod.update_record(d, r.get("id"), category=new_cat)
                changed += 1
                any_change = True
        if any_change:
            dates_touched.append(d)
    return changed, dates_touched


def rename_tag(old, new):
    """
    把所有 category 里的 old 改名为 new。同时更新别名表。
    返回受影响记录数。
    """
    old_c = canonical(old)
    new_c = canonical(new)
    if not old_c or not new_c or old_c == new_c:
        return 0
    n, _ = _rewrite_category_field(old_c, new_c, dry_run=False)
    # 把别名表里指向 old 的也跟着改
    aliases = dict(load_aliases())
    aliases[old_c] = new_c
    for k, v in list(aliases.items()):
        if canonical(v) == old_c:
            aliases[k] = new_c
    save_aliases(aliases)
    return n


def merge_tags(sources, target):
    """
    把 sources（list[str]）里的标签全部并入 target。
    返回 (受影响记录数, 各源标签处理结果)
    """
    target_c = canonical(target)
    if not target_c: return 0, {}
    total = 0
    per_src = {}
    aliases = dict(load_aliases())
    for s in sources:
        sc = canonical(s)
        if not sc or sc == target_c:
            per_src[s] = 0
            continue
        n, _ = _rewrite_category_field(sc, target_c, dry_run=False)
        per_src[s] = n
        total += n
        aliases[sc] = target_c
    save_aliases(aliases)
    return total, per_src


def delete_tag(tag):
    """
    从所有 category 中删除该标签 token。返回受影响记录数。
    不动 content 里的文字（那是 AI 写的，删了会破坏原文）。
    """
    c = canonical(tag)
    if not c: return 0
    n, _ = _rewrite_category_field(c, "", dry_run=False)
    return n


# ══════════════════════════════════════════════════
# 关联度评分（Jaccard 系数）
# ══════════════════════════════════════════════════
def compute_relations(target_tag, tag_freq, cooccur, top_n=15):
    if target_tag not in tag_freq:
        return []
    target_freq = tag_freq[target_tag]
    relations = []
    for (a, b), co in cooccur.items():
        if a == target_tag:
            other = b
        elif b == target_tag:
            other = a
        else:
            continue
        other_freq = tag_freq.get(other, 0)
        if other_freq == 0:
            continue
        union = target_freq + other_freq - co
        if union <= 0:
            continue
        jaccard = co / union
        relations.append({
            "tag":           other,
            "cooccur_count": co,
            "score":         round(jaccard, 3),
            "support":       co,
            "self_freq":     target_freq,
            "other_freq":    other_freq,
        })
    relations.sort(key=lambda x: (-x['score'], -x['support']))
    return relations[:top_n]


# ══════════════════════════════════════════════════
# 共现股票
# ══════════════════════════════════════════════════
def co_stocks(tag_a, tag_b, tag_records):
    if tag_a not in tag_records or tag_b not in tag_records:
        return []
    set_a = {(r['name'], r['code']) for r in tag_records[tag_a]}
    set_b = {(r['name'], r['code']) for r in tag_records[tag_b]}
    common = set_a & set_b
    return sorted(common)


# ══════════════════════════════════════════════════
# 调用 AI 推理连带逻辑
# ══════════════════════════════════════════════════
def build_relation_prompt(tag_a, tag_b, co_stock_list, freq_a, freq_b, co_count):
    stocks_str = "、".join(
        "{}({})".format(n, c) for n, c in co_stock_list[:12])
    return ("""请基于以下数据，分析两个 A 股细分标签之间的「连带关系」。

【标签A】：{tag_a}（在本地历史中出现 {freq_a} 次）
【标签B】：{tag_b}（在本地历史中出现 {freq_b} 次）
【两者共同出现】：{co_count} 次
【同时具备这两个标签的代表股票】：{stocks}

请用简洁中文（300字以内）回答：
1. 这两个标签的产业逻辑是什么关系？
2. 一旦标签A行情启动，标签B大概率如何反应？
3. 投资中可以怎么利用这种关联？
4. 风险点是什么？
""").format(tag_a=tag_a, tag_b=tag_b, freq_a=freq_a, freq_b=freq_b,
            co_count=co_count, stocks=stocks_str)


def query_ai_relation(tag_a, tag_b, co_stock_list, freq_a, freq_b, co_count,
                      api_key, cfg):
    prompt = build_relation_prompt(tag_a, tag_b, co_stock_list,
                                   freq_a, freq_b, co_count)
    import requests, json, traceback
    headers = {"Authorization": "Bearer " + api_key,
               "Content-Type":  "application/json"}
    is_volcano = api_client._is_volcano_endpoint(cfg["api_url"])
    payload = {
        "messages":   [{"role": "user", "content": prompt}],
        "model":      cfg["model"],
        "stream":     False,
        "max_tokens": 800,
        "temperature": 0.3,
    }
    if not is_volcano:
        payload["search_source"] = "baidu_search_v2"
        payload["search_mode"]   = "auto"
    try:
        resp = requests.post(cfg["api_url"], headers=headers,
                             data=json.dumps(payload),
                             timeout=cfg.get("timeout", 60))
        if resp.status_code != 200:
            return "❌ HTTP {}: {}".format(resp.status_code, resp.text[:200]), False
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return "❌ 无返回内容", False
        return choices[0]["message"]["content"], True
    except Exception:
        return "❌ 异常: {}".format(traceback.format_exc()[:300]), False


# ══════════════════════════════════════════════════
# 批量分析（自定义 Prompt）
# ══════════════════════════════════════════════════
DEFAULT_BULK_PROMPT = """以下为 A 股涨停细分标签数据，请提取并解读这些词语的信息，并划分关联度。
关联度大于 50% 的标签需要你放在同一个细分主线下。

【标签清单及出现频次】
{tag_list}

【两两共现 Top 20】
{cooccur_list}

请按以下格式输出（用中文）：

## 🎯 主线划分
主线1：某某主线
  - 标签A、标签B、标签C（关联度 75%）
  - 产业逻辑：...

## 🔗 跨主线连带

## ⚠️ 注意事项

请直接输出，不要客套话。
"""


def collect_bulk_data(tag_freq, cooccur, top_tags=40, top_pairs=20):
    tags_sorted = sorted(tag_freq.items(), key=lambda x: -x[1])[:top_tags]
    tag_list_str = "\n".join(
        "  · {} ({} 次)".format(t, c) for t, c in tags_sorted)
    pairs_sorted = sorted(cooccur.items(), key=lambda x: -x[1])[:top_pairs]
    pairs_str = "\n".join(
        "  · {} ⇄ {} （共现 {} 次）".format(a, b, c)
        for (a, b), c in pairs_sorted)
    return tag_list_str, pairs_str


def query_ai_bulk_clustering(tag_freq, cooccur, api_key, cfg,
                              custom_prompt=None):
    tag_list_str, cooccur_str = collect_bulk_data(tag_freq, cooccur)
    template = custom_prompt or DEFAULT_BULK_PROMPT
    try:
        prompt = template.format(
            tag_list=tag_list_str, cooccur_list=cooccur_str)
    except KeyError:
        prompt = template + "\n\n" + tag_list_str + "\n\n" + cooccur_str

    import requests, json, traceback
    headers = {"Authorization": "Bearer " + api_key,
               "Content-Type":  "application/json"}
    is_volcano = api_client._is_volcano_endpoint(cfg["api_url"])
    payload = {
        "messages":   [{"role": "user", "content": prompt}],
        "model":      cfg["model"],
        "stream":     False,
        "max_tokens": 3000,
        "temperature": 0.3,
    }
    if not is_volcano:
        payload["search_source"] = "baidu_search_v2"
        payload["search_mode"]   = "auto"
    try:
        resp = requests.post(cfg["api_url"], headers=headers,
                             data=json.dumps(payload),
                             timeout=cfg.get("timeout", 120))
        if resp.status_code != 200:
            return "❌ HTTP {}: {}".format(resp.status_code, resp.text[:200]), False
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return "❌ 无返回内容", False
        return choices[0]["message"]["content"], True
    except Exception:
        return "❌ 异常: {}".format(traceback.format_exc()[:300]), False


def load_bulk_prompt_template():
    from .paths import DIRS
    from pathlib import Path
    p = Path(DIRS["config"]) / "tag_relation_bulk_prompt.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return DEFAULT_BULK_PROMPT


def save_bulk_prompt_template(text):
    from .paths import DIRS
    from pathlib import Path
    p = Path(DIRS["config"]) / "tag_relation_bulk_prompt.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text or DEFAULT_BULK_PROMPT, encoding="utf-8")