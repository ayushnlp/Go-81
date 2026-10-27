"""
Main entry point for Project Go 81 Backend.
Exposes the unified FastAPI application with local-first Ollama runtime and encrypted memory.
"""

from backend.main import (
    app,
    get_orchestrator,
    get_planner,
    orchestrator,
    planner,
)


__all__ = [
    "app",
    "get_orchestrator",
    "get_planner",
    "orchestrator",
    "planner",
]

if __name__ == "__main__":
    import os
    import uvicorn
    host = os.environ.get("GO81_HOST", "0.0.0.0")
    port = int(os.environ.get("GO81_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
