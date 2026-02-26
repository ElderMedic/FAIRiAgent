"""
Package Selection Quality Analyzer

Analyzes whether models make appropriate metadata package selections
based on document content and domain.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Set
from collections import Counter


class PackageSelectionAnalyzer:
    """Analyze metadata package selection quality."""
    
    # Package to domain mapping
    PACKAGE_DOMAINS = {
        'metagenome': ['metagenomics', 'microbiome', 'environmental'],
        'transcriptome': ['transcriptomics', 'rna-seq', 'gene expression'],
        'genome': ['genomics', 'sequencing', 'assembly'],
        'proteome': ['proteomics', 'protein', 'mass spectrometry'],
        'metabolome': ['metabolomics', 'metabolite'],
        'default': ['general', 'basic', 'unspecified']
    }
    
    def __init__(self):
        """Initialize package selection analyzer."""
        pass
    
    def analyze_package_selection(
        self,
        runs: List[Dict[str, Any]],
        ground_truth: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze package selection quality across runs.
        
        Args:
            runs: List of run data (must include selected_package, extracted_fields)
            ground_truth: Ground truth document with expected_package
            
        Returns:
            Dict with package selection analysis
        """
        expected_package = ground_truth.get('metadata', {}).get('expected_package', 'default')
        document_domain = ground_truth.get('metadata', {}).get('domain', 'unknown')
        
        # Analyze each run
        run_analyses = []
        for run in runs:
            analysis = self._analyze_single_run(
                run, expected_package, document_domain, ground_truth
            )
            run_analyses.append(analysis)
        
        # Aggregate statistics
        total_runs = len(run_analyses)
        correct_package = sum(1 for r in run_analyses if r['package_correct'])
        domain_aligned = sum(1 for r in run_analyses if r['domain_aligned'])
        high_quality = sum(1 for r in run_analyses if r['quality_score'] >= 0.8)
        
        # Package distribution
        package_counts = Counter(r['selected_package'] for r in run_analyses)
        
        # Average mandatory coverage
        avg_mandatory = np.mean([r['mandatory_coverage'] for r in run_analyses])
        
        return {
            'total_runs': total_runs,
            'correct_package_count': correct_package,
            'correct_package_rate': correct_package / total_runs if total_runs else 0,
            'domain_aligned_count': domain_aligned,
            'domain_aligned_rate': domain_aligned / total_runs if total_runs else 0,
            'high_quality_count': high_quality,
            'high_quality_rate': high_quality / total_runs if total_runs else 0,
            'package_distribution': dict(package_counts),
            'expected_package': expected_package,
            'document_domain': document_domain,
            'average_mandatory_coverage': avg_mandatory,
            'per_run_details': run_analyses
        }
    
    def _analyze_single_run(
        self,
        run: Dict[str, Any],
        expected_package: str,
        document_domain: str,
        ground_truth: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze a single run's package selection."""
        selected_package = run.get('selected_package', 'unknown')
        extracted_fields = set(run.get('extracted_field_names', []))
        
        # 1. Package correctness
        package_correct = (selected_package == expected_package)
        
        # 2. Domain alignment
        domain_aligned = self._check_domain_alignment(selected_package, document_domain)
        
        # 3. Mandatory coverage for selected package
        gt_fields = ground_truth.get('ground_truth_fields', [])
        mandatory_fields = {
            f['field_name'] for f in gt_fields
            if f.get('is_required', False) and
               f.get('package_source', 'default') in [selected_package, 'default']
        }
        
        covered_mandatory = extracted_fields & mandatory_fields
        mandatory_coverage = len(covered_mandatory) / len(mandatory_fields) if mandatory_fields else 0
        
        # 4. Quality score
        quality_score = 0
        if package_correct:
            quality_score += 0.5
        if domain_aligned:
            quality_score += 0.2
        if mandatory_coverage >= 1.0:
            quality_score += 0.3
        
        # 5. Decision quality label
        if quality_score >= 0.8:
            decision_quality = 'EXCELLENT'
        elif quality_score >= 0.5:
            decision_quality = 'GOOD'
        elif quality_score >= 0.3:
            decision_quality = 'ACCEPTABLE'
        else:
            decision_quality = 'POOR'
        
        return {
            'selected_package': selected_package,
            'expected_package': expected_package,
            'package_correct': package_correct,
            'domain_aligned': domain_aligned,
            'mandatory_coverage': mandatory_coverage,
            'mandatory_count': len(mandatory_fields),
            'mandatory_covered': len(covered_mandatory),
            'quality_score': quality_score,
            'decision_quality': decision_quality
        }
    
    def _check_domain_alignment(self, package: str, domain: str) -> bool:
        """Check if package aligns with document domain."""
        if package not in self.PACKAGE_DOMAINS:
            # Unknown package, check if it contains domain keyword
            return domain.lower() in package.lower()
        
        package_domains = self.PACKAGE_DOMAINS[package]
        return any(pd.lower() in domain.lower() for pd in package_domains)
    
    def create_package_domain_matrix(
        self,
        all_runs: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        Create matrix showing package selections by document domain.
        
        Args:
            all_runs: List of all runs across all documents
            
        Returns:
            DataFrame with domain x package frequency matrix
        """
        # Collect data
        matrix_data = []
        for run in all_runs:
            matrix_data.append({
                'document_id': run.get('document_id', 'unknown'),
                'domain': run.get('document_domain', 'unknown'),
                'selected_package': run.get('selected_package', 'unknown'),
                'model_name': run.get('model_name', 'unknown')
            })
        
        df = pd.DataFrame(matrix_data)
        
        # Create pivot table
        pivot = pd.crosstab(
            df['domain'],
            df['selected_package'],
            normalize='index'  # Normalize by row (domain)
        )
        
        return pivot
    
    def analyze_alternative_packages(
        self,
        run: Dict[str, Any],
        ground_truth: Dict[str, Any],
        available_packages: List[str]
    ) -> Dict[str, Any]:
        """
        Analyze how well the run would have done with alternative packages.
        
        Counterfactual analysis: "What if the agent selected a different package?"
        
        Args:
            run: Single run data
            ground_truth: Ground truth document
            available_packages: List of available package options
            
        Returns:
            Dict with alternative package analysis
        """
        extracted_fields = set(run.get('extracted_field_names', []))
        selected_package = run.get('selected_package', 'default')
        
        gt_fields = ground_truth.get('ground_truth_fields', [])
        
        alternative_scores = {}
        
        for package in available_packages:
            # Get mandatory fields for this alternative package
            mandatory = {
                f['field_name'] for f in gt_fields
                if f.get('is_required', False) and
                   f.get('package_source', 'default') in [package, 'default']
            }
            
            if not mandatory:
                continue
            
            # Calculate coverage
            covered = extracted_fields & mandatory
            coverage = len(covered) / len(mandatory)
            
            alternative_scores[package] = {
                'mandatory_total': len(mandatory),
                'mandatory_covered': len(covered),
                'coverage': coverage,
                'would_succeed': coverage == 1.0
            }
        
        # Find best alternative
        best_alt = max(
            alternative_scores.items(),
            key=lambda x: x[1]['coverage']
        ) if alternative_scores else (None, {'coverage': 0})
        
        return {
            'selected_package': selected_package,
            'selected_coverage': alternative_scores.get(selected_package, {}).get('coverage', 0),
            'alternatives': alternative_scores,
            'best_alternative': best_alt[0],
            'best_alternative_coverage': best_alt[1]['coverage'],
            'optimal_selection': best_alt[0] == selected_package
        }
    
    def compute_model_package_preferences(
        self,
        all_runs: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute which packages each model prefers.
        
        Args:
            all_runs: List of all runs across all models
            
        Returns:
            Dict mapping model -> package -> selection_rate
        """
        df = pd.DataFrame([
            {
                'model_name': run.get('model_name', 'unknown'),
                'selected_package': run.get('selected_package', 'unknown')
            }
            for run in all_runs
        ])
        
        # Calculate selection rates by model
        preferences = {}
        for model in df['model_name'].unique():
            model_df = df[df['model_name'] == model]
            package_counts = model_df['selected_package'].value_counts()
            total = len(model_df)
            
            preferences[model] = {
                pkg: count / total
                for pkg, count in package_counts.items()
            }
        
        return preferences
