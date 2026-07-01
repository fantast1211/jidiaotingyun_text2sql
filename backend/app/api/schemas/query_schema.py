from pydantic import BaseModel


class QuerySchema(BaseModel):
    query: str


class PreviewResponse(BaseModel):
    query_id: str
    sql: str | None = None
    explanation: str = ""
    involved_tables: list[str] = []
    involved_columns: list[str] = []
    safety_status: str = "pending"  # "safe", "blocked", "pending"
    executable: bool = False
    error_message: str | None = None


class ExecuteRequest(BaseModel):
    query_id: str


class ExecuteResponse(BaseModel):
    executed_sql: str | None = None
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    error_message: str | None = None
