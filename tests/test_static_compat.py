"""Guard Streamlit's media middleware against incompatible Starlette gzip behavior."""
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient
from streamlit.web.server.starlette.starlette_gzip_middleware import SelectiveGZipMiddleware


@pytest.mark.parametrize("encoding", ["gzip", "identity"])
def test_favicon_response_keeps_http_headers_before_body(encoding):
    async def favicon(request):
        return Response(b"test-icon-payload", media_type="image/png")
    app = Starlette(routes=[Route("/favicon.png", favicon)], middleware=[
        Middleware(SelectiveGZipMiddleware, minimum_size=500, compresslevel=6)])
    with TestClient(app) as client:
        response = client.get("/favicon.png", headers={"Accept-Encoding": encoding})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"test-icon-payload"
