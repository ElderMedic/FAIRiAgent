# Mem0 快速开始

## 这是什么

FAIRiAgent 集成了 mem0 记忆层，用于在 workflow 运行之间保留可检索的语义记忆。

它主要带来三件事：

- **上下文压缩**：把一次运行中的关键信息保存下来
- **运行前检索**：在 agent 执行前取回相关记忆
- **跨会话延续**：在 resume 或重复运行时复用已有上下文

## 安装

### 1. 安装依赖

```bash
pip install mem0ai qdrant-client
```

### 2. 启动 Qdrant（可选，默认会自动尝试拉起本地容器）

```bash
docker run -d --name fairiagent-qdrant -p 6333:6333 qdrant/qdrant
```

### 3. 配置 `.env`

```bash
MEM0_ENABLED=true
MEM0_QDRANT_URL=http://localhost:6333
MEM0_COLLECTION_NAME=fairifier_memories
```

如果你使用本地 Ollama embedding，也可以补：

```bash
MEM0_EMBEDDING_MODEL=nomic-embed-text
MEM0_OLLAMA_BASE_URL=http://localhost:11434
```

如果本地 Ollama embedding 不可用，系统会自动回退到 API embedding（当可用 API key/base URL 存在时）。

## 验证

```bash
python run_fairifier.py memory status
```

正常情况下你会看到 mem0 可用、Qdrant 可连接。

## 最常用命令

```bash
# 查看状态
python run_fairifier.py memory status

# 查看某个 session / project 的记忆
python run_fairifier.py memory list my_project

# 按 agent 过滤
python run_fairifier.py memory list my_project -a DocumentParser

# 清空某个 session / project 的记忆
python run_fairifier.py memory clear my_project
```

## 与 workflow 的关系

当 mem0 开启后，系统通常会这样工作：

1. agent 执行前检索相关记忆
2. agent 正常运行
3. 运行成功后把关键信息写回记忆层
4. 重试或恢复运行时复用这些记忆

这不会替代正常的 workflow state，也不会替代 checkpointer。

## 与 checkpointer 的区别

| 功能 | Checkpointer | mem0 |
|------|--------------|------|
| 目标 | 保存 workflow 状态 | 保存可检索的语义记忆 |
| 数据形态 | 完整状态字典 | 关键事实、摘要、上下文 |
| 恢复方式 | 精确恢复状态 | 为后续执行提供上下文 |
| 存储 | memory / sqlite | Qdrant |

## 常见问题

### mem0 不可用

先检查：

```bash
python run_fairifier.py memory status
docker ps | grep qdrant
```

常见原因：

- Qdrant 没启动
- `MEM0_QDRANT_URL` 配置错误
- `mem0ai` / `qdrant-client` 没安装

### 系统是否会因为 mem0 不可用而报错

默认不会。

如果 mem0 不可用，FAIRiAgent 会：

- 自动关闭记忆功能
- 继续执行普通 workflow
- 记录 warning 日志

## 适合什么时候启用

建议在以下情况启用：

- 你在调试多轮 workflow
- 你想测试 session memory / persistent memory
- 你想观察 agent 是否能复用前一轮上下文

如果只是一次性跑通流程，mem0 不是必需的。

## 相关文档

- [中文快速开始](QUICKSTART.md)
- [英文 Mem0 Quick Start](../../MEM0_QUICKSTART.md)
- [Memory Guide](../../MEMORY_GUIDE.md)
