#!/usr/bin/env python3
"""Historical aggregate evaluator for FAIRiAgent outputs.

The version-2 benchmark entry point is
``python -m evaluation.benchmark.evaluate_run_index``.  This compatibility
script is deliberately single-run-per-document: it refuses to select a
"best" repetition, because doing so removes failures from the denominator and
invalidates reliability estimates.
"""

import sys
import argparse
import json
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import os

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path=None, override=False):
        if path is None:
            return False
        env_path = Path(path)
        if not env_path.exists():
            return False
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if override or key not in os.environ:
                os.environ[key] = value
        return True

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parents[2]))

from fairifier.output_paths import resolve_metadata_output_read_path
from evaluation.evaluators import find_source_text

class EvaluationOrchestrator:
    """Orchestrate all evaluations on FAIRiAgent outputs."""
    
    @staticmethod
    def classify_run_status(run_dir: Path) -> Dict[str, Any]:
        """
        Classify a run's status based on its output files.
        
        Returns status dict with:
        - 'category': 'success', 'genuine_failure', 'incomplete' (excluded from analysis)
        - 'has_metadata': bool
        - 'error_type': str or None
        - 'error_message': str or None
        """
        status = {
            'category': 'incomplete',
            'has_metadata': False,
            'metadata_path': None,
            'error_type': None,
            'error_message': None
        }
        
        metadata_file = resolve_metadata_output_read_path(run_dir)
        eval_result_file = run_dir / 'eval_result.json'
        
        # Check if metadata exists
        if metadata_file is not None:
            status['has_metadata'] = True
            status['category'] = 'success'
            status['metadata_path'] = metadata_file
            return status
        
        # Check eval_result.json for error information
        if eval_result_file.exists():
            try:
                with open(eval_result_file, 'r', encoding='utf-8') as f:
                    eval_result = json.load(f)
                    error_msg = eval_result.get('error', '').lower()
                    
                    # JSON parsing failure = genuine failure (LLM output problem)
                    if 'json parsing' in error_msg or 'json' in error_msg and 'parsing' in error_msg:
                        status['category'] = 'genuine_failure'
                        status['error_type'] = 'json_parsing'
                        status['error_message'] = eval_result.get('error')
                    # Timeout = incomplete (external issue, exclude from analysis)
                    elif 'timeout' in error_msg or 'timed out' in error_msg:
                        status['category'] = 'incomplete'
                        status['error_type'] = 'timeout'
                        status['error_message'] = eval_result.get('error')
                    # Metadata not found = incomplete (workflow issue, exclude from analysis)
                    elif 'not found' in error_msg and 'metadata' in error_msg:
                        status['category'] = 'incomplete'
                        status['error_type'] = 'metadata_not_found'
                        status['error_message'] = eval_result.get('error')
                    # Other errors = incomplete by default
                    else:
                        status['category'] = 'incomplete'
                        status['error_type'] = 'other'
                        status['error_message'] = eval_result.get('error')
            except Exception as e:
                status['error_message'] = f"Failed to parse eval_result.json: {e}"
        
        return status
    
    def __init__(
        self,
        run_dir: Path,
        ground_truth_path: Path,
        env_file: Path
    ):
        """
        Initialize evaluation orchestrator.
        
        Args:
            run_dir: Directory containing batch evaluation outputs
            ground_truth_path: Path to ground truth JSON
            env_file: Evaluation env file (for LLM judge config)
        """
        self.run_dir = run_dir
        self.ground_truth_path = ground_truth_path
        self.env_file = env_file
        
        # Load environment
        load_dotenv(env_file)
        
        # Load ground truth
        with open(ground_truth_path, 'r', encoding='utf-8') as f:
            gt_data = json.load(f)
            self.ground_truth_docs = {
                doc['document_id']: doc 
                for doc in gt_data.get('documents', [])
            }
        
        print(f"📊 Loaded ground truth for {len(self.ground_truth_docs)} documents")
        
        # Initialize evaluators
        self._initialize_evaluators()
    
    def _initialize_evaluators(self):
        """Initialize all evaluators."""
        from evaluation.evaluators import (
            CompletenessEvaluator,
            CorrectnessEvaluator,
            SchemaValidator,
            OntologyEvaluator,
            LLMJudgeEvaluator,
            InternalMetricsEvaluator,
            RetrievalCoverageEvaluator,
            ValueAccuracyEvaluator,
            StructuralEvaluator,
            NovelFieldEvaluator,
        )

        # Completeness evaluator
        self.completeness_evaluator = CompletenessEvaluator()
        
        # Schema validator
        self.schema_validator = SchemaValidator()
        
        # Ontology evaluator
        kb_path = Path(__file__).parents[2] / 'kb'
        self.ontology_evaluator = OntologyEvaluator(kb_path=kb_path)
        
        # Correctness evaluator (with LLM judge)
        judge_provider = os.getenv('EVAL_JUDGE_PROVIDER', 'anthropic')
        judge_config = {
            'provider': judge_provider,
            'model': os.getenv('EVAL_JUDGE_MODEL', 'claude-sonnet-4-6'),
            'api_key': os.getenv('EVAL_JUDGE_API_KEY') or os.getenv('LLM_API_KEY'),
            'temperature': os.getenv('EVAL_JUDGE_TEMPERATURE', '0.0')
        }
        
        # Add base_url for Qwen
        if judge_provider == 'qwen':
            judge_config['base_url'] = os.getenv('QWEN_API_BASE_URL') or os.getenv('EVAL_JUDGE_BASE_URL') or 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
        self.correctness_evaluator = CorrectnessEvaluator(judge_config=judge_config)
        
        # LLM Judge evaluator (holistic)
        self.llm_judge_evaluator = LLMJudgeEvaluator(judge_config=judge_config)
        
        # Internal metrics evaluator (extracts FAIRiAgent's own confidence scores)
        self.internal_metrics_evaluator = InternalMetricsEvaluator()
        self.retrieval_coverage_evaluator = RetrievalCoverageEvaluator()

        # Layer 2/3/4 evaluators (evaluation-metrics redesign). These require
        # per-document *value*-level ground truth
        # (evaluation/datasets/annotated/values/ground_truth_{doc}_values.json),
        # which is optional/sparser than the field-presence GT used above --
        # loaded lazily per document in _load_ground_truth_values_doc().
        self.value_accuracy_evaluator = ValueAccuracyEvaluator()
        self.structural_evaluator = StructuralEvaluator(value_evaluator=self.value_accuracy_evaluator)
        self.novel_field_evaluator = NovelFieldEvaluator()
        self._gt_values_cache: Dict[str, Any] = {}

        print("✅ All evaluators initialized")

    def _load_ground_truth_values_doc(self, doc_id: str) -> Any:
        """Load the value-level GT for one document, if it exists (else None)."""
        if doc_id in self._gt_values_cache:
            return self._gt_values_cache[doc_id]
        values_path = (
            self.ground_truth_path.parent / 'values' / f'ground_truth_{doc_id}_values.json'
        )
        doc = None
        if values_path.exists():
            try:
                with open(values_path, 'r', encoding='utf-8') as f:
                    doc = json.load(f)
            except Exception:
                doc = None
        self._gt_values_cache[doc_id] = doc
        return doc
    
    def evaluate_all(self) -> Dict[str, Any]:
        """
        Run all evaluations on batch outputs.
        
        Returns:
            Complete evaluation results
        """
        results = {
            'evaluation_metadata': {
                'start_time': datetime.now().isoformat(),
                'run_dir': str(self.run_dir),
                'ground_truth': str(self.ground_truth_path),
                'n_documents': len(self.ground_truth_docs)
            },
            'per_model_results': {}
        }
        
        # Find all model configurations
        outputs_dir = self.run_dir / 'outputs'
        if not outputs_dir.exists():
            # Batch runner layout: {run_dir}/{config_name}/{doc_id}/run_N/
            skip = {'outputs', 'results'}
            model_configs = [
                d for d in self.run_dir.iterdir()
                if d.is_dir() and d.name not in skip and not d.name.startswith('.')
            ]
            if model_configs:
                print(f"  📁 Using batch layout under: {self.run_dir}")
            else:
                raise ValueError(f"Outputs directory not found: {outputs_dir}")
        else:
            model_configs = [d for d in outputs_dir.iterdir() if d.is_dir()]
        
        print(f"\n🔍 Found {len(model_configs)} model configurations to evaluate\n")
        
        # Evaluate each model configuration
        for model_dir in model_configs:
            config_name = model_dir.name
            print(f"\n{'='*70}")
            print(f"📊 Evaluating config: {config_name}")
            print(f"{'='*70}\n")
            
            model_results = self._evaluate_model_config(model_dir, config_name)
            results['per_model_results'][config_name] = model_results
        
        # Compute model comparison
        print(f"\n{'='*70}")
        print("📈 Computing model comparison metrics")
        print(f"{'='*70}\n")
        results['model_comparison'] = self._compute_model_comparison(results['per_model_results'])
        
        # Compute correlation analysis (internal metrics vs actual quality)
        print(f"\n{'='*70}")
        print("🔗 Computing internal metric correlations")
        print(f"{'='*70}\n")
        results['correlation_analysis'] = self._compute_correlations(results['per_model_results'])
        
        results['evaluation_metadata']['end_time'] = datetime.now().isoformat()
        
        # Save results
        results_dir = self.run_dir / 'results'
        results_dir.mkdir(parents=True, exist_ok=True)
        
        results_file = results_dir / 'evaluation_results.json'
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✅ Evaluation complete!")
        print(f"📄 Results saved to: {results_file}")
        
        return results
    
    def _evaluate_model_config(self, model_dir: Path, config_name: str) -> Dict[str, Any]:
        """Evaluate all outputs for a single model configuration."""
        # Load all FAIRiAgent outputs for this model
        # Support multiple directory structures:
        # 1. model_dir/outputs/{config_name}/{doc_id}/run_{N}/metadata.json
        # 2. model_dir/{config_name}/{doc_id}/run_{N}/metadata.json
        # 3. model_dir/{doc_id}/metadata.json (legacy; old runs may use metadata_json.json)
        fairifier_outputs = {}
        
        # Try different directory structures
        possible_paths = [
            model_dir / 'outputs' / config_name,  # Structure 1
            model_dir / config_name,  # Structure 2
            model_dir  # Structure 3 (legacy)
        ]
        
        doc_dirs = []
        for path in possible_paths:
            if path.exists() and path.is_dir():
                doc_dirs = [d for d in path.iterdir() if d.is_dir()]
                if doc_dirs:
                    print(f"  📁 Found outputs in: {path}")
                    break
        
        if not doc_dirs:
            print(f"  ⚠️  No document directories found in {model_dir}")
            return {}
        
        # Track output directories for loading workflow_report.json
        output_dirs = {}
        
        for doc_dir in doc_dirs:
            doc_id = doc_dir.name
            
            # Find all run directories for this document
            run_dirs = [d for d in doc_dir.iterdir() if d.is_dir() and d.name.startswith('run_')]
            
            if not run_dirs:
                print(f"  ⚠️  No run directories found for {doc_id}, skipping")
                continue

            if len(run_dirs) > 1:
                raise ValueError(
                    "Legacy aggregate evaluation refuses to select a best run for "
                    f"{doc_id}: found {len(run_dirs)} repetitions. Build a v2 run "
                    "index and use evaluation.benchmark.evaluate_run_index instead."
                )
            
            # Classify all runs
            successful_runs = []
            genuine_failures = []
            incomplete_runs = []
            
            for run_dir in sorted(run_dirs):
                status = self.classify_run_status(run_dir)
                
                if status['category'] == 'success':
                    # Use path from same classify_run_status snapshot (avoid second resolve / race skew)
                    metadata_file = status.get('metadata_path')
                    if metadata_file is None:
                        incomplete_runs.append({
                            'run_dir': run_dir,
                            'status': {
                                **status,
                                'category': 'incomplete',
                                'error_type': 'metadata_path_missing',
                                'error_message': (
                                    'classify_run_status reported success but metadata_path is missing'
                                ),
                            },
                        })
                        continue
                    workflow_report_file = run_dir / 'workflow_report.json'
                    
                    run_info = {
                        'metadata_file': metadata_file,
                        'run_dir': run_dir,
                        'status': status,
                        'is_fully_successful': False,
                        'has_failures': False,
                        'has_retries': False,
                        'workflow_status': 'unknown',
                        'failed_steps': 0,
                        'steps_requiring_retry': 0
                    }
                    
                    # Check workflow_report.json for detailed info
                    if workflow_report_file.exists():
                        try:
                            with open(workflow_report_file, 'r', encoding='utf-8') as f:
                                workflow_report = json.load(f)
                                exec_summary = workflow_report.get('execution_summary', {})
                                run_info['workflow_status'] = workflow_report.get('workflow_status', 'unknown')
                                run_info['failed_steps'] = exec_summary.get('failed_steps', 0)
                                run_info['steps_requiring_retry'] = exec_summary.get('steps_requiring_retry', 0)
                                run_info['has_failures'] = run_info['failed_steps'] > 0
                                run_info['has_retries'] = run_info['steps_requiring_retry'] > 0
                                run_info['is_fully_successful'] = (
                                    run_info['workflow_status'] == 'completed' and
                                    not run_info['has_failures'] and
                                    not run_info['has_retries']
                                )
                        except:
                            pass
                    
                    successful_runs.append(run_info)
                
                elif status['category'] == 'genuine_failure':
                    genuine_failures.append({'run_dir': run_dir, 'status': status})
                
                else:  # incomplete
                    incomplete_runs.append({'run_dir': run_dir, 'status': status})
            
            # Report statistics
            print(f"  ✅ Successful: {len(successful_runs)}")
            print(f"  ❌ Genuine failures: {len(genuine_failures)} (JSON parsing errors)")
            print(f"  ⏭️  Incomplete (excluded): {len(incomplete_runs)} (timeouts, metadata not found, etc.)")
            
            # A single successful run is retained for historical compatibility.
            # Repeated runs are rejected above and must use the v2 run index.
            if not successful_runs:
                print(f"  ⚠️  No successful runs for {doc_id}, skipping from analysis")
                # Store failure info for statistics
                continue
            
            selected_run = successful_runs[0]
            metadata_file = selected_run['metadata_file']
            if metadata_file is None:
                print(
                    f"  ⚠️  No metadata path for {doc_id} (selected run); skipping load"
                )
                continue
            
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    fairifier_outputs[doc_id] = json.load(f)
                    # Store the output directory for this document (to load workflow_report.json)
                    output_dirs[doc_id] = metadata_file.parent

                    # Prefer compiled sidecar only when metadata carries
                    # isa_matrix_id (new sync path). Older runs stay on
                    # metadata.json.isa_values to avoid silent regressions.
                    sidecar = metadata_file.parent / "isa_values_json.json"
                    if fairifier_outputs[doc_id].get("isa_matrix_id") and sidecar.is_file():
                        try:
                            with open(sidecar, "r", encoding="utf-8") as sf:
                                canonical = json.load(sf)
                            if isinstance(canonical, dict) and any(
                                isinstance(block, dict)
                                and ("columns" in block or "rows" in block)
                                for block in canonical.values()
                            ):
                                fairifier_outputs[doc_id]["isa_values"] = canonical
                        except (OSError, json.JSONDecodeError):
                            pass
                    
                    # Print status message
                    status_msg = "fully successful"
                    if not selected_run['is_fully_successful']:
                        status_msg = f"completed with {selected_run.get('failed_steps', 0)} failed steps"
                    if selected_run.get('has_retries'):
                        status_msg += f", {selected_run.get('steps_requiring_retry', 0)} retries"
                    
                    print(f"  ✅ Loaded {doc_id} from {metadata_file.parent.name} ({status_msg})")
            except Exception as e:
                print(f"  ⚠️  Failed to load metadata for {doc_id}: {e}")
                continue
        
        print(f"  📄 Loaded {len(fairifier_outputs)} outputs")
        
        # Run all evaluators
        results = {}
        
        # 1. Completeness
        print(f"  🔍 Running completeness evaluation...")
        results['completeness'] = self.completeness_evaluator.evaluate_batch(
            fairifier_outputs,
            self.ground_truth_docs
        )
        
        # 2. Correctness (field presence only, no value comparison)
        print(f"  🔍 Running field presence evaluation...")
        results['correctness'] = self.correctness_evaluator.evaluate_batch(
            fairifier_outputs,
            self.ground_truth_docs,
            use_llm_judge=False  # Not needed for field presence evaluation
        )
        
        # 3. Schema validation
        print(f"  🔍 Running schema validation...")
        results['schema_validation'] = self.schema_validator.validate_batch(
            fairifier_outputs
        )
        
        # 4. Ontology evaluation
        print(f"  🔍 Running ontology evaluation...")
        results['ontology'] = self.ontology_evaluator.evaluate_batch(
            fairifier_outputs
        )
        
        # 5. LLM Judge (holistic)
        print(f"  🔍 Running LLM judge evaluation...")
        results['llm_judge'] = self.llm_judge_evaluator.evaluate_batch(
            fairifier_outputs,
            self.ground_truth_docs
        )
        
        # 6. Internal Metrics (from FAIRiAgent workflow)
        print(f"  🔍 Extracting internal metrics from FAIRiAgent workflow...")
        results['internal_metrics'] = self.internal_metrics_evaluator.evaluate_batch(
            fairifier_outputs,
            output_dirs
        )

        # 6b. Retrieval coverage (hybrid retrieval / section-map-reduce rollout,
        # diagnostic only -- not part of the Layer 1-4 aggregate score below).
        print(f"  🔍 Evaluating retrieval coverage metrics...")
        results['retrieval_coverage'] = self.retrieval_coverage_evaluator.evaluate_batch(
            fairifier_outputs,
            output_dirs,
            ground_truth_docs=self.ground_truth_docs,
        )

        # 7. Value accuracy (Layer 2) -- only for docs with values-level GT
        gt_values_docs = {
            doc_id: self._load_ground_truth_values_doc(doc_id)
            for doc_id in fairifier_outputs
        }
        gt_values_docs = {k: v for k, v in gt_values_docs.items() if v is not None}
        if gt_values_docs:
            print(f"  🔍 Running value accuracy evaluation (Layer 2, {len(gt_values_docs)} docs with values-GT)...")
            results['value_accuracy'] = self.value_accuracy_evaluator.evaluate_batch(
                fairifier_outputs, gt_values_docs
            )

            # 8. Structural / hierarchical evaluation (Layer 3), same GT subset
            print(f"  🔍 Running structural evaluation (Layer 3)...")
            results['structural'] = self.structural_evaluator.evaluate_batch(
                fairifier_outputs, gt_values_docs
            )
        else:
            print(f"  ⏭️  No values-level GT available for this config's documents; skipping Layer 2/3")

        # 9. Novel field classification (Layer 4) -- evidence-grounded, all docs
        print(f"  🔍 Running novel field classification (Layer 4)...")
        gt_field_names_by_doc = {
            doc_id: {f['field_name'] for f in self.ground_truth_docs[doc_id].get('ground_truth_fields', [])}
            for doc_id in fairifier_outputs
            if doc_id in self.ground_truth_docs
        }
        source_texts_by_doc = {
            doc_id: find_source_text(output_dirs[doc_id])
            for doc_id in fairifier_outputs
            if doc_id in output_dirs
        }
        true_positives_by_doc = {
            doc_id: doc_result['summary_metrics'].get('true_positives', 0)
            for doc_id, doc_result in results['correctness'].get('per_document', {}).items()
        }
        results['novel_fields'] = self.novel_field_evaluator.evaluate_batch(
            fairifier_outputs,
            gt_field_names_by_doc,
            source_texts_by_doc=source_texts_by_doc,
            true_positives_by_doc=true_positives_by_doc,
        )

        # Compute aggregate score (now includes internal metrics)
        results['aggregate_score'] = self._compute_aggregate_score(results)
        
        print(f"  ✅ Aggregate score: {results['aggregate_score']:.3f}")
        
        return results
    
    # Named, documented composite weights (evaluation-metrics redesign).
    # These intentionally do NOT include the old confidence-based
    # discovery/fabrication penalty; `precision_excl_discoveries` (Layer 4)
    # already only penalizes evidence-ungrounded extra fields, so it's a
    # more defensible substitute for the old "adjusted precision".
    #
    # `beneficial_discovery_rate` / `untracked_insight_rate` are intentionally
    # EXCLUDED from the composite -- they are diagnostic/exploratory signals
    # ("may inspire researchers"), not first-order quality penalties/bonuses.
    # If a component's ground truth is unavailable for a given config (e.g.
    # values-level GT missing for Layer 2/3), its weight is dropped and the
    # remaining weights are renormalized (see the `sum(weights)` divisor
    # below), rather than treating the missing component as a zero score.
    WEIGHT_FIELD_COVERAGE_RECALL = 0.20   # Layer 1: did we find the GT fields at all?
    WEIGHT_VALUE_ACCURACY = 0.35          # Layer 2: are the extracted values actually correct?
    WEIGHT_STRUCTURAL_F1 = 0.15           # Layer 3: correct ISA sheet + row placement
    WEIGHT_SCHEMA_COMPLIANCE = 0.10       # FAIR-DS JSON schema validity
    WEIGHT_PRECISION_EXCL_DISCOVERIES = 0.20  # Layer 4: fabrication-adjusted precision

    def _compute_aggregate_score(self, results: Dict[str, Any]) -> float:
        """Compute overall aggregate quality score from the layered metrics.

        See the ``WEIGHT_*`` class constants above for the composite's
        components and rationale. All disaggregated component scores remain
        available in ``results`` for full transparency; this composite is a
        single headline number for ranking/sorting, not a replacement for
        looking at the layers individually.
        """
        scores = []
        weights = []

        # Layer 1: field coverage recall (did we find the GT fields at all?)
        if 'correctness' in results:
            recall = results['correctness']['aggregated'].get('mean_field_coverage_recall', 0.0)
            scores.append(recall)
            weights.append(self.WEIGHT_FIELD_COVERAGE_RECALL)

        # Layer 2: true value accuracy (MUC-style partial credit), when
        # values-level GT was available for this config's documents.
        if 'value_accuracy' in results and results['value_accuracy'].get('aggregated'):
            value_acc = results['value_accuracy']['aggregated'].get('mean_value_partial_credit_score', 0.0)
            scores.append(value_acc)
            weights.append(self.WEIGHT_VALUE_ACCURACY)

        # Layer 3: structural correctness -- mean of sheet-placement accuracy
        # (3a) and CEAF-style row-alignment F1 (3b).
        if 'structural' in results and results['structural'].get('aggregated'):
            agg = results['structural']['aggregated']
            structural = (
                agg.get('mean_sheet_placement_accuracy', 0.0)
                + agg.get('mean_row_alignment_f1', 0.0)
            ) / 2
            scores.append(structural)
            weights.append(self.WEIGHT_STRUCTURAL_F1)

        # Schema compliance
        if 'schema_validation' in results:
            schema = results['schema_validation']['aggregated'].get('mean_compliance_rate', 0.0)
            scores.append(schema)
            weights.append(self.WEIGHT_SCHEMA_COMPLIANCE)

        # Layer 4: fabrication-adjusted precision (TP / (TP + unsupported_fabrication))
        if 'novel_fields' in results and results['novel_fields'].get('aggregated'):
            precision_excl = results['novel_fields']['aggregated'].get('mean_precision_excl_discoveries', 0.0)
            scores.append(precision_excl)
            weights.append(self.WEIGHT_PRECISION_EXCL_DISCOVERIES)

        if not scores:
            return 0.0

        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    
    def _compute_model_comparison(self, per_model_results: Dict[str, Any]) -> Dict[str, Any]:
        """Compute model-vs-model comparison metrics."""
        comparison = {
            'models': list(per_model_results.keys()),
            'metrics': {}
        }
        
        # Extract key metrics for each model
        for model_name, results in per_model_results.items():
            if not results:
                comparison['metrics'][model_name] = {'aggregate_score': 0.0}
                continue

            value_acc_agg = results.get('value_accuracy', {}).get('aggregated', {})
            structural_agg = results.get('structural', {}).get('aggregated', {})
            novel_agg = results.get('novel_fields', {}).get('aggregated', {})

            comparison['metrics'][model_name] = {
                'aggregate_score': results.get('aggregate_score', 0.0),
                'completeness': results['completeness']['aggregated'].get('mean_overall_completeness', 0.0),
                # Layer 1: field-name coverage only (never checks values).
                'field_coverage_recall': results['correctness']['aggregated'].get('mean_field_coverage_recall', 0.0),
                'field_coverage_f1': results['correctness']['aggregated'].get('mean_field_coverage_f1', 0.0),
                'gt_field_populated_rate': results['correctness']['aggregated'].get('mean_gt_field_populated_rate', 0.0),
                # Layer 2: true value accuracy (only populated when values-GT exists).
                'value_partial_credit_score': value_acc_agg.get('mean_value_partial_credit_score'),
                'value_match_rate': value_acc_agg.get('mean_value_match_rate'),
                # Layer 3: structural/hierarchical correctness.
                'sheet_placement_accuracy': structural_agg.get('mean_sheet_placement_accuracy'),
                'row_alignment_f1': structural_agg.get('mean_row_alignment_f1'),
                # Layer 4: evidence-grounded novel-field classification.
                'discovery_rate': novel_agg.get('mean_discovery_rate'),
                'untracked_insight_rate': novel_agg.get('mean_untracked_insight_rate'),
                'precision_excl_discoveries': novel_agg.get('mean_precision_excl_discoveries'),
                'schema_compliance': results['schema_validation']['aggregated'].get('mean_compliance_rate', 0.0),
                'llm_judge_score': results['llm_judge']['aggregated'].get('mean_overall_score', 0.0)
            }
        
        # Rank models
        ranked = sorted(
            comparison['metrics'].items(),
            key=lambda x: x[1]['aggregate_score'],
            reverse=True
        )
        comparison['ranking'] = [model for model, _ in ranked]
        
        return comparison
    
    def _compute_correlations(self, per_model_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute calibration diagnostics (Layer 5, fast-follow) between
        FAIRiAgent's internal (self-reported) confidence and actual quality.

        Uses per-document *mean field confidence* (``internal_metrics``) as
        the predicted confidence, and per-document true value accuracy
        (Layer 2's ``value_mean_score``, when values-level GT is available;
        else Layer 1's ``field_coverage_recall`` as a coarser fallback) as the
        outcome, then reports Pearson correlation plus proper calibration
        metrics (ECE, Brier score) via ``evaluation.evaluators.calibration``.
        A plain correlation coefficient does not tell you whether confidence
        values are *numerically* trustworthy (e.g. a model that reports 0.95
        for everything can still correlate if the ranking is right) --
        ECE/Brier catch that.
        """
        from scipy.stats import pearsonr
        from evaluation.evaluators import calibration

        correlations = {}

        for model_name, results in per_model_results.items():
            if not results:
                continue

            internal_confidences = []
            correctness_scores = []

            per_doc_internal = results.get('internal_metrics', {}).get('per_document', {})
            per_doc_value_acc = results.get('value_accuracy', {}).get('per_document', {})
            per_doc_correctness = results.get('correctness', {}).get('per_document', {})

            for doc_id, doc_internal in per_doc_internal.items():
                mean_conf = doc_internal.get('field_confidence_stats', {}).get('mean_confidence')
                if mean_conf is None:
                    continue

                if doc_id in per_doc_value_acc:
                    outcome = per_doc_value_acc[doc_id]['summary_metrics'].get('value_mean_score')
                elif doc_id in per_doc_correctness:
                    outcome = per_doc_correctness[doc_id]['summary_metrics'].get('field_coverage_recall')
                else:
                    outcome = None
                if outcome is None:
                    continue

                internal_confidences.append(mean_conf)
                correctness_scores.append(outcome)

            if len(correctness_scores) >= 3:  # Need at least 3 points for correlation
                try:
                    corr, p_value = pearsonr(internal_confidences, correctness_scores)
                    entry = {
                        'correlation': corr,
                        'p_value': p_value,
                        'n_samples': len(correctness_scores),
                    }
                except Exception:
                    entry = {'error': 'Could not compute correlation'}
                entry.update(calibration.calibration_report(internal_confidences, correctness_scores))
                correlations[model_name] = {'confidence_vs_correctness': entry}

        return correlations


def main():
    parser = argparse.ArgumentParser(
        description="Historical single-run evaluator (use the v2 run-index path for new results)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--env-file', type=Path, required=True,
                       help='Evaluation env file')
    parser.add_argument('--run-dir', type=Path, required=True,
                       help='Directory containing batch evaluation outputs')
    parser.add_argument('--ground-truth', type=Path, required=True,
                       help='Ground truth JSON file')
    parser.add_argument('--approval-id', type=str, default=None,
                       help='Human approval identifier required before the historical LLM judge runs')
    
    args = parser.parse_args()

    if not args.approval_id:
        parser.error(
            'historical evaluation invokes an LLM judge and requires --approval-id; '
            'use the v2 deterministic evaluator for new benchmark results'
        )
    
    # Initialize orchestrator
    orchestrator = EvaluationOrchestrator(
        run_dir=args.run_dir,
        ground_truth_path=args.ground_truth,
        env_file=args.env_file
    )
    
    # Run all evaluations
    orchestrator.evaluate_all()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
