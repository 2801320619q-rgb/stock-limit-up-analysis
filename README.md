# 程序化分析（涨停复盘 / AI 分析工具）

基于 Tkinter 的桌面应用，对接百度千帆 / 火山方舟 API 做股票分析，支持与同花顺双向联动。

## 首次使用

```bash
git clone <repo>
cd <repo>
pip install -r requirements.txt
python main.py
```

第一次启动后，在 **"⚙️ API 设置"** Tab 里填入你自己的：

- 千帆 API Key（百度千帆控制台获取，形如 `bce-v3/ALTAK-xxx/yyy`）
- 火山方舟 API Key（火山引擎控制台获取）

所有配置保存在 `data/config/config.json`，**该文件已在 `.gitignore` 中，不会进 git**。

## 可选：同花顺联动

仅 Windows。在同花顺已运行的情况下：

- 📥 浮窗顶栏开关：跟随同花顺切股
- 🔗 主程序 / 浮窗里点蓝字股票代码：推送到同花顺
- 需要 `pip install pywin32 psutil pymem`

详见 `CHANGELOG.md` 中的版本变更说明。

## 协议

按你想要的协议补充。
