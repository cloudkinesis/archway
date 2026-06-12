from pathlib import Path


def test_compiler_stages_do_not_reference_example_specific_layout_ids():
    forbidden = {
        'node.id == "assistant"',
        "node.id == 'assistant'",
        '"rag_orchestrator"',
        "'rag_orchestrator'",
        '"APP-VPC"',
        "'APP-VPC'",
        'label == "Workloads"',
        "label == 'Workloads'",
    }
    checked_files = [
        "src/archway_diagram_compiler/compiler.py",
        "src/archway_diagram_compiler/views.py",
        "src/archway_diagram_compiler/view_planner.py",
        "src/archway_diagram_compiler/layout_ir.py",
        "src/archway_diagram_compiler/d2_backend.py",
        "src/archway_diagram_compiler/qa.py",
        "src/archway_diagram_compiler/svg_postprocess.py",
    ]
    for filename in checked_files:
        text = Path(filename).read_text(encoding="utf-8")
        assert not [token for token in forbidden if token in text], filename
