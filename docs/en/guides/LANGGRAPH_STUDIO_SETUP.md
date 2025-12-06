# LangGraph Studio 设置指南

本指南说明如何使用 `langgraph dev` 启动本地 LangGraph 服务器，并连接到 LangSmith 进行可视化和调试。

## 📋 前置要求

1. 安装 LangGraph CLI（包含 inmem 扩展）：
```bash
pip install -U "langgraph-cli[inmem]"
```

2. 确保已安装项目依赖：
```bash
pip install -r requirements.txt
```

## 🔧 配置步骤

### 1. 设置 LangSmith API Key

在项目根目录的 `.env` 文件中添加您的 LangSmith API Key：

```bash
# .env 文件
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=fairifier-studio
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=fairifier-studio
```

### 2. 启动 LangGraph 开发服务器

在项目根目录运行：

```bash
langgraph dev
```

如果成功启动，您将看到类似以下的输出：

```
Ready!

* API: http://localhost:2024
* Docs: http://localhost:2024/docs
* LangGraph Studio Web UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

### 3. 访问 LangGraph Studio

打开浏览器，访问日志中提供的 LangGraph Studio Web UI 链接：

```
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

## 🎯 功能特性

在 LangGraph Studio 中，您可以：

1. **可视化工作流**：查看完整的 FAIRifier 工作流图
2. **调试执行**：逐步执行并查看每个节点的状态
3. **查看状态**：实时查看工作流状态的变化
4. **测试输入**：直接在工作流中测试不同的输入
5. **查看 LangSmith 追踪**：所有执行都会自动记录到 LangSmith

## 🔍 工作流节点

FAIRifier 工作流包含以下节点：

- `read_file`: 读取文档内容
- `plan_workflow`: LLM 规划工作流策略
- `parse_document`: 解析文档并提取信息
- `evaluate_parsing`: Critic 评估解析结果
- `retrieve_knowledge`: 从 FAIR-DS API 检索知识
- `evaluate_retrieval`: Critic 评估检索结果
- `generate_json`: 生成 FAIR-DS 兼容的 JSON 元数据
- `evaluate_generation`: Critic 评估生成结果
- `finalize`: 完成工作流并生成摘要

## 🐛 故障排除

### Safari 浏览器连接问题

如果使用 Safari 浏览器遇到连接问题，可以使用 `--tunnel` 参数：

```bash
langgraph dev --tunnel
```

### 调试模式

如果需要逐步调试，可以使用 `--debug-port` 参数：

```bash
langgraph dev --debug-port 5678
```

### 检查配置

确保 `langgraph.json` 文件在项目根目录，内容如下：

```json
{
  "graphs": {
    "fairifier": "./fairifier/graph/__dev__.py:graph"
  },
  "env": ".env",
  "dependencies": [
    "."
  ]
}
```

**注意**：`dependencies` 字段是必需的，至少需要包含一个依赖项。使用 `"."` 表示当前项目目录。

## 📝 注意事项

1. **LangSmith 追踪**：所有执行都会自动记录到 LangSmith，确保已设置 `LANGSMITH_API_KEY`
2. **状态管理**：工作流使用内存检查点（MemorySaver），重启服务器会丢失状态
3. **文件路径**：在 Studio 中测试时，确保 `document_path` 指向有效的文件路径

## 🚀 快速开始

```bash
# 1. 设置环境变量
export LANGSMITH_API_KEY=your_key_here

# 2. 启动开发服务器
langgraph dev

# 3. 访问 Studio UI（在浏览器中打开日志中显示的链接）
```

现在您可以在 LangGraph Studio 中可视化和调试 FAIRifier 工作流了！

