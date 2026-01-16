#!/usr/bin/env python3
"""
Biological and Methodological Insights Analyzer

Treats repeated agent executions across models and batches as replicated measurements
of experimental interpretation, enabling biological and methodological insights
beyond single-run automation.

Key analyses:
1. Consensus metadata analysis (cross-model consistency = biological signal strength)
2. Agent disagreement analysis (proxy for reporting ambiguity)
3. Intra-model stability analysis (metadata robustness, like technical replicates)
4. Model-specific bias analysis (domain priors and training bias)
5. Emergent metadata patterns (implicit community knowledge beyond standards)
6. Field importance ranking (workflow-critical vs descriptive metadata)

Author: FAIRiAgent Evaluation Framework
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
import statistics
import math

logger = logging.getLogger(__name__)


@dataclass
class FieldOccurrence:
    """Tracks occurrence of a metadata field across runs."""
    field_name: str
    isa_sheet: str
    total_occurrences: int = 0
    runs_with_field: List[str] = field(default_factory=list)
    values: List[Any] = field(default_factory=list)
    confidence_scores: List[float] = field(default_factory=list)
    statuses: List[str] = field(default_factory=list)
    package_sources: List[str] = field(default_factory=list)
    evidences: List[str] = field(default_factory=list)


@dataclass
class ConsensusResult:
    """Result of consensus analysis for a field."""
    field_name: str
    isa_sheet: str
    consensus_score: float  # 0-1, proportion of runs including this field
    consensus_tier: str  # 'high' (>90%), 'medium' (40-90%), 'low' (<40%)
    avg_confidence: float
    value_consistency: float  # How consistent are the values (0-1)
    interpretation: str
    is_required: bool = False  # From ground truth
    is_recommended: bool = False  # From ground truth
    in_ground_truth: bool = False  # Whether field exists in ground truth


@dataclass
class DisagreementResult:
    """Result of disagreement analysis between models."""
    field_name: str
    isa_sheet: str
    disagreement_score: float  # 0-1, variance across models
    presence_variance: float  # Variance in whether field is present
    value_variance: float  # Variance in values when present
    models_that_include: List[str]
    models_that_exclude: List[str]
    interpretation: str


@dataclass
class StabilityResult:
    """Result of intra-model stability analysis."""
    model_name: str
    field_name: str
    isa_sheet: str
    stability_score: float  # 0-1, proportion of runs including this field
    value_consistency: float  # Consistency of values across runs
    avg_confidence: float
    interpretation: str


class BiologicalInsightsAnalyzer:
    """
    Analyzes agent outputs from a biological/methodological perspective,
    treating repeated executions as replicated measurements.
    """
    
    # Field categories for bias analysis
    FIELD_CATEGORIES = {
        'biological': {
            'keywords': ['scientific name', 'ncbi taxonomy', 'host', 'organism', 
                        'species', 'strain', 'isolate', 'biome', 'environmental',
                        'tissue', 'biosafety', 'pathogen', 'disease'],
            'description': 'Biological context and organism-related metadata'
        },
        'technical_sequencing': {
            'keywords': ['platform', 'instrument', 'library', 'sequencing', 'read',
                        'forward file', 'reverse file', 'insert size', 'adapter'],
            'description': 'Sequencing technology and technical parameters'
        },
        'sample_collection': {
            'keywords': ['collection date', 'geographic', 'latitude', 'longitude',
                        'sample', 'sampling', 'isolation source', 'collection device'],
            'description': 'Sample collection and provenance metadata'
        },
        'experimental_design': {
            'keywords': ['study', 'investigation', 'assay', 'protocol', 'treatment',
                        'experimental factor', 'observation unit', 'replicate'],
            'description': 'Experimental design and study structure'
        },
        'administrative': {
            'keywords': ['identifier', 'name', 'title', 'description', 'author',
                        'firstname', 'lastname', 'email', 'orcid', 'organization'],
            'description': 'Administrative and identification metadata'
        }
    }
    
    # Standard FAIR-DS fields (known ISA structure fields)
    STANDARD_FIELDS = {
        'investigation': ['investigation identifier', 'investigation title', 
                         'investigation description', 'firstname', 'lastname',
                         'email address', 'orcid', 'organization', 'department'],
        'study': ['study identifier', 'study title', 'study description',
                 'investigation identifier'],
        'assay': ['assay identifier', 'assay description', 'protocol', 'facility',
                 'assay date', 'sample identifier', 'platform', 'instrument model',
                 'library source', 'library selection', 'library strategy'],
        'sample': ['sample identifier', 'sample name', 'sample description',
                  'ncbi taxonomy id', 'scientific name', 'biosafety level',
                  'observation unit identifier', 'collection date',
                  'geographic location (country and/or sea)'],
        'observationunit': ['observation unit identifier', 'observation unit name',
                           'observation unit description', 'study identifier']
    }
    
    # Completed model directories (exclude ongoing runs and archive)
    COMPLETED_MODELS = {
        'gpt4.1', 'gpt5', 'haiku', 'o3', 'sonnet', 
        'qwen_flash', 'qwen_max', 'qwen_plus'
    }
    
    def __init__(self, runs_dir: Path, ground_truth_path: Optional[Path] = None,
                 filter_completed: bool = True):
        """
        Initialize analyzer.
        
        Args:
            runs_dir: Path to evaluation/runs directory
            ground_truth_path: Optional path to ground truth JSON
            filter_completed: If True, only analyze completed model runs
        """
        self.runs_dir = Path(runs_dir)
        self.filter_completed = filter_completed
        self.ground_truth = None
        if ground_truth_path and Path(ground_truth_path).exists():
            with open(ground_truth_path) as f:
                self.ground_truth = json.load(f)
        
        # Data structures
        self.all_runs: Dict[str, Dict] = {}  # model -> doc -> run -> metadata
        self.field_occurrences: Dict[str, Dict[str, FieldOccurrence]] = {}  # doc -> field_key -> occurrence
        self.model_field_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
    def load_all_runs(self) -> int:
        """Load all evaluation runs from the runs directory."""
        total_loaded = 0
        
        for model_dir in self.runs_dir.iterdir():
            if not model_dir.is_dir() or model_dir.name in ['archive', 'outputs']:
                continue
            
            model_name = model_dir.name
            
            # Filter to only completed models if enabled
            if self.filter_completed and model_name not in self.COMPLETED_MODELS:
                logger.debug(f"Skipping incomplete model directory: {model_name}")
                continue
            
            self.all_runs[model_name] = {}
            
            for doc_dir in model_dir.iterdir():
                if not doc_dir.is_dir():
                    continue
                
                doc_name = doc_dir.name
                self.all_runs[model_name][doc_name] = {}
                
                for run_dir in doc_dir.iterdir():
                    if not run_dir.is_dir() or not run_dir.name.startswith('run_'):
                        continue
                    
                    metadata_file = run_dir / 'metadata_json.json'
                    if metadata_file.exists():
                        try:
                            with open(metadata_file) as f:
                                metadata = json.load(f)
                            self.all_runs[model_name][doc_name][run_dir.name] = metadata
                            total_loaded += 1
                        except Exception as e:
                            logger.warning(f"Failed to load {metadata_file}: {e}")
        
        logger.info(f"Loaded {total_loaded} runs from {len(self.all_runs)} models")
        return total_loaded
    
    def _extract_fields_from_metadata(self, metadata: Dict) -> List[Dict]:
        """Extract all fields from a metadata JSON structure."""
        fields = []
        isa_structure = metadata.get('isa_structure', {})
        
        for sheet_name, sheet_data in isa_structure.items():
            if isinstance(sheet_data, dict) and 'fields' in sheet_data:
                for field_data in sheet_data['fields']:
                    fields.append({
                        'isa_sheet': sheet_name,
                        **field_data
                    })
        
        return fields
    
    def _get_field_key(self, field_name: str, isa_sheet: str) -> str:
        """Generate unique key for a field."""
        return f"{isa_sheet}::{field_name.lower()}"
    
    def _categorize_field(self, field_name: str) -> str:
        """Categorize a field into biological/technical/etc categories."""
        field_lower = field_name.lower()
        for category, info in self.FIELD_CATEGORIES.items():
            if any(kw in field_lower for kw in info['keywords']):
                return category
        return 'other'
    
    def _is_standard_field(self, field_name: str, isa_sheet: str) -> bool:
        """Check if field is in standard ISA templates."""
        standard_fields = self.STANDARD_FIELDS.get(isa_sheet, [])
        return field_name.lower() in [f.lower() for f in standard_fields]
    
    def _get_ground_truth_fields(self, document_id: str) -> Dict[str, Dict]:
        """Get ground truth field info (required/recommended) for a document."""
        if not self.ground_truth:
            return {}
        
        gt_fields = {}
        for doc in self.ground_truth.get('documents', []):
            if doc['document_id'] == document_id:
                for field in doc.get('ground_truth_fields', []):
                    key = self._get_field_key(field['field_name'], field['isa_sheet'])
                    gt_fields[key] = {
                        'is_required': field.get('is_required', False),
                        'is_recommended': field.get('is_recommended', False),
                        'package_source': field.get('package_source', 'unknown')
                    }
        return gt_fields
    
    def analyze_consensus(self, document_id: Optional[str] = None) -> Dict[str, List[ConsensusResult]]:
        """
        Analyze consensus across all models for metadata fields.
        
        High consensus fields (>90%) = Core experimental variables
        Medium consensus fields (40-90%) = Domain-dependent metadata
        Low consensus fields (<40%) = Marginal or reporting-deficient fields
        
        Returns:
            Dict mapping document_id to list of ConsensusResult
        """
        results = {}
        
        # Group all fields by document
        docs_to_analyze = [document_id] if document_id else self._get_all_documents()
        
        for doc in docs_to_analyze:
            field_occurrences = defaultdict(lambda: {
                'total_runs': 0,
                'runs_with_field': [],
                'values': [],
                'confidences': [],
                'models': set()
            })
            
            total_runs = 0
            
            for model_name, model_data in self.all_runs.items():
                if doc not in model_data:
                    continue
                
                for run_name, metadata in model_data[doc].items():
                    total_runs += 1
                    run_id = f"{model_name}:{run_name}"
                    
                    fields = self._extract_fields_from_metadata(metadata)
                    seen_fields = set()
                    
                    for field_data in fields:
                        field_key = self._get_field_key(
                            field_data['field_name'], 
                            field_data['isa_sheet']
                        )
                        
                        if field_key in seen_fields:
                            continue
                        seen_fields.add(field_key)
                        
                        occ = field_occurrences[field_key]
                        occ['runs_with_field'].append(run_id)
                        occ['values'].append(field_data.get('value', ''))
                        occ['confidences'].append(field_data.get('confidence', 0))
                        occ['models'].add(model_name)
                        occ['field_name'] = field_data['field_name']
                        occ['isa_sheet'] = field_data['isa_sheet']
            
            # Get ground truth fields for this document
            gt_fields = self._get_ground_truth_fields(doc)
            
            # Calculate consensus scores
            doc_results = []
            for field_key, occ in field_occurrences.items():
                consensus_score = len(occ['runs_with_field']) / total_runs if total_runs > 0 else 0
                
                # Get ground truth info
                gt_info = gt_fields.get(field_key, {})
                is_required = gt_info.get('is_required', False)
                is_recommended = gt_info.get('is_recommended', False)
                in_ground_truth = field_key in gt_fields
                
                # Determine tier
                if consensus_score >= 0.9:
                    tier = 'high'
                    interpretation = "Core experimental variable - consistently captured across all models"
                elif consensus_score >= 0.4:
                    tier = 'medium'
                    interpretation = "Domain-dependent metadata - captured by some models/contexts"
                else:
                    tier = 'low'
                    interpretation = "Marginal metadata - may indicate reporting deficiency or optional nature"
                
                # Add ground truth status to interpretation
                if is_required:
                    interpretation += " [REQUIRED in ground truth]"
                elif is_recommended:
                    interpretation += " [RECOMMENDED in ground truth]"
                elif not in_ground_truth:
                    interpretation += " [NOT in ground truth - emergent field]"
                
                # Calculate value consistency
                unique_values = set(str(v).lower().strip() for v in occ['values'] 
                                   if v and str(v).lower() not in ['not specified', 'not applicable', 'n/a'])
                value_consistency = 1.0 / len(unique_values) if unique_values else 0
                
                avg_confidence = statistics.mean(occ['confidences']) if occ['confidences'] else 0
                
                doc_results.append(ConsensusResult(
                    field_name=occ['field_name'],
                    isa_sheet=occ['isa_sheet'],
                    consensus_score=consensus_score,
                    consensus_tier=tier,
                    avg_confidence=avg_confidence,
                    value_consistency=min(value_consistency, 1.0),
                    interpretation=interpretation,
                    is_required=is_required,
                    is_recommended=is_recommended,
                    in_ground_truth=in_ground_truth
                ))
            
            # Sort by consensus score
            doc_results.sort(key=lambda x: x.consensus_score, reverse=True)
            results[doc] = doc_results
        
        return results
    
    def analyze_disagreement(self, document_id: Optional[str] = None) -> Dict[str, List[DisagreementResult]]:
        """
        Analyze disagreement between models as proxy for reporting ambiguity.
        
        High disagreement = Ambiguous reporting in source documents
        Low disagreement = Clear community consensus
        
        Returns:
            Dict mapping document_id to list of DisagreementResult
        """
        results = {}
        docs_to_analyze = [document_id] if document_id else self._get_all_documents()
        
        for doc in docs_to_analyze:
            # Track which models include each field
            field_by_model = defaultdict(lambda: defaultdict(list))
            
            for model_name, model_data in self.all_runs.items():
                if doc not in model_data:
                    continue
                
                for run_name, metadata in model_data[doc].items():
                    fields = self._extract_fields_from_metadata(metadata)
                    
                    for field_data in fields:
                        field_key = self._get_field_key(
                            field_data['field_name'],
                            field_data['isa_sheet']
                        )
                        field_by_model[field_key][model_name].append({
                            'value': field_data.get('value', ''),
                            'confidence': field_data.get('confidence', 0),
                            'field_name': field_data['field_name'],
                            'isa_sheet': field_data['isa_sheet']
                        })
            
            # Calculate disagreement scores
            doc_results = []
            all_models = set(self.all_runs.keys())
            
            for field_key, model_occurrences in field_by_model.items():
                models_with_field = set(model_occurrences.keys())
                models_without_field = all_models - models_with_field
                
                # Presence variance: binary (0 or 1) for each model
                presence_scores = [1 if m in models_with_field else 0 for m in all_models]
                presence_variance = statistics.variance(presence_scores) if len(presence_scores) > 1 else 0
                
                # Value variance: unique values across models
                all_values = []
                for model, occurrences in model_occurrences.items():
                    for occ in occurrences:
                        val = str(occ['value']).lower().strip()
                        if val and val not in ['not specified', 'not applicable', 'n/a']:
                            all_values.append(val)
                
                unique_value_ratio = len(set(all_values)) / len(all_values) if all_values else 0
                value_variance = unique_value_ratio  # Higher = more disagreement
                
                # Combined disagreement score
                disagreement_score = (presence_variance + value_variance) / 2
                
                # Get field info from first occurrence
                first_occ = next(iter(next(iter(model_occurrences.values()))))
                
                # Generate interpretation
                if disagreement_score > 0.5:
                    interpretation = "High disagreement - indicates ambiguous reporting or domain-specific interpretation"
                elif disagreement_score > 0.2:
                    interpretation = "Moderate disagreement - some variation in how models interpret this field"
                else:
                    interpretation = "Low disagreement - consistent interpretation across models"
                
                doc_results.append(DisagreementResult(
                    field_name=first_occ['field_name'],
                    isa_sheet=first_occ['isa_sheet'],
                    disagreement_score=disagreement_score,
                    presence_variance=presence_variance,
                    value_variance=value_variance,
                    models_that_include=list(models_with_field),
                    models_that_exclude=list(models_without_field),
                    interpretation=interpretation
                ))
            
            # Sort by disagreement score
            doc_results.sort(key=lambda x: x.disagreement_score, reverse=True)
            results[doc] = doc_results
        
        return results
    
    def analyze_intra_model_stability(self) -> Dict[str, Dict[str, List[StabilityResult]]]:
        """
        Analyze stability of field mentions within the same model across runs.
        
        Like technical replicates in biological experiments.
        High stability = Robust metadata extraction
        Low stability = Sensitive to stochastic variations
        
        Returns:
            Dict mapping model -> document -> list of StabilityResult
        """
        results = {}
        
        for model_name, model_data in self.all_runs.items():
            results[model_name] = {}
            
            for doc_name, doc_runs in model_data.items():
                if not doc_runs:
                    continue
                
                # Track field occurrence across runs
                field_occurrences = defaultdict(lambda: {
                    'runs_with_field': [],
                    'values': [],
                    'confidences': [],
                    'field_name': '',
                    'isa_sheet': ''
                })
                
                total_runs = len(doc_runs)
                
                for run_name, metadata in doc_runs.items():
                    fields = self._extract_fields_from_metadata(metadata)
                    seen_fields = set()
                    
                    for field_data in fields:
                        field_key = self._get_field_key(
                            field_data['field_name'],
                            field_data['isa_sheet']
                        )
                        
                        if field_key in seen_fields:
                            continue
                        seen_fields.add(field_key)
                        
                        occ = field_occurrences[field_key]
                        occ['runs_with_field'].append(run_name)
                        occ['values'].append(field_data.get('value', ''))
                        occ['confidences'].append(field_data.get('confidence', 0))
                        occ['field_name'] = field_data['field_name']
                        occ['isa_sheet'] = field_data['isa_sheet']
                
                # Calculate stability for each field
                doc_results = []
                for field_key, occ in field_occurrences.items():
                    stability_score = len(occ['runs_with_field']) / total_runs if total_runs > 0 else 0
                    
                    # Value consistency
                    unique_values = set(str(v).lower().strip() for v in occ['values']
                                       if v and str(v).lower() not in ['not specified', 'not applicable'])
                    value_consistency = 1.0 - (len(unique_values) - 1) / max(len(occ['values']), 1)
                    value_consistency = max(0, min(1, value_consistency))
                    
                    avg_confidence = statistics.mean(occ['confidences']) if occ['confidences'] else 0
                    
                    # Interpretation
                    if stability_score >= 0.9:
                        interpretation = "Highly stable - model consistently extracts this field"
                    elif stability_score >= 0.5:
                        interpretation = "Moderately stable - field extracted in most runs"
                    else:
                        interpretation = "Unstable - sensitive to stochastic variation or marginal field"
                    
                    doc_results.append(StabilityResult(
                        model_name=model_name,
                        field_name=occ['field_name'],
                        isa_sheet=occ['isa_sheet'],
                        stability_score=stability_score,
                        value_consistency=value_consistency,
                        avg_confidence=avg_confidence,
                        interpretation=interpretation
                    ))
                
                doc_results.sort(key=lambda x: x.stability_score, reverse=True)
                results[model_name][doc_name] = doc_results
        
        return results
    
    def analyze_model_bias(self) -> Dict[str, Dict[str, Any]]:
        """
        Analyze model-specific biases in metadata extraction.
        
        Different models may have different "domain priors" based on training data,
        leading to systematic biases in which metadata categories they emphasize.
        
        Returns:
            Dict mapping model_name to bias analysis
        """
        results = {}
        
        for model_name, model_data in self.all_runs.items():
            category_counts = defaultdict(int)
            total_fields = 0
            isa_sheet_counts = defaultdict(int)
            
            for doc_name, doc_runs in model_data.items():
                for run_name, metadata in doc_runs.items():
                    fields = self._extract_fields_from_metadata(metadata)
                    
                    for field_data in fields:
                        total_fields += 1
                        category = self._categorize_field(field_data['field_name'])
                        category_counts[category] += 1
                        isa_sheet_counts[field_data['isa_sheet']] += 1
            
            # Calculate proportions
            category_proportions = {
                cat: count / total_fields if total_fields > 0 else 0
                for cat, count in category_counts.items()
            }
            
            sheet_proportions = {
                sheet: count / total_fields if total_fields > 0 else 0
                for sheet, count in isa_sheet_counts.items()
            }
            
            # Identify dominant categories
            sorted_categories = sorted(category_proportions.items(), 
                                       key=lambda x: x[1], reverse=True)
            
            # Calculate bias interpretation
            if sorted_categories:
                dominant_category = sorted_categories[0][0]
                interpretation = f"Model shows strongest emphasis on {dominant_category} metadata "
                interpretation += f"({sorted_categories[0][1]*100:.1f}% of extracted fields). "
            else:
                dominant_category = 'unknown'
                interpretation = "No metadata fields extracted. "
            
            if 'biological' in category_proportions and category_proportions['biological'] > 0.3:
                interpretation += "Strong biological context awareness. "
            if 'technical_sequencing' in category_proportions and category_proportions['technical_sequencing'] > 0.25:
                interpretation += "Good technical/sequencing metadata coverage. "
            
            results[model_name] = {
                'total_fields_extracted': total_fields,
                'category_counts': dict(category_counts),
                'category_proportions': category_proportions,
                'isa_sheet_distribution': sheet_proportions,
                'dominant_category': dominant_category,
                'interpretation': interpretation,
                'category_descriptions': {
                    cat: self.FIELD_CATEGORIES[cat]['description']
                    for cat in category_proportions.keys()
                    if cat in self.FIELD_CATEGORIES
                }
            }
        
        return results
    
    def analyze_emergent_patterns(self) -> Dict[str, Any]:
        """
        Identify emergent metadata patterns - fields suggested by agents
        that are not in standard ISA templates but appear frequently.
        
        These may represent:
        - Implicit community knowledge not yet formalized
        - Domain-specific best practices
        - Potential extensions to standards
        
        Returns:
            Analysis of emergent patterns
        """
        # Track non-standard fields
        non_standard_fields = defaultdict(lambda: {
            'count': 0,
            'models': set(),
            'documents': set(),
            'values_sample': [],
            'confidences': [],
            'category': ''
        })
        
        total_fields = 0
        
        for model_name, model_data in self.all_runs.items():
            for doc_name, doc_runs in model_data.items():
                for run_name, metadata in doc_runs.items():
                    fields = self._extract_fields_from_metadata(metadata)
                    
                    for field_data in fields:
                        total_fields += 1
                        field_name = field_data['field_name']
                        isa_sheet = field_data['isa_sheet']
                        
                        if not self._is_standard_field(field_name, isa_sheet):
                            field_key = self._get_field_key(field_name, isa_sheet)
                            nf = non_standard_fields[field_key]
                            nf['count'] += 1
                            nf['models'].add(model_name)
                            nf['documents'].add(doc_name)
                            nf['field_name'] = field_name
                            nf['isa_sheet'] = isa_sheet
                            nf['category'] = self._categorize_field(field_name)
                            
                            if len(nf['values_sample']) < 5:
                                nf['values_sample'].append(field_data.get('value', ''))
                            
                            nf['confidences'].append(field_data.get('confidence', 0))
        
        # Analyze patterns
        emergent_results = []
        for field_key, info in non_standard_fields.items():
            model_coverage = len(info['models']) / len(self.all_runs) if self.all_runs else 0
            doc_coverage = len(info['documents']) / len(self._get_all_documents())
            avg_confidence = statistics.mean(info['confidences']) if info['confidences'] else 0
            
            # Score for potential standard extension
            extension_score = (model_coverage * 0.4 + doc_coverage * 0.3 + avg_confidence * 0.3)
            
            # Interpretation
            if model_coverage > 0.7 and doc_coverage > 0.5:
                interpretation = "Strong candidate for standard extension - consistently identified across models and documents"
            elif model_coverage > 0.4:
                interpretation = "Potential community practice - recognized by multiple models"
            else:
                interpretation = "Domain-specific or experimental metadata"
            
            emergent_results.append({
                'field_name': info['field_name'],
                'isa_sheet': info['isa_sheet'],
                'occurrence_count': info['count'],
                'model_coverage': model_coverage,
                'document_coverage': doc_coverage,
                'models': list(info['models']),
                'documents': list(info['documents']),
                'category': info['category'],
                'avg_confidence': avg_confidence,
                'extension_score': extension_score,
                'interpretation': interpretation,
                'sample_values': info['values_sample'][:3]
            })
        
        # Sort by extension score
        emergent_results.sort(key=lambda x: x['extension_score'], reverse=True)
        
        # Category distribution of emergent fields
        category_distribution = defaultdict(int)
        for r in emergent_results:
            category_distribution[r['category']] += 1
        
        return {
            'total_emergent_fields': len(emergent_results),
            'total_field_extractions': total_fields,
            'emergent_proportion': len(emergent_results) / max(len(set(
                self._get_field_key(f['field_name'], f['isa_sheet'])
                for m in self.all_runs.values()
                for d in m.values()
                for r in d.values()
                for f in self._extract_fields_from_metadata(r)
            )), 1),
            'category_distribution': dict(category_distribution),
            'top_candidates': emergent_results[:20],
            'all_emergent_fields': emergent_results
        }
    
    def analyze_field_importance(self) -> Dict[str, List[Dict]]:
        """
        Rank fields by their importance for downstream workflows.
        
        Categories:
        - Workflow-critical: Essential for pipeline execution
        - Biologically-critical: Essential for biological interpretation
        - Descriptive: Nice-to-have but not essential
        
        Returns:
            Dict mapping document to ranked fields
        """
        # Define workflow-critical fields
        workflow_critical = {
            'platform', 'instrument model', 'library strategy', 'library source',
            'scientific name', 'ncbi taxonomy id', 'forward file', 'reverse file',
            'sample identifier', 'assay identifier'
        }
        
        biologically_critical = {
            'scientific name', 'ncbi taxonomy id', 'host scientific name',
            'environmental medium', 'isolation source', 'tissue type',
            'broad-scale environmental context', 'local environmental context',
            'sample description', 'experimental factor'
        }
        
        results = {}
        
        for doc in self._get_all_documents():
            field_analysis = []
            
            # Get consensus results for this document
            consensus = self.analyze_consensus(doc).get(doc, [])
            
            for cr in consensus:
                field_lower = cr.field_name.lower()
                
                # Determine importance category
                is_workflow_critical = any(wc in field_lower for wc in workflow_critical)
                is_bio_critical = any(bc in field_lower for bc in biologically_critical)
                
                if is_workflow_critical:
                    importance = 'workflow_critical'
                    importance_score = 3
                elif is_bio_critical:
                    importance = 'biologically_critical'
                    importance_score = 2
                else:
                    importance = 'descriptive'
                    importance_score = 1
                
                # Combined score: consensus * importance
                combined_score = cr.consensus_score * importance_score
                
                field_analysis.append({
                    'field_name': cr.field_name,
                    'isa_sheet': cr.isa_sheet,
                    'importance_category': importance,
                    'importance_score': importance_score,
                    'consensus_score': cr.consensus_score,
                    'combined_score': combined_score,
                    'avg_confidence': cr.avg_confidence,
                    'interpretation': f"{importance.replace('_', ' ').title()} field with {cr.consensus_tier} consensus"
                })
            
            field_analysis.sort(key=lambda x: x['combined_score'], reverse=True)
            results[doc] = field_analysis
        
        return results
    
    def _get_all_documents(self) -> List[str]:
        """Get list of all documents across all models."""
        docs = set()
        for model_data in self.all_runs.values():
            docs.update(model_data.keys())
        return list(docs)
    
    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive biological insights report.
        
        Returns:
            Complete analysis results
        """
        logger.info("Running comprehensive biological insights analysis...")
        
        # Load data if not already loaded
        if not self.all_runs:
            self.load_all_runs()
        
        # Run all analyses
        consensus = self.analyze_consensus()
        disagreement = self.analyze_disagreement()
        stability = self.analyze_intra_model_stability()
        model_bias = self.analyze_model_bias()
        emergent = self.analyze_emergent_patterns()
        importance = self.analyze_field_importance()
        
        # Summary statistics
        summary = {
            'total_models': len(self.all_runs),
            'total_documents': len(self._get_all_documents()),
            'total_runs': sum(
                len(doc_runs)
                for model_data in self.all_runs.values()
                for doc_runs in model_data.values()
            ),
            'models_analyzed': list(self.all_runs.keys()),
            'documents_analyzed': self._get_all_documents()
        }
        
        # Key insights
        insights = []
        
        # Consensus insights
        for doc, results in consensus.items():
            high_consensus = [r for r in results if r.consensus_tier == 'high']
            low_consensus = [r for r in results if r.consensus_tier == 'low']
            
            if high_consensus:
                insights.append({
                    'type': 'consensus',
                    'document': doc,
                    'insight': f"{len(high_consensus)} fields show high consensus (>90%), representing core experimental variables",
                    'fields': [r.field_name for r in high_consensus[:5]]
                })
            
            if low_consensus:
                insights.append({
                    'type': 'reporting_gap',
                    'document': doc,
                    'insight': f"{len(low_consensus)} fields show low consensus (<40%), suggesting reporting ambiguity or optional metadata",
                    'fields': [r.field_name for r in low_consensus[:5]]
                })
        
        # Model bias insights
        for model, bias_data in model_bias.items():
            insights.append({
                'type': 'model_bias',
                'model': model,
                'insight': bias_data['interpretation']
            })
        
        # Emergent patterns insights
        top_emergent = emergent['top_candidates'][:5]
        if top_emergent:
            insights.append({
                'type': 'emergent_patterns',
                'insight': f"Found {len(emergent['all_emergent_fields'])} non-standard fields, {len([e for e in emergent['all_emergent_fields'] if e['extension_score'] > 0.5])} are strong candidates for standard extensions",
                'top_candidates': [e['field_name'] for e in top_emergent]
            })
        
        return {
            'summary': summary,
            'insights': insights,
            'consensus_analysis': {
                doc: [
                    {
                        'field_name': r.field_name,
                        'isa_sheet': r.isa_sheet,
                        'consensus_score': r.consensus_score,
                        'consensus_tier': r.consensus_tier,
                        'avg_confidence': r.avg_confidence,
                        'interpretation': r.interpretation,
                        'is_required': r.is_required,
                        'is_recommended': r.is_recommended,
                        'in_ground_truth': r.in_ground_truth
                    }
                    for r in results
                ]
                for doc, results in consensus.items()
            },
            'disagreement_analysis': {
                doc: [
                    {
                        'field_name': r.field_name,
                        'isa_sheet': r.isa_sheet,
                        'disagreement_score': r.disagreement_score,
                        'presence_variance': r.presence_variance,
                        'value_variance': r.value_variance,
                        'models_that_include': r.models_that_include,
                        'interpretation': r.interpretation
                    }
                    for r in results
                ]
                for doc, results in disagreement.items()
            },
            'stability_analysis': {
                model: {
                    doc: [
                        {
                            'field_name': r.field_name,
                            'isa_sheet': r.isa_sheet,
                            'stability_score': r.stability_score,
                            'value_consistency': r.value_consistency,
                            'avg_confidence': r.avg_confidence,
                            'interpretation': r.interpretation
                        }
                        for r in results
                    ]
                    for doc, results in doc_data.items()
                }
                for model, doc_data in stability.items()
            },
            'model_bias_analysis': model_bias,
            'emergent_patterns_analysis': emergent,
            'field_importance_analysis': importance
        }


def main():
    """Run biological insights analysis."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze agent outputs for biological insights')
    parser.add_argument('--runs-dir', type=Path, default=Path('evaluation/runs'),
                       help='Path to runs directory')
    parser.add_argument('--ground-truth', type=Path, 
                       default=Path('evaluation/datasets/annotated/ground_truth_filtered.json'),
                       help='Path to ground truth JSON')
    parser.add_argument('--output', type=Path, default=Path('evaluation/analysis/output/biological_insights.json'),
                       help='Output path for results')
    parser.add_argument('--all-models', action='store_true',
                       help='Include all models (including incomplete runs)')
    
    args = parser.parse_args()
    
    filter_completed = not args.all_models
    analyzer = BiologicalInsightsAnalyzer(args.runs_dir, args.ground_truth, filter_completed)
    analyzer.load_all_runs()
    
    report = analyzer.generate_comprehensive_report()
    
    # Save results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"Biological insights report saved to {args.output}")
    
    # Print summary
    print("\n" + "="*60)
    print("BIOLOGICAL INSIGHTS SUMMARY")
    print("="*60)
    print(f"Models analyzed: {report['summary']['total_models']}")
    print(f"Documents analyzed: {report['summary']['total_documents']}")
    print(f"Total runs: {report['summary']['total_runs']}")
    print(f"\nKey insights: {len(report['insights'])}")
    
    for insight in report['insights'][:10]:
        print(f"\n[{insight['type'].upper()}]")
        print(f"  {insight.get('insight', '')}")


if __name__ == '__main__':
    main()
