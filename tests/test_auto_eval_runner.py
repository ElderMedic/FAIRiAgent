import importlib.util
import json
import sys
from pathlib import Path


def _load_runner():
    path = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "prototypes"
        / "auto_repair_classifier"
        / "run_auto_eval.py"
    )
    spec = importlib.util.spec_from_file_location("auto_eval_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_read_target_documents_from_baseline_metadata(tmp_path):
    runner = _load_runner()
    metadata = {
        "per_model_per_document": {
            "model": {
                "doc_b": [],
                "doc_a": [],
            }
        }
    }
    path = tmp_path / "run_metadata.json"
    path.write_text(json.dumps(metadata), encoding="utf-8")

    assert runner.read_target_documents(path) == ["doc_b", "doc_a"]


def test_write_auto_model_config_appends_overrides(tmp_path):
    runner = _load_runner()
    base = tmp_path / "base.env"
    out = tmp_path / "artifacts" / "auto.env"
    base.write_text("LLM_PROVIDER=deepseek\nFAIRIFIER_RETRIEVAL_MODE=tuned\n", encoding="utf-8")

    runner.write_auto_model_config(base, out)
    text = out.read_text(encoding="utf-8")

    assert "LLM_PROVIDER=deepseek" in text
    assert "FAIRIFIER_RETRIEVAL_MODE=auto" in text
    assert "FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=true" in text
    assert "FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true" in text


def test_write_auto_eval_env_appends_overrides_after_base_env(tmp_path):
    runner = _load_runner()
    base = tmp_path / "env.evaluation"
    out = tmp_path / "artifacts" / "env.evaluation.auto"
    base.write_text(
        "FAIRIFIER_RETRIEVAL_MODE=tuned\n"
        "FAIRIFIER_AUTO_REPAIR_ENABLED=false\n",
        encoding="utf-8",
    )

    runner.write_auto_eval_env(base, out)
    merged = runner.parse_env_file(out)

    assert merged["FAIRIFIER_RETRIEVAL_MODE"] == "auto"
    assert merged["FAIRIFIER_AUTO_REPAIR_ENABLED"] == "true"
    assert merged["FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES"] == "true"
    assert merged["FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED"] == "true"


def test_build_batch_command_includes_documents_and_paths(tmp_path):
    runner = _load_runner()
    cmd = runner.build_batch_command(
        python_exe="python",
        eval_env=tmp_path / "env.evaluation.auto",
        model_config=tmp_path / "auto.env",
        ground_truth=tmp_path / "ground_truth.json",
        output_dir=tmp_path / "auto_pro_tuned",
        documents=["doc_a", "doc_b"],
        timeout=123,
        workers=2,
    )

    assert cmd[:2] == [
        "python",
        str(runner.PROJECT_ROOT / "evaluation" / "scripts" / "run_batch_evaluation.py"),
    ]
    assert "--include-documents" in cmd
    assert cmd[-2:] == ["doc_a", "doc_b"]
    assert cmd[cmd.index("--timeout") + 1] == "123"
    assert cmd[cmd.index("--workers") + 1] == "2"


def test_mirror_results_layout(tmp_path):
    runner = _load_runner()
    output_dir = tmp_path / "auto_pro_tuned"
    output_dir.mkdir()
    root_result = output_dir / "evaluation_results.json"
    root_result.write_text('{"ok": true}', encoding="utf-8")

    runner.mirror_results_layout(output_dir)

    mirrored = output_dir / "results" / "evaluation_results.json"
    assert mirrored.read_text(encoding="utf-8") == '{"ok": true}'


def test_preflight_check_passes_for_local_files(tmp_path):
    runner = _load_runner()
    doc_path = tmp_path / "doc.pdf"
    doc_path.write_text("pdf placeholder", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(doc_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    model_config = tmp_path / "model.env"
    model_config.write_text("LLM_PROVIDER=deepseek\n", encoding="utf-8")
    eval_env = tmp_path / "env.auto"
    eval_env.write_text(
        "FAIRIFIER_RETRIEVAL_MODE=auto\n"
        "FAIRIFIER_AUTO_REPAIR_ENABLED=true\n"
        "FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=true\n"
        "FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true\n",
        encoding="utf-8",
    )

    report = runner.preflight_check(
        eval_env=eval_env,
        model_config=model_config,
        ground_truth=ground_truth,
        output_dir=tmp_path / "out",
        documents=["doc_a"],
    )

    assert report["passed"] is True


def test_mineru_readiness_detects_preconverted_markdown(tmp_path):
    runner = _load_runner()
    source = tmp_path / "paper.pdf"
    source.write_text("pdf placeholder", encoding="utf-8")
    markdown = tmp_path / "mineru_paper" / "paper" / "vlm" / "paper.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Converted", encoding="utf-8")

    report = runner.mineru_readiness_for_document(source)

    assert report["preconverted"] is True
    assert report["requires_mineru"] is False


def test_mineru_readiness_reports_missing_preconversion(tmp_path):
    runner = _load_runner()
    source = tmp_path / "paper.pdf"
    source.write_text("pdf placeholder", encoding="utf-8")

    report = runner.mineru_readiness_for_document(source)

    assert report["preconverted"] is False
    assert report["requires_mineru"] is True
    assert report["missing_sources"] == [str(source)]


def test_preflight_service_check_reports_mineru_missing_inputs(tmp_path):
    runner = _load_runner()
    doc_path = tmp_path / "paper.pdf"
    doc_path.write_text("pdf placeholder", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(doc_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    model_config = tmp_path / "model.env"
    model_config.write_text("LLM_PROVIDER=deepseek\n", encoding="utf-8")
    eval_env = tmp_path / "env.auto"
    eval_env.write_text(
        "FAIRIFIER_RETRIEVAL_MODE=auto\n"
        "FAIRIFIER_AUTO_REPAIR_ENABLED=true\n"
        "FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=true\n"
        "FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true\n"
        "FAIR_DS_API_URL=\n"
        "MINERU_SERVER_URL=\n",
        encoding="utf-8",
    )

    report = runner.preflight_check(
        eval_env=eval_env,
        model_config=model_config,
        ground_truth=ground_truth,
        output_dir=tmp_path / "out",
        documents=["doc_a"],
        check_services=True,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["document_mineru_preconverted:doc_a"]["passed"] is False
    assert checks["service_reachable:MINERU_SERVER_URL"]["passed"] is False
    assert "missing preconverted inputs" in checks["service_reachable:MINERU_SERVER_URL"]["detail"]
    assert report["summary"]["missing_mineru_documents"] == ["doc_a"]
    blocker_keys = {
        blocker["key"] for blocker in report["summary"]["blocked_requirements"]
    }
    assert "mineru_missing_docs" in blocker_keys
    assert "mineru_service" in blocker_keys


def test_preflight_reports_local_preconvert_dependency_when_mineru_unreachable(
    tmp_path,
    monkeypatch,
):
    runner = _load_runner()
    doc_path = tmp_path / "paper.pdf"
    doc_path.write_text("pdf placeholder", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(doc_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    model_config = tmp_path / "model.env"
    model_config.write_text("LLM_PROVIDER=deepseek\n", encoding="utf-8")
    eval_env = tmp_path / "env.auto"
    eval_env.write_text(
        "FAIRIFIER_RETRIEVAL_MODE=auto\n"
        "FAIRIFIER_AUTO_REPAIR_ENABLED=true\n"
        "FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=true\n"
        "FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true\n"
        "FAIR_DS_API_URL=http://fairds.test\n"
        "MINERU_SERVER_URL=http://mineru.test\n",
        encoding="utf-8",
    )

    def fake_reachable(url):
        if "mineru.test" in url:
            return "unreachable:down"
        return "reachable"

    monkeypatch.setattr(runner, "_check_url_reachable", fake_reachable)
    monkeypatch.setattr(
        "fairifier.services.mineru_health.importlib.util.find_spec",
        lambda name: None,
    )

    report = runner.preflight_check(
        eval_env=eval_env,
        model_config=model_config,
        ground_truth=ground_truth,
        output_dir=tmp_path / "out",
        documents=["doc_a"],
        check_services=True,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["local_mineru_preconvert_dependencies"]["passed"] is False
    assert (
        checks["local_mineru_preconvert_dependencies"]["detail"]
        == "missing_python_module:doclayout_yolo"
    )
    dependency_blocker = next(
        item
        for item in report["summary"]["blocked_requirements"]
        if item["key"] == "mineru_preconvert_dependency"
    )
    assert dependency_blocker["dependency_errors"] == [
        "missing_python_module:doclayout_yolo"
    ]
    assert dependency_blocker["install_hint"] == (
        "pip install 'mineru[pipeline]>=3.4.0,<4'"
    )
    assert "auto_configuration" not in {
        item["key"] for item in report["summary"]["blocked_requirements"]
    }


def test_preflight_service_check_includes_qdrant_and_embedding(tmp_path, monkeypatch):
    runner = _load_runner()
    doc_path = tmp_path / "doc.md"
    doc_path.write_text("# no mineru needed", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(doc_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    model_config = tmp_path / "model.env"
    model_config.write_text("LLM_PROVIDER=deepseek\n", encoding="utf-8")
    eval_env = tmp_path / "env.auto"
    eval_env.write_text(
        "FAIRIFIER_RETRIEVAL_MODE=auto\n"
        "FAIRIFIER_AUTO_REPAIR_ENABLED=true\n"
        "FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=true\n"
        "FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true\n"
        "FAIR_DS_API_URL=http://fairds.test\n"
        "MINERU_SERVER_URL=http://mineru.test\n"
        "MEM0_ENABLED=true\n"
        "MEM0_QDRANT_HOST=localhost\n"
        "MEM0_QDRANT_PORT=6335\n"
        "FAIRIFIER_SEMANTIC_INDEX_ENABLED=true\n"
        "FAIRIFIER_RETRIEVAL_EMBEDDING_BACKEND=ollama\n"
        "FAIRIFIER_RETRIEVAL_EMBEDDING_BASE_URL=http://ollama.test\n",
        encoding="utf-8",
    )

    def fake_reachable(url):
        if "ollama.test" in url:
            return "unreachable:down"
        return "reachable"

    monkeypatch.setattr(runner, "_check_url_reachable", fake_reachable)

    report = runner.preflight_check(
        eval_env=eval_env,
        model_config=model_config,
        ground_truth=ground_truth,
        output_dir=tmp_path / "out",
        documents=["doc_a"],
        check_services=True,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["service_reachable:QDRANT"]["passed"] is True
    assert "http://localhost:6335/readyz" in checks["service_reachable:QDRANT"]["detail"]
    assert checks["service_reachable:RETRIEVAL_EMBEDDING"]["passed"] is False
    assert "http://ollama.test/api/tags" in checks["service_reachable:RETRIEVAL_EMBEDDING"]["detail"]
    assert report["summary"]["failed_services"] == {
        "RETRIEVAL_EMBEDDING": "http://ollama.test/api/tags: unreachable:down"
    }
    assert [
        blocker["key"] for blocker in report["summary"]["blocked_requirements"]
    ] == ["retrieval_embedding"]


def test_preflight_check_fails_when_auto_mode_missing(tmp_path):
    runner = _load_runner()
    doc_path = tmp_path / "doc.pdf"
    doc_path.write_text("pdf placeholder", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(doc_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    model_config = tmp_path / "model.env"
    model_config.write_text("LLM_PROVIDER=deepseek\n", encoding="utf-8")
    eval_env = tmp_path / "env.not_auto"
    eval_env.write_text(
        "FAIRIFIER_RETRIEVAL_MODE=tuned\n"
        "FAIRIFIER_AUTO_REPAIR_ENABLED=false\n"
        "FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=false\n",
        encoding="utf-8",
    )

    report = runner.preflight_check(
        eval_env=eval_env,
        model_config=model_config,
        ground_truth=ground_truth,
        output_dir=tmp_path / "out",
        documents=["doc_a"],
    )

    assert report["passed"] is False
    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "retrieval_mode_auto" in failed
    assert "auto_repair_enabled" in failed
    assert "auto_repair_classifier_shadow_enabled" in failed


def test_write_preflight_report_writes_json_and_markdown(tmp_path):
    runner = _load_runner()
    report = {
        "passed": False,
        "checks": [
            {
                "name": "service_reachable:FAIR_DS_API_URL",
                "passed": False,
                "detail": "unreachable",
            }
        ],
        "summary": {
            "blocked_requirements": [
                {
                    "key": "mineru_preconvert_dependency",
                    "detail": "local MinerU preconversion dependency is missing",
                    "dependency_errors": ["missing_python_module:doclayout_yolo"],
                    "install_hint": "pip install 'mineru[pipeline]>=3.4.0,<4'",
                    "documents": ["pea_cold_stress"],
                    "service": "MINERU_SERVER_URL",
                }
            ]
        },
    }
    path = tmp_path / "artifacts" / "auto_eval_preflight_report.json"

    runner.write_preflight_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8")) == report
    markdown = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "Status: **fail**" in markdown
    assert "FAIL `service_reachable:FAIR_DS_API_URL`: unreachable" in markdown
    assert "`missing_python_module:doclayout_yolo`" in markdown
    assert "`pip install 'mineru[pipeline]>=3.4.0,<4'`" in markdown
    assert "`pea_cold_stress`" in markdown
    assert "`MINERU_SERVER_URL`" in markdown
