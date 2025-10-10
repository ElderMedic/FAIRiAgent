#!/usr/bin/env python3
"""
示例：如何使用集成了LLM的FAIRifier系统

运行前请设置环境变量：
export OPENAI_API_KEY="your-openai-api-key"
export FAIRIFIER_LLM_PROVIDER="openai"
export FAIRIFIER_LLM_MODEL="gpt-4o-mini"
"""

import asyncio
import os
from pathlib import Path

# 设置项目路径
project_root = Path(__file__).parent
import sys
sys.path.append(str(project_root))

from fairifier.graph.workflow import FAIRifierWorkflow
from fairifier.models import FAIRifierState


async def main():
    """演示LLM增强的FAIRifier工作流"""
    
    # 检查API密钥
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("CLAUDE_API_KEY"):
        print("错误：请设置 OPENAI_API_KEY 或 CLAUDE_API_KEY 环境变量")
        print("例如：export OPENAI_API_KEY='your-api-key-here'")
        return
    
    # 示例文档路径
    test_document = project_root / "examples" / "inputs" / "test_document.txt"
    
    if not test_document.exists():
        print(f"警告：测试文档不存在: {test_document}")
        print("请确保有测试文档或修改路径")
        return
    
    # 创建初始状态
    initial_state = FAIRifierState(
        document_path=str(test_document),
        document_content="",
        document_info={},
        retrieved_knowledge=[],
        metadata_fields=[],
        artifacts={},
        validation_results={},
        confidence_scores={},
        needs_human_review=False,
        errors=[]
    )
    
    print("🚀 启动LLM增强的FAIRifier工作流...")
    print(f"📄 处理文档: {test_document.name}")
    print(f"🤖 使用LLM: {os.getenv('FAIRIFIER_LLM_PROVIDER', 'openai')}")
    print(f"📋 模型: {os.getenv('FAIRIFIER_LLM_MODEL', 'gpt-4o-mini')}")
    print("-" * 50)
    
    try:
        # 创建工作流
        workflow = FAIRifierWorkflow()
        
        # 运行工作流
        result = await workflow.run_async(initial_state)
        
        print("✅ 工作流完成！")
        print(f"📊 置信度分数: {result.get('confidence_scores', {})}")
        print(f"🔍 需要人工审核: {result.get('needs_human_review', False)}")
        
        # 显示生成的元数据字段数量
        metadata_fields = result.get('metadata_fields', [])
        print(f"📝 生成的元数据字段数量: {len(metadata_fields)}")
        
        # 显示前几个字段作为示例
        if metadata_fields:
            print("\n📋 生成的元数据字段示例:")
            for i, field in enumerate(metadata_fields[:5]):
                print(f"  {i+1}. {field.get('name', 'N/A')}: {field.get('example_value', 'N/A')}")
            
            if len(metadata_fields) > 5:
                print(f"  ... 还有 {len(metadata_fields) - 5} 个字段")
        
        # 显示验证结果
        validation = result.get('validation_results', {})
        if validation:
            print(f"\n✔️ 验证结果:")
            print(f"  有效: {validation.get('is_valid', False)}")
            print(f"  质量评分: {validation.get('score', 0):.2f}")
            
            errors = validation.get('errors', [])
            if errors:
                print(f"  错误数量: {len(errors)}")
        
        # 显示生成的制品
        artifacts = result.get('artifacts', {})
        if artifacts:
            print(f"\n📦 生成的制品:")
            for artifact_name in artifacts.keys():
                print(f"  - {artifact_name}")
        
        print("\n🎉 处理完成！查看 output/ 目录获取生成的文件。")
        
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        print("请检查API密钥和网络连接")


if __name__ == "__main__":
    asyncio.run(main())