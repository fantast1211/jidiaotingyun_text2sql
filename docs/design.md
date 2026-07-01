# 设计文档：自然语言转 SQL 助手

## 1. 系统架构

### 1.1 整体架构

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   Frontend   │────▶│                   Backend                    │
│  (Vue/Vite)  │◀────│              (FastAPI + LangGraph)           │
└─────────────┘     └──────────┬───────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ┌──────────┐    ┌──────────┐    ┌──────────────┐
        │  MySQL   │    │  Qdrant  │    │Elasticsearch │
        │ (meta+dw)│    │ (向量DB) │    │  (全文检索)   │
        └──────────┘    └──────────┘    └──────────────┘
```

- **Frontend**：Vue 3 + Vite 单页应用，提供问题输入、SQL 预览、确认执行、结果展示和 CSV 导出
- **Backend**：FastAPI 服务，承载 LangGraph Agent 流程和 REST API
- **MySQL**：存储元数据（meta 库）和业务数据（dw 库）
- **Qdrant**：存储字段和指标的向量表示，支持语义召回
- **Elasticsearch**：存储字段取值，支持全文检索召回

### 1.2 API 设计

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /api/query/preview` | SSE 流 | 接收自然语言问题，返回 SQL 预览（不执行） |
| `POST /api/query/execute` | JSON | 接收 query_id，执行已缓存的 SQL |

**Preview 流程**：
1. 接收 `{"query": "问题"}`
2. 返回 SSE 流：多个 `progress` 事件 + 一个 `preview_result` 事件
3. `preview_result` 包含：`query_id`, `sql`, `explanation`, `involved_tables`, `involved_columns`, `safety_status`, `executable`, `error_message`

**Execute 流程**：
1. 接收 `{"query_id": "uuid"}`
2. 从缓存获取 SQL，重新安全校验，执行查询
3. 返回 `{"executed_sql", "columns", "rows", "row_count", "error_message"}`

### 1.3 确认执行模型

- Preview 成功后，SQL 存入服务端内存缓存（TTL 30 分钟）
- 前端通过 `query_id` 确认执行，不提交原始 SQL
- 执行前重新运行 SQL 安全校验（防御纵深）
- 执行后缓存自动清除（一次性使用）

## 2. Agent 流程

### 2.1 LangGraph 节点图

```
START
  │
  ▼
extract_keywords ─────────┬──────────────┬──────────────┐
  (jieba 分词)             │              │              │
                          ▼              ▼              ▼
                   recall_column    recall_value    recall_metric
                   (Qdrant 向量)   (ES 全文检索)    (Qdrant 向量)
                          │              │              │
                          └──────────────┼──────────────┘
                                         ▼
                              merge_retrieved_info
                                    │       │
                              ┌─────┘       └─────┐
                              ▼                   ▼
                        filter_table        filter_metric
                        (LLM 过滤)          (LLM 过滤)
                              │                   │
                              └─────────┬─────────┘
                                        ▼
                              add_extra_context
                              (日期 + DB 版本)
                                        │
                                        ▼
                                  generate_sql
                                  (LLM 生成 SQL)
                                        │
                                        ▼
                                  validate_sql
                                  (EXPLAIN 验证)
                                   ╱          ╲
                              有错误           无错误
                                │               │
                                ▼               ▼
                            correct_sql      [END / execute_sql]
                            (LLM 校正)
                                │
                                ▼
                            [END / execute_sql]
```

### 2.2 节点说明

| 节点 | 功能 | 输入 | 输出 |
|------|------|------|------|
| extract_keywords | jieba 分词提取关键词 | query | keywords |
| recall_column | LLM 扩展关键词 + Qdrant 向量搜索 | query, keywords | retrieved_columns |
| recall_value | LLM 扩展关键词 + ES 全文搜索 | query, keywords | retrieved_values |
| recall_metric | LLM 扩展关键词 + Qdrant 向量搜索 | query, keywords | retrieved_metrics |
| merge_retrieved_info | 合并召回信息，补充主外键 | columns, values, metrics | table_infos, metric_infos |
| filter_table | LLM 过滤无关表和字段 | query, table_infos | filtered table_infos |
| filter_metric | LLM 过滤无关指标 | query, metric_infos | filtered metric_infos |
| add_extra_context | 注入当前日期和 DB 版本 | - | date_info, db_info |
| generate_sql | LLM 生成 SQL | 所有上下文 | sql |
| validate_sql | EXPLAIN 验证 SQL 语法 | sql | error (null 或错误信息) |
| correct_sql | LLM 最小修正 SQL | sql, error | corrected sql |
| execute_sql | 执行 SQL 查询 | sql | result rows |

### 2.3 Preview 模式

- **Preview 模式**：运行到 `validate_sql` 后停止，不执行 SQL。用于 `/api/query/preview` 端点。
- 图中保留了 `execute_sql` 节点定义，但 preview 模式的图编译不包含该节点，确保 SQL 不会在预览阶段被执行。
- 执行仅通过 `/api/query/execute` 端点完成，该端点基于 `query_id` 从缓存获取 SQL，经过安全复检后再执行。

## 3. 检索策略

### 3.1 三层召回

1. **字段召回（Column Recall）**：
   - LLM 将用户问题扩展为多个字段概念关键词
   - 每个关键词通过 Embedding 向量化
   - 在 Qdrant 中搜索最相似的字段元数据
   - 返回相关字段列表（包含表归属、类型、描述、别名）

2. **值召回（Value Recall）**：
   - LLM 将用户问题扩展为可能的字段取值关键词
   - 在 Elasticsearch 中全文搜索匹配的字段取值
   - 用于识别过滤条件中的具体值（如"华东"对应 region_name）

3. **指标召回（Metric Recall）**：
   - LLM 将用户问题扩展为指标概念关键词
   - 每个关键词通过 Embedding 向量化
   - 在 Qdrant 中搜索最相似的指标元数据
   - 返回相关指标列表（包含计算公式和关联字段）

### 3.2 信息合并

- 将三层召回结果按表分组
- 补充每个表的主键和外键字段（确保 JOIN 条件完整）
- 将字段取值合并到对应字段的 examples 中

### 3.3 LLM 过滤

- 使用 LLM 对合并后的表和字段进行二次过滤
- 移除与用户问题无关的表和字段
- 减少传给 SQL 生成 LLM 的上下文量

## 4. SQL 安全设计

### 4.1 安全层次

```
用户输入
  │
  ▼
[1] 用户意图预检 ──▶ 阻止明显的恶意输入
  │
  ▼
[2] LLM 生成 SQL
  │
  ▼
[3] EXPLAIN 验证 ──▶ 检查 SQL 语法正确性
  │
  ▼
[4] 确定性安全校验 ──▶ sqlparse 解析 + 规则检查
  │
  ▼
[5] 执行前复检 ──▶ 再次运行安全校验
  │
  ▼
执行 SQL
```

### 4.2 安全规则

| 规则 | 说明 | 实现方式 |
|------|------|----------|
| 单语句 | 不允许多条 SQL | sqlparse 解析后检查语句数量 |
| 仅 SELECT | 阻止 DDL/DML | 检查语句类型 token |
| 危险关键字 | 阻止 DROP/DELETE 等 | 关键字匹配（去除注释后） |
| 注释绕过 | 防止用注释隐藏关键字 | 先去除注释再检查 |
| 表黑名单 | blocked_tables 中的表不可访问 | 从 SQL 中提取表名比对 |
| 表白名单 | visible_tables 之外的表不可访问 | 从 SQL 中提取表名比对 |
| 行数限制 | 强制 LIMIT | 缺失则添加，超出则减少 |

### 4.3 表访问控制优先级

```
blocked_tables（最高优先级）
    ↓
visible_tables（如果配置了）
    ↓
所有已知表（默认）
```

- 表名匹配不区分大小写
- `blocked_tables` 始终生效，即使表在 `visible_tables` 中

## 5. API 流程详解

### 5.1 Preview 流程

```
前端                    后端
  │                      │
  │── POST /preview ────▶│
  │                      ├── 用户意图预检
  │                      ├── 运行 LangGraph (preview 模式)
  │◀── SSE: progress ────│    ├── extract_keywords
  │◀── SSE: progress ────│    ├── recall_column/value/metric
  │◀── SSE: progress ────│    ├── merge_retrieved_info
  │◀── SSE: progress ────│    ├── filter_table/metric
  │◀── SSE: progress ────│    ├── add_extra_context
  │◀── SSE: progress ────│    ├── generate_sql
  │◀── SSE: progress ────│    └── validate_sql
  │                      ├── SQL 安全校验
  │                      ├── 存入缓存 (query_id)
  │◀── SSE: preview ─────│
  │                      │
```

### 5.2 Execute 流程

```
前端                    后端
  │                      │
  │── POST /execute ────▶│
  │   {query_id: "..."}  ├── 从缓存获取 SQL
  │                      ├── 重新安全校验
  │                      ├── 执行 SQL
  │                      ├── 清除缓存
  │◀── JSON result ──────│
  │                      │
```

## 6. 确认执行流程

1. 用户输入问题
2. 前端调用 `POST /api/query/preview`
3. 后端运行 Agent 生成 SQL，进行安全校验
4. 前端展示 SQL 预览、生成说明、安全状态
5. 如果 SQL 安全（`executable: true`），显示"确认执行"按钮
6. 用户点击确认
7. 前端调用 `POST /api/query/execute`，传入 `query_id`
8. 后端从缓存获取 SQL，重新校验，执行查询
9. 前端展示结果表格
10. 用户可导出 CSV

## 7. 关键权衡

### 7.1 Preview 缓存策略

- **选择**：内存缓存 + TTL（30 分钟）
- **原因**：最小版本不需要持久化，内存缓存足够简单可靠
- **权衡**：服务重启会丢失缓存，但对演示场景可接受

### 7.2 SQL 安全实现

- **选择**：sqlparse 解析 + 关键字匹配
- **原因**：确定性验证，不依赖 LLM 遵守 prompt 指令
- **权衡**：可能有误报（如字段名包含危险关键字），但安全性优先

### 7.3 两步 API 设计

- **选择**：Preview + Execute 分离
- **原因**：用户可以在执行前审查 SQL，防止意外查询
- **权衡**：增加了一次交互步骤，但提升了安全性和用户体验

### 7.4 前端 CSV 导出

- **选择**：前端实现，导出当前结果
- **原因**：简单直接，不需要额外后端端点
- **权衡**：只能导出当前返回的行数，不支持大数据量异步导出

### 7.5 Agent 预览模式

- **选择**：通过图裁剪实现预览模式（去掉 execute_sql 节点）
- **原因**：复用完整 Agent 流程，只跳过执行步骤
- **权挡**：需要维护两个图编译版本，但代码差异最小
