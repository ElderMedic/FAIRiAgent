# 评估分析失败分类说明

## 失败定义更新

根据最新要求，运行失败分为以下三类：

### 1. **成功运行** (Success)
- 有 `metadata_json.json` 文件
- Workflow 完整执行并生成了输出
- **纳入分析**

### 2. **真正的失败** (Genuine Failure)  
- Workflow 完成，但 LLM 输出有问题
- 典型错误：**JSON 解析失败**
- 有 `eval_result.json` 但没有 `metadata_json.json`
- Error 消息包含 "JSON parsing"
- **应该纳入分析和统计**（作为失败案例）

### 3. **不完整运行** (Incomplete - Excluded)
- 由于外部原因未完成
- 典型情况：
  - **Timeout**：网络断线、超时
  - **Metadata 未找到**：Workflow 问题
  - 其他技术问题
- **排除出分析**（不算成功也不算失败）

## 修改内容

### evaluate_outputs.py

已添加 `classify_run_status()` 静态方法来分类运行状态：

```python
@staticmethod
def classify_run_status(run_dir: Path) -> Dict[str, Any]:
    """
    分类运行状态
    
    返回:
        category: 'success', 'genuine_failure', 'incomplete'
        has_metadata: bool
        error_type: 'json_parsing', 'timeout', 'metadata_not_found', etc.
        error_message: str
    """
```

###_load_fairifier_outputs() 方法

修改为：
1. 遍历所有 run_* 目录
2. 使用 `classify_run_status()` 分类每个运行
3. 统计：
   - 成功运行数
   - 真正失败数（JSON 解析错误）
   - 不完整运行数（排除）
4. 只加载成功的运行用于分析
5. 报告统计信息

输出示例：
```
  ✅ Successful: 9
  ❌ Genuine failures: 1 (JSON parsing errors)
  ⏭️  Incomplete (excluded): 2 (timeouts, metadata not found, etc.)
```

## 分析结果影响

### 之前的逻辑
- 只统计有 metadata_json.json 的运行
- 所有没有 metadata 的都被忽略

### 新的逻辑  
- **成功**：有 metadata_json.json → 纳入分析
- **真正失败**：JSON 解析错误 → 纳入统计（作为失败）
- **不完整**：Timeout 等 → 完全排除

## 统计指标

在评估结果中应包含：

```json
{
  "failure_statistics": {
    "total_runs": 10,
    "successful": 8,
    "genuine_failures": 1,
    "incomplete_excluded": 1,
    "by_error_type": {
      "json_parsing": 1,
      "timeout": 1
    }
  }
}
```

## 重新运行分析

修改完成后，重新运行分析：

```bash
python evaluation/analysis/run_analysis.py
```

预期变化：
- Qwen-Flash 的 JSON 解析错误会被标记为"真正的失败"
- Timeout 等会被排除，不影响成功率计算
- 报告中会显示失败分类统计

## 可视化更新

可以添加新的图表：
- 失败类型分布（genuine vs incomplete）
- 每个模型的真正失败率
- 排除不完整运行后的成功率对比

