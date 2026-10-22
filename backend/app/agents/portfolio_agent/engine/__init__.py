"""
Deterministic portfolio engine. Nothing in this package calls an LLM: every
allocation, amount and metric is computed and validated here, so the
numbers are reproducible and testable independent of any model output.
"""
