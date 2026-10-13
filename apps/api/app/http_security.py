"""Bound request bodies before parsing/writing; never log credentials or bodies."""
import os

from starlette.responses import JSONResponse

MAX_BODY_BYTES = 64 * 1024


def error_response(status: int, code: str, message: str, headers=None):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() not in (b"cache-control", b"x-content-type-options")]
                message = {**message, "headers": headers + [(b"cache-control", b"no-store"),
                                                            (b"x-content-type-options", b"nosniff")]}
            await send(message)

        async def fail(status, code, message):
            await error_response(status, code, message)(scope, receive, secure_send)

        if os.getenv("REQUIRE_HTTPS", "false").lower() == "true" and scope["scheme"] != "https":
            return await fail(400, "https_required", "HTTPS is required")
        # Experience contracts have no query parameters. Do not reflect them.
        if scope["path"].startswith("/api/v1/experience") and scope.get("query_string"):
            return await fail(400, "query_not_allowed", "Use the Authorization header; query parameters are not supported")
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
                if declared < 0:
                    raise ValueError
            except ValueError:
                return await fail(400, "invalid_request", "Invalid request framing")
            if declared > MAX_BODY_BYTES:
                return await fail(413, "body_too_large", "Request body exceeds 64 KiB")
        chunks, count = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            count += len(message.get("body", b""))
            if count > MAX_BODY_BYTES:
                return await fail(413, "body_too_large", "Request body exceeds 64 KiB")
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return chunks.pop(0) if chunks else await receive()

        # A last boundary catches unexpected errors without reflecting exception data.
        started = False

        async def track_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await secure_send(message)

        try:
            await self.app(scope, replay, track_send)
        except Exception:
            if started:
                raise
            await fail(500, "internal_error", "Request could not be completed")
