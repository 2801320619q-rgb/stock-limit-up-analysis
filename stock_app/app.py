"""
主 App 类
- 加载 Tab 模块
- 处理事件循环
- 快捷键
- 🔁 v9.9.5：浮窗改回主程序内嵌（tk.Toplevel），不再开独立 Python 进程
            旧的 signal.json / trigger.json IPC 全部砍掉，改成直接方法调用
"""
import queue, signal
import tkinter as tk
from tkinter import ttk, messagebox

from .core import config as cfg_mod
from .core.paths import ensure_dirs
from .core.theme import get as theme, set_theme
from .bus import bus, Events, state
from .tabs import ALL_TABS
from .popup_window import PopupWindow


class App:
    def __init__(self):
        ensure_dirs()

        self.cfg = cfg_mod.load_config()
        s = cfg_mod.load_settings()
        set_theme(s.get('theme', 'dark'))
        self.C = theme()

        self.root = tk.Tk()
        self.root.title("📈 涨停复盘分析工具")
        self.root.geometry("1200x820")
        self.root.minsize(960, 680)
        self.root.configure(bg=self.C['bg'])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.tabs = {}

        self._build_ui()
        self._setup_shortcuts()
        self._setup_signals()
        self._poll_queues()

        # 🔁 v9.9.5：浮窗内嵌，作为主程序 root 的 Toplevel
        # 改前是 subprocess.Popen 启独立进程 + 信号文件轮询
        try:
            self._popup = PopupWindow(self)
        except Exception:
            import traceback; traceback.print_exc()
            self._popup = None

    # ════════════════════════════════════════════════
    # 浮窗公开 API（保留方法签名以兼容旧 Tab 调用方）
    # ════════════════════════════════════════════════
    def show_stock_popup(self, code, name=None):
        """全局便捷入口：显示一只股票（无视模式开关，主动让浮窗显示）"""
        try:
            if self._popup: self._popup.show(code, name)
        except Exception:
            import traceback; traceback.print_exc()

    def notify_stock_focus(self, code, name=None):
        """
        左键单击 / 选中行 → 通知浮窗"主程序在看这只股"。
        🔁 v9.9.6：浮窗自动跟随主程序操作，不再有"📍 主程序联动"开关
                   这里直接把信号转成 popup.show 即可。
        """
        try:
            if self._popup: self._popup.notify_main_click(code, name)
        except Exception:
            pass

    def push_to_hexin(self, code, name=None):
        """
        显式推送一只股票到同花顺（直接调底层桥，不经过浮窗）。
        高级用法：让某个 Tab 主动把"我刚选中的股票"丢给同花顺。
        """
        try:
            from .core import hexin_bridge as hexin
            ok, reason = hexin.push_code_to_hexin(str(code or "").zfill(6))
            if not ok:
                print("[push_to_hexin] 失败:", reason)
        except Exception:
            import traceback; traceback.print_exc()

    def push_to_hexin_silent(self, code, name=None):
        """
        🆕 v9.9.6：蓝字下划线代码点击的统一入口。
        语义："只推送同花顺，不刷新浮窗"。

        浮窗当前是否更新只取决于一件事：
            同花顺侧切到这只股 → watcher 读到 → 浮窗刷新
        但因为 hexin_bridge.push_code_to_hexin 推完会登记静默期，watcher
        读到同一只代码时会被过滤掉。所以浮窗内容不会因为本次点击改变——
        这正是用户要求的"浮窗内容不变"。

        如果用户在同花顺侧手动切到别的股，那才是"非程序相关的切换"，浮窗
        会自然跟随。
        """
        try:
            from .core import hexin_bridge as hexin
            ok, reason = hexin.push_code_to_hexin(str(code or "").zfill(6))
            if not ok:
                if self._popup and hasattr(self._popup, '_hexin_status_var'):
                    try:
                        self._popup._hexin_status_var.set("❌ 推送失败: " + reason)
                    except Exception: pass
                print("[push_silent] 失败:", reason)
            else:
                if self._popup and hasattr(self._popup, '_hexin_status_var'):
                    try:
                        self._popup._hexin_status_var.set(
                            "📤 已推送 {} 到同花顺 (前缀 {})".format(code, reason))
                    except Exception: pass
        except Exception:
            import traceback; traceback.print_exc()

    def popup_lock_code(self, code):
        """🆕 v9.9.6.2：让浮窗 lock 一个代码，watcher 读到时浮窗不刷新。
        被 widgets.attach_code_links 在 scope='popup' 时调用。"""
        try:
            if self._popup and hasattr(self._popup, 'lock_code'):
                self._popup.lock_code(code)
        except Exception:
            import traceback; traceback.print_exc()

    # ════════════════════════════════════════════════
    # 浮窗反向触发：AI 分析
    # （现在浮窗在同进程内，直接调用，不再走 trigger.json）
    # ════════════════════════════════════════════════
    def _do_ai_analyze_from_popup(self, code, name):
        """收到浮窗的 AI 分析请求 → 切到单股搜索 Tab + 填好 + 触发"""
        if not code: return
        try:
            single = self.tabs.get('SingleTab')
            if not single: return
            # 切 Tab
            for i in range(self.nb.index('end')):
                txt = self.nb.tab(i, 'text') or ""
                if '单股' in txt or 'Single' in txt.lower():
                    self.nb.select(i); break
            if hasattr(single, 'name_var'): single.name_var.set(name or '')
            if hasattr(single, 'code_var'): single.code_var.set(code)
            if hasattr(single, 'trigger_search'):
                single.trigger_search()
            # 把主程序窗口提到前面
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except Exception: pass
        except Exception:
            import traceback; traceback.print_exc()

    # ════════════════════════════════════════════════
    # 兼容性 shim：保留 self.stock_popup.xxx 调用方式
    # （旧代码遗留：`app.stock_popup.is_follow_mode()` 等）
    # ════════════════════════════════════════════════
    @property
    def stock_popup(self):
        """
        v9.9.5：内嵌浮窗后直接返回 PopupWindow 实例本身。
        它实现了 is_follow_mode() / show() / follow() 等老 API。
        """
        return self._popup if self._popup else _NullPopup()

    # ════════════════════════════════════════════════
    def _build_ui(self):
        C = self.C

        # 顶栏
        hdr = tk.Frame(self.root, bg=C['acc_dark'], height=50)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text="  📈  涨停复盘分析工具",
                 font=('微软雅黑', 13, 'bold'),
                 bg=C['acc_dark'], fg='white').pack(side='left', padx=16)
        tk.Label(hdr, text="千帆AI · 多Tab模块化",
                 font=('微软雅黑', 9), bg=C['acc_dark'], fg='#aac8ff').pack(side='left')

        # 主体
        body = tk.Frame(self.root, bg=C['bg'])
        body.pack(fill='both', expand=True)

        # Notebook 样式
        style = ttk.Style()
        style.theme_use('default')
        style.configure('App.TNotebook', background=C['bg'], borderwidth=0, tabmargins=0)
        style.configure('App.TNotebook.Tab',
                        background=C['panel'], foreground=C['dim'],
                        font=('微软雅黑', 9), padding=[18, 8], borderwidth=0)
        style.map('App.TNotebook.Tab',
                  background=[('selected', C['acc_dark'])],
                  foreground=[('selected', 'white')])
        style.configure("Treeview", background=C['card'], foreground=C['text'],
                        fieldbackground=C['card'], borderwidth=0)
        style.configure("Treeview.Heading", background=C['panel'], foreground=C['accent'],
                        font=('微软雅黑', 9, 'bold'), borderwidth=0)
        style.map("Treeview", background=[('selected', C['acc_dark'])])

        self.nb = ttk.Notebook(body, style='App.TNotebook')
        self.nb.pack(fill='both', expand=True)

        # 加载所有 Tab
        for title, TabCls in ALL_TABS:
            frame = tk.Frame(self.nb, bg=C['bg'])
            self.nb.add(frame, text=title)
            tab_instance = TabCls(self)
            tab_instance.build(frame)
            self.tabs[TabCls.__name__] = tab_instance

    def _build_shortcut_spec(self):
        """
        🆕 v9.9.6.3：快捷键统一规格表
        返回 list[(settings_key, default_sequence, callable, description)]

        每次调用都新建（量很小，不是热点），settings_tab 和
        _setup_shortcuts / rebind_shortcuts 都从这里取数据。
        """
        spec = [
            ('shortcut_search',       '<Control-Return>',
                self._kb_search,        '🔍 单股搜索 → 触发搜索'),
            ('shortcut_clear_log',    '<Control-l>',
                self._kb_clear,         '🧹 清空当前 Tab 日志'),
            ('shortcut_undo',         '<Control-z>',
                self._kb_undo,          '⏪ 回退浮窗上一只股'),
            ('shortcut_toggle_popup', '<F1>',
                self._kb_toggle_popup,  '👁  显示/隐藏浮窗'),
            ('shortcut_minimize_popup', '<F2>',
                self._kb_minimize_popup, '📐 最小化/复原浮窗'),
        ]
        # 8 个切 Tab 快捷键
        for i in range(8):
            spec.append((
                'shortcut_tab_{}'.format(i + 1),
                '<Control-Key-{}>'.format(i + 1),
                (lambda i=i: self._kb_tab(i)),
                '🗂 切到 Tab {}'.format(i + 1),
            ))
        return spec

    def _setup_shortcuts(self):
        """
        🆕 v9.9.6.3：全部快捷键改用 bind_all 绑定（root.bind 只在焦点在 root
        时触发，Entry/Text/Treeview 抢焦点后就拦截了，所以之前 Ctrl+Z / F1
        在主界面下大多不生效）。bind_all 是 Tk 应用级绑定，无视焦点。
        """
        s = cfg_mod.load_settings()
        self._bound_shortcuts = {}  # settings_key → 实际绑定的 sequence
        for key, default, action, desc in self._build_shortcut_spec():
            seq = (s.get(key) or default).strip()
            if not seq:
                continue
            try:
                # 用 default 参数 a=action 把 action 闭包到 lambda，
                # 否则循环变量 action 会被覆盖（典型 Python 闭包陷阱）
                self.root.bind_all(seq, lambda e, a=action: a())
                self._bound_shortcuts[key] = seq
                print("[shortcuts] bind_all {} → {}".format(seq, key))
            except Exception:
                import traceback; traceback.print_exc()

    def rebind_shortcuts(self, new_mapping):
        """
        🆕 v9.9.6.3：settings_tab 改了快捷键后调本方法立即重新 bind。
        new_mapping: dict[settings_key → new_sequence]
        """
        spec_map = {k: (d, a, ds) for k, d, a, ds in self._build_shortcut_spec()}
        # 先 unbind_all 即将被改的旧 sequence
        for key in new_mapping:
            old_seq = self._bound_shortcuts.get(key)
            if old_seq:
                try:
                    self.root.unbind_all(old_seq)
                except Exception:
                    import traceback; traceback.print_exc()
        # 再 bind_all 新的
        for key, new_seq in new_mapping.items():
            if key not in spec_map:
                continue
            new_seq = (new_seq or '').strip()
            if not new_seq:
                continue
            _, action, _ = spec_map[key]
            try:
                self.root.bind_all(new_seq, lambda e, a=action: a())
                self._bound_shortcuts[key] = new_seq
                print("[shortcuts] rebind_all {} → {}".format(new_seq, key))
            except Exception:
                import traceback; traceback.print_exc()

    def _kb_tab(self, idx):
        """切到第 idx 个 Tab（0-indexed）"""
        try:
            if idx < self.nb.index('end'):
                self.nb.select(idx)
        except Exception:
            pass

    def _kb_undo(self):
        """⏪ 回退浮窗上一只股"""
        if self._popup and hasattr(self._popup, 'undo'):
            try: self._popup.undo()
            except Exception: import traceback; traceback.print_exc()

    def _kb_toggle_popup(self):
        """👁 显示/隐藏浮窗"""
        if self._popup and hasattr(self._popup, 'toggle_visibility'):
            try: self._popup.toggle_visibility()
            except Exception: import traceback; traceback.print_exc()

    def _kb_minimize_popup(self):
        """📐 最小化/复原浮窗"""
        if self._popup and hasattr(self._popup, 'toggle_minimize'):
            try: self._popup.toggle_minimize()
            except Exception: import traceback; traceback.print_exc()

    def _setup_signals(self):
        def handle_signal(signum, frame):
            state.shutdown.set()
        try:
            signal.signal(signal.SIGINT, handle_signal)
        except Exception:
            pass

    def _kb_search(self):
        try:
            idx = self.nb.index(self.nb.select())
            if idx == 1:  # 单股搜索
                self.tabs['SingleTab'].trigger_search()
        except Exception:
            pass

    def _kb_clear(self):
        try:
            idx = self.nb.index(self.nb.select())
            from .widgets import clear_log
            if idx == 0 and 'BatchTab' in self.tabs:
                clear_log(self.tabs['BatchTab'].log_w)
            elif idx == 1 and 'SingleTab' in self.tabs:
                clear_log(self.tabs['SingleTab'].log_w)
        except Exception:
            pass

    def _poll_queues(self):
        """每 80ms 处理一次日志和 UI 队列"""
        from .widgets import write_log
        try:
            while True:
                item = state.log_queue.get_nowait()
                if len(item) == 3:
                    widget, msg, tag = item
                    write_log(widget, msg, tag)
                else:
                    msg, tag = item
                    # 默认写到 BatchTab
                    if 'BatchTab' in self.tabs:
                        write_log(self.tabs['BatchTab'].log_w, msg, tag)
        except queue.Empty:
            pass

        try:
            while True:
                fn = state.ui_queue.get_nowait()
                fn()
        except queue.Empty:
            pass

        self.root.after(80, self._poll_queues)

    def _on_close(self):
        if 'BatchTab' in self.tabs and self.tabs['BatchTab'].running:
            if not messagebox.askyesno("退出", "分析正在进行，确认退出？"):
                return
            state.shutdown.set()
        # 板块分析等 Tab 的关闭兜底存盘
        try:
            sector_tab = self.tabs.get('SectorTab')
            if sector_tab and hasattr(sector_tab, '_save_partial_on_close'):
                sector_tab._save_partial_on_close()
        except Exception:
            pass
        # 🔁 v9.9.5：浮窗内嵌后，要主动停掉同花顺监听线程，否则
        # 非守护线程会阻止主程序退出
        try:
            if self._popup:
                self._popup.destroy()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ════════════════════════════════════════════════
# 兜底：如果浮窗初始化失败，让 app.stock_popup.xxx 调用不抛异常
# ════════════════════════════════════════════════
class _NullPopup:
    """浮窗创建失败时的占位对象，所有方法都是 no-op"""
    def is_follow_mode(self): return False
    def show(self, code, name=None): pass
    def follow(self, code, name=None): pass
    def notify_main_click(self, code, name=None): pass
    def push_to_hexin(self, code, name=None): pass
    def push_to_hexin_silent(self, code, name=None): pass
    def hide(self): pass
    def destroy(self): pass
    def restart_hexin_watcher(self): pass
    def toggle_visibility(self): pass
    def toggle_minimize(self): pass
    def undo(self): pass
    def lock_code(self, code): pass
