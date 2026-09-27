"""AWS Lambda export with lazy client composition and no import-time I/O."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from eventpulse.handler import create_handler


@lru_cache(maxsize=1)
def _handler() -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    from eventpulse.aws import create_aws_runtime

    return create_handler(create_aws_runtime())


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return _handler()(event, context)
