"""
Tests for src/mcp_handlers/wrapper_generator.py - Typed wrapper generation.

Tests _json_type_to_python, create_typed_wrapper, _create_simple_wrapper.
"""

import pytest
import asyncio
import inspect
import sys
from pathlib import Path
from typing import Optional, Union

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.wrapper_generator import (
    _json_type_to_python,
    create_typed_wrapper,
    _create_simple_wrapper,
)


# ============================================================================
# _json_type_to_python
# ============================================================================

class TestJsonTypeToPython:

    def test_string(self):
        assert _json_type_to_python("string") is str

    def test_integer(self):
        assert _json_type_to_python("integer") is int

    def test_number(self):
        assert _json_type_to_python("number") is float

    def test_boolean(self):
        result = _json_type_to_python("boolean")
        assert result == Union[str, bool]

    def test_array(self):
        assert _json_type_to_python("array") is list

    def test_object(self):
        assert _json_type_to_python("object") is dict

    def test_unknown_type_defaults_to_str(self):
        assert _json_type_to_python("foobar") is str

    def test_list_single_type(self):
        result = _json_type_to_python(["string"])
        assert result is str

    def test_list_single_type_with_null(self):
        result = _json_type_to_python(["string", "null"])
        assert result == Optional[str]

    def test_list_two_non_null(self):
        result = _json_type_to_python(["number", "string"])
        assert result == Union[float, str]

    def test_list_two_non_null_with_null(self):
        result = _json_type_to_python(["number", "string", "null"])
        assert result == Optional[Union[float, str]]

    def test_list_three_non_null(self):
        result = _json_type_to_python(["string", "integer", "number"])
        assert result == Union[str, int, float]

    def test_list_only_null(self):
        result = _json_type_to_python(["null"])
        assert result is str

    def test_list_more_than_three_non_null(self):
        # Should fallback to first type
        result = _json_type_to_python(["string", "integer", "number", "boolean"])
        assert result is str


# ============================================================================
# _create_simple_wrapper
# ============================================================================

class TestCreateSimpleWrapper:

    def test_creates_callable(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {"ok": True}
            return handler

        wrapper = _create_simple_wrapper("test_tool", [], get_handler)
        assert callable(wrapper)
        assert wrapper.__name__ == "test_tool"

    def test_has_correct_signature(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {}
            return handler

        param_info = [
            ("name", str, True),
            ("age", int, False),
        ]
        wrapper = _create_simple_wrapper("test_tool", param_info, get_handler)
        sig = inspect.signature(wrapper)
        assert "name" in sig.parameters
        assert "age" in sig.parameters
        assert sig.parameters["age"].default is None

    def test_required_param_has_no_default(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {}
            return handler

        param_info = [("required_param", str, True)]
        wrapper = _create_simple_wrapper("test_tool", param_info, get_handler)
        sig = inspect.signature(wrapper)
        assert sig.parameters["required_param"].default is inspect.Parameter.empty

    def test_wrapper_calls_handler(self):
        call_log = []

        def get_handler(name):
            async def handler(**kwargs):
                call_log.append(kwargs)
                return {"result": "done"}
            return handler

        wrapper = _create_simple_wrapper("test_tool", [], get_handler)
        result = asyncio.run(wrapper(foo="bar"))
        assert result == {"result": "done"}
        assert call_log[0] == {"foo": "bar"}

    def test_wrapper_filters_none_values(self):
        call_log = []

        def get_handler(name):
            async def handler(**kwargs):
                call_log.append(kwargs)
                return {}
            return handler

        wrapper = _create_simple_wrapper("test_tool", [], get_handler)
        asyncio.run(wrapper(a="keep", b=None))
        assert "b" not in call_log[0]
        assert call_log[0] == {"a": "keep"}

    def test_wrapper_unwraps_kwargs_dict(self):
        call_log = []

        def get_handler(name):
            async def handler(**kwargs):
                call_log.append(kwargs)
                return {}
            return handler

        wrapper = _create_simple_wrapper("test_tool", [], get_handler)
        asyncio.run(wrapper(kwargs={"inner_key": "inner_val"}))
        assert call_log[0] == {"inner_key": "inner_val"}

    def test_wrapper_unwraps_kwargs_json_string(self):
        call_log = []

        def get_handler(name):
            async def handler(**kwargs):
                call_log.append(kwargs)
                return {}
            return handler

        wrapper = _create_simple_wrapper("test_tool", [], get_handler)
        asyncio.run(wrapper(kwargs='{"json_key": "json_val"}'))
        assert call_log[0] == {"json_key": "json_val"}

    def test_wrapper_handles_invalid_json_kwargs_string(self):
        call_log = []

        def get_handler(name):
            async def handler(**kwargs):
                call_log.append(kwargs)
                return {}
            return handler

        wrapper = _create_simple_wrapper("test_tool", [], get_handler)
        asyncio.run(wrapper(kwargs="not valid json"))
        # Should pass through as-is since it's a string (not a dict), gets filtered
        assert call_log[0] == {}


# ============================================================================
# create_typed_wrapper
# ============================================================================

class TestCreateTypedWrapper:

    def test_simple_wrapper(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {"tool": name}
            return handler

        schema = {
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"]
        }
        wrapper = create_typed_wrapper("search", schema, get_handler)
        assert wrapper.__name__ == "search"
        assert callable(wrapper)

    def test_empty_schema(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {}
            return handler

        wrapper = create_typed_wrapper("no_params", {}, get_handler)
        assert wrapper.__name__ == "no_params"

    def test_schema_with_optional_params(self):
        def get_handler(name):
            async def handler(**kwargs):
                return kwargs
            return handler

        schema = {
            "properties": {
                "required_field": {"type": "string"},
                "optional_field": {"type": "integer"},
            },
            "required": ["required_field"]
        }
        wrapper = create_typed_wrapper("mixed", schema, get_handler)
        sig = inspect.signature(wrapper)
        assert "required_field" in sig.parameters
        assert "optional_field" in sig.parameters

    def test_wrapper_qualname_set(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {}
            return handler

        wrapper = create_typed_wrapper("my_tool", {}, get_handler)
        assert wrapper.__qualname__ == "my_tool"

    def test_multiple_type_params(self):
        def get_handler(name):
            async def handler(**kwargs):
                return {}
            return handler

        schema = {
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "enabled": {"type": "boolean"},
                "items": {"type": "array"},
                "config": {"type": "object"},
            },
            "required": []
        }
        wrapper = create_typed_wrapper("multi_type", schema, get_handler)
        sig = inspect.signature(wrapper)
        assert len(sig.parameters) == 6
