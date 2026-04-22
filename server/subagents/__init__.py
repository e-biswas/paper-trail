"""Subagents that the conductor delegates narrow tasks to.

Each exposes one async entry function and returns a `SubagentResult`.
"""
from .base import SubagentResult, extract_result_block, load_subagent_prompt

__all__ = [
    "SubagentResult",
    "extract_result_block",
    "load_subagent_prompt",
]
