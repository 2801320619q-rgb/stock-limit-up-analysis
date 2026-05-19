"""
所有外部API接口
- 千帆AI搜索
- 腾讯财经实时行情
- 东方财富涨停板 / 板块 / 全市场
"""
import re, json, time, random, threading, traceback
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from urllib3.util import Retry

from .text_utils import validate_response, clean_symbols


# ══════════════════════════════════════════════════
# 东方财富统一 HTTP 层（防封 IP 核心）
#   - Session 连接复用 + cookie 持久化
#   - 全局节流（两次请求最小间隔 + 抖动）
#   - 自动重试 + 退避
#   - 完整 Chrome 125 指纹
#   - 强制 HTTPS
#   - 可选代理（IP 被封时应急）
# ══════════════════════════════════════════════════
_EM_LOCK = threading.Lock()
_EM_SESSION = None
_EM_LAST_REQ_TS = 0.0
_EM_PROXIES = None  # 由 set_em_proxy 设置

_EM_HEADERS = {
    # 🛡️ 保持与老版本几乎一致的请求形态，避免被东财识别为"另一个客户端"
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",   # ⚠️ 不要加 br：环境没装 brotli 会解码失败返回空
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "http://quote.eastmoney.com/",
}


def _get_em_session():
    """惰性创建 Session：连接复用 + 自动重试。不预热、不加额外头。"""
    global _EM_SESSION
    with _EM_LOCK:
        if _EM_SESSION is not None:
            return _EM_SESSION
        s = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.5,   # 1.5s, 3s, 6s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry,
                              pool_connections=4, pool_maxsize=4)
        s.mount("https://", adapter)
        s.mount("http://",  adapter)
        s.headers.update(_EM_HEADERS)
        if _EM_PROXIES:
            s.proxies = _EM_PROXIES
        _EM_SESSION = s
        return s


def _em_get(url, params=None, timeout=15, min_interval=0.6):
    """
    东财专用 GET：Session 连接复用 + 全局节流 + 自动重试。
    🛡️ 不再强制 HTTPS，不再注入 Sec-* / Origin 等头部，
       保持与老版本相同的请求形态，仅在客户端做透明优化。
    min_interval: 全局两次请求之间最小间隔秒数（带抖动）
    """
    global _EM_LAST_REQ_TS
    sess = _get_em_session()

    # 全局节流（线程安全）
    with _EM_LOCK:
        now = time.time()
        wait = (_EM_LAST_REQ_TS + min_interval) - now
        if wait > 0:
            time.sleep(wait + random.uniform(0, min_interval * 0.3))
        _EM_LAST_REQ_TS = time.time()

    return sess.get(url, params=params, timeout=timeout)


def set_em_proxy(proxy_url):
    """
    IP 被封时应急用。
    proxy_url 形如:
        "http://user:pass@1.2.3.4:8080"
        "socks5://1.2.3.4:1080"
    传 None 表示取消代理（需要 socks 时 pip install requests[socks]）
    """
    global _EM_PROXIES, _EM_SESSION
    if proxy_url:
        _EM_PROXIES = {"http": proxy_url, "https": proxy_url}
    else:
        _EM_PROXIES = None
    # 强制重建 session 让代理生效
    with _EM_LOCK:
        _EM_SESSION = None


# ══════════════════════════════════════════════════
# 腾讯财经实时行情接口
# ══════════════════════════════════════════════════
def _get_market_prefix(code):
    if code.startswith(("60", "68", "90", "11")):
        return "sh" + code
    elif code.startswith(("00", "30", "39", "12")):
        return "sz" + code
    return code


def fetch_change_pct(codes):
    """
    批量获取涨跌幅
    返回 {code: {"name", "price", "change_pct", "time"}}
    """
    if not codes:
        return {}
    full_codes = [_get_market_prefix(c) for c in codes]
    url = "http://qt.gtimg.cn/q={}".format(",".join(full_codes))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://gu.qq.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        # 🛡️ gbk 优先，但兜底 utf-8：腾讯偶发返回 utf-8，遇生僻字名时不再变 "?"
        raw = resp.content
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
        text = text.strip()
        result = {}
        for m in re.finditer(r'v_.*?="(.*?)"', text):
            fields = m.group(1).split("~")
            if len(fields) < 4:          # 最低要有名称+代码+现价+昨收
                continue
            try:
                code6 = fields[2]
                name  = fields[1]
                if not code6 or not re.match(r'^\d{6}$', code6):
                    continue
                price   = round(float(fields[3]), 2) if fields[3] else 0.0
                yclose  = float(fields[4]) if len(fields) > 4 and fields[4] else 0.0
                # 优先用字段32（涨跌幅），fallback 用计算值
                if len(fields) > 32 and fields[32]:
                    try:
                        chg_pct = round(float(fields[32]), 2)
                    except ValueError:
                        chg_pct = round((price - yclose) / yclose * 100, 2) if yclose else 0.0
                else:
                    chg_pct = round((price - yclose) / yclose * 100, 2) if yclose else 0.0
                # 更新时间
                raw_t = fields[30] if len(fields) > 30 else ""
                if len(raw_t) == 14 and raw_t.isdigit():
                    upd = "{}-{}-{} {}:{}:{}".format(
                        raw_t[:4], raw_t[4:6], raw_t[6:8],
                        raw_t[8:10], raw_t[10:12], raw_t[12:14])
                else:
                    upd = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                result[code6] = {"name": name, "price": price,
                                 "change_pct": chg_pct, "time": upd}
            except (ValueError, IndexError, ZeroDivisionError):
                continue
        return result
    except Exception:
        return {}


# ══════════════════════════════════════════════════
# 🆕 v9.4：股票代码 → 名称兜底反查（含磁盘缓存）
#   优先用本地学习的 stock_dict（config.get_code_to_name_lookup）
#   缺失的部分用腾讯接口批量补全，结果落盘缓存
# ══════════════════════════════════════════════════
_NAME_CACHE = None
_NAME_CACHE_LOCK = threading.Lock()

def _name_cache_path():
    from .paths import DIRS
    return DIRS["config"] / "code_name_cache.json"

def _load_name_cache():
    global _NAME_CACHE
    with _NAME_CACHE_LOCK:
        if _NAME_CACHE is not None:
            return _NAME_CACHE
        p = _name_cache_path()
        if not p.exists():
            _NAME_CACHE = {}
            return _NAME_CACHE
        try:
            _NAME_CACHE = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(_NAME_CACHE, dict):
                _NAME_CACHE = {}
        except Exception:
            _NAME_CACHE = {}
        return _NAME_CACHE

def _save_name_cache():
    p = _name_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        import os, tempfile
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_NAME_CACHE or {}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    except Exception:
        pass

def fetch_stock_names(codes, use_cache=True, refresh_missing=True):
    """
    批量查股票代码→名称的映射。
    优先级：磁盘缓存 > stock_dict > 腾讯接口实时拉取。
    返回 {code6: name}，查不到的 code 不在返回字典里。
    """
    if not codes: return {}
    codes6 = [str(c).zfill(6) for c in codes if c]
    out = {}

    # 1. stock_dict（用户自己学习过的）
    try:
        from . import config as cfg_mod
        local = cfg_mod.get_code_to_name_lookup()
        for c in codes6:
            if c in local:
                out[c] = local[c]
    except Exception:
        pass

    # 2. 磁盘缓存
    if use_cache:
        cache = _load_name_cache()
        for c in codes6:
            if c not in out and c in cache:
                out[c] = cache[c]

    # 3. 兜底：腾讯接口实时拉
    missing = [c for c in codes6 if c not in out]
    if refresh_missing and missing:
        try:
            data = fetch_change_pct(missing)
            cache = _load_name_cache()
            changed = False
            for c in missing:
                if c in data and data[c].get("name"):
                    out[c] = data[c]["name"]
                    cache[c] = data[c]["name"]
                    changed = True
            if changed:
                _save_name_cache()
        except Exception:
            pass

    return out


def extract_linked_codes(text):
    """
    从分析文本中提取联动标的股票代码
    策略：先定位 ④ 段落，找不到则全文搜
    关键修复：lookahead 中 ⑤ 必须是独立符号，不能匹配列表序号 "5."
    """
    chunk = ""

    # 找 ④/4 开头的联动标的段落，到 ⑤（全角圆圈数字）或 "⑤" / 段落结束为止
    # 注意：不要用 [5] 作为停止符，会把 "5. xxx" 列表项也截掉
    patterns = [
        # ④ 和关键词之间允许任意字符（含换行）
        r'[④]\s*[^④⑤\n]{0,30}同逻辑联动标的[^】\n]*[】]?(.*?)(?=⑤|同逻辑标的板块事件|\Z)',
        r'同逻辑联动标的[^】\n]*[】]?(.*?)(?=⑤|同逻辑标的板块事件|\Z)',
        r'联动标的[^】\n]*[】]?(.*?)(?=⑤|板块事件|\Z)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m and len(m.group(1).strip()) > 10:
            chunk = m.group(1)
            break

    src = chunk if len(chunk) > 30 else text

    # 优先匹配括号格式  (000001) / （000001）
    codes_paren = re.findall(r'[（(](\d{6})[）)]', src)
    # 再匹配裸数字（不被小数点或更多数字包围）
    codes_bare  = re.findall(r'(?<![.\d])(\d{6})(?![.\d])', src)

    all_codes = codes_paren + [c for c in codes_bare if c not in codes_paren]

    # 🛡️ 白名单：A 股代码合法前缀（沪深京三市）
    #   60/68/90/11  → 沪市主板/科创板/B股/可转债
    #   00/30/12/39  → 深市主板/创业板/可转债/指数
    #   83/87/43/82  → 北交所/新三板精选层
    # 之前用 BAD_STARTS 黑名单堵不完，邮编 / 电话尾号 / 订单号都会误匹配
    VALID_PREFIXES = ("60", "68", "00", "30", "11", "12",
                      "83", "87", "43", "82")
    seen, valid = set(), []
    for c in all_codes:
        if c in seen:
            continue
        if not any(c.startswith(p) for p in VALID_PREFIXES):
            continue
        # 额外排除全 0 / 明显异常
        if c == "000000" or c.startswith("0000"):
            continue
        seen.add(c)
        valid.append(c)
    return valid[:12]


def append_realtime_data(text, on_log=None, main_code=None):
    """
    在分析结果末尾追加联动标的实时行情
    🆕 v9.9.6：main_code 不为空时把当前主股票也加进去（放在列表最前面），
              以便在详情里显示行情时能用 ⭐ 标记主股。
    """
    codes = extract_linked_codes(text)
    # 主股加到最前面（去重）
    main6 = str(main_code or "").zfill(6) if main_code else ""
    if main6 and main6.isdigit() and len(main6) == 6:
        if main6 in codes:
            codes.remove(main6)
        codes = [main6] + codes
    if not codes:
        return text
    if on_log:
        on_log("查询联动标的实时行情: {}".format(codes), "purple")
    data = fetch_change_pct(codes)
    if not data:
        return text
    lines = ["\n\n" + "─" * 40]
    lines.append("📊 同逻辑联动标的  实时行情（腾讯财经）")
    lines.append("─" * 40)
    for code, info in data.items():
        chg = info["change_pct"]
        arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
        sign  = "+" if chg > 0 else ""
        # 🆕 v9.9.6：主股票前面加 ⭐ 标识，跟 history_tab _requery_realtime 的视觉一致
        prefix = "  ⭐ " if (main6 and code == main6) else "    "
        lines.append("{}{}（{}）  {}  {}{}%   {}".format(
            prefix, info["name"], code, info["price"],
            arrow, sign + str(chg), info["time"]))
    lines.append("─" * 40)
    return text + "\n".join(lines)


# ══════════════════════════════════════════════════
# 东方财富涨停板
# ══════════════════════════════════════════════════
def fetch_limit_up_stocks(min_pct=9.5, max_pages=5):
    """
    分页拉取涨停/接近涨停股票列表
    - min_pct:   最低涨幅过滤，默认 9.5%
    - max_pages: 最多页数，每页 100 条（默认5页=最多500条）
    """
    PAGE_SIZE = 100
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    base_params = {
        "pz": PAGE_SIZE, "po": 1, "np": 1,
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": ("m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,"
               "m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2"),
        "fields": "f12,f14,f2,f3,f4,f5,f15,f16,f17,f18",
    }
    result = []
    seen   = set()
    try:
        for page in range(1, max_pages + 1):
            params = dict(base_params)
            params["pn"] = page
            params["_"]  = int(time.time() * 1000)
            resp  = _em_get(url, params=params, timeout=15, min_interval=0.6)
            body  = resp.json().get("data", {}) or {}
            items = body.get("diff", [])
            if not items:
                break
            for it in items:
                try:
                    chg = float(it.get("f3", 0))
                    if chg < min_pct:
                        return result   # 按涨幅降序，低于阈值后面也不用抓了
                    code = str(it.get("f12", "")).zfill(6)
                    if code in seen:
                        continue
                    seen.add(code)
                    result.append({
                        "code":       code,
                        "name":       it.get("f14", ""),
                        "price":      float(it.get("f2", 0)),
                        "change_pct": chg,
                        "open":       float(it.get("f17", 0)),
                        "high":       float(it.get("f15", 0)),
                        "low":        float(it.get("f16", 0)),
                    })
                except (TypeError, ValueError):
                    continue
            if len(items) < PAGE_SIZE:
                break
        return result
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════
# 千帆 AI 搜索
# ══════════════════════════════════════════════════
def _is_volcano_endpoint(url):
    """识别火山方舟 API（基于 URL）"""
    if not url:
        return False
    return "volces.com" in url or "ark.cn-beijing" in url


def call_qianfan(stock_name, stock_code, api_key, cfg, on_log=None, category=""):
    """
    调用 AI 搜索 API（同时支持百度千帆 / 火山方舟豆包）
    - category: 涨停类别（如"AI算力+算电协同"），如果传入且开关开启，作为补充上下文加入 prompt
    返回 (result_text, success, sources_list)
    """
    headers = {"Authorization": "Bearer " + api_key,
               "Content-Type":  "application/json"}
    prompt = cfg["prompt_template"].format(
        stock_name=stock_name, stock_code=stock_code)

    # 🔑 类别上下文：只有开关开启时才生效（统一控制 prompt 和结果中的标签行）
    use_category = cfg.get("use_category", True)
    has_category = bool(category and category.strip()) and use_category
    if has_category:
        prompt = ("⚠️ 已知该股票的涨停类别标签为：「{}」，请结合此标签深入分析，"
                  "确保 ②市场主要核心上涨共识 和 ④同逻辑联动标的 紧扣此主线。\n\n".format(
                      category.strip()) + prompt)

    api_url = cfg["api_url"]
    is_volcano = _is_volcano_endpoint(api_url)

    if is_volcano:
        # 火山方舟：标准 OpenAI 协议，不支持联网搜索
        payload = {
            "messages":   [{"role": "user", "content": prompt}],
            "model":      cfg["model"],
            "stream":     False,
            "max_tokens": cfg["max_tokens"],
            "temperature": cfg["temperature"],
        }
        if on_log:
            on_log("使用火山方舟 API（不支持联网）", "dim")
    else:
        # 百度千帆：带联网搜索
        payload = {
            "messages":      [{"role": "user", "content": prompt}],
            "model":         cfg["model"],
            "search_source": "baidu_search_v2",
            "search_mode":   "auto",
            "stream":        False,
            "max_tokens":    cfg["max_tokens"],
            "temperature":   cfg["temperature"],
        }

    sources = []
    try:
        resp = requests.post(api_url, headers=headers,
                             data=json.dumps(payload), timeout=cfg["timeout"])
        if on_log:
            on_log("HTTP {}".format(resp.status_code), "dim")

        if resp.status_code == 429:
            return "❌ 请求过多(429)", False, []
        if resp.status_code != 200:
            return "❌ HTTP {}: {}".format(resp.status_code, resp.text[:200]), False, []

        result = resp.json()
        if "error" in result:
            return "❌ API错误: {}".format(result["error"]), False, []

        # 提取数据源（仅千帆有，火山没有）
        if not is_volcano:
            si = result.get("search_info", {})
            raw_sources = si.get("search_results", []) or si.get("results", [])
            for s in raw_sources:
                sources.append({
                    "title": s.get("title") or s.get("name") or "未知来源",
                    "url":   s.get("url") or s.get("link") or "",
                })
            if on_log and sources:
                on_log("搜索到 {} 个数据源".format(len(sources)), "purple")

        choices = result.get("choices", [])
        if not choices:
            full = json.dumps(result, ensure_ascii=False)[:400]
            return "❌ 返回无 choices: {}".format(full), False, sources

        content = choices[0]["message"]["content"]
        if on_log:
            on_log("原始字数: {} 字".format(len(content)), "dim")

        # 🔑 关键修复：只有开关开启 + 有 category 时才插入标签行
        category_prefix = ""
        if has_category:
            category_prefix = "【细分标签】：{}\n\n".format(category.strip())

        ok, cleaned = validate_response(content)
        if ok:
            cleaned = category_prefix + cleaned
            cleaned = append_realtime_data(cleaned, on_log=on_log,
                                            main_code=stock_code)
            return cleaned, True, sources

        # 格式异常：清洗符号后追加实时行情
        raw_cleaned = clean_symbols(content)
        raw_cleaned = category_prefix + raw_cleaned
        raw_cleaned = append_realtime_data(raw_cleaned, on_log=on_log,
                                            main_code=stock_code)
        return "⚠️ 格式异常: {}\n\n原始:\n{}".format(cleaned, raw_cleaned), False, sources

    except requests.exceptions.Timeout:
        return "❌ 请求超时", False, []
    except Exception:
        return "❌ 异常: {}".format(traceback.format_exc()[:300]), False, []


# ══════════════════════════════════════════════════
# 东方财富板块接口
# ══════════════════════════════════════════════════
def fetch_sectors(sector_type="concept", top_n=200):
    """
    拉取板块列表（行业/概念）
    - sector_type: "concept" 概念板块 / "industry" 行业板块
    - top_n: 最多返回多少个板块（按涨幅降序）
    返回 [{"code","name","change_pct","price_change","turnover","amount",
           "main_inflow","leader_name","leader_pct"}, ...]
    """
    # m:90+t:2 概念板块；m:90+t:3 行业板块
    fs = "m:90+t:3" if sector_type == "industry" else "m:90+t:2"
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": top_n, "po": 1, "np": 1,
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": fs,
        "fields": "f12,f14,f2,f3,f4,f5,f6,f7,f62,f128,f136",
        "_": int(time.time() * 1000),
    }
    try:
        resp = _em_get(url, params=params, timeout=15, min_interval=0.6)
        body = resp.json().get("data", {}) or {}
        items = body.get("diff", []) or []
        result = []
        for it in items:
            try:
                result.append({
                    "code":         str(it.get("f12", "")),
                    "name":         it.get("f14", ""),
                    "price":        float(it.get("f2", 0)),
                    "change_pct":   float(it.get("f3", 0)),
                    "price_change": float(it.get("f4", 0)),
                    "turnover":     float(it.get("f5", 0)),      # 成交量(手)
                    "amount":       float(it.get("f6", 0)),      # 成交额(元)
                    "amplitude":    float(it.get("f7", 0)),      # 振幅
                    "main_inflow":  float(it.get("f62", 0)),     # 主力净流入(元)
                    "leader_name":  it.get("f128", ""),
                    "leader_pct":   float(it.get("f136", 0)),
                })
            except (TypeError, ValueError):
                continue
        return result
    except Exception as e:
        return {"error": str(e)}


def fetch_sector_stocks(sector_code, top_n=200):
    """
    拉取某板块下的所有成份股
    - sector_code: 板块代码（如 'BK0428'）
    返回 [{"code","name","price","change_pct","amount","turnover_rate","main_inflow","status"}, ...]
    其中 status: '一字板' / '涨停' / '炸板' / '冲高回落' / '正常' 等
    """
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": top_n, "po": 1, "np": 1,
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "b:{}".format(sector_code),
        "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f15,f16,f17,f18,f62",
        "_": int(time.time() * 1000),
    }
    try:
        resp  = _em_get(url, params=params, timeout=15, min_interval=0.6)
        body  = resp.json().get("data", {}) or {}
        items = body.get("diff", []) or []
        result = []
        for it in items:
            try:
                code  = str(it.get("f12", "")).zfill(6)
                name  = it.get("f14", "")
                price = float(it.get("f2", 0))
                chg   = float(it.get("f3", 0))
                high  = float(it.get("f15", 0))
                low   = float(it.get("f16", 0))
                opn   = float(it.get("f17", 0))
                prev  = float(it.get("f18", 0))
                tr_rate = float(it.get("f8", 0))    # 换手率
                amount  = float(it.get("f6", 0))
                main_in = float(it.get("f62", 0))

                # 判断状态：
                #   - 一字板: 开 = 高 = 低 = 现价 = 涨停价
                #   - 涨停:   现价 = 高 ≈ 涨停（涨幅约 9.8-10%）
                #   - 炸板:   日内最高 ≈ 涨停 but 现价 < 涨停
                #   - 冲高回落: 高 - 现 > 3%
                limit_up_pct = 9.8 if code.startswith(("6","00")) else 19.8 if code.startswith("30") else 9.8
                # 创业板/科创板 20%，其他 10%
                if code.startswith(("30","68")):
                    limit_up_pct = 19.8
                high_pct = ((high - prev) / prev * 100) if prev else 0

                if chg >= limit_up_pct and abs(price - high) < 0.01 and abs(opn - high) < 0.01 and abs(low - high) < 0.01:
                    status = "一字板"
                elif chg >= limit_up_pct and abs(price - high) < 0.01:
                    status = "涨停"
                elif high_pct >= limit_up_pct and chg < limit_up_pct - 1:
                    status = "炸板"
                elif high_pct - chg >= 3:
                    status = "冲高回落"
                elif chg >= 5:
                    status = "强势"
                elif chg >= 0:
                    status = "上涨"
                elif chg <= -limit_up_pct:
                    status = "跌停"
                else:
                    status = "下跌"

                result.append({
                    "code":          code,
                    "name":          name,
                    "price":         price,
                    "change_pct":    chg,
                    "high_pct":      round(high_pct, 2),
                    "amount":        amount,
                    "turnover_rate": tr_rate,
                    "main_inflow":   main_in,
                    "status":        status,
                })
            except (TypeError, ValueError):
                continue
        return result
    except Exception as e:
        return {"error": str(e)}



# ══════════════════════════════════════════════════
# 全市场行情快照（分页 + 节流版，防封 IP 关键改造）
# ══════════════════════════════════════════════════
def fetch_all_market_stocks(on_progress=None):
    """
    分页拉取全市场 A 股行情（含北交所）。

    ⚠️ 历史教训：旧版本用 pz=6000 单次请求触发了东财 WAF 黑名单。
       现改为 pz=200 分页 + _em_get 全局节流（默认 0.8s 间隔）。
    返回 [{"code","name","price","change_pct","high","low","prev_close"}, ...]
    """
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    fs = ("m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:0+t:7+f:!2,"
          "m:1+t:2+f:!2,m:1+t:23+f:!2,m:1+t:3+f:!2,m:0+t:81+f:!2")

    PAGE_SIZE = 200          # 不要超过 200
    MAX_PAGES = 30           # 30*200 = 6000 上限
    all_stocks = []
    seen = set()

    try:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "pn": page, "pz": PAGE_SIZE, "po": 1, "np": 1,
                "fltt": 2, "invt": 2, "fid": "f3",
                "fs": fs,
                "fields": "f12,f14,f2,f3,f15,f16,f18",
                "_": int(time.time() * 1000),
            }
            if on_progress:
                on_progress(page, MAX_PAGES)

            resp  = _em_get(url, params=params, timeout=20, min_interval=0.8)
            body  = resp.json().get("data", {}) or {}
            items = body.get("diff", []) or []
            if not items:
                break

            for it in items:
                try:
                    code = str(it.get("f12", "")).zfill(6)
                    if not code or code in seen:
                        continue
                    # 过滤退市股、停牌无数据等
                    name = it.get("f14", "")
                    if not name or code.startswith(("9", "2")):
                        continue
                    price = float(it.get("f2", 0))
                    if price <= 0:
                        continue
                    seen.add(code)
                    all_stocks.append({
                        "code":        code,
                        "name":        name,
                        "price":       price,
                        "change_pct":  float(it.get("f3", 0)),
                        "high":        float(it.get("f15", 0)),
                        "low":         float(it.get("f16", 0)),
                        "prev_close":  float(it.get("f18", 0)),
                    })
                except (TypeError, ValueError):
                    continue

            # 不足一页 → 已到末尾
            if len(items) < PAGE_SIZE:
                break

        return all_stocks
    except Exception as e:
        return {"error": str(e)}