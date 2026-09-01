import os
import pytest
from scripts.evaluate import run_evaluation_benchmark, export_evaluation_report

def test_phase12_evaluation_benchmark():
    metrics = run_evaluation_benchmark()

    # 1. Structural integrity: Verify all expected domains and keys exist
    expected_domains = [
        "obligation_extraction",
        "clause_extraction",
        "compliance_assessment",
        "change_detection_4step_pipeline",
        "change_detection_cosine_similarity_baseline",
        "impact_propagation",
        "human_in_the_loop"
    ]
    for domain in expected_domains:
        assert domain in metrics, f"Missing expected evaluation domain: {domain}"

    # 2. Verify metric values are within valid numeric bounds [0.0, 1.0]
    for domain, domain_metrics in metrics.items():
        if isinstance(domain_metrics, dict):
            for key, val in domain_metrics.items():
                if isinstance(val, (int, float)) and key not in ["sample_count"]:
                    assert 0.0 <= val <= 1.0, f"Metric {domain}.{key} = {val} is outside [0.0, 1.0]"

    # 3. Novelty Assertion: 4-step pipeline strictly outperforms baseline on change detection
    four_step = metrics["change_detection_4step_pipeline"]
    baseline = metrics["change_detection_cosine_similarity_baseline"]

    assert four_step["overall_accuracy"] > baseline["overall_accuracy"], (
        f"4-step accuracy ({four_step['overall_accuracy']}) must exceed baseline ({baseline['overall_accuracy']})"
    )
    assert four_step["deadline_change_case_accuracy"] > baseline["deadline_change_case_accuracy"], (
        f"4-step deadline accuracy ({four_step['deadline_change_case_accuracy']}) must exceed baseline ({baseline['deadline_change_case_accuracy']})"
    )

    # 4. Compliance assessment verification
    comp_metrics = metrics["compliance_assessment"]
    assert comp_metrics["false_positive_rate"] <= 0.05, "False positive rate on irrelevant evidence should be near zero"

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
