from fairifier.agents.critic import safe_json_parse


def test_safe_json_parse_handles_code_fence():
    payload = """```json
    {
      "score": 0.82,
      "decision": "accept",
      "issues": [],
      "improvement_ops": []
    }
    ```"""
    parsed = safe_json_parse(payload)
    assert parsed is not None
    assert parsed["score"] == 0.82
    assert parsed["decision"] == "accept"

