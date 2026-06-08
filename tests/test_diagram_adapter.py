import time

from app.services.diagram_compiler_adapter import DiagramCompilerAdapter


def test_diagram_compiler_health_imports_existing_compiler():
    result = DiagramCompilerAdapter().get_compiler_health()

    assert result.status == "ready"
    assert "Compiler package" in result.reason


def test_diagram_compiler_timeout_guard_fails_fast():
    adapter = DiagramCompilerAdapter()

    try:
        adapter._run_compiler_with_timeout(lambda: time.sleep(0.2), timeout_seconds=0.01)
    except TimeoutError as exc:
        assert "exceeded configured timeout" in str(exc)
    else:
        raise AssertionError("Expected compiler timeout guard to fail")
