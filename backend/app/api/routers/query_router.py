from fastapi import APIRouter
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import (
    QuerySchema,
    ExecuteRequest,
    ExecuteResponse,
)
from app.conf.app_config import app_config
from app.security.sql_safety import validate_sql
from app.services.preview_cache import preview_cache
from app.services.query_service import QueryService

query_router = APIRouter()


@query_router.post("/api/query/preview")
async def preview(
    query: QuerySchema, query_service: QueryService = Depends(get_query_service)
):
    """Preview endpoint: generate SQL without executing. Returns SSE stream with
    progress events followed by a preview_result event containing query_id."""
    return StreamingResponse(
        query_service.preview(query.query), media_type="text/event-stream"
    )


@query_router.post("/api/query/execute")
async def execute(
    request: ExecuteRequest,
    query_service: QueryService = Depends(get_query_service),
):
    """Execute endpoint: execute previously previewed SQL by query_id.
    Re-validates SQL safety before execution."""
    # Retrieve from cache
    entry = preview_cache.get(request.query_id)
    if entry is None:
        return ExecuteResponse(
            error_message="query_id 无效或已过期，请重新生成预览"
        )

    # Check if the preview was executable
    if not entry.executable:
        return ExecuteResponse(
            error_message=entry.error_message or "该SQL不可执行"
        )

    # Re-validate SQL safety before execution (defense in depth)
    security_config = app_config.security
    safety_result = validate_sql(
        sql=entry.sql,
        max_rows=security_config.max_rows,
        visible_tables=security_config.visible_tables or None,
        blocked_tables=security_config.blocked_tables or None,
    )

    if not safety_result.safe:
        preview_cache.remove(request.query_id)
        return ExecuteResponse(
            error_message=f"安全复检未通过: {safety_result.reason}"
        )

    # Execute the cached SQL
    result = await query_service.execute_sql_direct(safety_result.normalized_sql)

    # Remove from cache after execution (one-time use)
    preview_cache.remove(request.query_id)

    return ExecuteResponse(**result)
