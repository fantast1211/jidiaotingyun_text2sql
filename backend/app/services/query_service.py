import json
import uuid

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import preview_graph
from app.agent.state import DataAgentState
from app.conf.app_config import app_config
from app.core.log import logger
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.security.sql_safety import validate_sql, check_user_intent
from app.services.preview_cache import PreviewEntry, preview_cache


class QueryService:
    def __init__(self,
                 embedding_client: HuggingFaceEndpointEmbeddings,
                 column_qdrant_repository: ColumnQdrantRepository,
                 value_es_repository: ValueESRepository,
                 metric_qdrant_repository: MetricQdrantRepository,
                 meta_mysql_repository: MetaMySQLRepository,
                 dw_mysql_repository: DWMySQLRepository):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

    def _build_context(self) -> DataAgentContext:
        return DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository
        )

    async def preview(self, query: str):
        """Preview mode: generate SQL without executing. Streams SSE progress events,
        then sends a final preview result event with safety validation."""

        # Step 0: User intent pre-check
        intent_check = check_user_intent(query)
        if not intent_check.safe:
            query_id = str(uuid.uuid4())
            entry = PreviewEntry(
                query_id=query_id,
                query=query,
                sql="",
                explanation="",
                involved_tables=[],
                involved_columns=[],
                safety_status="blocked",
                executable=False,
                error_message=intent_check.reason,
            )
            preview_cache.put(entry)
            yield f"data: {json.dumps({'type': 'preview_result', 'query_id': query_id, 'sql': '', 'explanation': '', 'involved_tables': [], 'involved_columns': [], 'safety_status': 'blocked', 'executable': False, 'error_message': intent_check.reason}, ensure_ascii=False, default=str)}\n\n"
            return

        context = self._build_context()
        state = DataAgentState(query=query)

        # Track progress events and final state
        progress_events = []
        final_state = {}

        try:
            # Use "updates" mode: each chunk is {node_name: state_update}
            async for chunk in preview_graph.astream(input=state, context=context, stream_mode="updates"):
                for node_name, update in chunk.items():
                    progress_event = {
                        "type": "progress",
                        "step": node_name,
                        "status": "success"
                    }
                    progress_events.append(progress_event)
                    yield f"data: {json.dumps(progress_event, ensure_ascii=False, default=str)}\n\n"
                    # Merge update into final_state
                    if update:
                        final_state.update(update)

        except Exception as e:
            logger.error(f"Preview generation failed: {e}")
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False, default=str)}\n\n"
            return

        # Extract information from accumulated state
        sql = final_state.get("sql", "")
        error = final_state.get("error")
        table_infos = final_state.get("table_infos", [])
        metric_infos = final_state.get("metric_infos", [])

        # Build involved tables and columns
        involved_tables = []
        involved_columns = []
        for table_info in table_infos:
            involved_tables.append(table_info["name"])
            for col in table_info.get("columns", []):
                involved_columns.append(col["name"])

        # Build explanation
        explanation = self._build_explanation(table_infos, metric_infos, final_state.get("date_info"))

        # Step 1: Check agent-level errors (EXPLAIN validation)
        if error:
            query_id = str(uuid.uuid4())
            entry = PreviewEntry(
                query_id=query_id, query=query, sql=sql, explanation=explanation,
                involved_tables=involved_tables, involved_columns=involved_columns,
                safety_status="blocked", executable=False,
                error_message=f"SQL验证失败: {error}", progress_events=progress_events,
            )
            preview_cache.put(entry)
            yield f"data: {json.dumps({'type': 'preview_result', 'query_id': query_id, 'sql': sql, 'explanation': explanation, 'involved_tables': involved_tables, 'involved_columns': involved_columns, 'safety_status': 'blocked', 'executable': False, 'error_message': f'SQL验证失败: {error}'}, ensure_ascii=False, default=str)}\n\n"
            return

        if not sql:
            query_id = str(uuid.uuid4())
            entry = PreviewEntry(
                query_id=query_id, query=query, sql="", explanation=explanation,
                involved_tables=involved_tables, involved_columns=involved_columns,
                safety_status="blocked", executable=False,
                error_message="未能生成SQL", progress_events=progress_events,
            )
            preview_cache.put(entry)
            yield f"data: {json.dumps({'type': 'preview_result', 'query_id': query_id, 'sql': '', 'explanation': explanation, 'involved_tables': involved_tables, 'involved_columns': involved_columns, 'safety_status': 'blocked', 'executable': False, 'error_message': '未能生成SQL'}, ensure_ascii=False, default=str)}\n\n"
            return

        # Step 2: Deterministic SQL safety validation
        security_config = app_config.security
        safety_result = validate_sql(
            sql=sql,
            max_rows=security_config.max_rows,
            visible_tables=security_config.visible_tables or None,
            blocked_tables=security_config.blocked_tables or None,
        )

        if not safety_result.safe:
            query_id = str(uuid.uuid4())
            entry = PreviewEntry(
                query_id=query_id, query=query, sql=sql, explanation=explanation,
                involved_tables=involved_tables, involved_columns=involved_columns,
                safety_status="blocked", executable=False,
                error_message=f"安全检查未通过: {safety_result.reason}",
                progress_events=progress_events,
            )
            preview_cache.put(entry)
            yield f"data: {json.dumps({'type': 'preview_result', 'query_id': query_id, 'sql': sql, 'explanation': explanation, 'involved_tables': involved_tables, 'involved_columns': involved_columns, 'safety_status': 'blocked', 'executable': False, 'error_message': f'安全检查未通过: {safety_result.reason}'}, ensure_ascii=False, default=str)}\n\n"
            return

        # SQL is safe - use normalized version (with LIMIT enforced)
        normalized_sql = safety_result.normalized_sql

        # Store in cache
        query_id = str(uuid.uuid4())
        entry = PreviewEntry(
            query_id=query_id,
            query=query,
            sql=normalized_sql,
            explanation=explanation,
            involved_tables=involved_tables,
            involved_columns=involved_columns,
            safety_status="safe",
            executable=True,
            error_message=None,
            progress_events=progress_events,
        )
        preview_cache.put(entry)

        # Send preview result event
        preview_result = {
            "type": "preview_result",
            "query_id": query_id,
            "sql": normalized_sql,
            "explanation": explanation,
            "involved_tables": involved_tables,
            "involved_columns": involved_columns,
            "safety_status": "safe",
            "executable": True,
            "error_message": None,
        }
        yield f"data: {json.dumps(preview_result, ensure_ascii=False, default=str)}\n\n"

    def _build_explanation(self, table_infos: list, metric_infos: list, date_info: dict | None) -> str:
        """Build a concise explanation of the generated SQL."""
        parts = []

        # Tables
        if table_infos:
            table_names = [t["name"] for t in table_infos]
            parts.append(f"涉及表: {', '.join(table_names)}")

        # Metrics
        if metric_infos:
            metric_names = [m["name"] for m in metric_infos]
            parts.append(f"涉及指标: {', '.join(metric_names)}")

        # Date context
        if date_info:
            parts.append(f"当前日期: {date_info.get('date', '未知')}")

        return "；".join(parts) if parts else "已生成SQL预览"

    async def execute_sql_direct(self, sql: str) -> dict:
        """Execute SQL directly and return result. Used for execute endpoint."""
        try:
            result = await self.dw_mysql_repository.execute_sql(sql)
            columns = []
            rows = []
            if result and len(result) > 0:
                columns = list(result[0].keys())
                rows = [list(row.values()) for row in result]
            return {
                "executed_sql": sql,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "error_message": None,
            }
        except Exception as e:
            logger.error(f"SQL execution failed: {e}")
            return {
                "executed_sql": sql,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error_message": str(e),
            }
