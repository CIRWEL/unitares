"""Regression tests for transform_inputs response_text coercion.

The Pydantic schema for process_agent_update defines
`response_text: Optional[str] = Field(default=None)`. Arguments arriving at
transform_inputs always include the key (possibly with value=None). Downstream
code (execute_locked_update) calls re.findall / re.search on response_text,
which raise TypeError on None — causing every call that omits response_text
to fail with "expected string or bytes-like object, got 'NoneType'".
"""

from src.mcp_handlers.updates.context import UpdateContext
from src.mcp_handlers.updates.phases import transform_inputs


def test_transform_inputs_coerces_none_response_text_to_empty_string():
    """Caller passes response_text=None explicitly (schema default).
    transform_inputs must coerce to '' so downstream re.* calls are safe."""
    ctx = UpdateContext(arguments={"response_text": None, "complexity": 0.5})
    transform_inputs(ctx)
    assert ctx.response_text == ""
    assert isinstance(ctx.response_text, str)


def test_transform_inputs_preserves_non_empty_response_text():
    ctx = UpdateContext(
        arguments={"response_text": "wrote a test", "complexity": 0.5}
    )
    transform_inputs(ctx)
    assert ctx.response_text == "wrote a test"


def test_transform_inputs_missing_key_defaults_to_empty_string():
    """Key entirely absent (non-schema-validated callers)."""
    ctx = UpdateContext(arguments={"complexity": 0.5})
    transform_inputs(ctx)
    assert ctx.response_text == ""
