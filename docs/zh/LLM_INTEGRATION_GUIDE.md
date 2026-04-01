# LLM 集成指南

## 概述

FAIRiAgent 当前支持以下 LLM 提供商：

- `ollama`：本地模型
- `openai`
- `qwen`
- `gemini`
- `anthropic`

不同提供商共享同一套 FAIRiAgent workflow，主要差别在于 API Key、模型名和少量 provider-specific 配置。

## 核心环境变量

推荐在 `.env` 中配置：

```bash
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
LLM_API_KEY=your_api_key_here
FAIRIFIER_LLM_BASE_URL=http://localhost:11434
```

说明：

- `FAIRIFIER_LLM_BASE_URL` 主要给 `ollama` 和 OpenAI-compatible 接口使用。
- `gemini` 和 `anthropic` 使用官方 SDK/API，不依赖自定义 base URL。
- `LANGSMITH_API_KEY` 是可选项，仅在需要 tracing 时使用。

## 各提供商配置示例

### Ollama

```bash
LLM_PROVIDER=ollama
FAIRIFIER_LLM_MODEL=qwen3:30b
FAIRIFIER_LLM_BASE_URL=http://localhost:11434
```

### OpenAI

```bash
LLM_PROVIDER=openai
FAIRIFIER_LLM_MODEL=gpt-5.4
LLM_API_KEY=your_openai_api_key
```

### Qwen

```bash
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
LLM_API_KEY=your_dashscope_api_key

# 也可以使用别名：
# DASHSCOPE_API_KEY=your_dashscope_api_key
```

### Gemini

```bash
LLM_PROVIDER=gemini
FAIRIFIER_LLM_MODEL=gemini-3.1-pro-preview

# 推荐使用以下别名之一：
GOOGLE_API_KEY=your_google_api_key
# 或
GEMINI_API_KEY=your_google_api_key

# 通用方式也可以：
# LLM_API_KEY=your_google_api_key
```

### Anthropic

```bash
LLM_PROVIDER=anthropic
FAIRIFIER_LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=your_anthropic_api_key
```

## 安装

先安装项目依赖：

```bash
pip install -r requirements.txt
```

Gemini 支持依赖 `langchain-google-genai`，该依赖已经加入项目配置。

## 快速测试

```bash
cp env.example .env
# 编辑 .env

python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRxiv.pdf
```

如果想交互式使用：

```bash
python run_fairifier.py ui
```

当前 Streamlit UI 配置页支持：

- Qwen
- Gemini
- OpenAI
- Ollama
- Anthropic

## 推荐设置

- 结构化抽取建议保持 `LLM_TEMPERATURE=0.3`
- 开发测试可优先考虑：
  - `qwen-flash`
  - `gemini-3.1-pro-preview`
  - 本地 Ollama 模型
- 只有在需要 tracing 和调试时再配置 `LANGSMITH_API_KEY`

## 常见问题

### 提供商名称不识别

请使用以下之一：

- `ollama`
- `openai`
- `qwen`
- `gemini`
- `anthropic`

内部还支持两个别名：

- `google` -> `gemini`
- `claude` -> `anthropic`

### Gemini API Key 未生效

请设置以下任一变量：

- `GOOGLE_API_KEY`
- `GEMINI_API_KEY`
- `LLM_API_KEY`

### Qwen API Key 未生效

请设置以下任一变量：

- `LLM_API_KEY`
- `DASHSCOPE_API_KEY`

### base URL 应该怎么理解

- `ollama`：使用 `FAIRIFIER_LLM_BASE_URL`
- `openai`：可选自定义 base URL，不设置时走官方 API
- `qwen`：走 Qwen/DashScope 的 OpenAI-compatible 配置路径
- `gemini` 和 `anthropic`：走官方 SDK/API 路径，不需要自定义 base URL

## 相关文档

- [文档首页](../README.md)
- [中文快速开始](guides/QUICKSTART.md)
- [Mem0 快速开始（中文）](guides/MEM0_QUICKSTART.md)
- [英文 LLM 指南](../en/LLM_INTEGRATION_GUIDE.md)
