"""Reverse proxy — config-driven proxy routes from portal-registry.yaml.

For each system with a `proxy` field, registers a catch-all reverse proxy route.
Cloud: Nginx intercepts first (this is a no-op fallback).
Local: FastAPI proxies to the upstream service.
"""
import os

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from deps import PORTAL_REGISTRY

router = APIRouter(tags=["proxy"])

# httpx is optional — only register proxy routes if available
try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

if _HTTPX_AVAILABLE:
    _PROXY_SYSTEMS = [s for s in PORTAL_REGISTRY.get("systems", []) if s.get("proxy")]

    def _make_proxy_handler(upstream: str, prefix: str):
        """Create an async proxy handler for a given upstream."""
        async def handler(path: str, request: Request):
            target = f"{upstream}{prefix}/{path}"
            if request.url.query:
                target += f"?{request.url.query}"
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.request(
                        method=request.method,
                        url=target,
                        headers={k: v for k, v in request.headers.items() if k.lower() not in ("host",)},
                        content=await request.body(),
                    )
                    resp_headers = {k: v for k, v in resp.headers.items()
                                    if k.lower() not in ("content-encoding", "transfer-encoding", "content-length")}
                    return Response(
                        content=resp.content,
                        status_code=resp.status_code,
                        headers=resp_headers,
                    )
            except (httpx.ConnectError, httpx.TimeoutException):
                return JSONResponse(
                    {"error": "Service unavailable", "upstream": upstream},
                    status_code=502,
                )
        return handler

    # Register proxy routes from registry
    for _sys in _PROXY_SYSTEMS:
        _path = _sys["path"].rstrip("/")
        _upstream = _sys["proxy"]
        _handler = _make_proxy_handler(_upstream, _path)

        # Catch-all proxy route: /hotspot/{path}
        router.api_route(f"{_path}/{{path:path}}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])(_handler)

        # Root path proxy: /hotspot/
        async def _root_handler(request: Request, __handler=_handler):
            return await __handler("", request)
        router.get(f"{_path}/")(_root_handler)

        # Also register the bare path as proxy (no trailing slash)
        async def _bare_handler(request: Request, __handler=_handler):
            return await __handler("", request)
        router.get(f"{_path}")(_bare_handler)
