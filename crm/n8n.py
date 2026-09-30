"""Client for the n8n Lead Tools MCP server's `qualify_lead` tool, over streamable HTTP with a token."""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
from django.conf import settings
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

TOOL_NAME = "qualify_lead"


class N8nError(Exception):
    """Base class for failures talking to the n8n MCP server."""


class N8nUnavailable(N8nError):
    """A failure worth retrying: the server was unreachable, timed out, or the tool reported an error."""


class N8nBadResult(N8nError):
    """A failure not worth retrying: missing configuration or a result that is not the expected JSON."""


@dataclass(frozen=True)
class Qualification:
    """The fields LeadDesk keeps from one `qualify_lead` result."""

    fit_score: object
    industry: str
    company_summary: str
    need: str
    suggested_reply: str
    raw: dict[str, Any]
    external_id: str | None = None


def _read_token() -> str:
    """Read the bearer token from its file, failing clearly if it's missing."""
    path = Path(settings.N8N_MCP_TOKEN_FILE)
    if not path.is_file():
        raise N8nBadResult(f"n8n MCP token file not found at {path}")
    token = path.read_text().strip()
    if not token:
        raise N8nBadResult(f"n8n MCP token file at {path} is empty")
    return token


def _root_cause(exc: BaseException) -> BaseException:
    """Unwrap the exception groups the MCP SDK raises down to the error that caused them."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def parse_result(text: str) -> Qualification:
    """Parse the tool's text output, a JSON object or a one-item JSON array, into a Qualification."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise N8nBadResult(f"qualify_lead returned non-JSON output: {text[:200]!r}") from exc
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict) or "fit_score" not in data:
        raise N8nBadResult(f"qualify_lead result has no fit_score: {text[:200]!r}")
    return Qualification(
        fit_score=data["fit_score"],
        industry=str(data.get("industry") or "")[:200],
        company_summary=str(data.get("company_summary") or ""),
        need=str(data.get("need") or ""),
        suggested_reply=str(data.get("suggested_reply") or ""),
        raw=data,
        external_id=str(data["execution_id"]) if data.get("execution_id") else None,
    )


async def _call(arguments: dict[str, str]) -> str:
    """Open one MCP session, call the tool, and return its text content."""
    headers = {"Authorization": f"Bearer {_read_token()}"}
    http_client = httpx2.AsyncClient(headers=headers, timeout=settings.N8N_MCP_TIMEOUT_SECONDS)
    try:
        async with Client(
            streamable_http_client(settings.N8N_MCP_URL, http_client=http_client), cache=None
        ) as client:
            result = await client.call_tool(TOOL_NAME, arguments)
    except N8nError:
        raise
    except Exception as exc:  # noqa: BLE001 - any transport failure is a retryable outage
        raise N8nUnavailable(f"Could not reach n8n MCP server: {_root_cause(exc)}") from exc
    text = "\n".join(getattr(block, "text", "") for block in result.content).strip()
    if result.is_error:
        raise N8nUnavailable(f"qualify_lead reported an error: {text[:300]}")
    return text


def qualify(*, website: str, contact_name: str, contact_email: str, message: str) -> Qualification:
    """Score one lead through n8n; raises N8nUnavailable (retry) or N8nBadResult (give up)."""
    arguments = {
        "website": website,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "message": message,
    }
    logger.info("Calling n8n %s for %s", TOOL_NAME, website)
    return parse_result(asyncio.run(_call(arguments)))
