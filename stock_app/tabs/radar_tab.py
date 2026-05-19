"""
涨停雷达 Tab
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry
from ..core import api_client, config as cfg_mod
from ..bus import bus, Events, state


class RadarTab(BaseTab):
    title = "涨停雷达"

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=16, pady=12)

        hr = tk.Frame(body, bg=C['bg']); hr.pack(fill='x', pady=(0, 6))
        tk.Label(hr, text="📡 涨停雷达", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(side='left')
        tk.Label(hr, text="  东方财富  ·  分页拉取全部涨停",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim']).pack(side='left')
        styled_btn(hr, "🔄 刷新", C['accent'], self._refresh).pack(side='right', padx=(6, 0))
        styled_btn(hr, "🚀 全部分析", C['green'], self._analyze_all).pack(side='right')

        # 过滤条件行
        fr = tk.Frame(body, bg=C['bg']); fr.pack(fill='x', pady=(0, 6))
        tk.Label(fr, text="最低涨幅(%)", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._min_pct = tk.StringVar(value="9.5")
        styled_entry(fr, self._min_pct, 6).pack(side='left', ipady=3, padx=(0, 16))
        tk.Label(fr, text="最多页数(每页100条)", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._max_pages = tk.StringVar(value="5")
        styled_entry(fr, self._max_pages, 4).pack(side='left', ipady=3)
        tk.Label(fr, text="  最多可抓取 500 只", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(8, 0))

        self.status = tk.StringVar(value="未刷新")
        tk.Label(body, textvariable=self.status,
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['yellow']).pack(anchor='w', pady=(0, 6))

        cols = ('name', 'code', 'price', 'pct', 'high', 'low')
        # 加载持久化列宽
        from ..widgets import load_col_widths, save_col_widths
        col_widths = load_col_widths('radar')
        defaults = {'name':120,'code':90,'price':90,'pct':90,'high':90,'low':90}
        self.tree = ttk.Treeview(body, columns=cols, show='headings', height=20)
        for col, txt, w in [('name','名称',120),('code','代码',90),
                              ('price','现价',90),('pct','涨幅%',90),
                              ('high','最高',90),('low','最低',90)]:
            self.tree.heading(col, text=txt)
            self.tree.column(col,
                              width=col_widths.get(col, defaults[col]),
                              minwidth=40,
                              anchor='center', stretch=True)
        self.tree.pack(fill='both', expand=True, pady=(0, 8))
        self.tree.bind('<Double-1>', lambda e: self._analyze_selected())
        # 🆕 v9.6：左键选中行 → 顺带通知浮窗（联动模式开启时刷新）
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._on_row_focus())

        # 列宽保存
        def _save_widths(*_):
            widths = {c: self.tree.column(c, 'width') for c in cols}
            save_col_widths('radar', widths)
        self.tree.bind('<ButtonRelease-1>', _save_widths)

        # 右键菜单
        ctx = tk.Menu(self.tree, tearoff=0,
                       bg=C['panel'], fg=C['text'],
                       activebackground=C['acc_dark'],
                       activeforeground='white',
                       font=('微软雅黑', 9))
        ctx.add_command(label="🔎  查看股票详情",   command=self._show_popup_selected)
        ctx.add_separator()
        ctx.add_command(label="🔍  分析选中股票",   command=self._analyze_selected)
        ctx.add_command(label="⭐  加入自选股",     command=self._add_to_fav)
        ctx.add_separator()
        ctx.add_command(label="📋  复制代码",
                          command=lambda: self._copy_field(1))
        ctx.add_command(label="📋  复制 名称+代码",
                          command=lambda: self._copy_field('name_code'))
        self._ctx = ctx
        def _show_ctx(event):
            iid = self.tree.identify_row(event.y)
            if iid:
                if iid not in self.tree.selection():
                    self.tree.selection_set(iid)
                try:
                    ctx.tk_popup(event.x_root, event.y_root)
                finally:
                    ctx.grab_release()
        self.tree.bind('<Button-3>', _show_ctx)
        self.tree.bind('<Button-2>', _show_ctx)

        br = tk.Frame(body, bg=C['bg']); br.pack(fill='x')
        styled_btn(br, "🔍 分析选中", C['accent'], self._analyze_selected).pack(side='left', padx=(0, 6))
        styled_btn(br, "⭐ 加入自选", C['yellow'], self._add_to_fav).pack(side='left')
        tk.Label(br, text="  💡 双击=分析  右键=更多",
                 font=('微软雅黑', 8), bg=C['bg'], fg=C['dim']).pack(side='left', padx=12)

    def _copy_field(self, field):
        sel = self.tree.selection()
        if not sel: return
        v = self.tree.item(sel[0])['values']
        if field == 'name_code':
            s = "{} {}".format(v[0], v[1])
        else:
            s = str(v[field])
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(s)

    def _refresh(self):
        # 🌟 需求4：如果已有数据，刷新前需二次确认
        if self.tree.get_children():
            if not messagebox.askyesno("确认刷新", "当前有雷达数据，重新拉取将覆盖，是否继续？"):
                return
                
        self.status.set("正在拉取数据...")
        for i in self.tree.get_children():
            self.tree.delete(i)

        try:
            min_pct   = float(self._min_pct.get())
            max_pages = int(self._max_pages.get())
        except Exception:
            min_pct, max_pages = 9.5, 5

        def _do():
            data = api_client.fetch_limit_up_stocks(min_pct=min_pct, max_pages=max_pages)
            if isinstance(data, dict) and 'error' in data:
                state.ui_queue.put(lambda: self.status.set(
                    "❌ 拉取失败: {}".format(data['error'])))
                return
            def _update():
                # 🆕 v9.6：取一次代码→历史条数索引
                from ..core import history as hist_mod
                hidx = hist_mod.get_code_count_index()
                self.status.set("共找到 {} 只涨幅≥{:.1f}%的股票".format(len(data), min_pct))
                for s in data:
                    mark = " 📊" if hidx.get(str(s['code']).zfill(6), 0) > 0 else ""
                    self.tree.insert('', 'end', values=(
                        s['name'] + mark, s['code'],
                        "{:.2f}".format(s['price']),
                        "+{:.2f}%".format(s['change_pct']),
                        "{:.2f}".format(s['high']),
                        "{:.2f}".format(s['low'])))
            state.ui_queue.put(_update)

        threading.Thread(target=_do, daemon=True).start()

    def _analyze_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要分析的股票")
            return
        stocks = []
        for item in sel:
            v = self.tree.item(item)['values']
            if len(v) >= 2:
                stocks.append((str(v[0]), str(v[1])))
        bus.emit(Events.REQUEST_BATCH_RUN, stocks, "涨停雷达")

    def _analyze_all(self):
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("提示", "请先刷新数据")
            return
        if not messagebox.askyesno("确认", "将分析雷达全部 {} 只股票？".format(len(items))):
            return
        stocks = []
        for item in items:
            v = self.tree.item(item)['values']
            stocks.append((str(v[0]), str(v[1])))
        bus.emit(Events.REQUEST_BATCH_RUN, stocks, "涨停雷达")

    def _add_to_fav(self):
        sel = self.tree.selection()
        added = 0
        for item in sel:
            v = self.tree.item(item)['values']
            if cfg_mod.add_favorite(str(v[0]), str(v[1]), tag="涨停雷达"):
                added += 1
        if added:
            bus.emit(Events.FAVORITES_UPDATED)
        messagebox.showinfo("完成", "已添加 {} 只到自选股".format(added))

    def _show_popup_selected(self):
        """🆕 v9.5：在浮窗打开股票详情"""
        sel = self.tree.selection()
        if not sel: return
        v = self.tree.item(sel[0])['values']
        if len(v) >= 2:
            # 列序：(name, code, ...)；name 列可能带 " 📊"，剥离
            name = str(v[0]).replace(" 📊", "").replace("📊", "").strip()
            self.app.show_stock_popup(str(v[1]), name)

    def _on_row_focus(self):
        """🆕 v9.6：左键选中 → 通知浮窗（联动模式开启时刷新；关闭时无副作用）"""
        sel = self.tree.selection()
        if not sel: return
        v = self.tree.item(sel[0])['values']
        if len(v) >= 2:
            name = str(v[0]).replace(" 📊", "").replace("📊", "").strip()
            self.app.notify_stock_focus(str(v[1]), name)
