# 补跑失败运行指南

## 补跑统计

根据失败运行分析，需要补跑 **19 次**（已排除 JSON 解析错误）：

| 模型 | 文档 | 需补跑次数 | 原因 |
|------|------|-----------|------|
| **Anthropic Haiku** | biosensor | 1 | Timeout |
| **Anthropic Sonnet** | biosensor | 4 | Timeout |
| **OpenAI GPT-5** | biosensor | 7 | Timeout + Metadata未找到 |
| **OpenAI O3** | biosensor | 7 | Timeout + Metadata未找到 |

**说明**：
- JSON 解析错误已排除（这是 LLM 输出格式问题，不是 workflow 未完成）
- Qwen-Flash 的 JSON 解析错误不需要重跑
- biorem 文档已暂时移除（按方案 A）

## 使用 MinerU 输出跳过文档转换

为了节约时间，补跑脚本使用已有的 MinerU markdown 输出作为输入，这样可以：
1. ✅ **跳过 MinerU 转换步骤**（最耗时的部分）
2. ✅ **避免 MinerU 转换失败**（如 biorem 的 "Aborted!" 问题）
3. ✅ **加快运行速度**

### MinerU 输出文件
- **biosensor**: `evaluation/datasets/raw/biosensor/mineru_aec8570_CombinedPDF_v1/aec8570_CombinedPDF_v1/vlm/aec8570_CombinedPDF_v1.md`

### Ground Truth 配置
创建了专门的 `ground_truth_rerun.json`，只包含 biosensor 文档，并指向 markdown 文件而非 PDF：
```json
{
  "documents": [
    {
      "document_id": "biosensor",
      "document_path": "evaluation/datasets/raw/biosensor/mineru_aec8570_CombinedPDF_v1/aec8570_CombinedPDF_v1/vlm/aec8570_CombinedPDF_v1.md",
      ...
    }
  ]
}
```

## 运行补跑脚本

```bash
# 激活环境
mamba activate FAIRiAgent

# 运行补跑脚本
./evaluation/scripts/rerun_failed.sh
```

### 补跑顺序
1. Anthropic Haiku (1 次)
2. Anthropic Sonnet (4 次)
3. OpenAI GPT-5 (7 次)
4. OpenAI O3 (7 次)

**总计**: 19 次运行

### 输出目录
补跑结果将保存在：
```
evaluation/runs/rerun_<TIMESTAMP>/
├── anthropic_haiku/
│   └── anthropic_haiku/
│       └── outputs/
├── anthropic_sonnet/
│   └── anthropic_sonnet/
│       └── outputs/
├── openai_gpt5/
│   └── openai_gpt5/
│       └── outputs/
└── openai_o3/
    └── openai_o3/
        └── outputs/
```

## 合并补跑结果

补跑完成后，需要将新运行的结果合并到原始运行目录中：

```bash
# 示例：合并 Anthropic Haiku 的补跑结果
cp -r evaluation/runs/rerun_<TIMESTAMP>/anthropic_haiku/anthropic_haiku/outputs/* \
      evaluation/runs/anthropic_parallel_20251121_142534/haiku/outputs/anthropic_haiku/biosensor/

# 对其他模型重复此操作
```

**或者**直接在分析时包含补跑目录（推荐）。

## 重新运行分析

合并或包含补跑结果后，重新运行分析：

```bash
python evaluation/analysis/run_analysis.py
```

## 检查完成度

运行失败检查脚本验证所有运行是否完成：

```bash
python evaluation/analysis/check_failed_runs.py
```

预期输出应显示所有模型都达到 10/10 次成功运行。

## 注意事项

1. **网络稳定性**: 确保网络连接稳定，避免再次 timeout
2. **API 限额**: 注意 OpenAI API 的速率限制
3. **监控进度**: 补跑过程中可以通过查看输出目录监控进度
4. **备份**: 如有需要，在补跑前备份现有结果

## 故障排查

### 如果再次出现 timeout
- 检查网络连接
- 检查 API 服务状态
- 考虑降低并发数（修改 `WORKERS` 变量）

### 如果出现 metadata_not_found
- 检查 LLM 输出日志
- 可能需要调整 prompt 或增加 max_tokens

### 如果仍有 JSON 解析错误
- 这是 LLM 输出格式问题，不影响评估结果统计
- 可以考虑改进 JSON 提取逻辑或 prompt

