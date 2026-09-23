import json
from pathlib import Path

from fairifier.utils.json_logger import JSONLogger, save_processing_log


def test_save_processing_log_keeps_disk_events_and_memory_summary(
    tmp_path: Path,
):
    log_path = tmp_path / "logs" / "processing_log.jsonl"
    log_path.parent.mkdir()
    disk_event = {
        "event": "critic_evaluation",
        "timestamp": "2026-08-27T10:00:00",
        "agent_name": "DocumentParser",
        "critic_evaluation": {"decision": "ACCEPT", "score": 0.9},
    }
    log_path.write_text(json.dumps(disk_event) + "\n", encoding="utf-8")

    logger = JSONLogger(component="test", enable_stdout=False)
    logger.info(
        "processing_summary",
        status="completed",
        errors=["e0", "e1"],
        error_count=2,
    )
    save_processing_log(log_path, logger)

    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    names = [item.get("event") for item in events]
    assert "critic_evaluation" in names
    assert "processing_summary" in names
    summary = next(
        item for item in events if item["event"] == "processing_summary"
    )
    assert summary["errors"] == ["e0", "e1"]
