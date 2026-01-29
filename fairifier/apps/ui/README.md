# FAIRifier WebUI - 生产代码

本目录包含 Streamlit WebUI 实现。

## 📁 文件说明

### 🎯 生产代码（Production Ready）

1. **`streamlit_app.py`** - Streamlit WebUI
   - 完整实现
   - 多个专业标签页
   - 自定义流式输出
   - 完整集成核心功能

### ⚙️ 支持文件

2. **`__init__.py`** - 模块初始化

---

## 🚀 快速启动

### 方法 1: 使用启动脚本（推荐）

在项目根目录：

```bash
./start_streamlit.sh
```

### 方法 2: 直接运行

```bash
streamlit run fairifier/apps/ui/streamlit_app.py
# 默认端口 8501
```

### 方法 3: 通过 CLI

```bash
python run_fairifier.py ui [--port PORT]
```

---

## 🔧 依赖要求

```bash
pip install streamlit>=1.30.0

# 或使用项目根目录的脚本
cd ../../..  # 回到项目根目录
./install_webui_deps.sh
```

---

## 📚 详细文档

请查看项目根目录的文档：

- **Web UI 总览** - 见 `fairifier/apps/README.md`
- **主文档** - 见项目根目录 `README.md`

---

## ✅ 状态

- ✅ **streamlit_app.py**: 生产就绪，完整功能
- ✅ 已集成所有核心功能
- ✅ 可独立运行

---

## 🔗 相关资源

- [Streamlit 文档](https://docs.streamlit.io/)
- [FAIRifier 主文档](../../../README.md)
