"""
v9.9.5 起浮窗回到主程序内嵌（popup_window.PopupWindow）。
此文件保留为兼容 shim：旧代码 `from .stock_popup import StockPopup` 不会报 ImportError。
所有方法都委托到 app._popup（即 PopupWindow 实例）。
"""
class StockPopup:
    """已废弃：浮窗逻辑迁移到 popup_window.PopupWindow。这里只保留签名兼容。"""
    def __init__(self, app):
        self.app = app

    def _p(self):
        return getattr(self.app, '_popup', None)

    def is_follow_mode(self):
        p = self._p()
        try:
            return bool(p.is_follow_mode()) if p else False
        except Exception:
            return False

    def show(self, code, name=None):
        p = self._p()
        try:
            if p: p.show(code, name)
        except Exception: pass

    def follow(self, code, name=None):
        p = self._p()
        try:
            if p: p.notify_main_click(code, name)
        except Exception: pass

    def hide(self):
        p = self._p()
        try:
            if p: p.hide()
        except Exception: pass
