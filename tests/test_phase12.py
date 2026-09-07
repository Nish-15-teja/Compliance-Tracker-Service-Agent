import os
import pytest
from scripts.evaluate import run_evaluation_benchmark, export_evaluation_report

def test_phase12_evaluation_benchmark():
    metrics = run_evaluation_benchmark()

    # 1. Structural integrity: Verify all expected domains and keys exist
    expected_domains = [
        "obligation_extraction",
        "change_detection",
        "compliance_assessment",
        "hitl",
        "evidence_expiry",
        "impact_propagation"
    ]
    for domain in expected_domains:
        assert domain in metrics, f"Missing expected evaluation domain: {domain}"

    # 2. Verify metric values are within valid numeric bounds [0.0, 1.0]
    for domain, domain_metrics in metrics.items():
        if isinstance(domain_metrics, dict):
            for key, val in domain_metrics.items():
                if isinstance(val, (int, float)) and key not in ["sample_count", "total_benchmark_sample_count"]:
                    assert 0.0 <= val <= 1.0, f"Metric {domain}.{key} = {val} is outside [0.0, 1.0]"

    # 3. Novelty Assertion: Change detection outperforms baseline
    cd = metrics["change_detection"]
    assert cd["significance_accuracy"] >= cd["baseline_significance_accuracy"], (
        f"4-step accuracy ({cd['significance_accuracy']}) must exceed baseline ({cd['baseline_significance_accuracy']})"
    )

    # 4. Compliance assessment verification
    comp_metrics = metrics["compliance_assessment"]
    assert comp_metrics["false_positive_rate"] <= 0.25, "False positive rate on irrelevant evidence should be low (< 25%)"

    # 5. Verify report file exports (JSON, CSV, MD)
    test_dir = "test_eval_output"
    export_evaluation_report(output_dir=test_dir)

    json_file = os.path.join(test_dir, "evaluation_results.json")
    csv_file = os.path.join(test_dir, "evaluation_summary.csv")
    md_file = os.path.join(test_dir, "evaluation_report.md")

    assert os.path.exists(json_file)
    assert os.path.exists(csv_file)
    assert os.path.exists(md_file)

    # Cleanup test output files
    os.remove(json_file)
    os.remove(csv_file)
    os.remove(md_file)
    os.rmdir(test_dir)
