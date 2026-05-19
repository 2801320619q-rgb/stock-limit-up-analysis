"""
🎯 复盘中心 Tab
- 📋 复盘日报：当日盘面汇总
- 📁 个股档案：选股查档
- 🔥 热点演化：概念时间线
- 🔍 相似日匹配：找类似行情
- 🌐 次日表现追踪：批量抓取昨日记录的次日表现
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry
from ..core import replay, history as hist_mod, config as cfg_mod
from ..bus import bus, Events, state


class ReplayTab(BaseTab):
    title = "复盘中心"

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=10)

        # 顶部标题
        hr = tk.Frame(body, bg=C['bg']); hr.pack(fill='x', pady=(0, 8))
        tk.Label(hr, text="🎯 复盘中心",
                 font=('微软雅黑', 13, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(side='left')
        tk.Label(hr, text="  ·  复盘工具的灵魂：让历史数据为决策服务",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim']).pack(side='left')

        # 嵌套 Notebook
        sub_style = ttk.Style()
        sub_nb = ttk.Notebook(body, style='App.TNotebook')
        sub_nb.pack(fill='both', expand=True)

        # 4 个子 Tab
        f_daily   = tk.Frame(sub_nb, bg=C['bg'])
        f_profile = tk.Frame(sub_nb, bg=C['bg'])
        f_trend   = tk.Frame(sub_nb, bg=C['bg'])
        f_similar = tk.Frame(sub_nb, bg=C['bg'])
        f_track   = tk.Frame(sub_nb, bg=C['bg'])

        sub_nb.add(f_daily,   text="  📋 复盘日报  ")
        sub_nb.add(f_profile, text="  📁 个股档案  ")
        sub_nb.add(f_trend,   text="  🔥 热点演化  ")
        sub_nb.add(f_similar, text="  🔍 相似日匹配  ")
        sub_nb.add(f_track,   text="  🌐 次日追踪  ")

        self._build_daily(f_daily)
        self._build_profile(f_profile)
        self._build_trend(f_trend)
        self._build_similar(f_similar)
        self._build_track(f_track)

    # ════════════════════════════════════════════════
    # 子Tab 1: 复盘日报
    # ════════════════════════════════════════════════
    def _build_daily(self, parent):
        C = self.C
        # 顶部控制
        ctrl = tk.Frame(parent, bg=C['bg']); ctrl.pack(fill='x', pady=(8, 6))
        tk.Label(ctrl, text="日期", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._daily_date = tk.StringVar()
        self._daily_combo = ttk.Combobox(ctrl, textvariable=self._daily_date,
                                          state='readonly', width=14,
                                          font=('微软雅黑', 9))
        self._daily_combo.pack(side='left', padx=(0, 8))
        self._daily_combo.bind('<<ComboboxSelected>>',
                                lambda e: self._generate_daily_report())
        styled_btn(ctrl, "📋 生成日报", C['accent'],
                   self._generate_daily_report).pack(side='left', padx=(4, 0))
        styled_btn(ctrl, "🔄 刷新日期", C['idle'],
                   self._refresh_daily_dates).pack(side='right')

        # 报告显示区
        self._daily_text = tk.Text(parent, font=('微软雅黑', 10), wrap='word',
                                    bg=C['card'], fg=C['text'],
                                    relief='flat', padx=14, pady=10,
                                    state='disabled', cursor='arrow')
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=self._daily_text.yview)
        self._daily_text.configure(yscrollcommand=vsb.set)
        self._daily_text.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        # tag 配色
        for tag, color in [
            ('h1',      C['accent']),  ('h2', C['yellow']),
            ('star',    C['star']),    ('green', C['green']),
            ('red',     C['red']),     ('dim', C['dim']),
            ('hot',     C['red']),     ('cool', C['purple']),
        ]:
            self._daily_text.tag_config(tag, foreground=color)
        self._daily_text.tag_config('bold', font=('微软雅黑', 10, 'bold'))
        self._daily_text.tag_config('h1bold',
            font=('微软雅黑', 12, 'bold'), foreground=C['accent'])

        # 🆕 v9.5：复盘日报右键 → 看光标附近股票详情
        self._daily_text.bind('<Button-3>', self._daily_show_ctx)
        self._daily_text.bind('<Button-2>', self._daily_show_ctx)
        # 🆕 v9.6：左键联动 — 单击文字时识别附近股票并通知浮窗（不阻止默认行为）
        self._daily_text.bind('<Button-1>', self._daily_left_click_follow, add='+')
        self._daily_ctx = tk.Menu(self._daily_text, tearoff=0,
            bg=C['panel'], fg=C['text'],
            activebackground=C['acc_dark'], activeforeground='white',
            font=('微软雅黑', 9))
        self._daily_ctx.add_command(label="🔎  查看此股详情",
            command=self._daily_show_stock_popup)

        self._refresh_daily_dates()

    def _daily_show_ctx(self, event):
        try:
            self._daily_click_idx = self._daily_text.index(
                "@{},{}".format(event.x, event.y))
        except Exception:
            self._daily_click_idx = None
        try:
            self._daily_ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._daily_ctx.grab_release()

    def _daily_show_stock_popup(self):
        import re
        idx = getattr(self, '_daily_click_idx', None) or self._daily_text.index('insert')
        try:
            search_text = self._daily_text.get('sel.first', 'sel.last')
        except tk.TclError:
            search_text = ""
        if not search_text:
            try:
                ln = idx.split('.')[0]
                search_text = self._daily_text.get("{}.0".format(ln), "{}.end".format(ln))
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

    def _daily_left_click_follow(self, event):
        """v9.9.6：左键单击 → 通知浮窗刷新（浮窗永远跟随，不再需要开关判断）"""
        import re
        try:
            idx = self._daily_text.index("@{},{}".format(event.x, event.y))
            ln  = idx.split('.')[0]
            line_text = self._daily_text.get("{}.0".format(ln), "{}.end".format(ln))
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

    def _refresh_daily_dates(self):
        dates = hist_mod.list_history_dates()
        display = [d[:4]+'-'+d[4:6]+'-'+d[6:] for d in dates]
        self._daily_combo['values'] = display
        if dates and not self._daily_date.get():
            self._daily_combo.current(0)
            self._generate_daily_report()

    def _generate_daily_report(self):
        d = self._daily_date.get().replace('-', '')
        if not d:
            return
        self._daily_text.config(state='normal')
        self._daily_text.delete('1.0', 'end')

        report = replay.generate_daily_report(d)
        if not report:
            self._daily_text.insert('end', "该日无历史记录")
            self._daily_text.config(state='disabled')
            return

        T = self._daily_text
        def w(text, tag=None):
            if tag: T.insert('end', text, tag)
            else:   T.insert('end', text)

        # ── 标题 ──
        w("📋 复盘日报  ·  {}\n".format(report['date_display']), 'h1bold')
        w("━" * 50 + "\n\n", 'dim')

        # ── 基础数据 ──
        w("📊  当日分析数据\n", 'h2')
        w("─" * 50 + "\n", 'dim')
        w("  · 总分析数：{}  ·  ✅ 成功 {}  ·  ❌ 失败 {}\n".format(
            report['total'], report['ok'], report['fail']))
        w("  · ⭐ 加星：{} 只\n\n".format(report['stars']))

        # ── 主线分析 ──
        if report['top_concepts']:
            w("🎯  强势主线（按提及次数）\n", 'h2')
            w("─" * 50 + "\n", 'dim')
            for i, (concept, cnt) in enumerate(report['top_concepts'][:10], 1):
                tag = 'hot' if i <= 3 else ('cool' if i <= 6 else 'dim')
                w("  {:>2}.  {:<14s}".format(i, concept), tag)
                w("  {:>3} 次提及\n".format(cnt), 'dim')
            w("\n")

        # ── 联动热度 ──
        if report['top_linked']:
            w("🔗  联动热点股票（被提及最多）\n", 'h2')
            w("─" * 50 + "\n", 'dim')
            # 🛡️ v9.4：先本地反查，缺失的批量调东财兜底拉名字
            from ..core import api_client
            codes = [str(c).zfill(6) for c, _ in report['top_linked'][:10]]
            name_lookup = api_client.fetch_stock_names(codes)
            for i, (code, cnt) in enumerate(report['top_linked'][:10], 1):
                code_str = str(code).zfill(6)
                name = name_lookup.get(code_str, "")
                if name:
                    w("  {:>2}.  ".format(i), 'dim')
                    w("{}".format(name), 'h2')
                    w(" ({})".format(code_str), 'dim')
                else:
                    w("  {:>2}.  {}".format(i, code_str), 'dim')
                w("    被提及 {} 次\n".format(cnt), 'dim')
            w("\n")

        # ── 明星股 ──
        if report['star_records']:
            w("⭐  今日加星股票\n", 'h2')
            w("─" * 50 + "\n", 'dim')
            for r in report['star_records']:
                w("  ⭐ {} ({})".format(r['name'], r['code']), 'star')
                if r.get('note'):
                    w("  ·  📝 {}".format(r['note']), 'dim')
                w("\n")
            w("\n")

        # ── 次日表现 ──
        nd = report.get('next_day_summary')
        if nd:
            w("📈  次日表现复盘\n", 'h2')
            w("─" * 50 + "\n", 'dim')
            rate_tag = 'green' if nd['win_rate'] >= 0.5 else 'red'
            w("  · 已追踪：{} 只  ·  胜率 ".format(nd['count']))
            w("{:.0%}".format(nd['win_rate']), rate_tag)
            w("  ·  平均 ")
            avg_tag = 'green' if nd['avg_pct'] > 0 else 'red'
            w("{:+.2f}%\n\n".format(nd['avg_pct']), avg_tag)

            w("  🏆 次日最强（前5）\n", 'green')
            for x in nd['best']:
                w("    · {:<8s}({})".format(x['name'], x['code']))
                w("  {:+.2f}%\n".format(x['pct']), 'green')
            w("\n  📉 次日最弱（前5）\n", 'red')
            for x in nd['worst']:
                w("    · {:<8s}({})".format(x['name'], x['code']))
                w("  {:+.2f}%\n".format(x['pct']), 'red')
            w("\n")
        else:
            w("📈  次日表现复盘\n", 'h2')
            w("─" * 50 + "\n", 'dim')
            w("  · 暂无次日表现数据\n", 'dim')
            w("  · 切到「🌐 次日追踪」Tab 抓取这一天的次日行情\n\n", 'dim')

        w("━" * 50 + "\n", 'dim')
        w("提示：复盘日报基于本地历史数据，不调用任何 AI 接口，秒速生成\n", 'dim')

        T.config(state='disabled')
        # 🆕 v9.9.6：日报里所有 6 位代码渲染成蓝字下划线 → 点击推送同花顺
        try:
            from ..widgets import attach_code_links
            attach_code_links(T, self.app, scope='main')
        except Exception:
            import traceback; traceback.print_exc()

    # ════════════════════════════════════════════════
    # 子Tab 2: 个股档案
    # ════════════════════════════════════════════════
    def _build_profile(self, parent):
        C = self.C
        ctrl = tk.Frame(parent, bg=C['bg']); ctrl.pack(fill='x', pady=(8, 6))
        tk.Label(ctrl, text="股票代码", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._prof_code_var = tk.StringVar()
        e = styled_entry(ctrl, self._prof_code_var, 12)
        e.pack(side='left', ipady=3)
        e.bind('<Return>', lambda ev: self._show_profile())
        styled_btn(ctrl, "🔍 查询档案", C['accent'],
                   self._show_profile).pack(side='left', padx=4)

        tk.Label(ctrl, text="  💡 输入6位代码（如600519）",
                 font=('微软雅黑', 8), bg=C['bg'], fg=C['dim']).pack(side='left', padx=8)

        self._prof_text = tk.Text(parent, font=('微软雅黑', 10), wrap='word',
                                   bg=C['card'], fg=C['text'],
                                   relief='flat', padx=14, pady=10,
                                   state='disabled', cursor='arrow')
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=self._prof_text.yview)
        self._prof_text.configure(yscrollcommand=vsb.set)
        self._prof_text.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        for tag, color in [
            ('h1', C['accent']), ('h2', C['yellow']),
            ('green', C['green']), ('red', C['red']),
            ('dim', C['dim']), ('star', C['star']),
        ]:
            self._prof_text.tag_config(tag, foreground=color)
        self._prof_text.tag_config('bold', font=('微软雅黑', 10, 'bold'))
        self._prof_text.tag_config('h1bold',
            font=('微软雅黑', 13, 'bold'), foreground=C['accent'])

    def _show_profile(self):
        code = self._prof_code_var.get().strip()
        if not code:
            messagebox.showinfo("提示", "请输入股票代码")
            return
        import re
        code = re.sub(r'\D', '', code).zfill(6)[:6]

        T = self._prof_text
        T.config(state='normal')
        T.delete('1.0', 'end')
        T.insert('end', "📁 查询中...请稍候\n")
        T.config(state='disabled')

        def _do():
            profile = replay.build_stock_profile(code)
            def _render():
                T.config(state='normal')
                T.delete('1.0', 'end')

                def w(text, tag=None):
                    if tag: T.insert('end', text, tag)
                    else:   T.insert('end', text)

                # 标题
                name = profile.get("name", "") or "未知"
                w("📁  {}（{}）档案\n".format(name, code), 'h1bold')
                w("━" * 50 + "\n", 'dim')

                if profile["total_analyses"] == 0:
                    w("\n  本地历史中未找到该股票的分析记录\n", 'dim')
                    w("  请先在「单股搜索」或「批量分析」中分析该股票\n", 'dim')
                    T.config(state='disabled')
                    return

                # 实时行情
                from ..core import api_client
                try:
                    realtime = api_client.fetch_change_pct([code])
                    if realtime and code in realtime:
                        info = realtime[code]
                        w("\n📊 当前行情\n", 'h2')
                        w("─" * 50 + "\n", 'dim')
                        chg = info["change_pct"]
                        chg_tag = 'green' if chg > 0 else ('red' if chg < 0 else 'dim')
                        arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
                        w("  价格: {}".format(info["price"]))
                        w("    {} {:+.2f}%\n".format(arrow, chg), chg_tag)
                        w("  时间: {}\n".format(info["time"]), 'dim')
                except Exception:
                    pass

                # 历次分析
                w("\n📅 历次分析 ({} 次)\n".format(profile["total_analyses"]), 'h2')
                w("─" * 50 + "\n", 'dim')
                for r in profile["records"]:
                    d = r["date"]
                    date_str = "{}-{}-{}".format(d[:4], d[4:6], d[6:])
                    star = "⭐" if r.get("starred") else "  "
                    ok   = "✅" if r.get("success") else "❌"
                    w("  {}  {} {}  {} {}".format(
                        star, ok, date_str, r.get("time", ""),
                        replay.extract_main_logic(r.get("content", ""))[:50]
                    ), None)
                    # 次日表现
                    nd = r.get("next_day")
                    if nd and nd.get("change_pct") is not None:
                        pct = nd["change_pct"]
                        pct_tag = 'green' if pct > 0 else 'red'
                        w("\n      → 次日 ", 'dim')
                        w("{:+.2f}%".format(pct), pct_tag)
                        w("\n")
                    else:
                        w("\n")
                    if r.get("note"):
                        w("      📝 {}\n".format(r["note"]), 'star')
                w("\n")

                # 次日胜率统计
                stats = profile["next_day_stats"]
                if stats["count"] > 0:
                    w("🎯 历次涨停后次日表现\n", 'h2')
                    w("─" * 50 + "\n", 'dim')
                    win_tag = 'green' if stats["win_rate"] >= 0.5 else 'red'
                    w("  胜率: ")
                    w("{:.0%} ".format(stats["win_rate"]), win_tag)
                    w("({} 胜 / {} 总)".format(stats["win"], stats["count"]))
                    avg_tag = 'green' if stats["avg_pct"] > 0 else 'red'
                    w("    平均涨幅: ")
                    w("{:+.2f}%\n\n".format(stats["avg_pct"]), avg_tag)

                # 反复出现的逻辑
                if profile["logic_counter"]:
                    w("🔁 反复出现的逻辑/概念\n", 'h2')
                    w("─" * 50 + "\n", 'dim')
                    for concept, cnt in profile["logic_counter"]:
                        w("  · {:<14s}".format(concept))
                        w("  出现 {} 次\n".format(cnt), 'dim')
                    w("\n")

                # 经常联动
                if profile["linked_stocks"]:
                    w("🔗 经常联动的股票\n", 'h2')
                    w("─" * 50 + "\n", 'dim')
                    for code2, cnt in profile["linked_stocks"]:
                        w("  · {}  ".format(code2))
                        w("  共同出现 {} 次\n".format(cnt), 'dim')

                T.config(state='disabled')
                # 🆕 v9.9.6：档案里所有 6 位代码渲染成蓝字下划线 → 推送同花顺
                try:
                    from ..widgets import attach_code_links
                    attach_code_links(T, self.app, main_code=code, scope='main')
                except Exception:
                    import traceback; traceback.print_exc()
            state.ui_queue.put(_render)

        threading.Thread(target=_do, daemon=True).start()

    # ════════════════════════════════════════════════
    # 子Tab 3: 热点演化时间线
    # ════════════════════════════════════════════════
    def _build_trend(self, parent):
        C = self.C
        ctrl = tk.Frame(parent, bg=C['bg']); ctrl.pack(fill='x', pady=(8, 6))
        tk.Label(ctrl, text="概念关键词", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._trend_kw = tk.StringVar(value="算电协同")
        e = styled_entry(ctrl, self._trend_kw, 18)
        e.pack(side='left', ipady=3)
        e.bind('<Return>', lambda ev: self._show_trend())
        styled_btn(ctrl, "📈 生成时间线", C['accent'],
                   self._show_trend).pack(side='left', padx=4)
        tk.Label(ctrl, text="  💡 如：算电协同、AI算力、玻璃基板",
                 font=('微软雅黑', 8), bg=C['bg'], fg=C['dim']).pack(side='left', padx=8)

        # 时间线显示
        self._trend_text = tk.Text(parent, font=('微软雅黑', 10), wrap='word',
                                    bg=C['card'], fg=C['text'],
                                    relief='flat', padx=14, pady=10,
                                    state='disabled', cursor='arrow')
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=self._trend_text.yview)
        self._trend_text.configure(yscrollcommand=vsb.set)
        self._trend_text.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        for tag, color in [
            ('h1', C['accent']), ('h2', C['yellow']),
            ('stage_hot', C['red']), ('stage_cool', C['purple']),
            ('stage_mid', C['yellow']), ('stage_dim', C['dim']),
            ('dim', C['dim']),
        ]:
            self._trend_text.tag_config(tag, foreground=color)
        self._trend_text.tag_config('h1bold',
            font=('微软雅黑', 13, 'bold'), foreground=C['accent'])

    def _show_trend(self):
        kw = self._trend_kw.get().strip()
        if not kw:
            return
        T = self._trend_text
        T.config(state='normal')
        T.delete('1.0', 'end')

        def w(text, tag=None):
            if tag: T.insert('end', text, tag)
            else:   T.insert('end', text)

        timeline = replay.build_concept_timeline(kw, days=180)
        w("🔥  「{}」演化时间线\n".format(kw), 'h1bold')
        w("━" * 50 + "\n\n", 'dim')

        if not timeline:
            w("  本地历史记录中未找到该关键词\n", 'dim')
            T.config(state='disabled')
            return

        # 阶段统计
        max_count = max(x["mention_count"] for x in timeline)
        w("📊  共找到 {} 个交易日提及，峰值 {} 只/天\n\n".format(
            len(timeline), max_count), 'h2')

        # 时间线
        for i, node in enumerate(timeline):
            stage = node["stage"]
            # 颜色判定
            if "爆发" in stage or "高潮" in stage:
                stage_tag = 'stage_hot'
            elif "加速" in stage or "延续" in stage:
                stage_tag = 'stage_mid'
            elif "退潮" in stage or "衰退" in stage:
                stage_tag = 'stage_dim'
            else:
                stage_tag = 'stage_cool'

            # 柱状图（用 ▇ 表示热度）
            bar_len = int(node["mention_count"] / max_count * 30)
            bar = "▇" * bar_len

            w("  {}  ".format(node["date_display"]))
            w(stage + "  ", stage_tag)
            w(bar, 'h2')
            w("  {} 只\n".format(node["mention_count"]))

            # 列出当日股票（前5只）
            stocks_str = "、".join(
                "{}({})".format(s['name'], s['code'])
                for s in node["stocks"][:5])
            if len(node["stocks"]) > 5:
                stocks_str += "  +{}".format(len(node["stocks"]) - 5)
            w("      {}\n".format(stocks_str), 'dim')
            w("\n")

        # 判断当前阶段
        if timeline:
            cur_stage = timeline[-1]["stage"]
            w("━" * 50 + "\n", 'dim')
            w("📍 当前阶段判断：", 'h2')
            w(cur_stage + "\n", 'stage_hot' if "高潮" in cur_stage else 'stage_mid')

        T.config(state='disabled')
        # 🆕 v9.9.6：时间线里的股票代码加蓝字下划线 → 推送同花顺
        try:
            from ..widgets import attach_code_links
            attach_code_links(T, self.app, scope='main')
        except Exception:
            import traceback; traceback.print_exc()

    # ════════════════════════════════════════════════
    # 子Tab 4: 相似日匹配
    # ════════════════════════════════════════════════
    def _build_similar(self, parent):
        C = self.C
        ctrl = tk.Frame(parent, bg=C['bg']); ctrl.pack(fill='x', pady=(8, 6))
        tk.Label(ctrl, text="比较日期", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._sim_date = tk.StringVar()
        self._sim_combo = ttk.Combobox(ctrl, textvariable=self._sim_date,
                                         state='readonly', width=14,
                                         font=('微软雅黑', 9))
        self._sim_combo.pack(side='left', padx=(0, 8))
        styled_btn(ctrl, "🔍 查找相似日", C['accent'],
                   self._show_similar).pack(side='left', padx=4)
        styled_btn(ctrl, "🔄 刷新", C['idle'],
                   self._refresh_sim_dates).pack(side='right')

        self._sim_text = tk.Text(parent, font=('微软雅黑', 10), wrap='word',
                                  bg=C['card'], fg=C['text'],
                                  relief='flat', padx=14, pady=10,
                                  state='disabled', cursor='arrow')
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=self._sim_text.yview)
        self._sim_text.configure(yscrollcommand=vsb.set)
        self._sim_text.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        for tag, color in [
            ('h1', C['accent']), ('h2', C['yellow']),
            ('high', C['red']), ('mid', C['yellow']),
            ('low', C['dim']), ('dim', C['dim']),
        ]:
            self._sim_text.tag_config(tag, foreground=color)
        self._sim_text.tag_config('h1bold',
            font=('微软雅黑', 13, 'bold'), foreground=C['accent'])

        self._refresh_sim_dates()

    def _refresh_sim_dates(self):
        dates = hist_mod.list_history_dates()
        display = [d[:4]+'-'+d[4:6]+'-'+d[6:] for d in dates]
        self._sim_combo['values'] = display
        if dates and not self._sim_date.get():
            self._sim_combo.current(0)

    def _show_similar(self):
        d = self._sim_date.get().replace('-', '')
        if not d:
            messagebox.showinfo("提示", "请选择日期")
            return
        T = self._sim_text
        T.config(state='normal')
        T.delete('1.0', 'end')

        def w(text, tag=None):
            if tag: T.insert('end', text, tag)
            else:   T.insert('end', text)

        results = replay.find_similar_days(d, top_n=10)
        w("🔍  与 {} 最相似的历史日\n".format(self._sim_date.get()), 'h1bold')
        w("━" * 50 + "\n\n", 'dim')

        if not results:
            w("  无其他历史日可比较\n", 'dim')
            T.config(state='disabled')
            return

        for i, r in enumerate(results, 1):
            sim = r["similarity"]
            sim_tag = 'high' if sim >= 60 else ('mid' if sim >= 30 else 'low')
            w("  {:>2}.  {}\n".format(i, r["date_display"]), 'h2')
            w("       相似度: ")
            w("{}%".format(sim), sim_tag)
            w("    规模: {} 只\n".format(r["total_count"]))
            w("       主线: " + " · ".join(r["main_concepts"]), 'dim')
            w("\n\n")

        T.config(state='disabled')

    # ════════════════════════════════════════════════
    # 子Tab 5: 次日表现追踪
    # ════════════════════════════════════════════════
    def _build_track(self, parent):
        C = self.C
        ctrl = tk.Frame(parent, bg=C['bg']); ctrl.pack(fill='x', pady=(8, 6))
        tk.Label(ctrl, text="目标日期", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self._track_date = tk.StringVar()
        self._track_combo = ttk.Combobox(ctrl, textvariable=self._track_date,
                                           state='readonly', width=14,
                                           font=('微软雅黑', 9))
        self._track_combo.pack(side='left', padx=(0, 8))
        styled_btn(ctrl, "🌐 抓取该日所有股票的当前行情", C['purple'],
                   self._track_next_day).pack(side='left', padx=4)
        styled_btn(ctrl, "🔄 刷新", C['idle'],
                   self._refresh_track_dates).pack(side='right')

        info = tk.Frame(parent, bg=C['bg']); info.pack(fill='x', pady=(0, 6))
        tk.Label(info,
                 text="💡 使用场景：\n"
                 "   · 昨天分析了一批股票，今天盘后点这个按钮，会自动抓取所有股票的「次日表现」并写回历史记录。\n"
                 "   · 用于验证 AI 分析的准确度，构建胜率统计。\n"
                 "   · 注意：抓取的是当前实时价格，所以应在【目标日期的下一个交易日盘后】调用。",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim'],
                 justify='left').pack(anchor='w', padx=8)

        self._track_text = tk.Text(parent, font=('Consolas', 9), wrap='word',
                                    bg=C['card'], fg=C['text'],
                                    relief='flat', padx=10, pady=8,
                                    state='disabled', cursor='arrow')
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=self._track_text.yview)
        self._track_text.configure(yscrollcommand=vsb.set)
        self._track_text.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        for tag, color in [
            ('h1', C['accent']), ('green', C['green']),
            ('red', C['red']), ('dim', C['dim']),
            ('yellow', C['yellow']),
        ]:
            self._track_text.tag_config(tag, foreground=color)

        self._refresh_track_dates()

    def _refresh_track_dates(self):
        dates = hist_mod.list_history_dates()
        display = [d[:4]+'-'+d[4:6]+'-'+d[6:] for d in dates]
        self._track_combo['values'] = display
        if dates and not self._track_date.get():
            self._track_combo.current(0)

    def _track_next_day(self):
        d = self._track_date.get().replace('-', '')
        if not d:
            messagebox.showinfo("提示", "请选择日期")
            return
        if not messagebox.askyesno("确认",
                "将抓取「{}」当日全部记录股票的当前实时价格，作为次日表现写回历史。\n\n"
                "确认继续？".format(self._track_date.get())):
            return

        T = self._track_text
        T.config(state='normal')
        T.delete('1.0', 'end')
        T.insert('end', "🌐 开始批量抓取行情...\n\n", 'h1')
        T.config(state='disabled')

        def _do():
            def on_progress(i, total, name):
                def _upd():
                    T.config(state='normal')
                    # 删除最后一行进度
                    txt = T.get('1.0', 'end-1c')
                    last_nl = txt.rfind("\n📊")
                    if last_nl != -1:
                        T.delete("1.0+{}c".format(last_nl), 'end')
                    T.insert('end', "\n📊 进度: {}/{}  {}".format(i, total, name), 'yellow')
                    T.see('end')
                    T.config(state='disabled')
                state.ui_queue.put(_upd)

            result = replay.batch_update_next_day(d, None, on_progress=on_progress)

            def _done():
                T.config(state='normal')
                T.insert('end', "\n\n" + "━"*50 + "\n", 'dim')
                T.insert('end', "✅ 抓取完成\n\n", 'green')
                T.insert('end', "  · 更新: {} 条\n".format(result['updated']), 'green')
                T.insert('end', "  · 跳过(已有数据): {} 条\n".format(result['skipped']), 'dim')
                T.insert('end', "  · 失败: {} 条\n".format(result['failed']), 'red')
                T.insert('end', "\n💡 切回「📋 复盘日报」可看到次日表现统计\n", 'dim')
                T.config(state='disabled')
                bus.emit(Events.HISTORY_UPDATED)
            state.ui_queue.put(_done)

        threading.Thread(target=_do, daemon=True).start()
