# LangSmith Testing Guide for FAIRiAgent

## 🎯 Overview

LangSmith is LangChain's official debugging and monitoring platform that provides powerful tools for testing, debugging, and optimizing LangGraph-based multi-agent systems like FAIRiAgent.

## 🚀 Quick Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get LangSmith API Key

1. Go to [LangSmith](https://smith.langchain.com/)
2. Sign up for an account
3. Navigate to Settings → API Keys
4. Create a new API key
5. Copy the API key

### 3. Configure Environment

```bash
# Copy the example environment file
cp env.example .env

# Edit .env and add your LangSmith API key
export LANGSMITH_API_KEY="your_api_key_here"
export LANGSMITH_PROJECT="fairifier-testing"
```

### 4. Run Tests

```bash
# Run the LangSmith test script
python test_langsmith.py
```

## 📊 What You'll See in LangSmith

### 1. **Trace Visualization**
- Complete workflow execution flow
- Individual agent performance
- Token usage and costs
- Timing information

### 2. **Debug Information**
- Input/output for each agent
- Error messages and stack traces
- Intermediate state changes
- Confidence scores

### 3. **Performance Metrics**
- Execution time per agent
- Token consumption
- Cost analysis
- Success/failure rates

### 4. **Agent Interactions**
- How agents communicate
- State transitions
- Conditional logic flow
- Human-in-the-loop triggers

## 🔧 Testing Scenarios

### Basic Document Processing
```bash
python test_langsmith.py
```

### Custom Document Testing
```python
from test_langsmith import LangSmithTester
import asyncio

async def test_custom_document():
    tester = LangSmithTester()
    result = await tester.test_document_processing("path/to/your/document.pdf")
    print(f"Result: {result}")

asyncio.run(test_custom_document())
```

### Individual Agent Testing
```python
# Test specific agents in isolation
tester = LangSmithTester()
result = await tester.test_workflow_nodes("document.pdf")
```

## 📈 LangSmith Dashboard Features

### 1. **Projects View**
- Organize tests by project
- Compare different runs
- Track performance over time

### 2. **Runs View**
- Detailed execution traces
- Step-by-step debugging
- Error analysis

### 3. **Datasets View**
- Create test datasets
- Batch testing
- Performance benchmarking

### 4. **Evaluations View**
- Automated testing
- Quality metrics
- Regression testing

## 🎯 Best Practices

### 1. **Organize Your Tests**
- Use descriptive project names
- Group related tests together
- Tag runs with metadata

### 2. **Monitor Performance**
- Track token usage
- Monitor execution times
- Set up alerts for failures

### 3. **Debug Effectively**
- Use trace visualization
- Check intermediate states
- Analyze error patterns

### 4. **Optimize Workflows**
- Identify bottlenecks
- Reduce token usage
- Improve accuracy

## 🔍 Troubleshooting

### Common Issues

1. **API Key Not Working**
   ```bash
   # Check environment variables
   echo $LANGSMITH_API_KEY
   ```

2. **No Traces Appearing**
   ```bash
   # Ensure tracing is enabled
   export LANGCHAIN_TRACING_V2=true
   ```

3. **Project Not Found**
   ```bash
   # Check project name
   export LANGCHAIN_PROJECT=fairifier-testing
   ```

### Debug Mode
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Run with detailed logging
python test_langsmith.py
```

## 📚 Advanced Features

### 1. **Custom Evaluations**
```python
from langsmith.evaluation import evaluate

def custom_evaluator(run, example):
    # Your custom evaluation logic
    return {"score": 0.95, "reason": "High confidence"}

# Run evaluation
evaluate(
    lambda inputs: your_function(inputs),
    data=your_dataset,
    evaluators=[custom_evaluator]
)
```

### 2. **Batch Testing**
```python
# Test multiple documents
documents = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
for doc in documents:
    result = await tester.test_document_processing(doc)
```

### 3. **Performance Monitoring**
```python
# Monitor specific metrics
runs = tester.get_langsmith_runs(limit=100)
for run in runs:
    analysis = tester.analyze_run(str(run.id))
    print(f"Tokens: {analysis.get('total_tokens')}")
    print(f"Cost: {analysis.get('total_cost')}")
```

## 🎉 Next Steps

1. **Explore the Dashboard**: Check out all the visualization tools
2. **Create Datasets**: Upload test documents for batch testing
3. **Set Up Evaluations**: Create automated quality checks
4. **Monitor Performance**: Track improvements over time
5. **Optimize Workflows**: Use insights to improve your agents

## 📞 Support

- [LangSmith Documentation](https://docs.smith.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [FAIRiAgent Issues](https://github.com/your-repo/issues)

---

**Happy Testing! 🚀**
