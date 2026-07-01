"""Deterministic SQL safety validation module.

This module provides a safety boundary that is independent of the LLM.
It validates SQL using sqlparse with keyword-based fallback.
"""

import re

import sqlparse
from sqlparse.sql import Statement, Where, Parenthesis
from sqlparse.tokens import Keyword, DML, Punctuation

# Dangerous DDL/DML keywords that must be blocked
BLOCKED_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "CREATE", "ALTER",
    "TRUNCATE", "REPLACE", "MERGE", "CALL", "EXEC", "EXECUTE",
    "GRANT", "REVOKE", "DENY",
}

# Only SELECT is allowed
ALLOWED_STATEMENT_TYPES = {"SELECT"}


class SQLSafetyResult:
    """Result of SQL safety validation."""

    def __init__(self, safe: bool, reason: str = "", normalized_sql: str = ""):
        self.safe = safe
        self.reason = reason
        self.normalized_sql = normalized_sql

    def __bool__(self):
        return self.safe

    def __repr__(self):
        return f"SQLSafetyResult(safe={self.safe}, reason='{self.reason}')"


def validate_sql(
    sql: str,
    max_rows: int = 1000,
    visible_tables: list[str] | None = None,
    blocked_tables: list[str] | None = None,
) -> SQLSafetyResult:
    """Validate SQL for safety.

    Rules:
    1. Only one statement is allowed
    2. Only SELECT statements are allowed
    3. Dangerous keywords (DDL/DML) are blocked
    4. Table access rules are enforced (whitelist/blacklist)
    5. LIMIT is enforced (missing -> append, excessive -> reduce)

    Args:
        sql: The SQL string to validate
        max_rows: Maximum number of rows allowed (LIMIT)
        visible_tables: If non-empty, only these tables are allowed (whitelist)
        blocked_tables: These tables are always blocked (blacklist), takes priority

    Returns:
        SQLSafetyResult with safe/reason/normalized_sql
    """
    if not sql or not sql.strip():
        return SQLSafetyResult(False, "SQL为空")

    # Normalize whitespace
    sql = sql.strip()

    # Remove SQL comments to prevent keyword bypass
    cleaned_sql = _remove_comments(sql)
    if not cleaned_sql:
        return SQLSafetyResult(False, "SQL为空")

    # Check for dangerous keywords in the original SQL (before comment removal)
    # This catches cases like: SELECT /* DROP TABLE */ ...
    danger_check = _check_dangerous_keywords(sql)
    if not danger_check.safe:
        return danger_check

    # Parse with sqlparse
    try:
        statements = sqlparse.parse(cleaned_sql)
    except Exception as e:
        return SQLSafetyResult(False, f"SQL解析失败: {e}")

    if not statements:
        return SQLSafetyResult(False, "SQL解析结果为空")

    # Filter out empty statements
    statements = [s for s in statements if s.value.strip()]
    if not statements:
        return SQLSafetyResult(False, "SQL解析结果为空")

    # Rule 1: Only one statement
    if len(statements) > 1:
        return SQLSafetyResult(False, "不允许执行多条SQL语句")

    stmt = statements[0]

    # Rule 2: Only SELECT
    stmt_type = _get_statement_type(stmt)
    if stmt_type not in ALLOWED_STATEMENT_TYPES:
        return SQLSafetyResult(False, f"仅允许SELECT语句，不允许{stmt_type}语句")

    # Rule 3: Check for dangerous keywords in parsed tokens
    danger_check = _check_dangerous_keywords_in_tokens(stmt)
    if not danger_check.safe:
        return danger_check

    # Rule 4: Table access rules
    table_check = _check_table_access(stmt, visible_tables, blocked_tables)
    if not table_check.safe:
        return table_check

    # Rule 5: LIMIT enforcement
    normalized_sql = _enforce_limit(cleaned_sql, max_rows)

    return SQLSafetyResult(True, "", normalized_sql)


def _remove_comments(sql: str) -> str:
    """Remove SQL comments to prevent keyword bypass."""
    # Remove single-line comments (-- ...)
    sql = re.sub(r'--[^\n]*', '', sql)
    # Remove multi-line comments (/* ... */)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql.strip()


def _check_dangerous_keywords(sql: str) -> SQLSafetyResult:
    """Check for dangerous keywords using regex (works on original SQL with comments)."""
    # Convert to uppercase for case-insensitive matching
    sql_upper = sql.upper()

    # Check for blocked keywords as whole words
    for keyword in BLOCKED_KEYWORDS:
        # Use word boundary to avoid false positives (e.g., "UPDATED_AT" shouldn't match "UPDATE")
        pattern = r'\b' + keyword + r'\b'
        if re.search(pattern, sql_upper):
            return SQLSafetyResult(False, f"检测到危险关键字: {keyword}，仅允许只读查询")

    return SQLSafetyResult(True)


def _check_dangerous_keywords_in_tokens(stmt: Statement) -> SQLSafetyResult:
    """Check for dangerous keywords in parsed SQL tokens."""
    for token in stmt.flatten():
        if token.ttype is Keyword or token.ttype is DML:
            value = token.value.upper().strip()
            if value in BLOCKED_KEYWORDS:
                return SQLSafetyResult(False, f"检测到危险关键字: {value}，仅允许只读查询")
    return SQLSafetyResult(True)


def _get_statement_type(stmt: Statement) -> str:
    """Extract the statement type (SELECT, INSERT, etc.)."""
    for token in stmt.tokens:
        if token.ttype is DML:
            return token.value.upper()
        if token.ttype is Keyword:
            return token.value.upper()
    return "UNKNOWN"


def _check_table_access(
    stmt: Statement,
    visible_tables: list[str] | None,
    blocked_tables: list[str] | None,
) -> SQLSafetyResult:
    """Check if the SQL only accesses allowed tables."""
    # Extract table names from SQL (already lowercased by _extract_table_names)
    tables = _extract_table_names(stmt)

    if not tables:
        return SQLSafetyResult(True)

    blocked_lower = {t.lower() for t in (blocked_tables or [])}
    visible_lower = {t.lower() for t in (visible_tables or [])}

    def _table_matches(table: str, allowed: set[str]) -> bool:
        """Check if a table name matches any in the allowed set.
        Handles schema.table format by also checking just the table part."""
        if table in allowed:
            return True
        # For schema.table, also check just the table part
        if "." in table:
            table_only = table.split(".")[-1]
            if table_only in allowed:
                return True
        return False

    # Rule: blocked_tables always wins
    for table in tables:
        if _table_matches(table, blocked_lower):
            return SQLSafetyResult(False, f"表 '{table}' 在黑名单中，不允许访问")

    # Rule: if visible_tables is configured, only visible tables are allowed
    if visible_lower:
        for table in tables:
            if not _table_matches(table, visible_lower):
                return SQLSafetyResult(False, f"表 '{table}' 不在白名单中，不允许访问")

    return SQLSafetyResult(True)


def _extract_table_names(stmt: Statement) -> list[str]:
    """Extract table names from a parsed SQL statement, stripping aliases."""
    tables = set()

    # Use regex to extract table names from FROM and JOIN clauses
    # This handles aliases like "FROM fact_order f" or "FROM fact_order AS f"
    sql_text = stmt.value

    # Match: FROM/JOIN <table_name> [AS] [alias]
    # Captures the table name (possibly schema.table), skips alias
    pattern = r'(?:FROM|JOIN)\s+(`[^`]+`|"[^"]+"|[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?)\s*(?:AS\s+)?(?:`[^`]*`|"[^"]*"|[a-zA-Z_]\w*)?(?=\s|,|$|\(|ON|WHERE|GROUP|ORDER|HAVING|LIMIT|UNION|JOIN)'
    matches = re.findall(pattern, sql_text, re.IGNORECASE)
    for match in matches:
        name = match.strip().strip('`"\'')
        if name and name.lower() not in ('select', 'where', 'and', 'or', 'not', 'on', 'as'):
            tables.add(name.lower())

    # Also try a simpler fallback pattern for common cases
    simple_pattern = r'(?:FROM|JOIN)\s+([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?)\b'
    simple_matches = re.findall(simple_pattern, sql_text, re.IGNORECASE)
    for match in simple_matches:
        name = match.strip().strip('`"\'')
        if name and name.lower() not in ('select', 'where', 'and', 'or', 'not', 'on', 'as'):
            tables.add(name.lower())

    return list(tables)


def _enforce_limit(sql: str, max_rows: int) -> str:
    """Enforce LIMIT on the SQL.

    Rules:
    - If no LIMIT, append LIMIT max_rows
    - If LIMIT > max_rows, reduce to max_rows
    - If LIMIT <= max_rows, keep it
    """
    # Check if SQL already has a LIMIT
    limit_pattern = r'\bLIMIT\s+(\d+)\s*(?:,\s*(\d+))?\s*$'
    match = re.search(limit_pattern, sql, re.IGNORECASE)

    if match:
        # SQL has LIMIT
        if match.group(2):
            # LIMIT offset, count format
            offset = int(match.group(1))
            count = int(match.group(2))
            if count > max_rows:
                sql = re.sub(limit_pattern, f'LIMIT {offset}, {max_rows}', sql, flags=re.IGNORECASE)
        else:
            # LIMIT count format
            limit_val = int(match.group(1))
            if limit_val > max_rows:
                sql = re.sub(limit_pattern, f'LIMIT {max_rows}', sql, flags=re.IGNORECASE)
    else:
        # No LIMIT, append it
        sql = sql.rstrip(';').rstrip() + f' LIMIT {max_rows}'

    return sql


def check_user_intent(query: str) -> SQLSafetyResult:
    """Pre-check user natural language input for obvious dangerous intent.

    This is a lightweight check before sending to the LLM.
    It catches obvious cases like "DROP TABLE fact_order" or raw SQL with
    dangerous keywords. Natural language questions that happen to contain
    these words in a non-SQL context should still be allowed.
    """
    query_upper = query.upper().strip()

    # Check if the input looks like raw SQL with dangerous keywords
    for keyword in BLOCKED_KEYWORDS:
        pattern = r'\b' + keyword + r'\b'
        if re.search(pattern, query_upper):
            # Heuristic: if the input starts with the keyword or contains
            # SQL-like patterns (FROM, SET, TABLE, INTO, etc.), it's likely raw SQL
            starts_with_keyword = query_upper.startswith(keyword)
            has_sql_pattern = bool(re.search(
                r'\b(FROM|TABLE|INTO|SET|VALUES|WHERE|COLUMN)\b', query_upper
            ))
            has_table_name = bool(re.search(r'\b\w+\s*\(', query))

            if starts_with_keyword or has_sql_pattern or has_table_name:
                return SQLSafetyResult(
                    False,
                    f"检测到危险意图: {keyword}。系统仅支持只读查询，不支持数据修改或结构变更操作。"
                )

    return SQLSafetyResult(True)
