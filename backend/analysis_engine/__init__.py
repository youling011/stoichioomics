"""Scientific entry points, loaded on demand so process guards start promptly."""
__all__ = ["run_phase1_analysis_pipeline", "run_phase2_stoich_pipeline"]

def __getattr__(name):
    if name == "run_phase1_analysis_pipeline":
        from .phase1.runner_core import run_phase1_analysis_pipeline
        globals()[name] = run_phase1_analysis_pipeline
        return run_phase1_analysis_pipeline
    if name == "run_phase2_stoich_pipeline":
        from .phase2.runner_core import run_phase2_stoich_pipeline
        globals()[name] = run_phase2_stoich_pipeline
        return run_phase2_stoich_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
