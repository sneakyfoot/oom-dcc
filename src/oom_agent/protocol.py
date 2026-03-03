"""
JSON-RPC 2.0 protocol handler.
Handles request parsing, response formatting, and error codes.
"""

import json
from typing import Any, Dict, Optional, Callable, Awaitable
from pydantic import BaseModel, Field


class JsonRequest(BaseModel):
    """JSON-RPC 2.0 request model."""

    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[int | str] = None


class JsonResponse(BaseModel):
    """JSON-RPC 2.0 response model."""

    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[int | str] = None

    class Config:
        @staticmethod
        def json_schema_extra(schema: Dict[str, Any]) -> None:
            schema["required"] = ["result", "id"]


class JsonRpcError:
    """JSON-RPC error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


def parse_request(raw_body: str) -> JsonRequest:
    """Parse JSON-RPC request from raw body string."""
    try:
        data = json.loads(raw_body)
        return JsonRequest.model_validate(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Invalid request format: {exc}") from exc


def create_response(
    result: Any = None,
    error_code: Optional[int] = None,
    error_message: Optional[str] = None,
    request_id: Optional[int | str] = None,
) -> JsonResponse:
    """Create JSON-RPC response."""
    error = None
    if error_code is not None:
        error = {"code": error_code, "message": error_message or "Error"}

    return JsonResponse(model_validate({"result": result, "error": error, "id": request_id}))


def create_error_jsonrpc(
    code: int, message: str, request_id: Optional[int | str] = None
) -> Dict[str, Any]:
    """Create error response dict for raw JSON."""
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": request_id}


def create_success_jsonrpc(
    result: Any, request_id: Optional[int | str] = None
) -> Dict[str, Any]:
    """Create success response dict for raw JSON."""
    return {"jsonrpc": "2.0", "result": result, "id": request_id}


# Method handler registry
METHOD_REGISTRY: Dict[str, Callable[..., Awaitable[Any]]] = {}


def register_method(method_name: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to register a method handler."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        METHOD_REGISTRY[method_name] = func
        return func
    return decorator


async def resolve_method(method_name: str) -> Optional[Callable[..., Awaitable[Any]]]:
    """Resolve method handler from name."""
    return METHOD_REGISTRY.get(method_name)


def list_available_methods() -> list[str]:
    """List all registered method names."""
    return list(METHOD_REGISTRY.keys())
