# FAIRifier WebUI - 生产代码

本目录包含两个完整的、可直接运行的 WebUI 实现。

## 📁 文件说明

### 🎯 生产代码（Production Ready）

1. **`streamlit_app.py`** - Streamlit WebUI
   - 1291 行完整实现
   - 5个专业标签页
   - 自定义流式输出
   - 完整集成核心功能
   
2. **`gradio_app.py`** - Gradio WebUI
   - 850 行完整实现
   - 6个标签页
   - 原生流式输出
   - 自动 API 生成
   - 完整集成核心功能

### ⚙️ 支持文件

3. **`__init__.py`** - 模块初始化

---

## 🚀 快速启动

### 方法 1: 使用启动脚本（推荐）

在项目根目录：

```bash
# Streamlit
./start_streamlit.sh

# Gradio
./start_gradio.sh
```

### 方法 2: 直接运行

```bash
# Streamlit (端口 8501)
streamlit run fairifier/apps/ui/streamlit_app.py

# Gradio (端口 7860)
python fairifier/apps/ui/gradio_app.py
```

---

## 🔧 依赖要求

```bash
# 安装依赖
pip install streamlit>=1.30.0 gradio>=4.0.0

# 或使用项目根目录的脚本
cd ../../..  # 回到项目根目录
./install_webui_deps.sh
```

---

## 📊 功能对比

| 功能 | streamlit_app.py | gradio_app.py |
|------|-----------------|---------------|
| 标签页数 | 5 | 6 |
| 流式输出 | 自定义实现 | 原生支持 |
| API 生成 | ❌ | ✅ 自动 |
| 代码行数 | 1291 | 850 |
| 性能 | 中等 | 更好 |
| 数据展示 | 丰富 | 简洁 |

---

## 📚 详细文档

请查看项目根目录的文档：

- **`WEBUI_READY.md`** - 总览
- **`WEBUI_QUICKSTART.md`** - 快速开始
- **`WEBUI_TESTING_GUIDE.md`** - 测试指南
- **`docs/WEBUI_COMPARISON.md`** - 技术对比

---

## ✅ 状态

- ✅ **streamlit_app.py**: 生产就绪，完整功能
- ✅ **gradio_app.py**: 生产就绪，完整功能
- ✅ 两者都已集成所有核心功能
- ✅ 两者都可独立运行
- ✅ 无需修改即可使用

---

## 🎯 选择建议

**使用 Streamlit 如果：**
- 需要丰富的数据展示
- 熟悉 Streamlit
- 内部使用为主

**使用 Gradio 如果：**
- 需要流式输出（更流畅）
- 需要 API 访问
- 计划公开演示
- 追求更好的性能

**两者都保留：**
- 不同场景使用不同版本
- 继续对比优化

---

## 🔗 相关资源

- [Streamlit 文档](https://docs.streamlit.io/)
- [Gradio 文档](https://www.gradio.app/docs/)
- [FAIRifier 主文档](../../../README.md)

---

**最后更新**: 2025-11-27  
**版本**: 生产版（Production Ready）

