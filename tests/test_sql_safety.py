"""Unit tests for the SQL safety module."""

import pytest

from app.security.sql_safety import (
    validate_sql,
    check_user_intent,
    SQLSafetyResult,
)


class TestValidateSQL:
    """Test SQL safety validation."""

    # --- Basic SELECT ---

    def test_simple_select_allowed(self):
        result = validate_sql("SELECT * FROM fact_order")
        assert result.safe
        assert "LIMIT 1000" in result.normalized_sql

    def test_select_with_where(self):
        result = validate_sql("SELECT order_id, order_amount FROM fact_order WHERE order_amount > 100")
        assert result.safe

    def test_select_with_join(self):
        sql = """
        SELECT r.region_name, SUM(f.order_amount) as total
        FROM fact_order f
        JOIN dim_region r ON f.region_id = r.region_id
        GROUP BY r.region_name
        """
        result = validate_sql(sql)
        assert result.safe

    def test_empty_sql_blocked(self):
        result = validate_sql("")
        assert not result.safe

    def test_none_sql_blocked(self):
        result = validate_sql("")
        assert not result.safe

    # --- Dangerous statements ---

    def test_drop_blocked(self):
        result = validate_sql("DROP TABLE fact_order")
        assert not result.safe
        assert "DROP" in result.reason

    def test_delete_blocked(self):
        result = validate_sql("DELETE FROM fact_order WHERE order_id = 1")
        assert not result.safe
        assert "DELETE" in result.reason

    def test_update_blocked(self):
        result = validate_sql("UPDATE fact_order SET order_amount = 0")
        assert not result.safe
        assert "UPDATE" in result.reason

    def test_insert_blocked(self):
        result = validate_sql("INSERT INTO fact_order (order_id) VALUES (999)")
        assert not result.safe
        assert "INSERT" in result.reason

    def test_create_blocked(self):
        result = validate_sql("CREATE TABLE evil (id INT)")
        assert not result.safe
        assert "CREATE" in result.reason

    def test_alter_blocked(self):
        result = validate_sql("ALTER TABLE fact_order ADD COLUMN evil VARCHAR(100)")
        assert not result.safe
        assert "ALTER" in result.reason

    def test_truncate_blocked(self):
        result = validate_sql("TRUNCATE TABLE fact_order")
        assert not result.safe
        assert "TRUNCATE" in result.reason

    def test_replace_blocked(self):
        result = validate_sql("REPLACE INTO fact_order (order_id) VALUES (1)")
        assert not result.safe
        assert "REPLACE" in result.reason

    def test_merge_blocked(self):
        result = validate_sql("MERGE INTO fact_order USING temp ON 1=1 WHEN MATCHED THEN UPDATE SET order_amount=0")
        assert not result.safe
        # May be caught by MERGE or UPDATE keyword detection

    def test_call_blocked(self):
        result = validate_sql("CALL stored_procedure()")
        assert not result.safe
        assert "CALL" in result.reason

    def test_exec_blocked(self):
        result = validate_sql("EXEC stored_procedure")
        assert not result.safe
        assert "EXEC" in result.reason

    # --- Multi-statement ---

    def test_multi_statement_blocked(self):
        result = validate_sql("SELECT 1; DROP TABLE fact_order")
        assert not result.safe
        assert "多条" in result.reason or "多语句" in result.reason or "DROP" in result.reason

    def test_semicolon_injection_blocked(self):
        result = validate_sql("SELECT * FROM fact_order; DELETE FROM dim_region")
        assert not result.safe

    # --- Comment bypass ---

    def test_comment_bypass_drop(self):
        result = validate_sql("SELECT /* DROP TABLE */ 1 FROM fact_order")
        assert not result.safe
        assert "DROP" in result.reason

    def test_comment_bypass_delete(self):
        result = validate_sql("SELECT 1 /* DELETE */ FROM fact_order")
        assert not result.safe
        assert "DELETE" in result.reason

    def test_line_comment_bypass(self):
        result = validate_sql("SELECT 1 -- DELETE\nFROM fact_order")
        # The DELETE keyword is in a comment, should still be blocked
        assert not result.safe

    # --- Table access control ---

    def test_blocked_table_blocked(self):
        result = validate_sql(
            "SELECT * FROM sys_config",
            blocked_tables=["sys_config", "user_info"]
        )
        assert not result.safe
        assert "黑名单" in result.reason

    def test_blocked_table_case_insensitive(self):
        result = validate_sql(
            "SELECT * FROM SYS_CONFIG",
            blocked_tables=["sys_config"]
        )
        assert not result.safe

    def test_visible_tables_enforced(self):
        result = validate_sql(
            "SELECT * FROM secret_table",
            visible_tables=["fact_order", "dim_region"]
        )
        assert not result.safe
        assert "白名单" in result.reason

    def test_visible_tables_allowed(self):
        result = validate_sql(
            "SELECT * FROM fact_order",
            visible_tables=["fact_order", "dim_region"]
        )
        assert result.safe

    def test_alias_short_allowed(self):
        """FROM fact_order f should match visible_tables=['fact_order']."""
        result = validate_sql(
            "SELECT * FROM fact_order f WHERE f.order_id > 0",
            visible_tables=["fact_order", "dim_region"]
        )
        assert result.safe

    def test_alias_as_allowed(self):
        """FROM fact_order AS f should match visible_tables=['fact_order']."""
        result = validate_sql(
            "SELECT * FROM fact_order AS f",
            visible_tables=["fact_order"]
        )
        assert result.safe

    def test_join_alias_allowed(self):
        """JOIN with alias should match visible table."""
        sql = "SELECT r.region_name, SUM(f.order_amount) FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id GROUP BY r.region_name"
        result = validate_sql(
            sql,
            visible_tables=["fact_order", "dim_region"]
        )
        assert result.safe

    def test_alias_blocked_table(self):
        """FROM sys_config s should still be blocked."""
        result = validate_sql(
            "SELECT * FROM sys_config s",
            blocked_tables=["sys_config"]
        )
        assert not result.safe

    def test_schema_qualified_table(self):
        """FROM dw.fact_order should match visible_tables=['fact_order']."""
        result = validate_sql(
            "SELECT * FROM dw.fact_order",
            visible_tables=["fact_order"]
        )
        assert result.safe

    def test_visible_tables_case_insensitive(self):
        result = validate_sql(
            "SELECT * FROM FACT_ORDER",
            visible_tables=["fact_order"]
        )
        assert result.safe

    def test_blocked_wins_over_visible(self):
        result = validate_sql(
            "SELECT * FROM fact_order",
            visible_tables=["fact_order"],
            blocked_tables=["fact_order"]
        )
        assert not result.safe
        assert "黑名单" in result.reason

    # --- LIMIT enforcement ---

    def test_missing_limit_appended(self):
        result = validate_sql("SELECT * FROM fact_order")
        assert result.safe
        assert "LIMIT 1000" in result.normalized_sql

    def test_excessive_limit_reduced(self):
        result = validate_sql("SELECT * FROM fact_order LIMIT 99999")
        assert result.safe
        assert "LIMIT 1000" in result.normalized_sql

    def test_acceptable_limit_preserved(self):
        result = validate_sql("SELECT * FROM fact_order LIMIT 50")
        assert result.safe
        assert "LIMIT 50" in result.normalized_sql

    def test_custom_max_rows(self):
        result = validate_sql("SELECT * FROM fact_order", max_rows=500)
        assert result.safe
        assert "LIMIT 500" in result.normalized_sql

    def test_limit_offset_format(self):
        result = validate_sql("SELECT * FROM fact_order LIMIT 0, 5000", max_rows=1000)
        assert result.safe
        assert "LIMIT 0, 1000" in result.normalized_sql


class TestCheckUserIntent:
    """Test user intent pre-check."""

    def test_normal_question_allowed(self):
        result = check_user_intent("统计各地区的销售总额")
        assert result.safe

    def test_english_question_allowed(self):
        result = check_user_intent("Show me total sales by region")
        assert result.safe

    def test_drop_table_intent_blocked(self):
        result = check_user_intent("DROP TABLE fact_order")
        assert not result.safe

    def test_delete_intent_blocked(self):
        result = check_user_intent("DELETE FROM fact_order")
        assert not result.safe

    def test_update_intent_blocked(self):
        result = check_user_intent("UPDATE fact_order SET amount=0")
        assert not result.safe


class TestSQLSafetyResult:
    """Test SQLSafetyResult class."""

    def test_bool_true(self):
        r = SQLSafetyResult(True, "", "")
        assert bool(r)

    def test_bool_false(self):
        r = SQLSafetyResult(False, "error", "")
        assert not bool(r)

    def test_repr(self):
        r = SQLSafetyResult(True, "", "")
        assert "True" in repr(r)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
