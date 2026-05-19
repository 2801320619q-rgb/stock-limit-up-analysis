"""
🗂️ 我的板块（整合版）
─────────────────────────────────────
左侧导航：
  📌 自选股                  ← 原 自选股 Tab
  ─────────
  📂 半导体（用户自建板块）
  📂 AI算力
  📂 ...
  ─────────
  🕸️ 标签关联度              ← 原 标签关联 Tab

右侧根据选择切换：
  - 自选股：列表 + 详情（含历史分析）
  - 自建板块：股票表 + 行情 + 详情
  - 标签关联度：图表 + AI 推理

主界面顶部统一一个「📥 快速导入栏」：
  粘贴 "半导体：寒武纪 海光信息 600519" → 自动建板块+加股票
"""
import json
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# matplotlib（用于关联度图表）
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
try:
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
except Exception:
    pass

from .base import BaseTab
from ..widgets import load_col_widths, save_col_widths
from ..widgets import make_card, styled_btn, styled_entry, apply_highlight
from ..core import (config as cfg_mod, history as hist_mod,
                    api_client, my_sectors, tag_relation as tr)
from ..bus import bus, Events, state


# 三种视图
VIEW_FAV   = "favorites"
VIEW_USER  = "user_sector"
VIEW_TAG   = "tag_relation"


class MySectorsTab(BaseTab):
    title = "我的板块"

    def __init__(self, app):
        super().__init__(app)
        self._cur_view = None    # VIEW_FAV / VIEW_USER / VIEW_TAG
        self._cur_sector_name = None
        self._row_data = {}      # iid -> dict（自选股/板块共用）
        self._auto_refresh_id = None
        self._auto_refresh_on = False
        # 标签关联度
        self._tag_freq = {}
        self._cooccur  = {}
        self._tag_records = {}
        self._cur_tag  = None
        self._cur_rels = []
        self._cur_other_tag = None

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=10, pady=8)

        # ═══════════ 顶部：快速导入栏 ═══════════
        top = tk.Frame(body, bg=C['panel'],
                        highlightbackground=C['border'], highlightthickness=1)
        top.pack(fill='x', pady=(0, 6))
        ti = tk.Frame(top, bg=C['panel']); ti.pack(fill='x', padx=8, pady=6)
        tk.Label(ti, text="📥 快速导入", font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=(0, 6))

        self._quick_var = tk.StringVar()
        quick_entry = tk.Entry(ti, textvariable=self._quick_var,
                                font=('微软雅黑', 10),
                                bg=C['card'], fg=C['text'],
                                insertbackground='white', relief='flat')
        quick_entry.pack(side='left', fill='x', expand=True, ipady=4)
        quick_entry.bind('<Return>', lambda e: self._quick_import())

        styled_btn(ti, "➕ 导入", C['green'],
                   self._quick_import).pack(side='left', padx=(6, 0))

        tk.Label(top,
                 text="💡 格式：「板块名：股票1 股票2 代码1 ...」  例：半导体：寒武纪 海光信息 600519",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(anchor='w', padx=10, pady=(0, 4))

        # ═══════════ 主体：左导航 / 右内容 ═══════════
        pw = tk.PanedWindow(body, bg=C['bg'], sashwidth=5,
                             sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        left  = tk.Frame(pw, bg=C['bg'])
        right = tk.Frame(pw, bg=C['bg'])
        pw.add(left,  minsize=200)
        pw.add(right, minsize=620)

        # ─── 左：导航 ───
        tk.Label(left, text="🗂️ 我的导航",
                 font=('微软雅黑', 9, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(anchor='w', pady=(0, 4))

        self._nav = tk.Listbox(left,
                                font=('微软雅黑', 10),
                                bg=C['card'], fg=C['text'],
                                selectbackground=C['acc_dark'],
                                selectforeground='white',
                                relief='flat', highlightthickness=0,
                                activestyle='none')
        nvsb = ttk.Scrollbar(left, orient='vertical', command=self._nav.yview)
        self._nav.configure(yscrollcommand=nvsb.set)
        self._nav.pack(side='left', fill='both', expand=True)
        nvsb.pack(side='right', fill='y')
        self._nav.bind('<<ListboxSelect>>', lambda e: self._on_nav_select())

        # 左下按钮
        lb = tk.Frame(left, bg=C['bg']); lb.pack(fill='x', pady=(4, 0))
        styled_btn(lb, "➕ 新建板块", C['green'],
                   self._create_sector_dialog).pack(side='left', padx=(0, 3))
        styled_btn(lb, "✏️ 重命名", C['accent'],
                   self._rename_sector).pack(side='left', padx=(0, 3))
        styled_btn(lb, "🗑 删除", C['red'],
                   self._delete_sector).pack(side='left')
        tk.Label(left, text="💡 Ctrl+N 新建  Ctrl+Enter 分析",
                 font=('微软雅黑', 7), bg=C['bg'], fg=C['dim']).pack(anchor='w', pady=(2, 0))

        # ─── 右：三种视图共用容器（动态切换） ───
        self._right_container = tk.Frame(right, bg=C['bg'])
        self._right_container.pack(fill='both', expand=True)

        # 预先构建三个视图（懒加载）
        self._views = {}

        # 初始化
        self._refresh_nav()
        # 默认选中第一项（自选股）
        if self._nav.size() > 0:
            self._nav.selection_set(0)
            self._on_nav_select()

        # 事件
        bus.on(Events.FAVORITES_UPDATED,
               lambda *a: self.app.root.after(100, self._on_event_update))
        bus.on(Events.HISTORY_UPDATED,
               lambda *a: self.app.root.after(100, self._on_event_update))

        # 快捷键
        self._bind_shortcuts()

    def _on_event_update(self):
        """事件触发时，根据当前视图刷新"""
        if self._cur_view == VIEW_FAV:
            self._render_favorites()
        elif self._cur_view == VIEW_USER:
            self._render_user_sector()

    def _bind_shortcuts(self):
        root = self.app.root
        root.bind('<Control-n>', lambda e: self._maybe(self._create_sector_dialog))
        root.bind('<Control-N>', lambda e: self._maybe(self._create_sector_dialog))
        root.bind('<Control-Return>', lambda e: self._maybe(self._analyze_current))

    def _maybe(self, fn):
        try:
            if self.app.nb.select() == str(self.frame):
                fn()
        except Exception:
            pass

    # ════════════════════════════════════════════════
    # 导航
    # ════════════════════════════════════════════════
    def _refresh_nav(self):
        cur_sel = self._nav.curselection()
        cur_text = self._nav.get(cur_sel[0]) if cur_sel else ""

        self._nav.delete(0, 'end')
        # 1. 自选股
        favs = cfg_mod.load_favorites()
        self._nav.insert('end', "📌 自选股 ({})".format(len(favs)))
        # 2. 分隔
        self._nav.insert('end', "─" * 22)
        # 3. 自建板块
        for name in my_sectors.list_sectors():
            sector = my_sectors.get_sector(name)
            n = len(sector['stocks']) if sector else 0
            self._nav.insert('end', "  📂 {}  ({})".format(name, n))
        # 4. 分隔
        self._nav.insert('end', "─" * 22)
        # 5. 标签关联度
        self._nav.insert('end', "🕸️ 标签关联度")

        # 恢复选中
        for i in range(self._nav.size()):
            if self._nav.get(i) == cur_text:
                self._nav.selection_set(i)
                return
        if self._nav.size() > 0:
            self._nav.selection_set(0)

    def _on_nav_select(self):
        sel = self._nav.curselection()
        if not sel: return
        text = self._nav.get(sel[0])

        if text.startswith("─"):
            # 分隔行，跳过
            return

        # 清空右侧
        for w in self._right_container.winfo_children():
            w.destroy()

        if text.startswith("📌 自选股"):
            self._cur_view = VIEW_FAV
            self._cur_sector_name = None
            self._build_favorites_view()
        elif text.startswith("🕸️"):
            self._cur_view = VIEW_TAG
            self._cur_sector_name = None
            self._build_tag_relation_view()
        elif "📂" in text:
            # 提取板块名
            name = text.strip().lstrip("📂 ").strip()
            # 去掉末尾的 (N)
            name = re.sub(r'\s*\(\d+\)\s*$', '', name).strip()
            self._cur_view = VIEW_USER
            self._cur_sector_name = name
            self._build_user_sector_view()

    # ════════════════════════════════════════════════
    # 快速导入
    # ════════════════════════════════════════════════
    def _quick_import(self):
        text = self._quick_var.get().strip()
        if not text:
            return

        name_lookup = cfg_mod.get_name_lookup()
        parsed = my_sectors.parse_smart(text, name_lookup=name_lookup)
        sector_name = parsed.get('sector_name')
        stocks = parsed.get('stocks', [])

        if not sector_name:
            # 没有板块名 → 默认放到当前板块
            if self._cur_view == VIEW_USER and self._cur_sector_name:
                sector_name = self._cur_sector_name
            else:
                messagebox.showinfo("提示",
                    "请按格式输入：板块名：股票1 股票2 ...\n"
                    "例如：半导体：寒武纪 海光信息 600519\n\n"
                    "或先选中一个板块再粘贴股票")
                return

        if not stocks:
            messagebox.showinfo("提示",
                "未识别到任何股票代码。\n\n"
                "若使用中文名导入，请确保该名称已在历史记录中出现过。\n"
                "或使用6位代码导入（如 688256）。")
            return

        # 板块不存在则创建
        if not my_sectors.get_sector(sector_name):
            ok, msg = my_sectors.create_sector(sector_name)
            if not ok:
                messagebox.showwarning("失败", msg); return

        # 加入股票
        ok, msg, added = my_sectors.add_stocks(sector_name, stocks)

        # 清空输入框
        self._quick_var.set("")
        self._refresh_nav()

        # 切换到该板块
        for i in range(self._nav.size()):
            line = self._nav.get(i)
            if sector_name in line and "📂" in line:
                self._nav.selection_clear(0, 'end')
                self._nav.selection_set(i)
                self._cur_view = VIEW_USER
                self._cur_sector_name = sector_name
                for w in self._right_container.winfo_children():
                    w.destroy()
                self._build_user_sector_view()
                break

        # 后台异步刷新行情
        threading.Thread(target=lambda: (
            my_sectors.refresh_quotes(sector_name),
            state.ui_queue.put(self._render_user_sector)
        ), daemon=True).start()

        # 提示用户结果
        not_found = []
        if added < len(stocks):
            # 比较代码 vs 想加入的总数
            existing_codes = {s['code'] for s in my_sectors.get_sector(sector_name)['stocks']}
            for s in stocks:
                if s['code'] not in existing_codes:
                    not_found.append("{}({})".format(s.get('name','?'), s['code']))

        # 简短的临时提示（不弹窗，免打扰）
        msg = "✅ 导入「{}」：识别 {} 只，新增 {} 只".format(
            sector_name, len(stocks), added)
        bus.emit(Events.FAVORITES_UPDATED)

    # ════════════════════════════════════════════════
    # 视图1: 自选股
    # ════════════════════════════════════════════════
    def _build_favorites_view(self):
        C = self.C
        v = tk.Frame(self._right_container, bg=C['bg'])
        v.pack(fill='both', expand=True)
        self._views[VIEW_FAV] = v

        # 顶部
        hr = tk.Frame(v, bg=C['bg']); hr.pack(fill='x', pady=(0, 6))
        tk.Label(hr, text="📌 自选股", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(side='left')
        styled_btn(hr, "🚀 全部分析", C['green'], self._fav_analyze_all).pack(side='right')
        styled_btn(hr, "🔄 刷新", C['idle'], self._render_favorites).pack(side='right', padx=(0, 4))

        # 内嵌添加栏
        ar = tk.Frame(v, bg=C['panel'],
                       highlightbackground=C['border'], highlightthickness=1)
        ar.pack(fill='x', pady=(0, 6))
        ar_in = tk.Frame(ar, bg=C['panel']); ar_in.pack(fill='x', padx=8, pady=6)
        self._fav_name = tk.StringVar()
        self._fav_code = tk.StringVar()
        self._fav_tag  = tk.StringVar()
        for lbl, var, w in [("名称", self._fav_name, 12),
                              ("代码", self._fav_code, 8),
                              ("标签/类别", self._fav_tag, 18)]:
            tk.Label(ar_in, text=lbl, font=('微软雅黑', 8),
                     bg=C['panel'], fg=C['dim']).pack(side='left', padx=(0, 3))
            styled_entry(ar_in, var, w).pack(side='left', padx=(0, 8), ipady=3)
        styled_btn(ar_in, "➕ 添加", C['accent'], self._fav_add).pack(side='left')

        # 双栏：左表 / 右详情
        pw = tk.PanedWindow(v, bg=C['bg'], sashwidth=5,
                             sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        lf = tk.Frame(pw, bg=C['bg'])
        rf = tk.Frame(pw, bg=C['bg'])
        pw.add(lf, minsize=360)
        pw.add(rf, minsize=400)

        cols = ('name', 'code', 'tag', 'last_date', 'next_day', 'added')
        col_widths = load_col_widths('favorites')
        defaults = {'name': 100, 'code': 75, 'tag': 130,
                    'last_date': 90, 'next_day': 75, 'added': 130}
        titles   = {'name': '名称', 'code': '代码',
                    'tag': '细分标签', 'last_date': '最近分析',
                    'next_day': '次日%', 'added': '添加时间'}
        self._fav_tree = ttk.Treeview(lf, columns=cols, show='headings', height=22)
        for col in cols:
            self._fav_tree.heading(col, text=titles[col])
            self._fav_tree.column(col,
                                   width=col_widths.get(col, defaults[col]),
                                   minwidth=40,
                                   anchor='center' if col != 'name' else 'w',
                                   stretch=True)
        fvsb = ttk.Scrollbar(lf, orient='vertical', command=self._fav_tree.yview)
        self._fav_tree.configure(yscrollcommand=fvsb.set)
        self._fav_tree.pack(side='left', fill='both', expand=True)
        fvsb.pack(side='right', fill='y')

        def _save_w(*_):
            save_col_widths('favorites',
                {c: self._fav_tree.column(c, 'width') for c in cols})
        self._fav_tree.bind('<ButtonRelease-1>', _save_w)

        self._fav_tree.tag_configure('green', foreground=C['red'])
        self._fav_tree.tag_configure('red',   foreground=C['green'])
        self._fav_tree.tag_configure('flat',  foreground=C['dim'])
        self._fav_tree.bind('<<TreeviewSelect>>', lambda e: self._fav_show_detail())
        self._fav_tree.bind('<Delete>',           lambda e: self._fav_remove())
        self._fav_tree.bind('<Double-1>',         lambda e: self._fav_analyze_sel())

        # 右键菜单
        self._fav_ctx = self._build_fav_ctx()
        self._fav_tree.bind('<Button-3>', self._show_fav_ctx)
        self._fav_tree.bind('<Button-2>', self._show_fav_ctx)

        # 详情面板
        rh = tk.Frame(rf, bg=C['panel'],
                       highlightbackground=C['border'], highlightthickness=1)
        rh.pack(fill='x')
        self._fav_title = tk.StringVar(value="📄 详情（点击左侧）")
        tk.Label(rh, textvariable=self._fav_title,
                 font=('微软雅黑', 10, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=8, pady=6)
        styled_btn(rh, "✨ 自动高亮", C['acc_dark'],
                   lambda: apply_highlight(self._fav_detail, keep_editable=True),
                   pady=3).pack(side='right', padx=(0, 4), pady=4)

        self._fav_detail = tk.Text(rf, font=('微软雅黑', 10), wrap='word',
                                    bg=C['card'], fg=C['text'],
                                    relief='flat', padx=10, pady=8,
                                    state='disabled', cursor='arrow')
        dvsb = ttk.Scrollbar(rf, orient='vertical', command=self._fav_detail.yview)
        self._fav_detail.configure(yscrollcommand=dvsb.set)
        self._fav_detail.pack(side='left', fill='both', expand=True)
        dvsb.pack(side='right', fill='y')

        for tag, fg, bg in [
            ('accent', C['accent'], ''), ('star_tag', C['star'], ''),
            ('dim', C['dim'], ''), ('policy', C['yellow'], ''),
            ('concept', C['green'], ''), ('money', C['red'], ''),
            ('percent', C['accent'], ''),
            ('category', 'white', C['purple']),
            ('category_kw', '#1a1d23', C['star']),
            ('h2', C['yellow'], ''),
        ]:
            kw = {'foreground': fg}
            if bg: kw['background'] = bg
            if tag == 'category':
                kw['font'] = ('微软雅黑', 10, 'bold')
            self._fav_detail.tag_config(tag, **kw)

        self._render_favorites()

    def _build_fav_ctx(self):
        C = self.C
        m = tk.Menu(self._fav_tree, tearoff=0,
                     bg=C['panel'], fg=C['text'],
                     activebackground=C['acc_dark'],
                     activeforeground='white',
                     font=('微软雅黑', 9))
        m.add_command(label="🔎  查看股票详情", command=self._fav_show_popup)
        m.add_separator()
        m.add_command(label="🔍  分析选中", command=self._fav_analyze_sel)
        m.add_command(label="🚀  分析全部", command=self._fav_analyze_all)
        m.add_separator()
        m.add_command(label="📋  复制代码", command=lambda: self._fav_copy('code'))
        m.add_command(label="📋  复制 名称+代码", command=lambda: self._fav_copy('name_code'))
        m.add_separator()
        m.add_command(label="🏷️  编辑标签", command=self._fav_edit_tag)
        m.add_command(label="📜  查看完整历史", command=self._fav_view_history)
        m.add_separator()
        m.add_command(label="🗑  删除", command=self._fav_remove)
        return m

    def _fav_show_popup(self):
        sel = self._fav_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if data:
            self.app.show_stock_popup(data.get('code',''), data.get('name',''))

    def _show_fav_ctx(self, event):
        iid = self._fav_tree.identify_row(event.y)
        if iid:
            if iid not in self._fav_tree.selection():
                self._fav_tree.selection_set(iid)
            try:
                self._fav_ctx.tk_popup(event.x_root, event.y_root)
            finally:
                self._fav_ctx.grab_release()

    def _render_favorites(self):
        if not hasattr(self, '_fav_tree'):
            return
        for i in self._fav_tree.get_children():
            self._fav_tree.delete(i)
        self._row_data.clear()

        favs = cfg_mod.load_favorites()
        index = self._build_history_index()
        hidx = hist_mod.get_code_count_index()
        for f in favs:
            code = f.get('code', '')
            last = index.get(code)
            last_date = ""
            nd_str = ""
            row_tag = ''
            if last:
                d = last['date']
                last_date = "{}-{}".format(d[4:6], d[6:])
                nd = last.get('next_day')
                if nd and nd.get('change_pct') is not None:
                    pct = nd['change_pct']
                    nd_str = "{:+.1f}%".format(pct)
                    row_tag = 'green' if pct > 0 else ('red' if pct < 0 else 'flat')
            # 🆕 v9.6：有历史则 name 后追加 📊
            mark = " 📊" if hidx.get(str(code).zfill(6), 0) > 0 else ""
            iid = self._fav_tree.insert('', 'end', values=(
                f.get('name','') + mark, f.get('code',''),
                f.get('tag',''), last_date, nd_str, f.get('added_at','')
            ), tags=(row_tag,) if row_tag else ())
            self._row_data[iid] = {**f, 'last_record': last}

    def _build_history_index(self):
        index = {}
        for date_key in hist_mod.list_history_dates():
            for r in hist_mod.load_history(date_key):
                code = r.get('code', '')
                if not code: continue
                if code not in index or date_key > index[code]['date']:
                    index[code] = {**r, 'date': date_key}
        return index

    def _fav_show_detail(self):
        sel = self._fav_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        # 🆕 v9.6：通知浮窗（联动模式开启时刷新）
        self.app.notify_stock_focus(data.get('code',''), data.get('name',''))

        T = self._fav_detail
        T.config(state='normal')
        T.delete('1.0', 'end')

        name = data.get('name', ''); code = data.get('code', '')
        tag  = data.get('tag', '')
        self._fav_title.set("📄 {} ({})".format(name, code))

        def w(text, t=None):
            if t: T.insert('end', text, t)
            else: T.insert('end', text)

        w("⭐ {} ({})\n".format(name, code), 'accent')
        if tag:
            w("🏷️ 标签 / 涨停类别: ", 'star_tag')
            w(tag + "\n", 'category')
        w("📅 加入时间: " + data.get('added_at', '未知') + "\n", 'dim')
        w("\n")

        last = data.get('last_record')
        if last:
            d = last['date']
            w("─" * 50 + "\n", 'dim')
            w("📈 最近一次分析  ", 'h2')
            w("({}-{}-{}  {})\n".format(d[:4], d[4:6], d[6:],
                                          last.get('time', '')), 'dim')
            nd = last.get('next_day')
            if nd and nd.get('change_pct') is not None:
                pct = nd['change_pct']
                ct = 'concept' if pct > 0 else 'money'
                w("📊 次日: ", 'star_tag')
                w("{:+.2f}%".format(pct), ct)
                w("  (" + nd.get('date', '') + ")\n", 'dim')
            if last.get('note'):
                w("📝 " + last['note'] + "\n", 'star_tag')
            w("\n")
            content = last.get('content', '')
            if content:
                w(content)
                apply_highlight(T, keep_editable=True)
            else:
                w("（无分析内容）\n", 'dim')
        else:
            w("─" * 50 + "\n", 'dim')
            w("⚠️ 本地历史中暂无该股票的分析记录\n", 'dim')

        T.config(state='disabled')
        # 🆕 v9.9.6：详情里所有 6 位代码加蓝字下划线 → 推送同花顺
        try:
            from ..widgets import attach_code_links
            attach_code_links(T, self.app, main_code=code, scope='main')
        except Exception:
            import traceback; traceback.print_exc()

    def _fav_add(self):
        name = self._fav_name.get().strip()
        code = self._fav_code.get().strip()
        tag  = self._fav_tag.get().strip()
        if not name or not code:
            messagebox.showwarning("提示", "名称和代码不能为空"); return
        code = re.sub(r'\D', '', code).zfill(6)[:6]
        if cfg_mod.add_favorite(name, code, tag):
            self._fav_name.set(""); self._fav_code.set(""); self._fav_tag.set("")
            bus.emit(Events.FAVORITES_UPDATED)
            self._refresh_nav()
        else:
            messagebox.showinfo("已存在", "该代码已在自选股中")

    def _fav_remove(self):
        sel = self._fav_tree.selection()
        if not sel: return
        if not messagebox.askyesno("确认", "删除 {} 只？".format(len(sel))):
            return
        for item in sel:
            data = self._row_data.get(item)
            if data:
                cfg_mod.remove_favorite(data['code'])
        bus.emit(Events.FAVORITES_UPDATED)
        self._refresh_nav()

    def _fav_edit_tag(self):
        sel = self._fav_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        new = simpledialog.askstring("编辑标签",
            "为 {} ({}) 设置标签（多个用 + 分隔）：".format(data['name'], data['code']),
            initialvalue=data.get('tag', ''), parent=self.app.root)
        if new is None: return
        cfg_mod.remove_favorite(data['code'])
        cfg_mod.add_favorite(data['name'], data['code'], new.strip())
        bus.emit(Events.FAVORITES_UPDATED)

    def _fav_analyze_sel(self):
        sel = self._fav_tree.selection()
        if not sel: return
        stocks = []
        for item in sel:
            data = self._row_data.get(item)
            if data:
                stocks.append((data['name'], data['code'], data.get('tag','')))
        bus.emit(Events.REQUEST_BATCH_RUN, stocks, "自选股")

    def _fav_analyze_all(self):
        favs = cfg_mod.load_favorites()
        if not favs:
            messagebox.showinfo("提示", "自选股为空"); return
        if not messagebox.askyesno("确认", "分析全部 {} 只？".format(len(favs))):
            return
        stocks = [(f['name'], f['code'], f.get('tag','')) for f in favs]
        bus.emit(Events.REQUEST_BATCH_RUN, stocks, "自选股")

    def _fav_copy(self, kind):
        sel = self._fav_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        if kind == 'code':
            s = data['code']
        else:
            s = "{} {}".format(data['name'], data['code'])
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(s)

    def _fav_view_history(self):
        sel = self._fav_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        ht = self.app.tabs.get('HistoryTab')
        if ht:
            try:
                idx = self.app.nb.index(ht.frame)
                self.app.nb.select(idx)
                if hasattr(ht, 'kw_var'):
                    ht.kw_var.set(data['code'])
                    if hasattr(ht, '_search'):
                        ht._search()
            except Exception:
                pass

    # ════════════════════════════════════════════════
    # 视图2: 用户自建板块
    # ════════════════════════════════════════════════
    def _build_user_sector_view(self):
        C = self.C
        v = tk.Frame(self._right_container, bg=C['bg'])
        v.pack(fill='both', expand=True)

        # 顶部
        hr = tk.Frame(v, bg=C['bg']); hr.pack(fill='x', pady=(0, 6))
        self._sector_title_var = tk.StringVar(value="📂 " + (self._cur_sector_name or ""))
        tk.Label(hr, textvariable=self._sector_title_var,
                 font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(side='left')

        self._auto_refresh_var = tk.BooleanVar(value=False)
        tk.Checkbutton(hr, text="🔁 自动刷新(30s)",
                       variable=self._auto_refresh_var,
                       font=('微软雅黑', 9),
                       bg=C['bg'], fg=C['yellow'],
                       selectcolor=C['card'],
                       activebackground=C['bg'],
                       command=self._toggle_auto_refresh).pack(side='right', padx=(0, 6))
        styled_btn(hr, "🔄 刷新行情", C['accent'],
                   self._refresh_user_quotes).pack(side='right', padx=(4, 0))
        styled_btn(hr, "🚀 分析整个板块", C['green'],
                   self._analyze_user_sector).pack(side='right', padx=(4, 0))

        # 统计卡
        self._stat_frame = tk.Frame(v, bg=C['bg'])
        self._stat_frame.pack(fill='x', pady=(0, 6))

        # 工具栏
        tb = tk.Frame(v, bg=C['panel'],
                      highlightbackground=C['border'], highlightthickness=1)
        tb.pack(fill='x', pady=(0, 4))
        tk.Label(tb, text="📋 股票列表",
                 font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=8, pady=5)
        styled_btn(tb, "➕ 添加", C['accent'],
                   self._user_add_stock_dialog).pack(side='right', padx=4, pady=4)
        styled_btn(tb, "🗑 删除选中", C['red'],
                   self._user_remove_selected).pack(side='right', padx=(0, 4), pady=4)

        # 双栏：左股票表 / 右详情
        pw = tk.PanedWindow(v, bg=C['bg'], sashwidth=5,
                             sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        lf = tk.Frame(pw, bg=C['bg'])
        rf = tk.Frame(pw, bg=C['bg'])
        pw.add(lf, minsize=420)
        pw.add(rf, minsize=380)

        cols = ('name', 'code', 'price', 'pct', 'last_date', 'next_day')
        col_widths = load_col_widths('user_sector')
        defaults = {'name': 110, 'code': 80, 'price': 70, 'pct': 80,
                    'last_date': 80, 'next_day': 70}
        titles = {'name': '名称', 'code': '代码', 'price': '现价',
                  'pct': '涨跌幅', 'last_date': '最近分析', 'next_day': '次日%'}
        self._user_tree = ttk.Treeview(lf, columns=cols, show='headings', height=22)
        for col in cols:
            self._user_tree.heading(col, text=titles[col])
            self._user_tree.column(col,
                                    width=col_widths.get(col, defaults[col]),
                                    minwidth=40,
                                    anchor='center' if col != 'name' else 'w',
                                    stretch=True)
        uvsb = ttk.Scrollbar(lf, orient='vertical', command=self._user_tree.yview)
        self._user_tree.configure(yscrollcommand=uvsb.set)
        self._user_tree.pack(side='left', fill='both', expand=True)
        uvsb.pack(side='right', fill='y')

        def _save_w(*_):
            save_col_widths('user_sector',
                {c: self._user_tree.column(c, 'width') for c in cols})
        self._user_tree.bind('<ButtonRelease-1>', _save_w)

        self._user_tree.tag_configure('lu', foreground=C['red'], background=C['acc_dark'])
        self._user_tree.tag_configure('up_strong', foreground=C['red'])
        self._user_tree.tag_configure('up',   foreground='#ff9a3c')
        self._user_tree.tag_configure('down', foreground=C['green'])
        self._user_tree.tag_configure('flat', foreground=C['dim'])
        self._user_tree.bind('<<TreeviewSelect>>',
                              lambda e: self._user_show_detail())

        # 右键菜单
        m = tk.Menu(self._user_tree, tearoff=0,
                     bg=C['panel'], fg=C['text'],
                     activebackground=C['acc_dark'],
                     activeforeground='white',
                     font=('微软雅黑', 9))
        m.add_command(label="🔎  查看股票详情",
                       command=self._user_show_popup)
        m.add_separator()
        m.add_command(label="🔍  单股分析（送AI）",
                       command=self._user_analyze_single)
        m.add_command(label="📋  复制代码",
                       command=lambda: self._user_copy('code'))
        m.add_command(label="📋  复制名称+代码",
                       command=lambda: self._user_copy('name_code'))
        m.add_separator()
        m.add_command(label="⭐  加入自选股",
                       command=self._user_add_to_fav)
        m.add_separator()
        m.add_command(label="🗑  从板块删除",
                       command=self._user_remove_selected)
        self._user_ctx = m
        def _show(event):
            iid = self._user_tree.identify_row(event.y)
            if iid:
                if iid not in self._user_tree.selection():
                    self._user_tree.selection_set(iid)
                try:
                    m.tk_popup(event.x_root, event.y_root)
                finally:
                    m.grab_release()
        self._user_tree.bind('<Button-3>', _show)
        self._user_tree.bind('<Button-2>', _show)

        # 右侧详情
        rh = tk.Frame(rf, bg=C['panel'],
                       highlightbackground=C['border'], highlightthickness=1)
        rh.pack(fill='x')
        self._user_detail_title = tk.StringVar(value="📄 详情（点击左侧）")
        tk.Label(rh, textvariable=self._user_detail_title,
                 font=('微软雅黑', 10, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=8, pady=6)
        styled_btn(rh, "✨ 自动高亮", C['acc_dark'],
                   lambda: apply_highlight(self._user_detail, keep_editable=True),
                   pady=3).pack(side='right', padx=(0, 4), pady=4)

        self._user_detail = tk.Text(rf, font=('微软雅黑', 10), wrap='word',
                                     bg=C['card'], fg=C['text'],
                                     relief='flat', padx=10, pady=8,
                                     state='disabled', cursor='arrow')
        udvsb = ttk.Scrollbar(rf, orient='vertical', command=self._user_detail.yview)
        self._user_detail.configure(yscrollcommand=udvsb.set)
        self._user_detail.pack(side='left', fill='both', expand=True)
        udvsb.pack(side='right', fill='y')
        for tag, fg, bg in [
            ('accent', C['accent'], ''), ('star_tag', C['star'], ''),
            ('dim', C['dim'], ''), ('policy', C['yellow'], ''),
            ('concept', C['green'], ''), ('money', C['red'], ''),
            ('percent', C['accent'], ''),
            ('category', 'white', C['purple']),
            ('category_kw', '#1a1d23', C['star']),
            ('h2', C['yellow'], ''),
        ]:
            kw = {'foreground': fg}
            if bg: kw['background'] = bg
            if tag == 'category':
                kw['font'] = ('微软雅黑', 10, 'bold')
            self._user_detail.tag_config(tag, **kw)

        self._render_user_sector()

    def _render_user_sector(self):
        if not hasattr(self, '_user_tree') or not self._cur_sector_name:
            return
        sector = my_sectors.get_sector(self._cur_sector_name)
        if not sector:
            return
        self._sector_title_var.set("📂 " + self._cur_sector_name)

        # 统计卡
        for w in self._stat_frame.winfo_children():
            w.destroy()
        stats = my_sectors.get_sector_stats(self._cur_sector_name)
        if stats:
            self._render_stat_card(stats, sector)

        # 表
        for i in self._user_tree.get_children():
            self._user_tree.delete(i)
        self._row_data.clear()

        quotes = sector.get('quotes', {})
        index = self._build_history_index()
        hidx = hist_mod.get_code_count_index()    # 🆕 v9.6
        stocks = list(sector['stocks'])
        if quotes:
            stocks.sort(key=lambda s: -quotes.get(s['code'], {}).get('change_pct', -999))

        for s in stocks:
            code = s.get('code', '')
            q = quotes.get(code, {})
            name = s.get('name') or q.get('name', '')
            price = q.get('price', '')
            chg = q.get('change_pct')
            pct_str = "--" if chg is None else "{:+.2f}%".format(chg)
            tag = 'flat'
            if chg is not None:
                if chg >= 9.7: tag = 'lu'
                elif chg >= 3: tag = 'up_strong'
                elif chg > 0:  tag = 'up'
                elif chg < 0:  tag = 'down'

            last = index.get(code)
            last_date = ""
            nd_str = ""
            if last:
                d = last['date']
                last_date = "{}-{}".format(d[4:6], d[6:])
                nd = last.get('next_day')
                if nd and nd.get('change_pct') is not None:
                    nd_str = "{:+.1f}%".format(nd['change_pct'])

            # 🆕 v9.6：有历史则 name 后追加 📊
            disp_name = name + (" 📊" if hidx.get(str(code).zfill(6), 0) > 0 else "")
            iid = self._user_tree.insert('', 'end',
                values=(disp_name, code, price, pct_str, last_date, nd_str),
                tags=(tag,))
            self._row_data[iid] = {'name': name, 'code': code,
                                    'last_record': last,
                                    'tag': self._cur_sector_name}

    def _render_stat_card(self, stats, sector):
        C = self.C
        row = tk.Frame(self._stat_frame, bg=C['bg'])
        row.pack(fill='x')
        refresh_str = "上次刷新: " + (sector.get('last_refresh', '未刷新'))
        tk.Label(row,
                 text="共 {} 只  ·  {}".format(stats['total'], refresh_str),
                 font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(anchor='w', padx=4, pady=(0, 4))

        row2 = tk.Frame(self._stat_frame, bg=C['bg'])
        row2.pack(fill='x')
        items = [
            ('🎯 涨停', "{} 只".format(stats['limit_up']), C['red']),
            ('📈 上涨', "{} 只".format(stats['up']),       C['red']),
            ('📉 下跌', "{} 只".format(stats['down']),     C['green']),
            ('📊 平均', "{:+.2f}%".format(stats['avg_pct']),
                       C['red'] if stats['avg_pct'] > 0 else C['green']),
        ]
        for lbl, val, color in items:
            cell = tk.Frame(row2, bg=C['panel'],
                             highlightbackground=C['border'], highlightthickness=1)
            cell.pack(side='left', fill='both', expand=True, padx=2)
            tk.Label(cell, text=lbl, font=('微软雅黑', 8),
                     bg=C['panel'], fg=C['dim']).pack(pady=(4, 0))
            tk.Label(cell, text=val, font=('微软雅黑', 12, 'bold'),
                     bg=C['panel'], fg=color).pack(pady=(0, 4))

    def _user_show_detail(self):
        sel = self._user_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        # 🆕 v9.6：通知浮窗（联动模式开启时刷新）
        self.app.notify_stock_focus(data.get('code',''), data.get('name',''))

        T = self._user_detail
        T.config(state='normal')
        T.delete('1.0', 'end')

        name = data.get('name', ''); code = data.get('code', '')
        self._user_detail_title.set("📄 {} ({})".format(name, code))

        def w(text, t=None):
            if t: T.insert('end', text, t)
            else: T.insert('end', text)

        w("📂 {} · {} ({})\n".format(self._cur_sector_name, name, code), 'accent')
        w("\n")

        last = data.get('last_record')
        if last:
            d = last['date']
            w("─" * 50 + "\n", 'dim')
            w("📈 最近一次分析  ", 'h2')
            w("({}-{}-{}  {})\n".format(d[:4], d[4:6], d[6:],
                                          last.get('time', '')), 'dim')
            nd = last.get('next_day')
            if nd and nd.get('change_pct') is not None:
                pct = nd['change_pct']
                ct = 'concept' if pct > 0 else 'money'
                w("📊 次日: ", 'star_tag')
                w("{:+.2f}%".format(pct), ct)
                w("\n")
            w("\n")
            content = last.get('content', '')
            if content:
                w(content)
                apply_highlight(T, keep_editable=True)
        else:
            w("─" * 50 + "\n", 'dim')
            w("⚠️ 该股票暂无历史分析记录\n", 'dim')
            w("💡 提示：右键 → 单股分析 开始分析\n", 'dim')

        T.config(state='disabled')
        # 🆕 v9.9.6：详情里所有 6 位代码加蓝字下划线 → 推送同花顺
        try:
            from ..widgets import attach_code_links
            attach_code_links(T, self.app, main_code=code, scope='main')
        except Exception:
            import traceback; traceback.print_exc()

    def _refresh_user_quotes(self):
        if not self._cur_sector_name: return
        def _do():
            my_sectors.refresh_quotes(self._cur_sector_name)
            state.ui_queue.put(self._render_user_sector)
        threading.Thread(target=_do, daemon=True).start()

    def _toggle_auto_refresh(self):
        self._auto_refresh_on = self._auto_refresh_var.get()
        if self._auto_refresh_on:
            self._schedule_next_refresh()
        else:
            if self._auto_refresh_id:
                try:
                    self.app.root.after_cancel(self._auto_refresh_id)
                except Exception:
                    pass
                self._auto_refresh_id = None

    def _schedule_next_refresh(self):
        if not self._auto_refresh_on or not self._cur_sector_name:
            return
        threading.Thread(target=lambda: (
            my_sectors.refresh_quotes(self._cur_sector_name),
            state.ui_queue.put(self._render_user_sector)
        ), daemon=True).start()
        self._auto_refresh_id = self.app.root.after(
            30000, self._schedule_next_refresh)

    def _user_add_stock_dialog(self):
        if not self._cur_sector_name: return
        s = simpledialog.askstring("添加股票",
            "输入名称+代码（如：寒武纪 688256）：", parent=self.app.root)
        if not s: return
        name_lookup = cfg_mod.get_name_lookup()
        parsed = my_sectors.parse_import_text(s, name_lookup=name_lookup)
        if not parsed:
            messagebox.showinfo("失败", "未识别到代码"); return
        my_sectors.add_stocks(self._cur_sector_name, parsed)
        self._refresh_user_quotes()
        self._refresh_nav()

    def _user_remove_selected(self):
        sel = self._user_tree.selection()
        if not sel or not self._cur_sector_name: return
        codes = [self._row_data.get(iid, {}).get('code', '')
                 for iid in sel]
        codes = [c for c in codes if c]
        if not codes: return
        if not messagebox.askyesno("确认",
                "从「{}」删除 {} 只？".format(self._cur_sector_name, len(codes))):
            return
        my_sectors.remove_stocks(self._cur_sector_name, codes)
        self._render_user_sector()
        self._refresh_nav()

    def _analyze_user_sector(self):
        if not self._cur_sector_name: return
        sector = my_sectors.get_sector(self._cur_sector_name)
        if not sector or not sector['stocks']:
            messagebox.showinfo("提示", "板块为空"); return
        stocks = [(s['name'] or s['code'], s['code'], self._cur_sector_name)
                  for s in sector['stocks']]
        if not messagebox.askyesno("确认",
                "分析「{}」板块的 {} 只股票？".format(
                    self._cur_sector_name, len(stocks))):
            return
        bus.emit(Events.REQUEST_BATCH_RUN, stocks, "板块·" + self._cur_sector_name)

    def _user_analyze_single(self):
        sel = self._user_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        single = self.app.tabs.get('SingleTab')
        if single:
            try:
                idx = self.app.nb.index(single.frame)
                self.app.nb.select(idx)
                single.name_var.set(data['name'])
                single.code_var.set(data['code'])
            except Exception:
                pass

    def _user_copy(self, kind):
        sel = self._user_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if not data: return
        if kind == 'code':
            s = data['code']
        else:
            s = "{} {}".format(data['name'], data['code'])
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(s)

    def _user_add_to_fav(self):
        sel = self._user_tree.selection()
        if not sel: return
        added = 0
        for iid in sel:
            data = self._row_data.get(iid)
            if data and cfg_mod.add_favorite(data['name'], data['code'],
                                             tag=self._cur_sector_name or ""):
                added += 1
        bus.emit(Events.FAVORITES_UPDATED)
        self._refresh_nav()

    def _user_show_popup(self):
        """🆕 v9.5：在浮窗打开股票详情"""
        sel = self._user_tree.selection()
        if not sel: return
        data = self._row_data.get(sel[0])
        if data:
            self.app.show_stock_popup(data.get('code',''), data.get('name',''))

    # ════════════════════════════════════════════════
    # 视图3: 标签关联度 (v9.2：天数控制 + API 收纳 + 标签管理 + 双击跳转)
    # ════════════════════════════════════════════════
    def _build_tag_relation_view(self):
        C = self.C
        v = tk.Frame(self._right_container, bg=C['bg'])
        v.pack(fill='both', expand=True)

        # ── 顶部标题 + 顶部按钮 ──
        hr = tk.Frame(v, bg=C['bg']); hr.pack(fill='x', pady=(0, 6))
        # 左侧装饰条 + 标题
        title_box = tk.Frame(hr, bg=C['bg']); title_box.pack(side='left')
        tk.Frame(title_box, bg=C['accent'], width=4).pack(side='left', fill='y', padx=(0, 8))
        tk.Label(title_box, text="标签关联度分析",
                 font=('微软雅黑', 13, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(side='left', pady=2)
        styled_btn(hr, "🏷️ 管理标签", C['purple'],
                   self._tag_open_manager).pack(side='right', padx=(4, 0))
        styled_btn(hr, "📝 聚类提示词", C['accent'],
                   self._edit_bulk_prompt).pack(side='right', padx=(4, 0))
        styled_btn(hr, "🔄 重新扫描", C['idle'],
                   self._tag_rescan).pack(side='right')

        # ── 扫描控制行（含回溯天数）──
        ctrl = tk.Frame(v, bg=C['bg']); ctrl.pack(fill='x', pady=(0, 4))
        tk.Label(ctrl, text="目标标签", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._tag_var = tk.StringVar()
        self._tag_combo = ttk.Combobox(ctrl, textvariable=self._tag_var,
                                        state='readonly', width=22,
                                        font=('微软雅黑', 9))
        self._tag_combo.pack(side='left', padx=(0, 8))
        self._tag_combo.bind('<<ComboboxSelected>>',
                              lambda e: self._tag_show_relations())

        # 🆕 回溯天数（默认 7）
        tk.Label(ctrl, text="回溯天数", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._tag_days = tk.StringVar(value="7")
        days_combo = ttk.Combobox(ctrl, textvariable=self._tag_days,
                                  values=["1", "3", "7", "14", "30", "全部"],
                                  state='readonly', width=6,
                                  font=('微软雅黑', 9))
        days_combo.pack(side='left', padx=(0, 8))
        days_combo.bind('<<ComboboxSelected>>', lambda e: self._tag_rescan())

        tk.Label(ctrl, text="最小频次", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._tag_min_freq = tk.StringVar(value="1")
        styled_entry(ctrl, self._tag_min_freq, 3).pack(side='left', ipady=3)

        self._tag_stat = tk.StringVar(value="点击「重新扫描」开始")
        tk.Label(v, textvariable=self._tag_stat,
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['yellow']).pack(anchor='w', pady=(0, 4))

        # ── 🆕 聚类专属 API 配置区（默认折叠，腾出主区域空间）──
        self._bulk_api_open = tk.BooleanVar(value=False)
        tog_row = tk.Frame(v, bg=C['bg']); tog_row.pack(fill='x', pady=(0, 2))
        self._bulk_api_btn = tk.Button(tog_row,
            text="▶ 🤖 聚类专属 API 配置（点击展开）",
            font=('微软雅黑', 9), bg=C['bg'], fg=C['dim'],
            relief='flat', anchor='w', cursor='hand2',
            command=self._toggle_bulk_api_panel)
        self._bulk_api_btn.pack(fill='x')

        self._bulk_api_card = make_card(v, "", pady_top=0)
        # 默认收起
        self._bulk_api_card.pack_forget()

        r1 = tk.Frame(self._bulk_api_card, bg=C['panel']); r1.pack(fill='x', pady=2)
        tk.Label(r1, text="API URL", font=('微软雅黑', 8), bg=C['panel'], fg=C['dim'], width=10, anchor='w').pack(side='left')
        self._bulk_url = tk.StringVar(value=self.app.cfg.get("api_url", ""))
        styled_entry(r1, self._bulk_url).pack(side='left', fill='x', expand=True, ipady=2)

        r2 = tk.Frame(self._bulk_api_card, bg=C['panel']); r2.pack(fill='x', pady=2)
        tk.Label(r2, text="API Key", font=('微软雅黑', 8), bg=C['panel'], fg=C['dim'], width=10, anchor='w').pack(side='left')
        self._bulk_key = tk.StringVar(value=self.app.cfg.get("api_keys", [""])[0] if self.app.cfg.get("api_keys") else "")
        styled_entry(r2, self._bulk_key).pack(side='left', fill='x', expand=True, ipady=2)

        r3 = tk.Frame(self._bulk_api_card, bg=C['panel']); r3.pack(fill='x', pady=2)
        tk.Label(r3, text="Model", font=('微软雅黑', 8), bg=C['panel'], fg=C['dim'], width=10, anchor='w').pack(side='left')
        cur_id = self.app.cfg.get("model", "")
        cur_disp = cfg_mod.model_id_to_display_name(cur_id)
        self._bulk_model_var = tk.StringVar(value=cur_disp)
        model_combo = ttk.Combobox(r3, textvariable=self._bulk_model_var,
                                    values=cfg_mod.MODEL_LIST, font=('微软雅黑', 8), state='readonly')
        model_combo.pack(side='left', fill='x', expand=True, ipady=2)

        btn_r = tk.Frame(self._bulk_api_card, bg=C['panel']); btn_r.pack(fill='x', pady=(6, 0))
        styled_btn(btn_r, "🌋 一键切火山方舟(豆包)", C['red'],
                   self._switch_bulk_to_volcano, pady=2).pack(side='left', padx=(0,4))
        styled_btn(btn_r, "🔵 一键切百度千帆", C['accent'],
                   self._switch_bulk_to_qianfan, pady=2).pack(side='left')

        # ── 聚类执行按钮 ──
        exec_row = tk.Frame(v, bg=C['bg']); exec_row.pack(fill='x', pady=(6, 4))
        styled_btn(exec_row, "🤖 AI 一键聚类（使用专属配置）", C['purple'],
                   self._tag_bulk_analyze, pady=6).pack(fill='x')

        # ── 双栏：左表 / 右图表+详情 ──
        pw = tk.PanedWindow(v, bg=C['bg'], sashwidth=5,
                             sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        lf = tk.Frame(pw, bg=C['bg'])
        rf = tk.Frame(pw, bg=C['bg'])
        pw.add(lf, minsize=340)
        pw.add(rf, minsize=460)

        # 左表头部加图例
        legend = tk.Frame(lf, bg=C['bg']); legend.pack(fill='x', pady=(0, 2))
        tk.Label(legend, text="🔥 强 ≥0.4", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['red']).pack(side='left', padx=(2, 8))
        tk.Label(legend, text="⭐ 中 ≥0.2", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['yellow']).pack(side='left', padx=(0, 8))
        tk.Label(legend, text="💤 弱", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='left')
        tk.Label(legend, text="(双击关联标签 → 切换目标)", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='right')

        cols = ('tag', 'score', 'support', 'self', 'other')
        col_widths = load_col_widths('tag_relation')
        defaults = {'tag': 130, 'score': 70, 'support': 70, 'self': 60, 'other': 60}
        self._tag_tree = ttk.Treeview(lf, columns=cols, show='headings', height=18)
        for col, txt in [('tag','关联标签'),('score','关联度'),
                           ('support','共现次数'),('self','本标签'),('other','对方')]:
            self._tag_tree.heading(col, text=txt)
            self._tag_tree.column(col,
                                   width=col_widths.get(col, defaults[col]),
                                   minwidth=40,
                                   anchor='center' if col != 'tag' else 'w',
                                   stretch=True)
        tvsb = ttk.Scrollbar(lf, orient='vertical', command=self._tag_tree.yview)
        self._tag_tree.configure(yscrollcommand=tvsb.set)
        self._tag_tree.pack(side='left', fill='both', expand=True)
        tvsb.pack(side='right', fill='y')

        def _save_w(*_):
            save_col_widths('tag_relation',
                {c: self._tag_tree.column(c, 'width') for c in cols})
        self._tag_tree.bind('<ButtonRelease-1>', _save_w)

        self._tag_tree.tag_configure('high', foreground=C['red'])
        self._tag_tree.tag_configure('mid',  foreground=C['yellow'])
        self._tag_tree.tag_configure('low',  foreground=C['dim'])
        self._tag_tree.bind('<<TreeviewSelect>>', lambda e: self._tag_show_rel_detail())
        # 🆕 B2 双击：切换该标签为新的目标
        self._tag_tree.bind('<Double-Button-1>', lambda e: self._tag_jump_to_selected())

        # 右：详情 + 图表（v9.4：把详情放第一个，让"个股清单"首屏可见）
        self._tag_sub_nb = ttk.Notebook(rf, style='App.TNotebook')
        self._tag_sub_nb.pack(fill='both', expand=True)

        # 详情 Tab 排第一个，默认显示，用户立刻看到本标签下的个股
        f_detail = tk.Frame(self._tag_sub_nb, bg=C['bg'])
        self._tag_sub_nb.add(f_detail, text="  📝 个股 + 详情 + AI推理  ")

        info_bar = tk.Frame(f_detail, bg=C['bg'])
        info_bar.pack(fill='x', pady=(6, 4))
        styled_btn(info_bar, "🤖 推理这对关联", C['purple'],
                   self._tag_ai_pair).pack(side='left', padx=(0, 4))
        styled_btn(info_bar, "🗑 清除缓存", C['idle'],
                   self._tag_clear_pair_cache).pack(side='left')
        self._tag_ai_status = tk.StringVar(value="")
        tk.Label(info_bar, textvariable=self._tag_ai_status,
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['yellow']).pack(side='left', padx=8)

        self._tag_detail = tk.Text(f_detail, font=('微软雅黑', 10), wrap='word',
                                    bg=C['card'], fg=C['text'],
                                    relief='flat', padx=10, pady=8,
                                    state='disabled', cursor='arrow')
        tdvsb = ttk.Scrollbar(f_detail, orient='vertical', command=self._tag_detail.yview)
        self._tag_detail.configure(yscrollcommand=tdvsb.set)
        self._tag_detail.pack(side='left', fill='both', expand=True)
        tdvsb.pack(side='right', fill='y')
        for tag, color in [('h1', C['accent']), ('h2', C['yellow']),
                            ('green', C['green']), ('red', C['red']),
                            ('dim', C['dim']), ('purple', C['purple'])]:
            self._tag_detail.tag_config(tag, foreground=color)
        self._tag_detail.tag_config('h1bold',
            font=('微软雅黑', 12, 'bold'), foreground=C['accent'])
        self._tag_detail.tag_config('ai',
            background='#2a1d4d', foreground='white')

        # 🆕 v9.5：标签详情区右键 → 看光标附近的股票详情
        self._tag_detail.bind('<Button-3>', self._tag_detail_show_ctx)
        self._tag_detail.bind('<Button-2>', self._tag_detail_show_ctx)
        # 🆕 v9.6：左键联动
        self._tag_detail.bind('<Button-1>', self._tag_detail_left_click_follow, add='+')
        self._tag_detail_ctx = tk.Menu(self._tag_detail, tearoff=0,
            bg=C['panel'], fg=C['text'],
            activebackground=C['acc_dark'], activeforeground='white',
            font=('微软雅黑', 9))
        self._tag_detail_ctx.add_command(label="🔎  查看此股详情",
            command=self._tag_detail_show_stock_popup)

        # 关联度图表 Tab（v9.4：调整为第二个，详情优先）
        f_chart = tk.Frame(self._tag_sub_nb, bg=C['bg'])
        self._tag_sub_nb.add(f_chart, text="  📊 关联度图表  ")
        self._tag_fig = Figure(figsize=(6, 4), dpi=90, facecolor=C['bg'])
        self._tag_ax  = self._tag_fig.add_subplot(111)
        self._tag_canvas = FigureCanvasTkAgg(self._tag_fig, master=f_chart)
        self._tag_canvas.get_tk_widget().pack(fill='both', expand=True, padx=8, pady=8)

    # ── 🆕 聚类专属 API 快捷切换 ──
    def _switch_bulk_to_volcano(self):
        self._bulk_url.set("https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        if not self._bulk_model_var.get().startswith("🌋"):
            self._bulk_model_var.set("🌋 doubao-seed-2-0-pro")

    def _switch_bulk_to_qianfan(self):
        self._bulk_url.set("https://qianfan.baidubce.com/v2/ai_search/chat/completions")
        if self._bulk_model_var.get().startswith("🌋"):
            self._bulk_model_var.set("🆓 ERNIE-4.5-Turbo-32K")

    # ── 扫描与图表逻辑 ──
    def _tag_rescan(self):
        try:
            mf = int(self._tag_min_freq.get())
        except Exception:
            mf = 1
        # 🆕 读回溯天数：可选 "1/3/7/14/30/全部"
        d_raw = (self._tag_days.get() if hasattr(self, '_tag_days') else '7').strip()
        if d_raw in ("", "全部", "all", "0"):
            days = 0   # 全部历史
        else:
            try: days = int(d_raw)
            except Exception: days = 7
        self._tag_stat.set("⏳ 扫描中...（{}）".format(
            "全部历史" if days == 0 else "近 {} 天".format(days)))
        def _do():
            tf, co, rec = tr.build_cooccurrence(days=days, min_freq=mf)
            def _upd():
                self._tag_freq = tf; self._cooccur = co; self._tag_records = rec
                if not tf:
                    self._tag_stat.set("⚠️ 未找到标签（请确保历史中有【细分标签】或概念关键词）")
                    self._tag_combo['values'] = []
                    return
                tags_sorted = sorted(tf.items(), key=lambda x: -x[1])
                self._tag_combo['values'] = [
                    "{} ({}次)".format(t, c) for t, c in tags_sorted]
                self._tag_stat.set("✅ 扫描完成：{} 个标签，{} 对共现（{}）".format(
                    len(tf), len(co),
                    "全部历史" if days == 0 else "近 {} 天".format(days)))
                if self._tag_combo['values'] and not self._tag_var.get():
                    self._tag_combo.current(0)
                    self._tag_show_relations()
            state.ui_queue.put(_upd)
        threading.Thread(target=_do, daemon=True).start()

    # 🆕 A4：折叠/展开 API 配置面板
    def _toggle_bulk_api_panel(self):
        opened = self._bulk_api_open.get()
        if opened:
            self._bulk_api_card.pack_forget()
            self._bulk_api_btn.config(text="▶ 🤖 聚类专属 API 配置（点击展开）")
            self._bulk_api_open.set(False)
        else:
            self._bulk_api_card.pack(fill='x', pady=(2, 4),
                                     after=self._bulk_api_btn.master)
            self._bulk_api_btn.config(text="▼ 🤖 聚类专属 API 配置（点击折叠）")
            self._bulk_api_open.set(True)

    # 🆕 B2：双击关联标签 → 切换该标签为新目标
    def _tag_jump_to_selected(self):
        sel = self._tag_tree.selection()
        if not sel: return
        idx = self._tag_tree.index(sel[0])
        if idx >= len(self._cur_rels): return
        new_tag = self._cur_rels[idx]['tag']
        freq = self._tag_freq.get(new_tag, 0)
        target_label = "{} ({}次)".format(new_tag, freq)
        # 在 combobox 候选里找
        for i, v in enumerate(self._tag_combo['values']):
            if v == target_label:
                self._tag_combo.current(i)
                break
        else:
            # 不在候选里（频次为 0），直接 set
            self._tag_var.set(target_label)
        self._tag_show_relations()

    def _tag_get_cur(self):
        v = self._tag_var.get()
        if not v: return None
        return v.split(" (")[0]

    def _tag_show_relations(self):
        tag = self._tag_get_cur()
        if not tag: return
        self._cur_tag = tag
        rels = tr.compute_relations(tag, self._tag_freq, self._cooccur, top_n=20)
        self._cur_rels = rels
        for i in self._tag_tree.get_children():
            self._tag_tree.delete(i)
        for r in rels:
            score = r['score']
            tg = 'high' if score >= 0.4 else ('mid' if score >= 0.2 else 'low')
            self._tag_tree.insert('', 'end', values=(
                r['tag'], "{:.3f}".format(score), r['support'],
                r['self_freq'], r['other_freq']), tags=(tg,))
        self._tag_draw_chart(tag, rels[:12])
        self._tag_render_overview(tag, rels)
        # 🆕 v9.4：自动切到"详情 Tab"，让概览中的个股清单直接可见
        try:
            self._tag_sub_nb.select(0)
        except Exception:
            pass

    def _tag_draw_chart(self, target, rels):
        C = self.C
        self._tag_ax.clear()
        if not rels:
            self._tag_ax.text(0.5, 0.5, "无关联数据",
                              transform=self._tag_ax.transAxes,
                              ha='center', va='center', color=C['dim'])
            self._tag_canvas.draw(); return
        labels = [r['tag'] for r in rels][::-1]
        scores = [r['score'] for r in rels][::-1]
        sups   = [r['support'] for r in rels][::-1]
        colors = [C['red'] if s >= 0.4 else (C['yellow'] if s >= 0.2 else C['accent'])
                  for s in scores]
        self._tag_fig.patch.set_facecolor(C['bg'])
        self._tag_ax.set_facecolor(C['card'])
        bars = self._tag_ax.barh(labels, scores, color=colors, edgecolor='none')
        for bar, sup in zip(bars, sups):
            self._tag_ax.text(bar.get_width() + 0.005,
                              bar.get_y() + bar.get_height()/2,
                              " {} 次".format(sup),
                              va='center', fontsize=8, color=C['text'])
        self._tag_ax.set_xlabel("Jaccard 关联度", color=C['dim'], fontsize=9)
        self._tag_ax.set_title("「{}」 关联标签 Top {}".format(target, len(rels)),
                                color=C['text'], fontsize=11, pad=10)
        self._tag_ax.tick_params(colors=C['text'])
        for spine in self._tag_ax.spines.values():
            spine.set_color(C['border'])
        self._tag_ax.grid(axis='x', alpha=0.2, color=C['border'])
        self._tag_fig.tight_layout()
        self._tag_canvas.draw()

    # ════════════════════════════════════════════════
    # 🆕 v9.5：标签详情区右键 → 看光标附近股票详情
    # ════════════════════════════════════════════════
    def _tag_detail_show_ctx(self, event):
        try:
            self._tag_detail_click_idx = self._tag_detail.index(
                "@{},{}".format(event.x, event.y))
        except Exception:
            self._tag_detail_click_idx = None
        try:
            self._tag_detail_ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._tag_detail_ctx.grab_release()

    def _tag_detail_show_stock_popup(self):
        import re
        idx = getattr(self, '_tag_detail_click_idx', None) or self._tag_detail.index('insert')
        # 优先用选中文本
        try:
            search_text = self._tag_detail.get('sel.first', 'sel.last')
        except tk.TclError:
            search_text = ""
        if not search_text:
            try:
                line_no = idx.split('.')[0]
                search_text = self._tag_detail.get("{}.0".format(line_no),
                                                    "{}.end".format(line_no))
            except Exception:
                search_text = ""
        m = re.search(r'[（(](\d{6})[)）]', search_text) or \
            re.search(r'(?<![.\d])(\d{6})(?![.\d])', search_text)
        if not m:
            messagebox.showinfo("提示", "未在光标附近识别到股票代码")
            return
        code = m.group(1)
        before = search_text[:m.start()]
        mname = re.search(r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*$',
                          before.rstrip())
        name = mname.group(1) if mname else ""
        self.app.show_stock_popup(code, name)

    def _tag_detail_left_click_follow(self, event):
        """🆕 v9.6：左键单击 → 通知浮窗刷新（v9.9.6 起浮窗永远跟随，无需判断开关）"""
        import re
        try:
            idx = self._tag_detail.index("@{},{}".format(event.x, event.y))
            ln = idx.split('.')[0]
            line_text = self._tag_detail.get("{}.0".format(ln), "{}.end".format(ln))
        except Exception:
            return
        m = re.search(r'[（(](\d{6})[)）]', line_text) or \
            re.search(r'(?<![.\d])(\d{6})(?![.\d])', line_text)
        if not m: return
        code = m.group(1)
        before = line_text[:m.start()]
        mname = re.search(r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*$',
                          before.rstrip())
        name = mname.group(1) if mname else ""
        self.app.notify_stock_focus(code, name)

    def _tag_render_overview(self, tag, rels):
        T = self._tag_detail
        T.config(state='normal'); T.delete('1.0', 'end')
        def w(text, tg=None):
            if tg: T.insert('end', text, tg)
            else:  T.insert('end', text)

        # ─── 标题区（加大间距 + 三栏汇总）───
        freq = self._tag_freq.get(tag, 0)
        recs = self._tag_records.get(tag, [])
        codes_set = {(r.get('name',''), r.get('code','')) for r in recs}
        codes_set.discard(('',''))

        w("\n  🕸️  ", 'h1bold')
        w("{}\n".format(tag), 'h1bold')
        w("    频次 ", 'dim'); w("{}".format(freq), 'h2')
        w("    涉及个股 ", 'dim'); w("{}".format(len(codes_set)), 'h2')
        w("    关联标签 ", 'dim'); w("{}\n".format(len(rels)), 'h2')
        w("  " + "━" * 48 + "\n\n", 'dim')

        # ─── 🆕 本标签下的个股清单（需求 3）───
        w("  💎  本标签下的个股 ", 'h2')
        w("({} 只)\n".format(len(codes_set)), 'dim')
        if codes_set:
            # 按代码 + 最近日期排序
            by_code = {}
            for r in recs:
                key = (r.get('name',''), r.get('code',''))
                if key == ('',''): continue
                d = r.get('date','')
                if key not in by_code or d > by_code[key]:
                    by_code[key] = d
            sorted_stocks = sorted(by_code.items(),
                                   key=lambda x: (-len(x[1]), x[0][1]))
            line_items = []
            for (name, code), last_date in sorted_stocks[:30]:
                short_d = last_date[4:8] if len(last_date) >= 8 else last_date
                line_items.append("{}({})·{}".format(name, code, short_d))
            # 每行 2 项
            for i in range(0, len(line_items), 2):
                row = "    ".join(line_items[i:i+2])
                w("    {}\n".format(row), 'concept')
            if len(sorted_stocks) > 30:
                w("    ……还有 {} 只\n".format(len(sorted_stocks) - 30), 'dim')
        else:
            w("    （无个股数据）\n", 'dim')
        w("\n")

        # ─── Top 关联标签（带 emoji 强度徽章）───
        w("  📊  Top 关联标签\n", 'h2')
        for i, r in enumerate(rels[:12], 1):
            stag = 'red' if r['score'] >= 0.4 else ('purple' if r['score'] >= 0.2 else 'dim')
            badge = "🔥" if r['score'] >= 0.4 else ("⭐" if r['score'] >= 0.2 else "💤")
            w("    {} {:>2}. ".format(badge, i), 'dim')
            w("{:<14s}".format(r['tag']))
            w("  Jaccard ", 'dim')
            w("{:.3f}".format(r['score']), stag)
            w("  共现 {} 次\n".format(r['support']), 'dim')

        w("\n  💡 点击左侧 → 看产业逻辑 · 双击 → 跳转到该标签\n", 'dim')
        T.config(state='disabled')

    def _tag_show_rel_detail(self):
        sel = self._tag_tree.selection()
        if not sel or not self._cur_tag: return
        idx = self._tag_tree.index(sel[0])
        if idx >= len(self._cur_rels): return
        rel = self._cur_rels[idx]
        self._cur_other_tag = rel['tag']

        T = self._tag_detail
        T.config(state='normal'); T.delete('1.0', 'end')
        def w(text, tg=None):
            if tg: T.insert('end', text, tg)
            else:  T.insert('end', text)

        w("\n  🔗  ", 'h1bold')
        w("{}".format(self._cur_tag), 'h1bold')
        w("  ⇄  ", 'dim')
        w("{}\n".format(rel['tag']), 'h1bold')
        w("  " + "━" * 48 + "\n\n", 'dim')

        # ── 关联度 chip ──
        stag = 'red' if rel['score'] >= 0.4 else ('purple' if rel['score'] >= 0.2 else 'dim')
        label = ("🔥 强关联" if rel['score'] >= 0.4 else
                 ("⭐ 中等" if rel['score'] >= 0.2 else "💤 弱"))
        w("    Jaccard 关联度  ", 'dim')
        w("{:.3f}".format(rel['score']), stag)
        w("    ", 'dim')
        w(label + "\n", stag)
        w("    共现 ", 'dim'); w("{}".format(rel['support']), 'h2')
        w("    {} 单独 ".format(self._cur_tag), 'dim'); w("{}".format(rel['self_freq']), 'h2')
        w("    {} 单独 ".format(rel['tag']), 'dim'); w("{}\n\n".format(rel['other_freq']), 'h2')

        # ── 共现股票 ──
        co = tr.co_stocks(self._cur_tag, rel['tag'], self._tag_records)
        if co:
            w("  💎  同时具备这两个标签的股票 ", 'h2')
            w("({} 只)\n".format(len(co)), 'dim')
            line_items = ["{}({})".format(n, c) for n, c in co[:24]]
            for i in range(0, len(line_items), 2):
                row = "    ".join(line_items[i:i+2])
                w("    {}\n".format(row), 'concept')
            if len(co) > 24:
                w("    ……还有 {} 只\n".format(len(co) - 24), 'dim')
            w("\n")

        # ── AI 推理 ──
        cache = self._load_pair_cache()
        key = self._pair_key(self._cur_tag, rel['tag'])
        if key in cache:
            w("  🤖  AI 推理（缓存）\n", 'h2')
            w(cache[key]['analysis'] + "\n", 'ai')
            w("\n  生成时间: " + cache[key].get('time', ''), 'dim')
        else:
            w("  🤖  暂无 AI 推理，点击上方「🤖 推理这对关联」按钮生成\n", 'dim')

        T.config(state='disabled')

    # ── AI pair cache ──
    def _pair_cache_path(self):
        from ..core.paths import DIRS
        from pathlib import Path
        return Path(DIRS["config"]) / "tag_relation_ai_cache.json"

    def _load_pair_cache(self):
        p = self._pair_cache_path()
        if not p.exists(): return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_pair_cache(self, cache):
        p = self._pair_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _pair_key(self, a, b):
        return "||".join(sorted([a, b]))

    def _tag_ai_pair(self):
        if not self._cur_tag or not self._cur_other_tag:
            messagebox.showinfo("提示", "请先选中一个关联标签"); return
        a, b = self._cur_tag, self._cur_other_tag
        cache = self._load_pair_cache()
        key = self._pair_key(a, b)
        if key in cache:
            if not messagebox.askyesno("已有缓存", "重新生成？"):
                return

        # 🆕 读取专属配置
        bulk_url = self._bulk_url.get().strip()
        bulk_key = self._bulk_key.get().strip()
        bulk_model = cfg_mod.display_name_to_model_id(self._bulk_model_var.get().strip())
        if not bulk_key:
            messagebox.showwarning("无 Key", "请在上方填写聚类专用 API Key"); return
        bulk_cfg = {"api_url": bulk_url, "model": bulk_model, "timeout": 60}

        co = tr.co_stocks(a, b, self._tag_records)
        co_count = self._cooccur.get(tuple(sorted([a, b])), 0)
        freq_a = self._tag_freq.get(a, 0)
        freq_b = self._tag_freq.get(b, 0)
        self._tag_ai_status.set("🤖 推理中...")

        def _do():
            result, ok = tr.query_ai_relation(
                a, b, co, freq_a, freq_b, co_count, bulk_key, bulk_cfg)  # 🆕 使用专属配置
            from datetime import datetime
            if ok:
                cache[key] = {
                    "tag_a": a, "tag_b": b, "analysis": result,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "co_count": co_count,
                }
                self._save_pair_cache(cache)
            def _done():
                self._tag_ai_status.set("✅ 完成" if ok else "❌ 失败")
                self.app.root.after(3000, lambda: self._tag_ai_status.set(""))
                self._tag_show_rel_detail()
            state.ui_queue.put(_done)
        threading.Thread(target=_do, daemon=True).start()

    def _tag_clear_pair_cache(self):
        if not self._cur_tag or not self._cur_other_tag: return
        cache = self._load_pair_cache()
        key = self._pair_key(self._cur_tag, self._cur_other_tag)
        if key in cache:
            del cache[key]
            self._save_pair_cache(cache)
            self._tag_show_rel_detail()

    # ════════════════════════════════════════════════
    # 🆕 B1：标签管理对话框
    # ════════════════════════════════════════════════
    def _tag_open_manager(self):
        """列出所有标签，支持重命名/合并/删除/查看别名表"""
        C = self.C
        dlg = tk.Toplevel(self.app.root)
        dlg.title("🏷️  标签管理")
        dlg.geometry("760x560")
        dlg.configure(bg=C['bg'])
        dlg.transient(self.app.root)

        # 顶部提示
        tk.Label(dlg, text="🏷️  标签管理",
                 font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(pady=(10, 2))
        hint = ("· 重命名: 选中 1 个标签，改名后所有历史 category 同步\n"
                "· 合并:   选中 2+ 个标签，输入目标名，全部并入目标\n"
                "· 删除:   选中 N 个标签，从所有 category 中移除（不动 AI 文本）")
        tk.Label(dlg, text=hint, font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim'], justify='left').pack(pady=(0, 8))

        # 表格
        wrap = tk.Frame(dlg, bg=C['bg']); wrap.pack(fill='both', expand=True, padx=14)
        cols = ('tag', 'freq', 'codes_n', 'first', 'last')
        tree = ttk.Treeview(wrap, columns=cols, show='headings', height=18,
                             selectmode='extended')
        for col, txt, w_ in [('tag','标签',180),('freq','频次',60),
                              ('codes_n','涉及股票数',90),
                              ('first','首次',88),('last','最近',88)]:
            tree.heading(col, text=txt)
            tree.column(col, width=w_, minwidth=40,
                         anchor='center' if col != 'tag' else 'w',
                         stretch=True)
        sb = ttk.Scrollbar(wrap, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # 状态条
        status = tk.StringVar(value="加载中...")
        tk.Label(dlg, textvariable=status, font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['yellow']).pack(anchor='w', padx=14, pady=(4, 2))

        # 数据加载
        def _reload():
            tree.delete(*tree.get_children())
            status.set("⏳ 扫描所有历史...")
            def _do():
                rows = tr.list_all_tags(days=0)
                def _upd():
                    for r in rows:
                        tree.insert('', 'end', values=(
                            r['tag'], r['freq'], r['codes_n'],
                            r['first_date'], r['last_date']))
                    status.set("✅ 共 {} 个标签".format(len(rows)))
                state.ui_queue.put(_upd)
            threading.Thread(target=_do, daemon=True).start()

        _reload()

        def _selected_tags():
            return [tree.item(iid)['values'][0] for iid in tree.selection()]

        # 操作按钮区
        def _do_rename():
            tags = _selected_tags()
            if len(tags) != 1:
                messagebox.showinfo("提示", "请选择 1 个标签进行重命名", parent=dlg); return
            old = tags[0]
            new = simpledialog.askstring("重命名",
                "把【{}】改为：".format(old),
                initialvalue=old, parent=dlg)
            if not new or new.strip() == old: return
            new = new.strip()
            def _do():
                n = tr.rename_tag(old, new)
                state.ui_queue.put(lambda: (
                    messagebox.showinfo("完成",
                        "已把 {} 条历史记录中的【{}】改为【{}】\n（同时写入了别名表）".format(n, old, new),
                        parent=dlg),
                    _reload()))
            threading.Thread(target=_do, daemon=True).start()

        def _do_merge():
            tags = _selected_tags()
            if len(tags) < 2:
                messagebox.showinfo("提示", "请至少选择 2 个标签进行合并", parent=dlg); return
            target = simpledialog.askstring("合并",
                "把下列 {} 个标签合并为：\n\n  {}".format(
                    len(tags), "、".join(tags[:8]) + ("..." if len(tags) > 8 else "")),
                initialvalue=tags[0], parent=dlg)
            if not target or not target.strip(): return
            target = target.strip()
            sources = [t for t in tags if t != target]
            if not sources: return
            def _do():
                n, per = tr.merge_tags(sources, target)
                detail = "\n".join("  · {} → {} 条".format(s, c) for s, c in per.items())
                state.ui_queue.put(lambda: (
                    messagebox.showinfo("完成",
                        "已合并 {} 个标签到【{}】，共影响 {} 条历史记录:\n\n{}".format(
                            len(sources), target, n, detail),
                        parent=dlg),
                    _reload()))
            threading.Thread(target=_do, daemon=True).start()

        def _do_delete():
            tags = _selected_tags()
            if not tags:
                messagebox.showinfo("提示", "请选择要删除的标签", parent=dlg); return
            if not messagebox.askyesno("确认",
                "确定要从所有历史 category 中删除以下 {} 个标签吗？\n\n{}\n\n"
                "（AI 生成的文本不会被改动）".format(
                    len(tags), "、".join(tags[:10]) + ("..." if len(tags) > 10 else "")),
                parent=dlg): return
            def _do():
                total = 0
                for t in tags:
                    total += tr.delete_tag(t)
                state.ui_queue.put(lambda: (
                    messagebox.showinfo("完成",
                        "已从 {} 条历史记录中移除 {} 个标签".format(total, len(tags)),
                        parent=dlg),
                    _reload()))
            threading.Thread(target=_do, daemon=True).start()

        def _do_view_aliases():
            aliases = tr.load_aliases()
            if not aliases:
                messagebox.showinfo("别名表", "暂无别名映射", parent=dlg); return
            lines = ["  · {} → {}".format(k, v) for k, v in sorted(aliases.items())]
            msg = "当前别名表（共 {} 条）：\n\n{}".format(
                len(aliases), "\n".join(lines[:50]))
            if len(aliases) > 50: msg += "\n\n...（仅显示前 50 条）"
            messagebox.showinfo("别名表", msg, parent=dlg)

        bb = tk.Frame(dlg, bg=C['bg']); bb.pack(fill='x', padx=14, pady=(0, 12))
        styled_btn(bb, "✏️ 重命名", C['accent'],     _do_rename, pady=6).pack(side='left', padx=(0, 4))
        styled_btn(bb, "🔀 合并",   C['purple'],     _do_merge,  pady=6).pack(side='left', padx=(0, 4))
        styled_btn(bb, "🗑 删除",   C['red'],        _do_delete, pady=6).pack(side='left', padx=(0, 4))
        styled_btn(bb, "🔗 查看别名表", C['idle'],   _do_view_aliases, pady=6).pack(side='left')
        styled_btn(bb, "🔄 刷新",   C['idle'],       lambda: _reload(), pady=6).pack(side='right')

        def _on_close():
            # 关闭时若有改动，刷新主关联视图
            dlg.destroy()
            try:
                self._tag_rescan()
            except Exception:
                pass
        dlg.protocol("WM_DELETE_WINDOW", _on_close)

    # ════════════════════════════════════════════════
    # 🆕 批量 AI 聚类（使用专属配置和提示词）
    # ════════════════════════════════════════════════
    def _edit_bulk_prompt(self):
        """编辑批量分析的提示词"""
        C = self.C
        dlg = tk.Toplevel(self.app.root)
        dlg.title("📝 编辑 AI 聚类专属提示词")
        dlg.geometry("760x560")
        dlg.configure(bg=C['bg'])
        dlg.transient(self.app.root)

        tk.Label(dlg, text="自定义批量聚类提示词",
                 font=('微软雅黑', 11, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(pady=(12, 4))
        tk.Label(dlg,
                 text="提示词中必须包含 {tag_list} 和 {cooccur_list} 占位符，系统会自动替换为扫描数据",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['yellow']).pack()
        
        text = tk.Text(dlg, font=('Consolas', 10), wrap='word',
                        bg=C['card'], fg=C['text'], insertbackground='white',
                        relief='flat', padx=8, pady=6, height=20, undo=True)
        text.pack(fill='both', expand=True, padx=24, pady=8)

        cur = tr.load_bulk_prompt_template()
        text.insert('1.0', cur)

        bb = tk.Frame(dlg, bg=C['bg']); bb.pack(fill='x', padx=24, pady=(0, 12))
        def _save():
            t = text.get('1.0', 'end-1c').strip()
            tr.save_bulk_prompt_template(t)
            messagebox.showinfo("已保存", "提示词已保存", parent=dlg)
            dlg.destroy()
        def _reset():
            if messagebox.askyesno("确认", "恢复为默认提示词？", parent=dlg):
                text.delete('1.0', 'end')
                text.insert('1.0', tr.DEFAULT_BULK_PROMPT)
        styled_btn(bb, "💾 保存并关闭", C['green'], _save, pady=8).pack(side='right', padx=(4, 0))
        styled_btn(bb, "↩️ 恢复默认", C['idle'], _reset, pady=8).pack(side='right')

    def _tag_bulk_analyze(self):
        if not self._tag_freq:
            messagebox.showinfo("提示", "请先点「重新扫描」"); return

        # 🆕 读取聚类专属 API 配置
        bulk_url = self._bulk_url.get().strip()
        bulk_key = self._bulk_key.get().strip()
        bulk_model_disp = self._bulk_model_var.get().strip()
        bulk_model = cfg_mod.display_name_to_model_id(bulk_model_disp)

        # 🌟 需求2：保存专属配置到全局设置
        self.app.cfg["tag_relation_api_settings"] = {
            "url": bulk_url, "key": bulk_key, "model_disp": bulk_model_disp
        }
        cfg_mod.save_config(self.app.cfg)

        if not bulk_key:
            messagebox.showwarning("无 Key", "请在上方填写聚类专用 API Key"); return

        bulk_cfg = {
            "api_url": bulk_url,
            "model": bulk_model,
            "timeout": 180,
            "max_tokens": 3000
        }

        if not messagebox.askyesno("确认",
                "将使用专属配置发送 AI 聚类请求：\n\n"
                "🌐 URL: {}\n"
                "🤖 Model: {}\n"
                "🔑 Key: {}...\n\n"
                "继续？".format(bulk_url[:50], self._bulk_model_var.get(), bulk_key[:15])):
            return

        prompt_template = tr.load_bulk_prompt_template()

        T = self._tag_detail
        T.config(state='normal'); T.delete('1.0', 'end')
        T.insert('end', "🤖 AI 批量聚类中...\n", 'h1')
        T.config(state='disabled')
        self._tag_ai_status.set("🤖 分析中（耗时较长）...")

        def _do():
            result, ok = tr.query_ai_bulk_clustering(
                self._tag_freq, self._cooccur, bulk_key,  # 🆕 使用专属 Key
                bulk_cfg,                                   # 🆕 使用专属 Cfg
                custom_prompt=prompt_template)

            from datetime import datetime
            try:
                from ..core.paths import DIRS
                from pathlib import Path
                p = Path(DIRS["config"]) / "tag_relation_bulk_result.txt"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(
                    "生成时间: {}\nModel: {}\n\n{}".format(
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        self._bulk_model_var.get(), result),
                    encoding="utf-8")
            except Exception:
                pass

            def _done():
                T.config(state='normal')
                T.delete('1.0', 'end')
                T.insert('end', "🤖  AI 批量聚类结果\n", 'h1')
                T.insert('end', "━" * 50 + "\n\n", 'dim')
                T.insert('end', result if ok else "❌ 分析失败: " + result)
                T.insert('end', "\n\n" + "━" * 50 + "\n", 'dim')
                T.insert('end', "✅ 结果已保存到 data/config/tag_relation_bulk_result.txt\n", 'dim')
                T.config(state='disabled')
                self._tag_ai_status.set("✅ 完成" if ok else "❌ 失败")
                self.app.root.after(5000, lambda: self._tag_ai_status.set(""))
            state.ui_queue.put(_done)
        threading.Thread(target=_do, daemon=True).start()

    # ════════════════════════════════════════════════
    # 全局：新建/重命名/删除板块
    # ════════════════════════════════════════════════
    def _create_sector_dialog(self):
        name = simpledialog.askstring("新建板块",
            "请输入板块名（如：半导体）", parent=self.app.root)
        if not name: return
        ok, msg = my_sectors.create_sector(name.strip())
        if not ok:
            messagebox.showwarning("失败", msg); return
        self._refresh_nav()
        for i in range(self._nav.size()):
            if name.strip() in self._nav.get(i) and "📂" in self._nav.get(i):
                self._nav.selection_clear(0, 'end')
                self._nav.selection_set(i)
                self._cur_view = VIEW_USER
                self._cur_sector_name = name.strip()
                for w in self._right_container.winfo_children():
                    w.destroy()
                self._build_user_sector_view()
                break

    def _rename_sector(self):
        if self._cur_view != VIEW_USER or not self._cur_sector_name:
            messagebox.showinfo("提示", "请先选中一个自建板块"); return
        new = simpledialog.askstring("重命名",
            "新名称：", initialvalue=self._cur_sector_name, parent=self.app.root)
        if not new: return
        ok, msg = my_sectors.rename_sector(self._cur_sector_name, new.strip())
        if not ok:
            messagebox.showwarning("失败", msg); return
        self._cur_sector_name = new.strip()
        self._refresh_nav()
        self._render_user_sector()

    def _delete_sector(self):
        if self._cur_view != VIEW_USER or not self._cur_sector_name:
            messagebox.showinfo("提示", "请先选中一个自建板块"); return
        if not messagebox.askyesno("确认",
                "删除板块「{}」？".format(self._cur_sector_name)):
            return
        my_sectors.delete_sector(self._cur_sector_name)
        self._cur_sector_name = None
        for w in self._right_container.winfo_children():
            w.destroy()
        self._refresh_nav()

    def _analyze_current(self):
        """快捷键 Ctrl+Enter 触发，按当前视图执行相应分析"""
        if self._cur_view == VIEW_FAV:
            self._fav_analyze_sel()
        elif self._cur_view == VIEW_USER:
            self._analyze_user_sector()