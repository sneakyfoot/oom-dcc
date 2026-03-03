"""
Server initialization and FastAPI app setup.
"""

import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from oom_agent.logging_config import setup_logging
from .protocol import (
    parse_request,
    create_error_jsonrpc,
    create_success_jsonrpc,
    resolve_method,
    list_available_methods,
    JsonRpcError,
)


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(title="OOM Agent Control Server", version="0.1.0")

    # Add CORS middleware
    middleware_cls: Any = CORSMiddleware
    app.add_middleware(
        middleware_cls,  # type: ignore[arg-type]
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


# Create global app instance
app = create_app()

# Import endpoints to register methods
import oom_agent.endpoints.session  # noqa: E402,F401
import oom_agent.endpoints.scene  # noqa: E402,F401
import oom_agent.endpoints.execution  # noqa: E402,F401
import oom_agent.endpoints.tools  # noqa: E402,F401


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/methods")
async def list_methods():
    """List all available JSON-RPC methods."""
    return {"methods": list_available_methods()}


@app.post("/rpc")
async def handle_rpc(request: Request):
    """Handle JSON-RPC request."""
    try:
        # Parse request body
        request_str = (await request.body()).decode("utf-8")

        # Parse request
        parsed = parse_request(request_str)

        # Lookup method
        handler = await resolve_method(parsed.method)

        if handler is None:
            return JSONResponse(
                status_code=404,
                content=create_error_jsonrpc(
                    JsonRpcError.METHOD_NOT_FOUND,
                    f"Method not found: {parsed.method}",
                    str(parsed.id),
                ),
            )

        # Execute method
        try:
            result = await handler(parsed.params or {})
            return JSONResponse(
                content=create_success_jsonrpc(result, parsed.id),
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content=create_error_jsonrpc(
                    JsonRpcError.INTERNAL_ERROR,
                    f"Internal error: {str(e)}",
                    str(parsed.id),
                ),
            )

    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content=create_error_jsonrpc(
                JsonRpcError.INVALID_REQUEST,
                str(e),
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=create_error_jsonrpc(
                JsonRpcError.PARSE_ERROR,
                f"Parse error: {str(e)}",
            ),
        )


def run_server():
    """Run the agent server."""
    setup_logging()
    uvicorn.run(
        "oom_agent.server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        reload=os.getenv("DEV_MODE", "").lower() in ("1", "true"),
    )


if __name__ == "__main__":
    run_server()
