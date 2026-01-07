"""Custom compression middleware supporting both zstd (preferred) and gzip (fallback)."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from starlette.requests import Request
from starlette.responses import Response
import gzip
from typing import Callable, Optional

# Try to import zstandard, fallback to None if not available
try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False
    zstd = None


class FastGZipMiddleware(BaseHTTPMiddleware):
    """Compression middleware supporting zstd (preferred) and gzip (fallback).
    
    - zstd: Fast compression with excellent ratios (~2x faster than gzip, better compression)
    - gzip level 1: Fast fallback compression when zstd is not supported
    
    Automatically detects browser support via Accept-Encoding header.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 1000,
        gzip_compresslevel: int = 1,  # Fast gzip compression (1=fastest, 9=best compression)
        zstd_compresslevel: int = 3,  # Balanced zstd compression (1=fastest, 22=best compression)
    ) -> None:
        super().__init__(app)
        self.minimum_size = minimum_size
        self.gzip_compresslevel = gzip_compresslevel
        self.zstd_compresslevel = zstd_compresslevel
        self.zstd_available = ZSTD_AVAILABLE
        
        if not self.zstd_available:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("zstandard library not available. Install with: pip install zstandard. Falling back to gzip only.")

    def _detect_preferred_encoding(self, accept_encoding: str) -> Optional[str]:
        """Detect preferred compression encoding from Accept-Encoding header.
        
        Priority: zstd > gzip > None
        """
        accept_encoding_lower = accept_encoding.lower()
        
        # Check for zstd support (common in modern browsers: Chrome 119+, Firefox 110+, Safari 16+)
        if self.zstd_available and "zstd" in accept_encoding_lower:
            return "zstd"
        
        # Fallback to gzip
        if "gzip" in accept_encoding_lower:
            return "gzip"
        
        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add compression to response if appropriate."""
        # Detect preferred encoding
        accept_encoding = request.headers.get("accept-encoding", "")
        encoding = self._detect_preferred_encoding(accept_encoding)
        
        if not encoding:
            return await call_next(request)

        response = await call_next(request)

        # Only compress if response is large enough and not already compressed
        if (
            response.status_code < 200
            or response.status_code >= 300
            or "content-encoding" in response.headers
            or response.headers.get("content-length", "0") == "0"
        ):
            return response

        # Check response size
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if len(body) < self.minimum_size:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Compress with preferred encoding
        compressed_body: bytes
        content_encoding: str
        
        if encoding == "zstd" and self.zstd_available:
            # Use zstd compression (faster and better compression than gzip)
            cctx = zstd.ZstdCompressor(level=self.zstd_compresslevel)
            compressed_body = cctx.compress(body)
            content_encoding = "zstd"
        else:
            # Fallback to gzip
            compressed_body = gzip.compress(body, compresslevel=self.gzip_compresslevel)
            content_encoding = "gzip"

        # Return compressed response
        return Response(
            content=compressed_body,
            status_code=response.status_code,
            headers={
                **response.headers,
                "content-encoding": content_encoding,
                "content-length": str(len(compressed_body)),
            },
            media_type=response.media_type,
        )

