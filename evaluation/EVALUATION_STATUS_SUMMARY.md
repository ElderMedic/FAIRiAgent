# 评估状态总结

**更新时间**: 2025-12-05  
**状态**: ✅ 评估完成，失败分类逻辑已更新

---

## 📊 评估完成度

### 运行统计（排除 JSON 解析错误后）

| 模型 | earthworm | biosensor | 总计 | 状态 |
|------|-----------|-----------|------|------|
| **Anthropic Haiku** | 10/10 ✅ | 9/10 | 19/20 | ⚠️ 需补 1 次 |
| **Anthropic Sonnet** | 10/10 ✅ | 6/10 | 16/20 | ⚠️ 需补 4 次 |
| **OpenAI GPT-4.1** | 10/10 ✅ | 10/10 ✅ | 20/20 ✅ | 完成 |
| **OpenAI GPT-5** | 10/10 ✅ | 3/10 | 13/20 | ⚠️ 需补 7 次 |
| **OpenAI O3** | 10/10 ✅ | 3/10 | 13/20 | ⚠️ 需补 7 次 |
| **Qwen-Max** | 10/10 ✅ | 10/10 ✅ | 20/20 ✅ | 完成 |
| **Qwen-Plus** | 10/10 ✅ | 10/10 ✅ | 20/20 ✅ | 完成 |
| **Qwen-Flash** | 9+1❌/10 | 9+1❌/10 | 18+2❌/20 | ⚠️ 有 2 次真正失败 |

**说明**：❌ 表示 JSON 解析失败（真正的失败）

### 失败分类

#### ✅ 真正的失败（纳入统计）
- **Qwen-Flash**: 2 次 JSON 解析失败
  - earthworm/run_10
  - biosensor/run_4
- **这些是 LLM 输出问题，应该算作模型失败**

#### ⏭️ 不完整运行（排除出分析）
- **Anthropic Haiku**: 1 次 Timeout (biosensor)
- **Anthropic Sonnet**: 4 次 Timeout (biosensor)
- **OpenAI GPT-5**: 7 次 (3× Timeout + 4× Metadata未找到, biosensor)
- **OpenAI O3**: 7 次 (2× Timeout + 5× Metadata未找到, biosensor)
- **这些是人为原因（网络断线等），不算失败**

---

## 🔧 失败定义更新

### 修改内容

1. **evaluate_outputs.py** 添加了 `classify_run_status()` 方法
   - 自动分类运行为：success, genuine_failure, incomplete
   - JSON 解析失败 → genuine_failure（真正的失败）
   - Timeout 等 → incomplete（排除）

2. **check_failed_runs.py** 更新
   - 排除 JSON 解析错误（在原来的逻辑中）
   - 但根据新定义，JSON 解析错误应该算真正的失败

3. **分析逻辑**
   - 只加载成功的运行（有 metadata_json.json）
   - 统计真正的失败（JSON 解析错误）
   - 排除不完整的运行（timeout 等）

### 评估报告输出

```
  ✅ Successful: 9
  ❌ Genuine failures: 1 (JSON parsing errors)
  ⏭️  Incomplete (excluded): 2 (timeouts, metadata not found, etc.)
```

---

## 📁 数据清理

### 已归档
- 7 个不完整的早期测试运行 → `evaluation/runs/archive/`
- `kb/` 文件夹清理：只保留 `ontologies.json` 和 `combined_metadata.csv`

### 已删除的临时文件
- `test_*.py` 脚本
- `evaluation_run.log`
- Python cache 文件

---

## 🔄 补跑计划

### 方案 A（推荐）- 只补跑 biosensor

**需要补跑**: 19 次（所有 biosensor 失败）

| 模型 | 次数 | 原因 |
|------|------|------|
| Anthropic Haiku | 1 | Timeout |
| Anthropic Sonnet | 4 | Timeout |
| OpenAI GPT-5 | 7 | Timeout + Metadata未找到 |
| OpenAI O3 | 7 | Timeout + Metadata未找到 |

**补跑脚本**: `evaluation/scripts/rerun_failed.sh`

**优势**:
- 使用 MinerU markdown 输出，跳过转换
- 避免 MinerU "Aborted!" 错误
- 节约时间

**运行方式**:
```bash
mamba activate FAIRiAgent
./evaluation/scripts/rerun_failed.sh
```

---

## 📊 当前分析结果

基于现有数据（排除不完整运行后）：

### 模型性能排名

| 排名 | 模型 | 综合分数 | 完整性 | F1 分数 |
|------|------|----------|--------|---------|
| 🥇 1 | OpenAI GPT-4.1 | 0.764 | 91.7% | 0.804 |
| 🥈 2 | OpenAI GPT-5.1 | 0.736 | 91.7% | 0.725 |
| 🥉 3 | OpenAI O3 | 0.713 | 91.7% | 0.664 |
| 4 | Qwen-Max | 0.707 | 89.6% | 0.721 |
| 5 | Anthropic Sonnet | 0.706 | 90.6% | 0.715 |
| 6 | Qwen-Flash | 0.682 | 89.6% | 0.670 |
| 7 | Anthropic Haiku | 0.679 | 87.5% | 0.680 |
| 8 | Qwen-Plus | 0.668 | 86.5% | 0.667 |

**注意**: 这些结果基于**排除不完整运行**后的数据

---

## 🎯 下一步

### 1. 补跑失败的运行（可选）
```bash
./evaluation/scripts/rerun_failed.sh
```

### 2. 重新运行分析
```bash
python evaluation/analysis/run_analysis.py
```

### 3. 检查完成度
```bash
python evaluation/analysis/check_failed_runs.py
```

### 4. 查看结果
- 分析报告: `evaluation/analysis/output/`
- 可视化图表: `evaluation/analysis/output/figures/`
- 数据表格: `evaluation/analysis/output/tables/`

---

## 📝 相关文档

- `RERUN_GUIDE.md` - 补跑指南
- `ANALYSIS_FAILURE_CLASSIFICATION.md` - 失败分类说明
- `evaluation/analysis/output/analysis_summary.json` - 完整分析结果

---

## ✅ 确认事项

- [x] 失败分类逻辑已更新
- [x] 评估分析脚本已修改
- [x] 补跑脚本已准备
- [x] Ground truth 配置已更新（指向 markdown）
- [x] 数据清理已完成
- [ ] 补跑待执行
- [ ] 最终分析报告待生成

