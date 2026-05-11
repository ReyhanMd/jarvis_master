"""OpenTelemetry tracing decorators (Phase 6).

Wraps async functions in OTel spans. NOOP when otel not installed
or trace_enabled=False.

Usage:
    from shail.observability.traces import trace_fn

    @trace_fn("hybrid_search")
    async def hybrid_search(...):
        ...
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_tracer = None
_enabled = False


def _get_tracer():
    global _tracer, _enabled
    if _tracer is not None:
        return _tracer
    try:
        from apps.shail.settings import get_settings
        s = get_settings()
        if not s.trace_enabled:
            return None
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        _prov = TracerProvider()
        if s.otel_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                _prov.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_endpoint)))
            except Exception as exc:
                logger.debug("OTLP exporter init failed: %s", exc)
        trace.set_tracer_provider(_prov)
        _tracer = trace.get_tracer("shail")
        _enabled = True
        logger.info("OTel tracing initialized → %s", s.otel_endpoint or "no-export")
    except ImportError:
        logger.debug("opentelemetry not installed — tracing disabled")
    except Exception as exc:
        logger.debug("Tracing init error: %s", exc)
    return _tracer


def trace_fn(span_name: Optional[str] = None, *, attributes: Optional[dict] = None):
    """Decorator: wrap an async function in an OTel span."""
    def decorator(fn: Callable) -> Callable:
        name = span_name or fn.__qualname__

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = _get_tracer()
            if tracer is None:
                return await fn(*args, **kwargs)
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, str(v))
                try:
                    result = await fn(*args, **kwargs)
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    raise

        return wrapper
    return decorator


def trace_retrieval(fn: Callable) -> Callable:
    """Shorthand decorator for retrieval functions."""
    return trace_fn(f"shail.retrieval.{fn.__name__}")(fn)
