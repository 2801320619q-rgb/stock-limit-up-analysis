"""
📊 板块分析 Tab（v9.7 重写）
- 主 Tab：[📊 板块分析] + [📡 涨停雷达] 两个子 Tab
- 顶部日期下拉：选「今日（实时）」走 API，选历史日期走快照
- 「刷新」按钮：拉实时 → 预先拉全部板块成份股 → 整体保存为今日快照
- 选历史日期时点刷新 → 弹确认对话框
- 龙头梯队 Text：单击带代码的行通知浮窗（联动模式开启时刷新）
"""
import threading, time
import tkinter as tk
from tkinter import ttk, messagebox

from .base import BaseTab
from ..widgets import make_card, styled_btn
from ..core import (api_client, sector as sector_core,
                     config as cfg_mod,
                     history as hist_mod,
                     sector_snapshot as snap_mod)
from ..bus import bus, Events, state


STATUS_COLORS = {
    "一字板":     "#ff3838",
    "涨停":       "#ff5c5c",
    "炸板":       "#ff9a3c",
    "冲高回落":   "#ffc94d",
    "强势":       "#3ddc84",
    "上涨":       "#4f9eff",
    "下跌":       "#8b8fa8",
    "跌停":       "#00d9ff",
}


class SectorTab(BaseTab):
    title = "板块分析"

    def __init__(self, app):
        super().__init__(app)
        self._sectors = []
        self._cur_sector = None
        self._cur_stocks = []
        self._stocks_by_sector = {}
        self._select_seq = 0
        self._radar_data = []
        self._cur_date_key = None
        self._available_dates = []

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=10)

        # 顶部
        hr = tk.Frame(body, bg=C['bg']); hr.pack(fill='x', pady=(0, 8))
        title_box = tk.Frame(hr, bg=C['bg']); title_box.pack(side='left')
        tk.Frame(title_box, bg=C['accent'], width=4).pack(side='left', fill='y', padx=(0, 8))
        tk.Label(title_box, text="板块 & 雷达分析",
                 font=('微软雅黑', 13, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(side='left', pady=2)

        tk.Label(hr, text="  📅 日期", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(18, 4))
        self._date_var = tk.StringVar(value="今日（实时）")
        self._date_combo = ttk.Combobox(hr, textvariable=self._date_var,
                                         state='readonly', width=18,
                                         font=('微软雅黑', 9))
        self._date_combo.pack(side='left')
        self._date_combo.bind('<<ComboboxSelected>>',
                               lambda e: self._on_date_change())

        self._sector_type = tk.StringVar(value="concept")
        type_frame = tk.Frame(hr, bg=C['bg'])
        type_frame.pack(side='left', padx=(14, 0))
        for val, lbl in [("concept", "💡 概念"), ("industry", "🏭 行业")]:
            tk.Radiobutton(type_frame, text=lbl, variable=self._sector_type,
                           value=val, font=('微软雅黑', 9),
                           bg=C['bg'], fg=C['text'],
                           selectcolor=C['card'], activebackground=C['bg'],
                           command=self._on_type_change).pack(side='left', padx=(0, 6))

        styled_btn(hr, "🔄 刷新（拉实时并保存今日快照）", C['accent'],
                   self._refresh).pack(side='right', padx=(6, 0))
        styled_btn(hr, "🚀 分析当前板块龙头", C['green'],
                   self._analyze_leaders).pack(side='right', padx=(0, 6))

        self._status_var = tk.StringVar(value="未刷新，请点击「刷新」")
        tk.Label(body, textvariable=self._status_var,
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['yellow']).pack(anchor='w', pady=(0, 6))

        self._sub_nb = ttk.Notebook(body, style='App.TNotebook')
        self._sub_nb.pack(fill='both', expand=True)

        self._sector_frame = tk.Frame(self._sub_nb, bg=C['bg'])
        self._sub_nb.add(self._sector_frame, text="  📊 板块分析  ")
        self._build_sector_view(self._sector_frame)

        self._radar_frame = tk.Frame(self._sub_nb, bg=C['bg'])
        self._sub_nb.add(self._radar_frame, text="  📡 涨停雷达  ")
        self._build_radar_view(self._radar_frame)

        self.app.root.after(100, self._auto_load_today_or_latest)

    # ─── 板块视图 ───
    def _build_sector_view(self, parent):
        C = self.C
        pw = tk.PanedWindow(parent, bg=C['bg'], sashwidth=5,
                             sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        left  = tk.Frame(pw, bg=C['bg'])
        right = tk.Frame(pw, bg=C['bg'])
        pw.add(left, minsize=420)
        pw.add(right, minsize=520)

        tk.Label(left, text="板块榜单（按涨幅排序）",
                 font=('微软雅黑', 9, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(anchor='w', pady=(0, 4))

        cols = ('name', 'pct', 'inflow', 'leader')
        self._sector_tree = ttk.Treeview(left, columns=cols,
                                          show='headings', height=22)
        for col, txt, w in [('name', '板块', 150), ('pct', '涨幅', 70),
                              ('inflow', '主力流入', 90), ('leader', '领涨股', 110)]:
            self._sector_tree.heading(col, text=txt)
            self._sector_tree.column(col, width=w,
                                      anchor='center' if col != 'name' else 'w')
        vsb = ttk.Scrollbar(left, orient='vertical',
                             command=self._sector_tree.yview)
        self._sector_tree.configure(yscrollcommand=vsb.set)
        self._sector_tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        self._sector_tree.tag_configure('up_strong', foreground=C['red'])
        self._sector_tree.tag_configure('up',        foreground='#ff9a3c')
        self._sector_tree.tag_configure('down',      foreground=C['green'])
        self._sector_tree.bind('<<TreeviewSelect>>',
                                lambda e: self._on_sector_select())

        head = tk.Frame(right, bg=C['panel'],
                        highlightbackground=C['border'], highlightthickness=1)
        head.pack(fill='x')
        self._sect_title = tk.StringVar(value="选中一个板块查看详情")
        tk.Label(head, textvariable=self._sect_title,
                 font=('微软雅黑', 11, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=10, pady=8)
        self._score_var = tk.StringVar(value="")
        tk.Label(head, textvariable=self._score_var,
                 font=('微软雅黑', 14, 'bold'),
                 bg=C['panel'], fg=C['yellow']).pack(side='right', padx=10, pady=8)

        self._breakdown_frame = tk.Frame(right, bg=C['bg'])
        self._breakdown_frame.pack(fill='x', pady=(4, 6))

        sub_nb = ttk.Notebook(right, style='App.TNotebook')
        sub_nb.pack(fill='both', expand=True)

        ladder_frame = tk.Frame(sub_nb, bg=C['bg'])
        sub_nb.add(ladder_frame, text="  🏆 龙头梯队  ")
        self._ladder_text = tk.Text(ladder_frame,
                                     font=('微软雅黑', 10), wrap='word',
                                     bg=C['card'], fg=C['text'],
                                     relief='flat', padx=10, pady=8,
                                     state='disabled', cursor='arrow')
        lvsb = ttk.Scrollbar(ladder_frame, orient='vertical',
                              command=self._ladder_text.yview)
        self._ladder_text.configure(yscrollcommand=lvsb.set)
        self._ladder_text.pack(side='left', fill='both', expand=True)
        lvsb.pack(side='right', fill='y')

        for tag, color in [('rank1', '#ffd700'), ('rank2', '#c0c0c0'),
                            ('rank3', '#cd7f32'), ('lu', C['red']),
                            ('broken', '#ff9a3c'), ('fading', C['yellow']),
                            ('follow', C['green']), ('section', C['accent']),
                            ('dim', C['dim'])]:
            self._ladder_text.tag_config(tag, foreground=color)
        self._ladder_text.tag_config('bold', font=('微软雅黑', 10, 'bold'))

        self._ladder_text.bind('<Button-1>',
                                self._ladder_left_click_follow, add='+')
        self._ladder_text.bind('<Button-3>', self._ladder_show_ctx)
        self._ladder_text.bind('<Button-2>', self._ladder_show_ctx)
        self._ladder_ctx = tk.Menu(self._ladder_text, tearoff=0,
            bg=C['panel'], fg=C['text'],
            activebackground=C['acc_dark'], activeforeground='white',
            font=('微软雅黑', 9))
        self._ladder_ctx.add_command(label="🔎  查看此股详情",
            command=self._ladder_show_stock_popup)

        history_frame = tk.Frame(sub_nb, bg=C['bg'])
        sub_nb.add(history_frame, text="  📅 历史回看  ")
        tk.Label(history_frame,
                 text="本地历史记录中该板块出现的所有日期",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim']).pack(anchor='w', pady=(6, 4))
        h_cols = ('date', 'count', 'stocks')
        self._hist_tree = ttk.Treeview(history_frame, columns=h_cols,
                                        show='headings', height=18)
        for col, txt, w in [('date', '日期', 100), ('count', '出现次数', 80),
                              ('stocks', '涉及股票', 350)]:
            self._hist_tree.heading(col, text=txt)
            self._hist_tree.column(col, width=w,
                                    anchor='center' if col != 'stocks' else 'w')
        h_vsb = ttk.Scrollbar(history_frame, orient='vertical',
                               command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=h_vsb.set)
        self._hist_tree.pack(side='left', fill='both', expand=True)
        h_vsb.pack(side='right', fill='y')

    # ─── 雷达视图 ───
    def _build_radar_view(self, parent):
        C = self.C
        top = tk.Frame(parent, bg=C['bg']); top.pack(fill='x', pady=(8, 6))
        tk.Label(top, text="最低涨幅", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._radar_min_pct = tk.StringVar(value="9.5")
        tk.Entry(top, textvariable=self._radar_min_pct, width=5,
                  font=('微软雅黑', 9)).pack(side='left')
        tk.Label(top, text="%   页数", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(4, 4))
        self._radar_pages = tk.StringVar(value="5")
        tk.Entry(top, textvariable=self._radar_pages, width=4,
                  font=('微软雅黑', 9)).pack(side='left')
        tk.Label(top, text="(每页100只)", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(4, 0))

        self._radar_sum_frame = tk.Frame(parent, bg=C['bg'])
        self._radar_sum_frame.pack(fill='x', pady=(0, 8))
        self._radar_sum_vars = {
            'limit_up':  tk.StringVar(value="—"),
            'avg_pct':   tk.StringVar(value="—"),
            'max_pct':   tk.StringVar(value="—"),
            'hot_codes': tk.StringVar(value="—"),
        }
        chip_items = [
            ('🎯 涨停股', 'limit_up'),
            ('📈 平均涨幅', 'avg_pct'),
            ('🚀 最高涨幅', 'max_pct'),
            ('🔥 本地有历史', 'hot_codes'),
        ]
        for label, key in chip_items:
            f = tk.Frame(self._radar_sum_frame, bg=C['card'])
            f.pack(side='left', padx=(0, 8), pady=2, ipadx=8, ipady=4)
            tk.Label(f, text=label, font=('微软雅黑', 8),
                     bg=C['card'], fg=C['dim']).pack(anchor='w')
            tk.Label(f, textvariable=self._radar_sum_vars[key],
                     font=('微软雅黑', 12, 'bold'),
                     bg=C['card'], fg=C['accent']).pack(anchor='w')

        pw = tk.PanedWindow(parent, bg=C['bg'], sashwidth=5,
                             sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        lf = tk.Frame(pw, bg=C['bg'])
        rf = tk.Frame(pw, bg=C['bg'])
        pw.add(lf, minsize=560)
        pw.add(rf, minsize=280)

        tk.Label(lf, text="涨幅榜（含可能涨停的股票）",
                 font=('微软雅黑', 9, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(anchor='w', pady=(0, 4))
        cols = ('name', 'code', 'price', 'pct', 'high', 'low')
        self._radar_tree = ttk.Treeview(lf, columns=cols,
                                          show='headings', height=20)
        for col, txt, w in [('name','名称',120),('code','代码',90),
                              ('price','现价',80),('pct','涨幅%',80),
                              ('high','最高',80),('low','最低',80)]:
            self._radar_tree.heading(col, text=txt)
            self._radar_tree.column(col, width=w, minwidth=40,
                                     anchor='center', stretch=True)
        self._radar_tree.pack(side='left', fill='both', expand=True)
        rvsb = ttk.Scrollbar(lf, orient='vertical',
                              command=self._radar_tree.yview)
        self._radar_tree.configure(yscrollcommand=rvsb.set)
        rvsb.pack(side='right', fill='y')
        self._radar_tree.tag_configure('lu', foreground=C['red'])
        self._radar_tree.tag_configure('up', foreground='#ff9a3c')

        self._radar_tree.bind('<<TreeviewSelect>>',
                               lambda e: self._radar_on_row_focus())
        self._radar_tree.bind('<Double-1>',
                               lambda e: self._radar_analyze_selected())
        self._radar_ctx = tk.Menu(self._radar_tree, tearoff=0,
            bg=C['panel'], fg=C['text'],
            activebackground=C['acc_dark'], activeforeground='white',
            font=('微软雅黑', 9))
        self._radar_ctx.add_command(label="🔎  查看股票详情",
            command=self._radar_show_popup_selected)
        self._radar_ctx.add_separator()
        self._radar_ctx.add_command(label="🔍  分析选中（送AI）",
            command=self._radar_analyze_selected)
        self._radar_ctx.add_command(label="⭐  加入自选股",
            command=self._radar_add_to_fav)
        self._radar_tree.bind('<Button-3>', self._radar_show_ctx)
        self._radar_tree.bind('<Button-2>', self._radar_show_ctx)

        tk.Label(rf, text="🔥 今日个股热度 TopN",
                 font=('微软雅黑', 9, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(anchor='w', pady=(0, 4))
        tk.Label(rf,
                 text="（涨幅榜 ∩ 本地历史）",
                 font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(anchor='w', pady=(0, 4))

        hot_cols = ('rank', 'name', 'code', 'pct', 'hist')
        self._hot_tree = ttk.Treeview(rf, columns=hot_cols,
                                       show='headings', height=15)
        for col, txt, w in [('rank','#',30),('name','名称',95),
                              ('code','代码',75),('pct','今涨',60),
                              ('hist','历史',50)]:
            self._hot_tree.heading(col, text=txt)
            self._hot_tree.column(col, width=w, minwidth=30,
                                   anchor='center' if col != 'name' else 'w')
        self._hot_tree.pack(fill='both', expand=True)
        self._hot_tree.tag_configure('lu', foreground=C['red'])
        self._hot_tree.bind('<<TreeviewSelect>>',
                             lambda e: self._hot_on_row_focus())
        self._hot_tree.bind('<Double-1>',
                             lambda e: self._hot_open_popup())

    # ─── 启动加载 ───
    def _auto_load_today_or_latest(self):
        self._refresh_date_dropdown()
        today = snap_mod.today_key()
        if snap_mod.load_snapshot(today) is not None:
            self._cur_date_key = today
            self._date_var.set("今日（实时）")
            self._load_snapshot_into_ui(today)
            self._status_var.set("📁 已加载今日快照（{}）".format(_now()))
            return
        dates = snap_mod.list_dates()
        if dates:
            d = dates[0]
            self._cur_date_key = d
            self._date_var.set("{} (历史)".format(snap_mod.format_date_label(d)))
            self._load_snapshot_into_ui(d)
            self._status_var.set(
                "📁 已加载 {} 的快照 · 点 🔄 刷新可拉取今日实时数据".format(
                    snap_mod.format_date_label(d)))
        else:
            self._status_var.set("未刷新，请点击「🔄 刷新」获取板块和雷达数据")

    def _refresh_date_dropdown(self):
        dates = snap_mod.list_dates()
        today = snap_mod.today_key()
        opts = ["今日（实时）"]
        for d in dates:
            if d == today:
                continue
            opts.append("{} (历史)".format(snap_mod.format_date_label(d)))
        self._available_dates = dates
        self._date_combo['values'] = opts

    def _on_date_change(self):
        text = self._date_var.get()
        today = snap_mod.today_key()
        if text == "今日（实时）":
            self._cur_date_key = today
            if snap_mod.load_snapshot(today) is not None:
                self._load_snapshot_into_ui(today)
                self._status_var.set("📁 已加载今日快照")
            else:
                self._status_var.set("今日尚未刷新，请点击「🔄 刷新」")
            return
        for d in self._available_dates:
            if snap_mod.format_date_label(d) in text:
                self._cur_date_key = d
                self._load_snapshot_into_ui(d)
                self._status_var.set("📁 历史快照: {}".format(
                    snap_mod.format_date_label(d)))
                break

    def _on_type_change(self):
        today = snap_mod.today_key()
        if self._cur_date_key == today or self._cur_date_key is None:
            self._refresh()
        else:
            # 历史快照里类型固定 → 强制还原回快照里的类型
            snap = snap_mod.load_snapshot(self._cur_date_key)
            if snap:
                self._sector_type.set(snap.get('type', 'concept'))
                self._load_snapshot_into_ui(self._cur_date_key)

    # ─── 刷新（拉实时 + 全板块预拉 + 保存） ───
    def _refresh(self):
        today = snap_mod.today_key()
        if self._cur_date_key and self._cur_date_key != today:
            if not messagebox.askyesno(
                "确认刷新",
                "当前正在查看历史快照（{}）。\n\n"
                "刷新会拉取实时数据并保存为今日（{}）快照，不会覆盖该历史日期。\n\n"
                "是否继续？".format(
                    snap_mod.format_date_label(self._cur_date_key),
                    snap_mod.format_date_label(today))):
                return

        sector_type = self._sector_type.get()
        radar_min_pct = self._safe_float(self._radar_min_pct.get(), 9.5)
        radar_pages   = max(1, min(10, self._safe_int(self._radar_pages.get(), 5)))

        self._status_var.set("⏳ 正在拉取板块榜单...")
        for i in self._sector_tree.get_children(): self._sector_tree.delete(i)
        for i in self._radar_tree.get_children():  self._radar_tree.delete(i)
        for i in self._hot_tree.get_children():    self._hot_tree.delete(i)
        self._clear_breakdown(); self._clear_ladder(); self._clear_history_tree()

        def _do():
            sectors = api_client.fetch_sectors(sector_type, top_n=200)
            if isinstance(sectors, dict) and 'error' in sectors:
                state.ui_queue.put(lambda: self._status_var.set(
                    "❌ 拉取板块失败: " + sectors['error']))
                return

            # 🆕 v9.8 修复：先把板块榜单渲染出来，不等成份股全部拉完
            def _early_render():
                self._render_sectors(sectors, sector_type)
                self._cur_date_key = today
                self._date_var.set("今日（实时）")
            state.ui_queue.put(_early_render)

            state.ui_queue.put(lambda: self._status_var.set(
                "⏳ 板块榜单 {} 个已加载，正在拉成份股...".format(len(sectors))))

            # 🆕 v9.8 修复：增量保存
            # 每拉 BATCH 个板块就保存一次快照，避免主程序中途关闭导致前功尽弃
            BATCH = 10
            stocks_by_sector = {}
            total = len(sectors)
            failed_codes = []
            for i, s in enumerate(sectors):
                code = s.get('code', '')
                stocks = api_client.fetch_sector_stocks(code, top_n=200)
                if isinstance(stocks, list) and stocks:
                    stocks_by_sector[code] = stocks
                else:
                    # 失败的板块不入快照（用户选项：Q3 选 1）
                    failed_codes.append(s.get('name', code))

                if (i + 1) % BATCH == 0 or i == total - 1:
                    # 进度提示
                    msg = "⏳ 已拉 {}/{} 个板块（成功 {}，失败 {}）".format(
                        i + 1, total, len(stocks_by_sector), len(failed_codes))
                    state.ui_queue.put(lambda m=msg: self._status_var.set(m))
                    # 🆕 增量保存当前已有数据，避免崩溃丢失
                    partial_payload = {
                        "type":   sector_type,
                        "sectors": sectors,
                        "stocks_by_sector": dict(stocks_by_sector),
                        "radar":  [],  # 雷达在最后拉
                        "radar_params": {
                            "min_pct": radar_min_pct, "pages": radar_pages},
                        "progress": {"done": i + 1, "total": total,
                                      "failed": list(failed_codes)},
                    }
                    try: snap_mod.save_snapshot(partial_payload, today)
                    except Exception: pass
                    # 更新内存里的 stocks_by_sector（让选板块能立刻看到数据）
                    self._stocks_by_sector = dict(stocks_by_sector)

            state.ui_queue.put(lambda: self._status_var.set(
                "⏳ 成份股全部拉完（{} 成功 / {} 失败），正在拉涨幅榜...".format(
                    len(stocks_by_sector), len(failed_codes))))
            radar = api_client.fetch_limit_up_stocks(
                min_pct=radar_min_pct, max_pages=radar_pages)
            if isinstance(radar, dict) and 'error' in radar:
                radar = []

            # 最终一次保存
            payload = {
                "type":   sector_type,
                "sectors": sectors,
                "stocks_by_sector": stocks_by_sector,
                "radar":  radar,
                "radar_params": {
                    "min_pct": radar_min_pct, "pages": radar_pages},
                "progress": {"done": total, "total": total,
                              "failed": failed_codes},
            }
            saved_ok = True
            try:
                snap_mod.save_snapshot(payload, today)
            except Exception as e:
                saved_ok = False
                err_msg = str(e)
                state.ui_queue.put(lambda m=err_msg: self._status_var.set(
                    "⚠️ 保存快照失败: " + m))

            def _render():
                self._refresh_date_dropdown()
                self._stocks_by_sector = stocks_by_sector
                self._render_radar(radar)
                if saved_ok:
                    tail = ""
                    if failed_codes:
                        tail = " · 失败 {} 个：{}".format(
                            len(failed_codes),
                            "、".join(failed_codes[:3]) +
                            ("..." if len(failed_codes) > 3 else ""))
                    self._status_var.set(
                        "✅ {} · 已保存今日快照（{}）{}".format(
                            "概念" if sector_type == "concept" else "行业",
                            _now(), tail))
            state.ui_queue.put(_render)

        threading.Thread(target=_do, daemon=True).start()

    # ════════════════════════════════════════════════
    # 🆕 v9.8：主程序关闭时的兜底保存
    # ════════════════════════════════════════════════
    def _save_partial_on_close(self):
        """App._on_close 调用：把当前内存里的成份股 + 板块再存一次"""
        try:
            if not self._sectors or not self._stocks_by_sector:
                return
            today = snap_mod.today_key()
            existing = snap_mod.load_snapshot(today) or {}
            # 仅在本次拉取数据 >= 既有数据时才覆盖
            existing_count = len(existing.get('stocks_by_sector', {}))
            new_count = len(self._stocks_by_sector)
            if new_count < existing_count:
                # 已有快照比内存数据更全，不动它
                return
            payload = {
                "type":   self._sector_type.get(),
                "sectors": self._sectors,
                "stocks_by_sector": self._stocks_by_sector,
                "radar":  self._radar_data,
                "radar_params": existing.get("radar_params", {}),
            }
            snap_mod.save_snapshot(payload, today)
        except Exception:
            import traceback; traceback.print_exc()

    def _load_snapshot_into_ui(self, date_key):
        snap = snap_mod.load_snapshot(date_key)
        if not snap: return
        saved_type = snap.get('type', 'concept')
        if saved_type != self._sector_type.get():
            self._sector_type.set(saved_type)
        sectors = snap.get('sectors', [])
        self._stocks_by_sector = snap.get('stocks_by_sector', {}) or {}
        self._render_sectors(sectors, saved_type)
        self._render_radar(snap.get('radar', []))

    # ─── 板块榜单 / 板块详情 ───
    def _render_sectors(self, sectors, sector_type):
        for i in self._sector_tree.get_children():
            self._sector_tree.delete(i)
        self._sectors = sectors
        for s in sectors:
            pct = s.get('change_pct', 0)
            inflow_yi = s.get('main_inflow', 0) / 1e8
            leader_text = "{} ({:+.1f}%)".format(
                s.get('leader_name', ''), s.get('leader_pct', 0)) \
                if s.get('leader_name') else ""
            if pct >= 3:   tag = 'up_strong'
            elif pct > 0:  tag = 'up'
            else:          tag = 'down'
            self._sector_tree.insert('', 'end', values=(
                s.get('name', ''),
                "{:+.2f}%".format(pct),
                "{:+.2f}亿".format(inflow_yi),
                leader_text), tags=(tag,))

    def _on_sector_select(self):
        sel = self._sector_tree.selection()
        if not sel: return
        idx = self._sector_tree.index(sel[0])
        if idx >= len(self._sectors): return
        sector = self._sectors[idx]
        self._cur_sector = sector
        self._sect_title.set("📂 {}  ({:+.2f}%)".format(
            sector['name'], sector.get('change_pct', 0)))
        self._clear_breakdown(); self._clear_ladder(); self._clear_history_tree()

        self._select_seq += 1
        my_seq = self._select_seq
        code = sector.get('code', '')
        stocks = self._stocks_by_sector.get(code, [])
        if not stocks:
            def _supply():
                fetched = api_client.fetch_sector_stocks(code, top_n=200)
                if isinstance(fetched, list):
                    self._stocks_by_sector[code] = fetched
                    def _r():
                        if my_seq != self._select_seq: return
                        self._render_sector_detail(sector, fetched)
                    state.ui_queue.put(_r)
            threading.Thread(target=_supply, daemon=True).start()
            return
        self._render_sector_detail(sector, stocks)

    def _render_sector_detail(self, sector, stocks):
        self._cur_stocks = stocks
        score, breakdown = sector_core.calc_sector_strength(sector, stocks)
        ladder = sector_core.identify_ladder(stocks)
        history_data = sector_core.search_sector_in_history(
            sector['name'], days=180)
        self._render_score(score, breakdown, len(stocks))
        self._render_ladder(ladder, sector)
        self._render_history(history_data)

    def _clear_breakdown(self):
        for w in self._breakdown_frame.winfo_children(): w.destroy()
        self._score_var.set("")

    def _render_score(self, score, breakdown, total_stocks):
        C = self.C
        for w in self._breakdown_frame.winfo_children(): w.destroy()
        if score >= 70: color = C['red']
        elif score >= 50: color = '#ff9a3c'
        elif score >= 30: color = C['yellow']
        else: color = C['dim']
        self._score_var.set("强度 {}/100".format(score))

        chips = [
            ("📈 涨停股", "{} 只".format(breakdown.get('limit_up', 0))),
            ("📊 涨幅",   "板块涨幅 {:+.2f}%".format(breakdown.get('sector_pct', 0))),
            ("🔥 涨家数比", "涨家数 {}".format(breakdown.get('up_ratio', '0/0'))),
            ("💰 主力净入", "主力净流入 {:+.2f} 亿".format(breakdown.get('inflow_yi', 0))),
        ]
        row = tk.Frame(self._breakdown_frame, bg=C['bg'])
        row.pack(fill='x', padx=4)
        for label, value in chips:
            chip = tk.Frame(row, bg=C['card'])
            chip.pack(side='left', padx=(0, 8), ipadx=6, ipady=3)
            tk.Label(chip, text=label, font=('微软雅黑', 8),
                     bg=C['card'], fg=C['dim']).pack(anchor='w')
            tk.Label(chip, text=value, font=('微软雅黑', 10, 'bold'),
                     bg=C['card'], fg=color).pack(anchor='w')

    def _clear_ladder(self):
        self._ladder_text.config(state='normal')
        self._ladder_text.delete('1.0', 'end')
        self._ladder_text.config(state='disabled')

    def _render_ladder(self, ladder, sector):
        C = self.C
        T = self._ladder_text
        T.config(state='normal'); T.delete('1.0', 'end')
        def w(text, tag=None):
            if tag: T.insert('end', text, tag)
            else:   T.insert('end', text)

        if not ladder:
            w("\n暂无梯队数据。", 'dim')
            T.config(state='disabled'); return

        w("\n📈 板块概况\n", 'section')
        w("成交额: {:.1f} 亿".format(ladder.get('total_volume', 0) / 1e8), 'dim')
        w("  ·  主力净流入: {:+.2f} 亿".format(
            sector.get('main_inflow', 0) / 1e8), 'dim')
        w("  ·  振幅: {:.2f}%\n\n".format(ladder.get('amplitude', 0)), 'dim')

        groups = [
            ("🔴 冲高回落（日内高位回落）", ladder.get('fading', []), 'fading'),
            ("🟡 炸板（涨停打开未封回）",  ladder.get('broken', []), 'broken'),
            ("🟢 强势龙头（按市值/涨幅）", ladder.get('leaders', []), 'rank1'),
            ("🔵 跟风梯队（次新）",        ladder.get('followers', []), 'follow'),
        ]
        for title, items, color_tag in groups:
            if not items: continue
            w(title + "  ", color_tag); w("{} 只\n".format(len(items)), 'dim')
            for i, st in enumerate(items[:15], 1):
                code = st.get('code', '')
                name = st.get('name', '')
                pct  = st.get('change_pct', 0)
                price= st.get('price', 0)
                high = st.get('high', 0)
                prev = st.get('prev_close', price)
                prefix = "龙{}".format(i) if title.startswith("🟢") else "·"
                w("  {} {}  ".format(prefix, name))
                w("({}) ".format(code), 'dim')
                w("现 {:+.2f}% / 高 {:+.2f}%\n".format(
                    pct,
                    100 * (high - prev) / max(1, prev)),
                  color_tag)
            w("\n")

        w("📊 板块结构: ", 'section')
        cnt = ladder.get('counts', {})
        parts = []
        for label, key in [('涨停','limit_up'),('补涨','followers'),
                            ('炸板','broken'),('冲高回落','fading'),
                            ('其他上涨','up'),('下跌','down')]:
            parts.append("{} {}".format(label, cnt.get(key, 0)))
        w("  ·  ".join(parts), 'dim')

        T.config(state='disabled')
        # 🆕 v9.9.6：龙头梯队里所有股票代码加蓝字下划线 → 推送同花顺
        try:
            from ..widgets import attach_code_links
            attach_code_links(T, self.app, scope='main')
        except Exception:
            import traceback; traceback.print_exc()

    def _clear_history_tree(self):
        for i in self._hist_tree.get_children():
            self._hist_tree.delete(i)

    def _render_history(self, history_data):
        for i in self._hist_tree.get_children():
            self._hist_tree.delete(i)
        if not history_data:
            self._hist_tree.insert('', 'end',
                values=("(无)", 0, "本地历史中未找到该板块"))
            return
        for entry in history_data:
            self._hist_tree.insert('', 'end', values=(
                entry['date'], entry['count'],
                "、".join(entry['stocks'][:5]) +
                ("..." if len(entry['stocks']) > 5 else "")))

    # ─── 雷达 ───
    def _render_radar(self, radar_data):
        for i in self._radar_tree.get_children():
            self._radar_tree.delete(i)
        self._radar_data = radar_data or []
        if not radar_data:
            self._radar_sum_vars['limit_up'].set("—")
            self._radar_sum_vars['avg_pct'].set("—")
            self._radar_sum_vars['max_pct'].set("—")
            self._radar_sum_vars['hot_codes'].set("—")
        else:
            limit_up = sum(1 for s in radar_data
                            if s.get('change_pct', 0) >= 9.7)
            pcts = [s.get('change_pct', 0) for s in radar_data]
            avg = sum(pcts) / max(1, len(pcts))
            mx  = max(pcts) if pcts else 0
            self._radar_sum_vars['limit_up'].set("{} 只".format(limit_up))
            self._radar_sum_vars['avg_pct'].set("+{:.2f}%".format(avg))
            self._radar_sum_vars['max_pct'].set("+{:.2f}%".format(mx))

        hidx = hist_mod.get_code_count_index()
        hit = 0
        hot_candidates = []
        for s in radar_data:
            code = str(s.get('code', '')).zfill(6)
            n_hist = hidx.get(code, 0)
            mark = " 📊" if n_hist > 0 else ""
            tag = 'lu' if s.get('change_pct', 0) >= 9.7 else 'up'
            self._radar_tree.insert('', 'end', values=(
                s.get('name', '') + mark, code,
                "{:.2f}".format(s.get('price', 0)),
                "+{:.2f}%".format(s.get('change_pct', 0)),
                "{:.2f}".format(s.get('high', 0)),
                "{:.2f}".format(s.get('low', 0))), tags=(tag,))
            if n_hist > 0:
                hit += 1
                hot_candidates.append({
                    'name': s.get('name', ''), 'code': code,
                    'pct': s.get('change_pct', 0),
                    'hist': n_hist,
                })
        self._radar_sum_vars['hot_codes'].set("{} 只".format(hit))

        hot_candidates.sort(key=lambda x: (-x['hist'], -x['pct']))
        for i in self._hot_tree.get_children():
            self._hot_tree.delete(i)
        for rank, st in enumerate(hot_candidates[:20], 1):
            tag = 'lu' if st['pct'] >= 9.7 else ''
            self._hot_tree.insert('', 'end', values=(
                rank, st['name'], st['code'],
                "+{:.1f}%".format(st['pct']),
                "{}次".format(st['hist'])), tags=(tag,) if tag else ())

    def _radar_on_row_focus(self):
        sel = self._radar_tree.selection()
        if not sel: return
        v = self._radar_tree.item(sel[0])['values']
        if len(v) >= 2:
            name = str(v[0]).replace(" 📊", "").replace("📊", "").strip()
            self.app.notify_stock_focus(str(v[1]), name)

    def _radar_show_popup_selected(self):
        sel = self._radar_tree.selection()
        if not sel: return
        v = self._radar_tree.item(sel[0])['values']
        if len(v) >= 2:
            name = str(v[0]).replace(" 📊", "").replace("📊", "").strip()
            self.app.show_stock_popup(str(v[1]), name)

    def _radar_show_ctx(self, e):
        try:
            self._radar_tree.identify_row(e.y)
            self._radar_ctx.tk_popup(e.x_root, e.y_root)
        finally:
            self._radar_ctx.grab_release()

    def _radar_analyze_selected(self):
        sel = self._radar_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要分析的股票"); return
        try:
            single = self.app.tabs.get('SingleTab')
            if not single: return
            v = self._radar_tree.item(sel[0])['values']
            name = str(v[0]).replace(" 📊", "").replace("📊", "").strip()
            code = str(v[1])
            for i in range(self.app.nb.index('end')):
                txt = self.app.nb.tab(i, 'text') or ""
                if '单股' in txt or 'Single' in txt.lower():
                    self.app.nb.select(i); break
            if hasattr(single, 'name_var'): single.name_var.set(name)
            if hasattr(single, 'code_var'): single.code_var.set(code)
            if hasattr(single, 'trigger_search'): single.trigger_search()
        except Exception:
            pass

    def _radar_add_to_fav(self):
        sel = self._radar_tree.selection()
        added = 0
        for it in sel:
            v = self._radar_tree.item(it)['values']
            if len(v) < 2: continue
            name = str(v[0]).replace(" 📊", "").replace("📊", "").strip()
            code = str(v[1])
            if cfg_mod.add_favorite(name, code, tag="涨停雷达"):
                added += 1
        if added:
            bus.emit(Events.FAVORITES_UPDATED)
        messagebox.showinfo("完成", "已添加 {} 只到自选股".format(added))

    def _hot_on_row_focus(self):
        sel = self._hot_tree.selection()
        if not sel: return
        v = self._hot_tree.item(sel[0])['values']
        if len(v) >= 3:
            self.app.notify_stock_focus(str(v[2]), str(v[1]))

    def _hot_open_popup(self):
        sel = self._hot_tree.selection()
        if not sel: return
        v = self._hot_tree.item(sel[0])['values']
        if len(v) >= 3:
            self.app.show_stock_popup(str(v[2]), str(v[1]))

    # ─── 龙头梯队左键 / 右键 ───
    def _ladder_left_click_follow(self, event):
        # v9.9.6：浮窗永远跟随主程序，无需 is_follow_mode 判断
        import re
        try:
            idx = self._ladder_text.index("@{},{}".format(event.x, event.y))
            ln = idx.split('.')[0]
            line_text = self._ladder_text.get(
                "{}.0".format(ln), "{}.end".format(ln))
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

    def _ladder_show_ctx(self, event):
        try:
            self._ladder_click_idx = self._ladder_text.index(
                "@{},{}".format(event.x, event.y))
        except Exception:
            self._ladder_click_idx = None
        try:
            self._ladder_ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ladder_ctx.grab_release()

    def _ladder_show_stock_popup(self):
        import re
        idx = getattr(self, '_ladder_click_idx', None) or self._ladder_text.index('insert')
        try:
            ln = idx.split('.')[0]
            search_text = self._ladder_text.get(
                "{}.0".format(ln), "{}.end".format(ln))
        except Exception:
            search_text = ""
        m = re.search(r'[（(](\d{6})[)）]', search_text) or \
            re.search(r'(?<![.\d])(\d{6})(?![.\d])', search_text)
        if not m:
            messagebox.showinfo("提示", "未识别到股票代码"); return
        code = m.group(1)
        before = search_text[:m.start()]
        mname = re.search(r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*$',
                          before.rstrip())
        name = mname.group(1) if mname else ""
        self.app.show_stock_popup(code, name)

    def _analyze_leaders(self):
        if not self._cur_sector or not self._cur_stocks:
            messagebox.showinfo("提示", "请先选择一个板块"); return
        ladder = sector_core.identify_ladder(self._cur_stocks)
        leaders = ladder.get('leaders', [])[:3]
        if not leaders:
            messagebox.showinfo("提示", "本板块无明显龙头"); return
        single = self.app.tabs.get('SingleTab')
        if not single: return
        for i in range(self.app.nb.index('end')):
            txt = self.app.nb.tab(i, 'text') or ""
            if '单股' in txt or 'Single' in txt.lower():
                self.app.nb.select(i); break
        if hasattr(single, 'name_var'):
            single.name_var.set(leaders[0].get('name', ''))
        if hasattr(single, 'code_var'):
            single.code_var.set(leaders[0].get('code', ''))
        if hasattr(single, 'trigger_search'):
            single.trigger_search()

    @staticmethod
    def _safe_int(s, dft):
        try: return int(s)
        except: return dft

    @staticmethod
    def _safe_float(s, dft):
        try: return float(s)
        except: return dft


def _now():
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")
