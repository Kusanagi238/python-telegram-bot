#!/usr/bin/env python
#
#  A library that provides a Python interface to the Telegram Bot API
#  Copyright (C) 2015-2025
#  Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser Public License for more details.
#
#  You should have received a copy of the GNU Lesser Public License
#  along with this program.  If not, see [http://www.gnu.org/licenses/].
from pathlib import Path
from typing import Optional

import pytest
from httpx import AsyncClient, AsyncHTTPTransport, Response

from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.strings import TextEncoding
from telegram._utils.types import ODVInput
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.request import BaseRequest, HTTPXRequest, RequestData


class NonchalantHttpxRequest(HTTPXRequest):
    """This Request class is used in the tests to suppress errors that we don't care about
    in the test suite.
    """

    async def _request_wrapper(
        self,
        method: str,
        url: str,
        request_data: Optional[RequestData] = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> bytes:
        try:
            return await super()._request_wrapper(
                method=method,
                url=url,
                request_data=request_data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        except RetryAfter:
            # Re-raise to allow tests/CI to observe and handle the retry-after condition
            raise
        except TimedOut:
            # Re-raise so the timeout is not silently converted to an XFAIL
            raise


class OfflineRequest(BaseRequest):
    """This Request class disallows making requests to Telegram's servers.
    Use this in tests that should not depend on the network.
    """

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    @property
    def read_timeout(self):
        return 1

    def __init__(self, *args, **kwargs):
        pass

    async def do_request(
        self,
        url: str,
        method: str,
        request_data: Optional[RequestData] = None,
        read_timeout: ODVInput[float] = BaseRequest.DEFAULT_NONE,
        write_timeout: ODVInput[float] = BaseRequest.DEFAULT_NONE,
        connect_timeout: ODVInput[float] = BaseRequest.DEFAULT_NONE,
        pool_timeout: ODVInput[float] = BaseRequest.DEFAULT_NONE,
    ) -> tuple[int, bytes]:
        pytest.fail("OfflineRequest: Network access disallowed in this test")


async def expect_bad_request(func, message, reason):
    """
    Wrapper for testing bot functions expected to result in an :class:`telegram.error.BadRequest`.
    If the specified error message is present, the exception is treated as the expected outcome
    and returned to the caller instead of being converted to an XFAIL.

    Args:
        func: The awaitable to be executed.
        message: The expected message of the bad request error. If another message is present,
            the error will be reraised.
        reason: Explanation for the expectation.

    Returns:
        On success, returns the return value of :attr:`func`. If a BadRequest with the expected
        message occurs, the caught exception is returned so the test can assert on it.
    """
    try:
        return await func()
    except BadRequest as e:
        if message in str(e):
            # Return the exception instead of marking the test XFAIL so the test harness
            # can treat this as the expected outcome.
            return e
        else:
            raise


async def send_webhook_message(
    ip: str,
    port: int,
    payload_str: Optional[str],
    url_path: str = "",
    content_len: int = -1,
    content_type: str = "application/json",
    get_method: Optional[str] = None,
    secret_token: Optional[str] = None,
    unix: Optional[Path] = None,
) -> Response:
    headers = {
        "content-type": content_type,
    }
    if secret_token:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret_token

    # Distinguish between "no payload provided" (None) and an empty payload string ("").
    if payload_str is None:
        payload = None
    else:
        payload = bytes(payload_str, encoding=TextEncoding.UTF_8)

    # If content_len is left as -1, compute it from the payload. For a None payload we
    # keep payload as None and will omit the Content-Length header; for an empty payload
    # (b''), content-length will be set to 0.
    if content_len == -1:
        content_len = len(payload) if payload is not None else 0

    if payload is not None:
        headers["content-length"] = str(content_len)

    url = f"http://{ip}:{port}/{url_path}"

    transport = AsyncHTTPTransport(uds=unix) if unix else None

    async with AsyncClient(transport=transport) as client:
        return await client.request(
            url=url, method=get_method or "POST", data=payload, headers=headers
        )
