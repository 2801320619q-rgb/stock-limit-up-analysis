"""
设置 Tab
"""
import re, json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry
from ..core import config as cfg_mod, api_client, history as hist_mod
from ..core.paths import DIRS
from ..core.scheduler import Scheduler


class SettingsTab(BaseTab):
    title = "设置"

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=16, pady=12)

        tk.Label(body, text="⚙️ 应用设置", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(anchor='w', pady=(0, 12))

        s = cfg_mod.load_settings()

        # 主题
        tc = make_card(body, "🎨  界面主题", pady_top=0)
        tk.Label(tc, text="切换需重启程序生效",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(anchor='w')
        tr = tk.Frame(tc, bg=C['panel']); tr.pack(fill='x', pady=(6, 0))
        self.theme_var = tk.StringVar(value=s.get('theme', 'dark'))
        for val, lbl in [('dark', '🌙 暗色'), ('light', '☀️ 亮色')]:
            tk.Radiobutton(tr, text=lbl, variable=self.theme_var, value=val,
                           font=('微软雅黑', 9), bg=C['panel'], fg=C['text'],
                           selectcolor=C['card'], activebackground=C['panel'],
                           command=self._save).pack(side='left', padx=(0, 16))

        # 高亮
        hc = make_card(body, "✨  关键词高亮")
        self.hl_var = tk.BooleanVar(value=s.get('highlight', True))
        tk.Checkbutton(hc, text="启用关键词高亮（政策/概念/资金/百分比）",
                       variable=self.hl_var, font=('微软雅黑', 9),
                       bg=C['panel'], fg=C['text'], selectcolor=C['card'],
                       activebackground=C['panel'],
                       command=self._save).pack(anchor='w')

        # 定时任务
        sc = make_card(body, "⏰  定时任务")
        tk.Label(sc, text="每天定时自动拉取涨停板并保存为 JSON",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(anchor='w')
        sr = tk.Frame(sc, bg=C['panel']); sr.pack(fill='x', pady=(6, 0))
        tk.Label(sr, text="时间(HH:MM)", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['text']).pack(side='left', padx=(0, 4))
        self.sched_time = tk.StringVar(value="15:30")
        styled_entry(sr, self.sched_time, 8).pack(side='left', ipady=3, padx=(0, 8))
        styled_btn(sr, "启动", C['green'], self._sched_start).pack(side='left', padx=(0, 4))
        styled_btn(sr, "停止", C['red'], self._sched_stop).pack(side='left')
        self.sched_status = tk.StringVar(value="未启用")
        tk.Label(sc, textvariable=self.sched_status,
                 font=('微软雅黑', 9), bg=C['panel'], fg=C['yellow']).pack(anchor='w', pady=(6, 0))

        # 🆕 v9.9.0 同花顺双向联动设置
        hc2 = make_card(body, "📡  同花顺双向联动（仅 Windows）")
        tk.Label(hc2, text="v9.9.6 起：浮窗顶栏只有 📥 跟随同花顺 一个开关；"
                 "推送同花顺改由点蓝字下划线代码触发。",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(anchor='w')

        # 模式说明
        modes_box = tk.Frame(hc2, bg=C['card'])
        modes_box.pack(fill='x', pady=(6, 4))
        tk.Label(modes_box,
                 text="  📥 跟随同花顺：在同花顺切股 → 浮窗自动跟着切\n"
                      "  🔗 点蓝字代码：推送同花顺切到那只股（主程序点同时让浮窗跟随；浮窗内点浮窗不变）\n"
                      "  ⓘ 推送走 WriteProcessMemory + 0x490 自定义消息（不抢焦点）",
                 font=('微软雅黑', 8), bg=C['card'], fg=C['text'],
                 justify='left').pack(anchor='w', padx=8, pady=6)

        # 启用开关
        self.hexin_enabled = tk.BooleanVar(value=s.get('hexin_watcher_enabled', True))
        tk.Checkbutton(hc2, text="启用同花顺读监听后台线程（关闭则两个模式都失效，需重启浮窗）",
                       variable=self.hexin_enabled, font=('微软雅黑', 9),
                       bg=C['panel'], fg=C['text'], selectcolor=C['card'],
                       activebackground=C['panel'],
                       command=self._save).pack(anchor='w', pady=(6, 4))

        # 偏移量输入（仅用于内存法 fallback，标题法不需要）
        hr = tk.Frame(hc2, bg=C['panel']); hr.pack(fill='x', pady=2)
        tk.Label(hr, text="内存偏移(0x...):", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['text']).pack(side='left', padx=(0, 4))
        self.hexin_offset = tk.StringVar(value=s.get('hexin_offset', '0x1E9A5B0'))
        styled_entry(hr, self.hexin_offset, 16).pack(side='left', ipady=3, padx=(0, 8))
        tk.Label(hr, text="（仅 pymem 内存法用；窗口标题法不需要）",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(side='left')

        hr2 = tk.Frame(hc2, bg=C['panel']); hr2.pack(fill='x', pady=2)
        tk.Label(hr2, text="进程名:", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['text']).pack(side='left', padx=(0, 4))
        self.hexin_proc = tk.StringVar(value=s.get('hexin_process_name', 'hexin.exe'))
        styled_entry(hr2, self.hexin_proc, 16).pack(side='left', ipady=3, padx=(0, 8))
        tk.Label(hr2, text="编码:", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['text']).pack(side='left', padx=(8, 4))
        self.hexin_enc = tk.StringVar(value=s.get('hexin_encoding', 'gbk'))
        styled_entry(hr2, self.hexin_enc, 6).pack(side='left', ipady=3, padx=(0, 8))
        tk.Label(hr2, text="轮询(ms):", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['text']).pack(side='left', padx=(8, 4))
        self.hexin_poll = tk.StringVar(value=str(s.get('hexin_poll_ms', 30)))
        styled_entry(hr2, self.hexin_poll, 6).pack(side='left', ipady=3)

        # 保存 + 重启浮窗 + 诊断
        hb = tk.Frame(hc2, bg=C['panel']); hb.pack(fill='x', pady=(6, 0))
        styled_btn(hb, "💾 保存同花顺设置", C['accent'],
                   self._save_hexin).pack(side='left', padx=(0, 6))
        styled_btn(hb, "🔄 重启浮窗（让设置生效）", C['purple'],
                   self._restart_popup).pack(side='left', padx=(0, 6))
        # 🆕 v9.9.0
        styled_btn(hb, "🩺 诊断", C['yellow'],
                   self._diagnose_hexin).pack(side='left', padx=(0, 6))
        styled_btn(hb, "🧪 测试推送 (000001)", C['green'],
                   lambda: self._test_push("000001")).pack(side='left')

        # 快捷键
        kc = make_card(body, "⌨️  快捷键（全部可自定义）")

        tk.Label(kc,
                 text="输入 tkinter 格式：<Control-z> 表 Ctrl+Z、<F1>、<Alt-x>、<Control-Shift-S>、"
                      "<Control-Key-1>；空白将恢复默认；保存后立即生效，不必重启。",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim'],
                 justify='left', wraplength=720).pack(anchor='w', pady=(0, 6))

        # 🆕 v9.9.6.3：自动从 app._build_shortcut_spec() 生成全部快捷键编辑行
        self._sc_vars = {}   # key → (StringVar, default_seq)
        try:
            spec = self.app._build_shortcut_spec()
        except Exception:
            spec = []
        for key, default, _action, desc in spec:
            cur = s.get(key) or default
            var = tk.StringVar(value=cur)
            self._sc_vars[key] = (var, default)
            row = tk.Frame(kc, bg=C['panel'])
            row.pack(fill='x', pady=2)
            tk.Label(row, text="  " + desc, font=('微软雅黑', 9),
                     bg=C['panel'], fg=C['text'],
                     width=26, anchor='w').pack(side='left')
            styled_entry(row, var, 22).pack(side='left', ipady=3, padx=(0, 6))
            tk.Label(row, text="默认 " + default,
                     font=('微软雅黑', 8), bg=C['panel'],
                     fg=C['dim']).pack(side='left')

        btn_row = tk.Frame(kc, bg=C['panel'])
        btn_row.pack(fill='x', pady=(10, 2))
        styled_btn(btn_row, "💾 保存全部并立即生效", C['accent'],
                   self._save_shortcuts).pack(side='left', padx=(0, 6))
        styled_btn(btn_row, "🔄 全部重置默认", C['purple'],
                   self._reset_shortcuts).pack(side='left')

        # 其它说明：非键盘类的固定交互
        helps = [
            ("Double Click",  "列表项=分析"),
            ("Delete",        "删除选中项"),
        ]
        tk.Label(kc, text="  其它固定交互：",
                 font=('微软雅黑', 8), bg=C['panel'],
                 fg=C['dim']).pack(anchor='w', pady=(10, 2))
        for key, desc in helps:
            row = tk.Frame(kc, bg=C['panel'])
            row.pack(anchor='w', fill='x', pady=1)
            tk.Label(row, text="  " + key, font=('微软雅黑', 9, 'bold'),
                     bg=C['panel'], fg=C['accent'], width=16, anchor='w').pack(side='left')
            tk.Label(row, text="= " + desc, font=('微软雅黑', 9),
                     bg=C['panel'], fg=C['text'], anchor='w').pack(side='left')

        # 数据统计
        dc = make_card(body, "📂  数据管理")
        stock_count = len(cfg_mod.load_stock_dict())
        fav_count   = len(cfg_mod.load_favorites())
        hist_count  = sum(len(hist_mod.load_history(d)) for d in hist_mod.list_history_dates())

        # 🆕 v9.4：分行显示，关键数字加粗加亮
        for label, value, unit in [
            ("自选股",   fav_count,   "只"),
            ("股票字典", stock_count, "条"),
            ("历史记录", hist_count,  "条"),
        ]:
            row = tk.Frame(dc, bg=C['panel'])
            row.pack(anchor='w', fill='x', pady=1)
            tk.Label(row, text="  · " + label + ": ", font=('微软雅黑', 9),
                     bg=C['panel'], fg=C['dim']).pack(side='left')
            tk.Label(row, text=str(value), font=('微软雅黑', 11, 'bold'),
                     bg=C['panel'], fg=C['accent']).pack(side='left')
            tk.Label(row, text=" " + unit, font=('微软雅黑', 9),
                     bg=C['panel'], fg=C['dim']).pack(side='left')

        # 数据目录单独一行（路径用等宽字体便于复制阅读）
        dir_row = tk.Frame(dc, bg=C['panel']); dir_row.pack(anchor='w', fill='x', pady=(4,0))
        tk.Label(dir_row, text="  · 数据目录: ", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['dim']).pack(side='left')
        tk.Label(dir_row, text=str(DIRS["history"].parent.resolve()),
                 font=('微软雅黑', 9), bg=C['panel'], fg=C['text']).pack(side='left')

        self._scheduler = Scheduler()

    def _save(self):
        s = cfg_mod.load_settings()
        s['theme']     = self.theme_var.get()
        s['highlight'] = self.hl_var.get()
        cfg_mod.save_settings(s)

    def _save_shortcuts(self):
        """🆕 v9.9.6.3：保存所有可自定义快捷键并立即生效"""
        new_mapping = {}
        for key, (var, default) in self._sc_vars.items():
            val = var.get().strip()
            if not val:
                # 空白 → 恢复默认
                val = default
                var.set(default)
            if not (val.startswith('<') and val.endswith('>') and len(val) >= 3):
                messagebox.showerror(
                    "格式错误",
                    "快捷键 {} 格式不对: {}\n\n"
                    "应是 tkinter bind 格式，如：\n"
                    "  <Control-z>      → Ctrl+Z\n"
                    "  <F1>             → F1\n"
                    "  <Alt-x>          → Alt+X\n"
                    "  <Control-Shift-S>→ Ctrl+Shift+S\n"
                    "  <Control-Key-1>  → Ctrl+1".format(key, val))
                return
            new_mapping[key] = val

        # 检查重复
        seen = {}
        for key, val in new_mapping.items():
            if val in seen:
                messagebox.showerror(
                    "冲突",
                    "快捷键 {} 与 {}\n都绑到了 {}\n\n请改一个再保存".format(
                        key, seen[val], val))
                return
            seen[val] = key

        s = cfg_mod.load_settings()
        s.update(new_mapping)
        cfg_mod.save_settings(s)
        try:
            if hasattr(self.app, 'rebind_shortcuts'):
                self.app.rebind_shortcuts(new_mapping)
            messagebox.showinfo("已保存",
                "✅ {} 个快捷键已立即生效".format(len(new_mapping)))
        except Exception as e:
            messagebox.showerror("重绑失败", str(e))

    def _reset_shortcuts(self):
        """🆕 v9.9.6.3：把所有快捷键重置回默认值"""
        if not messagebox.askyesno("确认", "把所有快捷键重置为默认值吗？"):
            return
        new_mapping = {}
        for key, (var, default) in self._sc_vars.items():
            var.set(default)
            new_mapping[key] = default
        s = cfg_mod.load_settings()
        s.update(new_mapping)
        cfg_mod.save_settings(s)
        try:
            if hasattr(self.app, 'rebind_shortcuts'):
                self.app.rebind_shortcuts(new_mapping)
            messagebox.showinfo("已重置",
                "✅ 所有快捷键已重置为默认并立即生效")
        except Exception as e:
            messagebox.showerror("重绑失败", str(e))

    def _sched_start(self):
        t = self.sched_time.get().strip()
        if not re.match(r'^\d{2}:\d{2}$', t):
            messagebox.showerror("错误", "时间格式应为 HH:MM")
            return

        def _task():
            data = api_client.fetch_limit_up_stocks(80)
            if isinstance(data, list):
                fname = DIRS["temp"] / "定时涨停_{}.json".format(
                    datetime.now().strftime("%Y%m%d_%H%M%S"))
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

        self._scheduler.start(t, _task)
        self.sched_status.set("✅ 已启用：每天 {} 自动拉取涨停板".format(t))

    def _sched_stop(self):
        self._scheduler.stop()
        self.sched_status.set("已停止")

    # ════════════════════════════════════════════════
    # 🆕 v9.8：同花顺监听设置保存 / 重启浮窗
    # ════════════════════════════════════════════════
    def _save_hexin(self):
        s = cfg_mod.load_settings()
        s['hexin_watcher_enabled'] = self.hexin_enabled.get()
        # 偏移量校验
        v = self.hexin_offset.get().strip()
        if not v.startswith('0x'): v = '0x' + v
        try:
            int(v, 16)
        except ValueError:
            messagebox.showerror("错误", "偏移量格式无效，必须是 0x 开头的十六进制数")
            return
        s['hexin_offset'] = v
        s['hexin_process_name'] = self.hexin_proc.get().strip() or 'hexin.exe'
        s['hexin_encoding'] = self.hexin_enc.get().strip() or 'gbk'
        try:
            s['hexin_poll_ms'] = max(10, int(self.hexin_poll.get().strip()))
        except ValueError:
            s['hexin_poll_ms'] = 30
        cfg_mod.save_settings(s)
        messagebox.showinfo("完成",
            "✅ 同花顺设置已保存\n\n点击「🔄 重启浮窗」让新设置生效。")

    def _restart_popup(self):
        """🔁 v9.9.5：浮窗已内嵌主程序，"重启浮窗"现在等价于
        "用新设置重启同花顺监听线程"——不会真的销毁窗体。
        """
        try:
            popup = getattr(self.app, '_popup', None)
            if popup and hasattr(popup, 'restart_hexin_watcher'):
                popup.restart_hexin_watcher()
                messagebox.showinfo("完成",
                    "✅ 已用新设置重启同花顺监听\n（浮窗窗体保持原状）")
            else:
                messagebox.showwarning("提示", "主程序未初始化浮窗")
        except Exception as e:
            messagebox.showerror("错误", "重启同花顺监听失败: " + str(e))

    # ════════════════════════════════════════════════
    # 🆕 v9.9.0：同花顺桥诊断 / 测试推送
    # ════════════════════════════════════════════════
    def _diagnose_hexin(self):
        """🆕 v9.9.2：活体诊断 —— 实际 attach + read 一次，把每步失败原因抖出来"""
        try:
            from ..core import hexin_bridge as hexin
            # 用用户当前 settings 里的偏移做诊断，不写死
            s = cfg_mod.load_settings()
            try:
                off_raw = s.get("hexin_offset", "0x1E9A5B0")
                if isinstance(off_raw, int):
                    offset = off_raw
                else:
                    off_raw = str(off_raw)
                    offset = int(off_raw, 16) if off_raw.lower().startswith("0x") \
                        else int(off_raw)
            except Exception:
                offset = 0x1E9A5B0
            text = hexin.diagnose_now(
                offset=offset,
                process_name=s.get("hexin_process_name", "hexin.exe"),
                str_len=int(s.get("hexin_string_length", 6)),
                encoding=s.get("hexin_encoding", "ascii"),
            )
        except Exception as e:
            import traceback
            text = "诊断过程异常: " + repr(e) + "\n\n" + traceback.format_exc()

        # 弹窗显示，加大尺寸 + 复制按钮
        C = self.C
        win = tk.Toplevel(self.app.root)
        win.title("🩺 同花顺桥活体诊断")
        win.geometry("620x460")
        win.configure(bg=C['bg'])
        tk.Label(win, text="🩺 同花顺联动 · 活体诊断",
                 font=('微软雅黑', 11, 'bold'),
                 bg=C['bg'], fg=C['accent']).pack(anchor='w', padx=12, pady=(10, 4))
        tk.Label(win,
                 text="这个诊断会实际去 attach 同花顺、读一次内存、并定位推送链路。"
                      "复制结果给开发者排查最有用。",
                 font=('微软雅黑', 8), bg=C['bg'], fg=C['dim'],
                 justify='left').pack(anchor='w', padx=12)

        text_frame = tk.Frame(win, bg=C['bg'])
        text_frame.pack(fill='both', expand=True, padx=12, pady=8)
        txt = tk.Text(text_frame, font=('Consolas', 9),
                      bg=C['card'], fg=C['text'],
                      relief='flat', padx=10, pady=8, wrap='word')
        vsb = tk.Scrollbar(text_frame, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        txt.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        txt.insert('1.0', text)
        txt.config(state='disabled')

        # 底部按钮：复制 + 重新诊断 + 关闭
        bar = tk.Frame(win, bg=C['bg'])
        bar.pack(fill='x', padx=12, pady=(0, 10))

        def _copy():
            try:
                self.app.root.clipboard_clear()
                self.app.root.clipboard_append(text)
                btn_copy.config(text="✅ 已复制")
                win.after(1500, lambda: btn_copy.config(text="📋 复制全部"))
            except Exception:
                pass
        btn_copy = tk.Button(bar, text="📋 复制全部", command=_copy,
                              font=('微软雅黑', 9), bg=C['accent'],
                              fg='white', relief='flat', padx=14)
        btn_copy.pack(side='left')
        tk.Button(bar, text="🔄 重新诊断",
                  command=lambda: (win.destroy(), self._diagnose_hexin()),
                  font=('微软雅黑', 9), bg=C['purple'],
                  fg='white', relief='flat', padx=14).pack(side='left', padx=(8, 0))
        tk.Button(bar, text="关闭", command=win.destroy,
                  font=('微软雅黑', 9), bg=C['panel'],
                  fg=C['text'], relief='flat', padx=14).pack(side='right')

    def _test_push(self, code):
        """测试一次推送：让同花顺跳到 code（v9.9.6 走 0x490 自定义消息）"""
        try:
            from ..core import hexin_bridge as hexin
            ok, reason = hexin.push_code_to_hexin(code)
        except Exception as e:
            ok, reason = False, repr(e)
        if ok:
            messagebox.showinfo("测试推送",
                "✅ 推送成功：同花顺应已跳转到 " + code +
                "  (市场前缀 " + reason + ")\n\n"
                "如果同花顺没反应：\n"
                "  · 确认同花顺已启动（hexin.exe 在跑）\n"
                "  · 同花顺以管理员启动时，本程序也要以管理员启动\n"
                "  · 杀毒软件可能拦截 WriteProcessMemory，加白名单")
        else:
            messagebox.showerror("测试推送失败", "❌ " + reason)
