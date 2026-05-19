"""
Tab 基类 - 所有 Tab 模块继承此类
"""
import tkinter as tk
from ..core.theme import get as theme


class BaseTab:
    """
    所有 Tab 模块的基类
    子类需实现：
    - build(parent) -> 构建UI
    - title 属性 (可选)
    """
    title = "Tab"

    def __init__(self, app):
        """
        app: 主 App 实例，可访问：
          - app.cfg          配置字典
          - app.state        全局状态
          - app.bus          事件总线
          - app.nb           Notebook
          - app.show_message 消息提示
        """
        self.app   = app
        self.frame = None
        self.C     = theme()

    def build(self, parent):
        """子类覆盖，构建该 Tab 的 UI"""
        self.frame = tk.Frame(parent, bg=self.C['bg'])
        self.frame.pack(fill='both', expand=True)
