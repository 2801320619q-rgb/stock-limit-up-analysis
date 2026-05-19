"""
通用 UI 组件
"""
import tkinter as tk
from tkinter import scrolledtext
from .core.theme import get as theme


def make_card(parent, title, pady_top=8):
    """带标题的卡片容器"""
    C = theme()
    outer = tk.Frame(parent, bg=C['panel'],
                     highlightbackground=C['border'], highlightthickness=1)
    outer.pack(fill='x', pady=(pady_top, 0))
    tk.Label(outer, text=title, font=('微软雅黑', 9, 'bold'),
             bg=C['panel'], fg=C['accent']).pack(anchor='w', padx=12, pady=(8, 3))
    inner = tk.Frame(outer, bg=C['panel'])
    inner.pack(fill='x', padx=10, pady=(0, 10))
    return inner


def styled_btn(parent, text, color, cmd, pady=6, **kwargs):
    """统一风格按钮"""
    C = theme()
    fg = 'white' if color != C['yellow'] else '#111'
    btn = tk.Button(parent, text=text, font=('微软雅黑', 9),
                    bg=color, fg=fg, relief='flat', cursor='hand2',
                    activebackground=C['acc_dark'],
                    command=cmd, pady=pady, **kwargs)
    return btn


def styled_entry(parent, var, width=None):
    """统一风格输入框"""
    C = theme()
    kw = dict(textvariable=var, font=('微软雅黑', 9),
              bg=C['card'], fg=C['text'], insertbackground='white',
              relief='flat')
    if width:
        kw['width'] = width
    return tk.Entry(parent, **kw)


def make_log_widget(parent, font_size=9):
    """统一日志输出控件"""
    C = theme()
    w = scrolledtext.ScrolledText(parent, font=('微软雅黑', font_size),
                                   wrap='word', bg=C['card'], fg=C['text'],
                                   insertbackground='white', relief='flat',
                                   state='disabled')
    w.pack(fill='both', expand=True)
    for tag, color in [('ok', C['green']), ('fail', C['red']),
                       ('yellow', C['yellow']), ('accent', C['accent']),
                       ('dim', C['dim']), ('info', C['text']),
                       ('purple', C['purple']),
                       ('policy', C['yellow']), ('concept', C['green']),
                       ('money', C['red']), ('percent', C['accent'])]:
        w.tag_config(tag, foreground=color)
    # 涨停类别标签：用紫色背景突出
    w.tag_config('category', foreground='white', background=C['purple'],
                  font=('微软雅黑', font_size, 'bold'))
    # 类别关键词：用黄色高亮
    w.tag_config('category_kw', foreground='#1a1d23', background=C['star'])
    return w


def write_log(widget, msg, tag='info'):
    """向日志控件追加一条"""
    from datetime import datetime
    ts = datetime.now().strftime('%H:%M:%S')
    widget.config(state='normal')
    widget.insert('end', "[{}] {}\n".format(ts, msg), tag)
    widget.see('end')
    widget.config(state='disabled')


def clear_log(widget):
    widget.config(state='normal')
    widget.delete('1.0', 'end')
    widget.config(state='disabled')


# ════════════════════════════════════════════════════════════════
# 🆕 v9.9.6：股票代码"蓝字下划线 + 点击推送同花顺"工具
# ════════════════════════════════════════════════════════════════
# 用法：在任何 Text widget 上 renderer 完毕后调一次
#   attach_code_links(text_widget, app)
# 即把内容里的 6 位股票代码识别出来加上：
#   - 蓝色 + 下划线 的可点击样式
#   - 鼠标手型光标
#   - 点击触发 app.push_to_hexin_silent(code, name) ——不刷新浮窗
#   - 点击瞬间字号 +2、80ms 后还原（轻微放大动画）
# 任意 widget 多次调用安全，重复区域会自动跳过。
import re as _re

# 6 位代码（不被更多数字 / 小数点包围）
_CODE_RE = _re.compile(r"(?<![.\d])(\d{6})(?![.\d])")

# A 股合法代码前缀白名单——避免把电话号尾号 / 邮编 / 订单号误识别成股票
_VALID_CODE_PREFIXES = (
    "60", "68", "00", "30",          # 沪深主板 / 科创 / 创业
    "11", "12",                      # 可转债
    "83", "87", "43", "82",          # 北交所 / 新三板
)

# Tag 名（多个 widget 共用，但每个 widget 自己 tag_config 一次）
_LINK_TAG = "stock_code_link"
_LINK_TAG_HOVER = "stock_code_link_hover"
_LINK_TAG_PRESS = "stock_code_link_press"


def _is_valid_code(code):
    if not (code and len(code) == 6 and code.isdigit()):
        return False
    if code == "000000" or code.startswith("0000"):
        return False
    return any(code.startswith(p) for p in _VALID_CODE_PREFIXES)


def _ensure_link_tags(widget):
    """首次调用时给 widget 配置三个 link 相关 tag"""
    C = theme()
    base_font = ('微软雅黑', 10)
    try:
        cur = widget.cget('font')
        if cur:
            base_font = _parse_widget_font(cur, default=base_font)
    except Exception:
        pass

    big_font = (base_font[0], base_font[1] + 2, 'bold')

    # 蓝字 + 下划线（链接基础态）
    widget.tag_config(_LINK_TAG,
                       foreground='#4ea8ff',
                       underline=True)
    # 悬浮态：更亮一点
    widget.tag_config(_LINK_TAG_HOVER,
                       foreground='#8bc6ff',
                       underline=True)
    # 按下态：放大字体 + 主色调
    widget.tag_config(_LINK_TAG_PRESS,
                       foreground=C['accent'],
                       underline=True,
                       font=big_font)

    # 🔑 v9.9.6.1：强制把 link tag 抬到最高优先级
    # 否则 history_tab 的 main_stock（金色 + 棕背景）等老 tag 会盖掉蓝色
    # tag_raise 没有"raise above all" API，但传第二个参数就行：
    # 不传第二参数 → 抬到所有 tag 之上
    try:
        widget.tag_raise(_LINK_TAG)
        widget.tag_raise(_LINK_TAG_HOVER)
        widget.tag_raise(_LINK_TAG_PRESS)
    except Exception:
        pass


def _parse_widget_font(font_spec, default=('微软雅黑', 10)):
    """把 widget.cget('font') 返回的奇形怪状字体描述统一成 (family, size)"""
    try:
        if isinstance(font_spec, str):
            parts = font_spec.replace('{', ' ').replace('}', ' ').split()
            if len(parts) >= 2:
                try:
                    return (parts[0], int(parts[1]))
                except ValueError:
                    return default
            return default
        if isinstance(font_spec, (tuple, list)) and len(font_spec) >= 2:
            return (font_spec[0], int(font_spec[1]))
    except Exception:
        pass
    return default


def attach_code_links(widget, app, main_code=None, scope='main'):
    """
    扫描 Text widget 的当前内容，把所有合法 A 股 6 位代码渲染成"蓝字下划线"
    + 点击推送同花顺。

    widget   : tkinter Text widget
    app      : 主 App 实例
    main_code: 可选，当前主股代码（仅作 hint，不影响渲染）
    scope    : 'main'  → 主程序内的 widget；点击 → 推送同花顺 + 让浮窗 show
               'popup' → 浮窗内的 widget；点击 → 只推送（浮窗内容不变）

    多次调用幂等：会先把旧 link tag 全部移除再重新扫描。

    🔑 v9.9.6.1：错误现在会 print 到 console，不再静默吞掉，方便诊断。
    """
    import traceback as _tb
    try:
        _ensure_link_tags(widget)
    except Exception:
        _tb.print_exc()
        return

    # 先清掉旧的 link 标记
    try:
        for tag in (_LINK_TAG, _LINK_TAG_HOVER, _LINK_TAG_PRESS):
            widget.tag_remove(tag, '1.0', 'end')
    except Exception:
        _tb.print_exc()
        return

    try:
        content = widget.get('1.0', 'end-1c')
    except Exception:
        _tb.print_exc()
        return

    matches = list(_CODE_RE.finditer(content))
    if not matches:
        # 没找到代码也绑事件（让后续 insert 进来的代码能响应）
        _bind_link_handlers(widget, app, scope=scope)
        return

    added = 0
    for m in matches:
        code = m.group(1)
        if not _is_valid_code(code):
            continue
        start = m.start()
        end = m.end()
        try:
            widget.tag_add(_LINK_TAG,
                           "1.0+{}c".format(start),
                           "1.0+{}c".format(end))
            added += 1
        except Exception:
            _tb.print_exc()
            continue

    # 再次确保 link tag 在最顶层（tag_add 后某些 tk 版本会重新排序）
    try:
        widget.tag_raise(_LINK_TAG)
    except Exception:
        pass

    _bind_link_handlers(widget, app, scope=scope)
    # 控制台诊断（用户能在终端看到，正常 GUI 用户也不会被打扰）
    if added:
        print("[attach_code_links] scope={} 给 widget 加了 {} 个代码链接".format(
            scope, added))


def _bind_link_handlers(widget, app, scope='main'):
    """
    给 widget 绑定 link 相关鼠标事件。多次绑同 tag 是安全的——
    tkinter 的 tag_bind 用同名 sequence 会替换，不会叠加。
    """
    def _name_near(idx):
        """在点击位置前面找最近的中文/英文短串当 name；找不到返回 ''"""
        try:
            ln = idx.split('.')[0]
            line_text = widget.get("{}.0".format(ln), idx)
        except Exception:
            return ""
        mname = _re.search(
            r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*[（(]?\s*$',
            line_text.rstrip())
        return mname.group(1) if mname else ""

    def _code_at(event):
        """取当前鼠标 / 事件位置覆盖的 link tag 范围对应的代码"""
        try:
            idx = widget.index("@{},{}".format(event.x, event.y))
            ranges = widget.tag_prevrange(_LINK_TAG, idx + " + 1c")
            if not ranges or len(ranges) < 2:
                return None, None, None
            start, end = ranges[0], ranges[1]
            if widget.compare(idx, "<", start) or widget.compare(idx, ">=", end):
                return None, None, None
            code = widget.get(start, end)
            if not _is_valid_code(code):
                return None, None, None
            name = _name_near(start)
            return code, name, (start, end)
        except Exception:
            return None, None, None

    def _on_enter(e):
        try: widget.config(cursor='hand2')
        except Exception: pass

    def _on_leave(e):
        try: widget.config(cursor='')
        except Exception: pass
        try:
            widget.tag_remove(_LINK_TAG_HOVER, '1.0', 'end')
            widget.tag_remove(_LINK_TAG_PRESS, '1.0', 'end')
        except Exception: pass

    def _on_motion(e):
        code, _, rng = _code_at(e)
        if code and rng:
            try:
                widget.tag_remove(_LINK_TAG_HOVER, '1.0', 'end')
                widget.tag_add(_LINK_TAG_HOVER, rng[0], rng[1])
                widget.config(cursor='hand2')
            except Exception: pass
        else:
            try:
                widget.tag_remove(_LINK_TAG_HOVER, '1.0', 'end')
                widget.config(cursor='')
            except Exception: pass

    def _on_press(e):
        code, name, rng = _code_at(e)
        if not (code and rng):
            return
        # 放大动画：先打 press tag、80ms 后清掉
        try:
            widget.tag_remove(_LINK_TAG_PRESS, '1.0', 'end')
            widget.tag_add(_LINK_TAG_PRESS, rng[0], rng[1])
        except Exception:
            pass
        # 🔑 v9.9.6.2：scope='popup' 时先 lock 浮窗本地，确保 watcher 回声不刷浮窗
        # 这是 hexin_bridge.push_silencer 之外的二级保险
        if scope == 'popup':
            try:
                if hasattr(app, 'popup_lock_code'):
                    app.popup_lock_code(code)
            except Exception:
                import traceback; traceback.print_exc()
        # 🔑 v9.9.6.1：根据 scope 决定行为
        #   scope='popup' → 只推送同花顺，浮窗内容不变
        #   scope='main'  → 推送同花顺 + 让浮窗 show 这只股（"浮窗跟同花顺一起变"）
        try:
            if hasattr(app, 'push_to_hexin_silent'):
                app.push_to_hexin_silent(code, name)
            elif hasattr(app, 'push_to_hexin'):
                app.push_to_hexin(code, name)
        except Exception:
            import traceback; traceback.print_exc()

        if scope == 'main':
            try:
                if hasattr(app, 'show_stock_popup'):
                    app.show_stock_popup(code, name)
            except Exception:
                import traceback; traceback.print_exc()
        # 80ms 后取消放大
        try:
            widget.after(80, lambda: _safe_remove_tag(widget, _LINK_TAG_PRESS))
        except Exception:
            pass
        return "break"

    # 绑 tag 局部事件
    try:
        widget.tag_bind(_LINK_TAG, '<Enter>', _on_enter)
        widget.tag_bind(_LINK_TAG, '<Leave>', _on_leave)
        widget.tag_bind(_LINK_TAG, '<Motion>', _on_motion)
        widget.tag_bind(_LINK_TAG, '<Button-1>', _on_press)
    except Exception:
        import traceback; traceback.print_exc()


def _safe_remove_tag(widget, tag):
    try:
        widget.tag_remove(tag, '1.0', 'end')
    except Exception:
        pass


def apply_highlight(widget, keep_editable=False):
    """
    对 Text widget 应用关键词高亮
    keep_editable=True  → 高亮后保持可编辑（历史详情等编辑面板用）
    keep_editable=False → 高亮后恢复 disabled 只读（日志面板用）
    """
    from .core import config as cfg_mod
    from .core import text_utils
    s = cfg_mod.load_settings()
    if not s.get('highlight', True):
        return
    prev_state = str(widget.cget('state'))
    widget.config(state='normal')
    content = widget.get('1.0', 'end-1c')
    spans = text_utils.find_highlights(content)
    tag_map = {'policy':'policy','concept':'concept',
               'money':'money','percent':'percent','date':'dim',
               'category':'category','category_kw':'category_kw'}
    for start, end, tag in spans:
        try:
            widget.tag_add(tag_map.get(tag, 'accent'),
                           "1.0+{}c".format(start),
                           "1.0+{}c".format(end))
        except Exception:
            pass
    # keep_editable=True 时不改变 state（保持可编辑）
    if not keep_editable:
        widget.config(state='disabled')


# ════════════════════════════════════════════════════════
# Treeview 列宽持久化（多个 Tab 共用）
# ════════════════════════════════════════════════════════
import json as _json
from pathlib import Path as _Path
from .core.paths import DIRS as _DIRS

def _colwidth_path():
    return _Path(_DIRS["config"]) / "column_widths.json"

def load_col_widths(tab_key):
    try:
        p = _colwidth_path()
        if p.exists():
            d = _json.loads(p.read_text(encoding="utf-8"))
            return d.get(tab_key, {})
    except Exception:
        pass
    return {}

def save_col_widths(tab_key, widths):
    try:
        p = _colwidth_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        d = {}
        if p.exists():
            d = _json.loads(p.read_text(encoding="utf-8"))
        d[tab_key] = widths
        p.write_text(_json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
