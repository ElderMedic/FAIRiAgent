# FAIRiAgent Baseline 设计方案摘要

**日期**: 2026年1月29日  
**版本**: 1.0

---

## 概述

为了全面评估 FAIRiAgent 的多智能体工作流性能，我们设计了 **5种baseline方法**，从简单的单次提示到复杂的RAG增强方法，使用相同的评估指标和数据集进行对比。

---

## 评估指标（来自现有evaluation框架）

| 类别 | 指标 | 说明 |
|------|------|------|
| **完整性** | Overall, Required, Recommended | 字段覆盖率 vs 真值 |
| **正确性** | Precision, Recall, F1-Score | 字段提取准确性 |
| **质量** | Adjusted Precision, Adjusted F1 | 考虑置信度的指标 |
| **可靠性** | 成功率, 重试率 | 工作流稳健性 |
| **效率** | 运行时间, Token使用量, 成本 | 资源消耗 |
| **Pass@k** | Pass@1, Pass@5, Pass@10 | k次尝试的成功概率 |

---

## 5种Baseline方法

### Baseline 1: 单次提示（已实现）✅

**特点**:
- 一次性LLM调用，包含所有指令和schema要求
- 无迭代改进、无验证循环、无critic反馈
- 快速（15-30秒/文档）、简单实现

**预期性能**:
- 完整性: 35-50%
- F1分数: 0.45-0.60
- 运行时间: 15-30秒

**实现状态**: ✅ 已完成 (`evaluation/scripts/baseline_single_prompt.py`)

---

### Baseline 2: Few-Shot提示（待实现）🆕

**特点**:
- 单次提示 + 2-3个样例
- 展示期望的输出结构和字段级细节
- 仍无迭代或验证

**预期性能**:
- 完整性: 45-60% (+10-15% vs Baseline 1)
- F1分数: 0.50-0.65
- 运行时间: 20-40秒

**优先级**: 🔥 高（第2阶段）

---

### Baseline 3: 链式思维推理（待实现）🆕

**特点**:
- 使用O1/O3模型或显式CoT提示
- 逐步推理和自我解释
- 更好处理复杂字段

**预期性能**:
- 完整性: 50-65%
- F1分数: 0.55-0.70
- 运行时间: 60-120秒（O1/O3较慢）

**优先级**: 🔥 中（第3阶段）

---

### Baseline 4: 两阶段（生成+验证）（待实现）🆕

**特点**:
- 阶段1: 提取元数据（类似Baseline 1）
- 阶段2: Schema验证（独立LLM调用）
- 基础质量检查，但无带反馈的重试

**预期性能**:
- 完整性: 40-55%
- F1分数: 0.50-0.65
- 运行时间: 25-50秒（2次LLM调用）

**优先级**: 🔥 中（第3阶段）

---

### Baseline 5: RAG增强单次提示（待实现）🆕

**特点**:
- 检索相关本体术语（ENVO, NCBI分类）
- 检索schema字段定义
- 上下文感知提取，但无迭代

**预期性能**:
- 完整性: 55-70% (最强baseline)
- F1分数: 0.60-0.75
- 运行时间: 30-60秒

**优先级**: 🔥 **最高**（第1阶段）- 最具竞争力的baseline

---

## 对比矩阵

| Baseline类型 | 复杂度 | 预期完整性 | 预期F1 | 运行时间 | 状态 |
|-------------|-------|-----------|--------|---------|------|
| **1. 单次提示** | ⭐ | 35-50% | 0.45-0.60 | 15-30s | ✅ 完成 |
| **2. Few-Shot** | ⭐⭐ | 45-60% | 0.50-0.65 | 20-40s | 🔲 待实现 |
| **3. CoT推理** | ⭐⭐ | 50-65% | 0.55-0.70 | 60-120s | 🔲 待实现 |
| **4. 两阶段** | ⭐⭐⭐ | 40-55% | 0.50-0.65 | 25-50s | 🔲 待实现 |
| **5. RAG增强** | ⭐⭐⭐⭐ | 55-70% | 0.60-0.75 | 30-60s | 🔲 待实现 |
| **FAIRiAgent** | ⭐⭐⭐⭐⭐ | **70-85%** | **0.75-0.85** | 400-600s | ✅ 主系统 |

---

## 实施路线图

### 第1阶段：关键Baseline（第1-2周）

**优先实现**:
1. ✅ **Baseline 1 (单次提示)** - 已完成
2. 🔲 **Baseline 5 (RAG增强)** - 最强竞争对手，优先对比
3. 🔲 **Baseline 2 (Few-Shot)** - 文献中常见方法

### 第2阶段：专门Baseline（第3周）

4. 🔲 **Baseline 3 (CoT)** - 测试推理能力
5. 🔲 **Baseline 4 (两阶段)** - 隔离验证组件

### 第3阶段：评估与分析（第4周）

- 运行所有evaluators
- 计算完整性、正确性、可靠性指标
- 计算Pass@k指标
- 生成对比可视化
- 统计显著性检验
- 创建LaTeX表格（用于论文）

---

## 快速开始

### 1. 运行现有Baseline 1

```bash
# 在所有文档上运行baseline 1
bash evaluation/scripts/run_baseline_all.sh
```

### 2. 实现新Baseline（以Baseline 5为例）

```bash
# 创建新脚本
touch evaluation/baselines/baseline_5_rag.py

# 参考模板
# - 复制 baseline_single_prompt.py
# - 添加知识检索步骤
# - 将检索到的上下文格式化到提示中
# - 单次LLM调用（无迭代）
```

### 3. 运行批量评估

```bash
python evaluation/baselines/run_baseline_5.py \
  --config-file evaluation/config/model_configs/openai_gpt4o.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_filtered.json \
  --output-dir evaluation/runs/baseline_5_rag \
  --workers 5 \
  --n-runs 10
```

### 4. 评估结果

```bash
python evaluation/scripts/evaluate_outputs.py \
  --run-dir evaluation/runs/baseline_5_rag \
  --ground-truth evaluation/datasets/annotated/ground_truth_filtered.json
```

### 5. 生成对比报告

```bash
python evaluation/analysis/run_analysis.py \
  --runs-dir evaluation/runs \
  --output-dir evaluation/analysis/output/baseline_comparison
```

---

## 预期成果

### 主要假设

**H1: 完整性提升**
- FAIRiAgent比最佳baseline（RAG增强）高 **+20-35%**
- 单次提示: 35-50% → RAG增强: 55-70% → **FAIRiAgent: 70-85%**

**H2: 正确性提升**
- FAIRiAgent的F1分数比最佳baseline高 **+0.10-0.20**
- 单次提示: 0.45-0.60 → RAG增强: 0.60-0.75 → **FAIRiAgent: 0.75-0.85**

**H3: 可靠性提升**
- FAIRiAgent成功率 **>85%**，尽管更复杂

**H4: 质量-时间权衡**
- FAIRiAgent的 **10-20倍运行时间** 被质量提升所证明
- 对于发表级质量的元数据，额外开销是可接受的

**H5: 组件价值分析**（消融研究）
- Few-shot: +5-10% 完整性
- CoT: +10-15% 完整性
- RAG: +15-20% 完整性
- 迭代: +15-20% 完整性（agentic vs RAG baseline）

---

## 评估数据集

使用现有ground truth:
- **Earthworm**: 基因组学/宏基因组学数据集
- **Haarika+Bhamidipati**: 控制数据集
- **BIOREM**: 生物修复留出数据集

每个数据集包含:
- Ground truth注释 (`ground_truth_filtered.json`)
- Required/recommended/optional字段分类
- ISA-Tab结构期望
- Package特定要求

---

## 关键优势

### 1. 全面覆盖
✅ 从简单到复杂的方法  
✅ 多种技术: Few-shot, CoT, 两阶段, RAG  
✅ 公平对比: 相同数据、指标、评估流程  
✅ 消融研究: 可以隔离组件贡献  

### 2. 可重现性
✅ 相同基础设施: 重用现有评估pipeline  
✅ 相同指标: CompletenessEvaluator, CorrectnessEvaluator等  
✅ 相同Ground Truth: 一致的注释  
✅ 版本控制: 所有baseline在git中  

### 3. 适合发表
✅ 严格: 多个baseline，统计检验  
✅ 透明: 清晰的方法论，开源  
✅ 可视化: 发表级质量的图表  
✅ 表格: LaTeX格式的对比表格  

---

## 时间线

| 周次 | 任务 | 交付成果 |
|------|------|----------|
| **第1周** | 实现baselines 2-5，测试 | 可工作的baseline脚本 |
| **第2周** | 运行批量评估 | 原始baseline输出 |
| **第3周** | 评估和分析结果 | 指标、图表、表格 |
| **第4周** | 撰写对比报告 | 论文就绪材料 |

---

## 文档链接

### 详细设计文档
📄 `docs/en/BASELINE_DESIGN_PLAN.md` - 完整英文设计方案（41页）

### 现有文档
- `evaluation/README.md` - 评估框架概述
- `docs/en/EVALUATION_METHODOLOGY.md` - 指标和工作流
- `evaluation/archive/docs/BASELINE_VS_AGENTIC_COMPARISON.md` - Baseline 1结果

### 关键脚本
- `evaluation/scripts/baseline_single_prompt.py` - Baseline 1实现
- `evaluation/scripts/run_baseline_batch.py` - 批量运行器
- `evaluation/evaluators/*.py` - 评估指标
- `evaluation/analysis/run_analysis.py` - 主分析pipeline

---

## 下一步行动

### 立即行动（本周）

1. ✅ **审阅设计方案** - 与团队讨论
2. 🔲 **实现Baseline 5 (RAG)** - 最高优先级
3. 🔲 **实现Baseline 2 (Few-Shot)** - 第二优先级
4. 🔲 **测试单次运行** - 验证每个baseline
5. 🔲 **启动批量评估** - 预计2-3天计算时间

### 中期目标（2-3周）

1. 🔲 完成所有5个baseline的实现
2. 🔲 运行批量评估（10 runs × 3 docs × 5 baselines）
3. 🔲 评估所有输出
4. 🔲 生成对比可视化

### 长期目标（1个月）

1. 🔲 完成统计分析
2. 🔲 撰写对比报告
3. 🔲 准备论文材料（图表、表格）
4. 🔲 验证假设

---

## 成功标准

baseline对比将被认为**成功**，如果:

1. ✅ 所有5个baseline在3个文档×10次运行上实现和测试
2. ✅ FAIRiAgent在主要指标上优于所有baseline（完整性、F1）
3. ✅ 关键对比达到统计显著性（p < 0.05）
4. ✅ 获得消融研究洞察：哪些组件贡献最大
5. ✅ 论文就绪结果：图表、表格和文本准备好用于手稿

---

## 联系与支持

- **详细设计**: 见 `docs/en/BASELINE_DESIGN_PLAN.md`
- **实施指南**: 见 `evaluation/baselines/README.md`
- **问题讨论**: 与研究团队联系

---

**文档状态**: 📝 草案 v1.0  
**审阅状态**: 待团队审阅  
**实施状态**: Baseline 1 ✅ | Baselines 2-5 🔲
