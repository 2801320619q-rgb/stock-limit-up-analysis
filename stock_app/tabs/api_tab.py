"""
API 管理 Tab
- 修改 API URL / 模型 / Keys
- 🆕 模型与URL强联动
- 🆕 Keys 池分离：百度千帆与火山方舟独立管理，随模型精准切换
"""
import tkinter as tk
from tkinter import ttk, messagebox

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry
from ..core import config as cfg_mod
from ..bus import bus, Events


class ApiTab(BaseTab):
    title = "API管理"

    def __init__(self, app):
        super().__init__(app)
        self._qianfan_keys = []
        self._volcano_keys = []
        self._current_key_type = "qianfan"  # 🆕 状态锁：记录当前文本框显示的是哪个池子

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=16, pady=12)

        tk.Label(body, text="🔑 API 全局管理", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(anchor='w', pady=(0, 8))
        tk.Label(body, text="切换模型时，URL和Key列表会自动联动切换，保存后全局生效",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim']).pack(anchor='w', pady=(0, 12))

        # ── 接口配置 ──────────────────────────
        rc = make_card(body, "🌐  接口与模型配置（强联动）", pady_top=0)

        # URL
        row_url = tk.Frame(rc, bg=C['panel'])
        row_url.pack(fill='x', pady=3)
        tk.Label(row_url, text="API URL", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['dim'], width=14, anchor='w').pack(side='left')
        self.url_var = tk.StringVar(value=self.app.cfg.get("api_url", ""))
        styled_entry(row_url, self.url_var).pack(side='left', fill='x', expand=True,
                                                  padx=(4, 0), ipady=4)

        # Model（下拉）
        row_model = tk.Frame(rc, bg=C['panel'])
        row_model.pack(fill='x', pady=3)
        tk.Label(row_model, text="模型 Model", font=('微软雅黑', 9),
                 bg=C['panel'], fg=C['dim'], width=14, anchor='w').pack(side='left')

        cur_id = self.app.cfg.get("model", "")
        cur_disp = cfg_mod.model_id_to_display_name(cur_id)
        self.model_var = tk.StringVar(value=cur_disp)

        style = ttk.Style()
        style.configure("Dark.TCombobox",
                        fieldbackground=C['card'], background=C['card'],
                        foreground=C['text'], arrowcolor=C['accent'],
                        borderwidth=0)
        self.model_combo = ttk.Combobox(row_model, textvariable=self.model_var,
                                        values=cfg_mod.MODEL_LIST,
                                        style="Dark.TCombobox",
                                        font=('微软雅黑', 9), state='readonly')
        self.model_combo.pack(side='left', fill='x', expand=True, padx=(4, 0), ipady=4)

        self.model_id_label = tk.Label(rc, text="ID: " + cur_id,
                                        font=('Consolas', 8),
                                        bg=C['panel'], fg=C['dim'])
        self.model_id_label.pack(anchor='w', padx=(150, 0), pady=(2, 0))

        # 🆕 核心：模型选择联动逻辑 (URL + Keys)
        def _on_model_change(e=None):
            new_id = cfg_mod.display_name_to_model_id(self.model_var.get())
            self.model_id_label.config(text="ID: " + new_id)
            
            disp = self.model_var.get()
            current_url = self.url_var.get().strip()
            volc_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
            qianfan_url = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"

            # 1. 🎯 关键修复：先根据当前状态锁，把文本框的内容存回它属于的池子！
            self._save_current_keys_to_memory()

            # 2. 判断要切换到哪个池子，并更新状态锁
            if disp.startswith("🌋"):
                target_type = "volcano"
                if current_url != volc_url:
                    self.url_var.set(volc_url)
            else:
                target_type = "qianfan"
                if "volces.com" in current_url or "ark.cn-beijing" in current_url:
                    self.url_var.set(qianfan_url)

            # 3. 加载新池子的数据到文本框
            self._current_key_type = target_type
            self._load_keys_to_ui()

        self.model_combo.bind("<<ComboboxSelected>>", _on_model_change)

        # 一键切换 API 厂商
        switch_row = tk.Frame(rc, bg=C['panel'])
        switch_row.pack(fill='x', pady=(8, 0))
        tk.Label(switch_row, text="快捷切换：", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim'], width=14, anchor='w').pack(side='left')
        styled_btn(switch_row, "🔵 切到百度千帆", C['accent'],
                   self._switch_to_qianfan, pady=2).pack(side='left', padx=(4, 4))
        styled_btn(switch_row, "🌋 切到火山方舟", C['red'],
                   self._switch_to_volcano, pady=2).pack(side='left', padx=(0, 4))

        # ── 🆕 Key 列表区域 (带动态大标题) ──────────────────────────
        kc = make_card(body, "🔑  当前编辑：", pady_top=8)
        
        # 动态大标题：明确告知用户现在编辑的是哪家
        self._key_type_hint = tk.StringVar(value="🔵 百度千帆 API Keys")
        tk.Label(kc, textvariable=self._key_type_hint, 
                 font=('微软雅黑', 11, 'bold'), 
                 bg=C['panel'], fg=C['accent']).pack(anchor='w', pady=(0, 6))

        self.keys_text = tk.Text(kc, font=('Consolas', 9),
                                 bg=C['card'], fg=C['text'],
                                 insertbackground='white', relief='flat',
                                 height=10)
        self.keys_text.pack(fill='x', pady=(0, 6))

        tk.Label(kc, text="💡 此列表随上方模型自动切换，请确保 Key 与模型匹配",
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(anchor='w')

        # ── 操作按钮 ──────────────────────────
        btn_row = tk.Frame(body, bg=C['bg'])
        btn_row.pack(fill='x', pady=(12, 0))
        styled_btn(btn_row, "💾  保存所有配置", C['green'],
                   self._save, pady=8).pack(side='left')
        self.save_status = tk.StringVar(value="")
        tk.Label(btn_row, textvariable=self.save_status,
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['green']).pack(side='left', padx=12)

        # 初始化加载 Keys 到内存和文本框
        self._init_keys()

    def _init_keys(self):
        """初始化读取分离的 Keys"""
        self._qianfan_keys = self.app.cfg.get("qianfan_api_keys", [])
        self._volcano_keys = self.app.cfg.get("volcano_api_keys", [])
        
        # 兼容旧版本
        if not self._qianfan_keys and not self._volcano_keys:
            self._qianfan_keys = self.app.cfg.get("api_keys", [])

        # 根据当前模型决定显示哪组 Keys
        if self.model_var.get().startswith("🌋"):
            self._current_key_type = "volcano"
        else:
            self._current_key_type = "qianfan"
            
        self._load_keys_to_ui()

    def _save_current_keys_to_memory(self):
        """🎯 核心：将当前文本框的 Keys 暂存到内存对应的列表"""
        raw_keys = self.keys_text.get("1.0", "end").strip().splitlines()
        current_keys = [k.strip() for k in raw_keys if k.strip()]
        
        # 根据状态锁判断，当前文本框里的内容应该存给谁
        if self._current_key_type == "volcano":
            self._volcano_keys = current_keys
        else:
            self._qianfan_keys = current_keys

    def _load_keys_to_ui(self):
        """将内存中的 Keys 填入文本框，并更新大标题"""
        if self._current_key_type == "volcano":
            keys_list = self._volcano_keys
            self._key_type_hint.set("🌋 火山方舟 API Keys")
        else:
            keys_list = self._qianfan_keys
            self._key_type_hint.set("🔵 百度千帆 API Keys")
            
        self.keys_text.config(state='normal')
        self.keys_text.delete('1.0', 'end')
        self.keys_text.insert('1.0', "\n".join(keys_list))

    def _save(self):
        # 1. 暂存当前文本框的 Keys
        self._save_current_keys_to_memory()

        # 2. 收集新值
        new_url   = self.url_var.get().strip()
        new_model = cfg_mod.display_name_to_model_id(self.model_var.get().strip())
        is_volcano = self.model_var.get().startswith("🌋")

        # 3. 写回配置
        self.app.cfg["api_url"]  = new_url
        self.app.cfg["model"]    = new_model
        self.app.cfg["qianfan_api_keys"] = self._qianfan_keys
        self.app.cfg["volcano_api_keys"] = self._volcano_keys
        
        # 全局 api_keys 根据当前选中的模型动态赋值
        self.app.cfg["api_keys"] = self._volcano_keys if is_volcano else self._qianfan_keys

        cfg_mod.save_config(self.app.cfg)

        # 触发事件 → 所有Tab自动刷新
        bus.emit(Events.API_KEYS_CHANGED, self.app.cfg["api_keys"])

        volc_cnt = len(self._volcano_keys)
        qf_cnt = len(self._qianfan_keys)
        self.save_status.set("✅ 已保存 (千帆: {}个, 火山: {}个, 当前激活: {})".format(
            qf_cnt, volc_cnt, "火山" if is_volcano else "千帆"))
        self.frame.after(4000, lambda: self.save_status.set(""))

    # ════════════════════════════════════════════
    # 🌋 火山方舟 / 🔵 百度千帆 一键切换
    # ════════════════════════════════════════════
    def _switch_to_qianfan(self):
        self.url_var.set("https://qianfan.baidubce.com/v2/ai_search/chat/completions")
        if self.model_var.get().startswith("🌋"):
            self.model_var.set("🆓 ERNIE-4.5-Turbo-32K")
            new_id = cfg_mod.display_name_to_model_id(self.model_var.get())
            self.model_id_label.config(text="ID: " + new_id)
        
        # 先存旧池子，再切新池子
        self._save_current_keys_to_memory()
        self._current_key_type = "qianfan"
        self._load_keys_to_ui()

    def _switch_to_volcano(self):
        self.url_var.set("https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        if not self.model_var.get().startswith("🌋"):
            self.model_var.set("🌋 doubao-seed-2-0-pro")
            new_id = cfg_mod.display_name_to_model_id(self.model_var.get())
            self.model_id_label.config(text="ID: " + new_id)
            
        # 先存旧池子，再切新池子
        self._save_current_keys_to_memory()
        self._current_key_type = "volcano"
        self._load_keys_to_ui()