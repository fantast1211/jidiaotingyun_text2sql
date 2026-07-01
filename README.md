# 自然语言转 SQL 助手

基于 LangGraph Agent 和 RAG 检索增强的自然语言转 SQL 查询系统。用户输入中文或英文业务问题，系统自动生成 SQL 预览，经安全校验后执行查询并展示结果。

## 功能特性

- **自然语言理解**：支持中文和英文业务问题输入
- **Schema 感知**：通过 Qdrant 向量召回和 Elasticsearch 值召回，自动识别相关表、字段和指标
- **SQL 预览**：执行前展示生成的 SQL 和简要说明，用户确认后再执行
- **安全防护**：基于 sqlparse 的确定性 SQL 安全校验，阻止危险操作
- **结果展示**：表格形式展示查询结果
- **CSV 导出**：支持将查询结果导出为 CSV 文件

## 快速开始

### 1. 环境要求

- Python >= 3.12
- Node.js >= 18
- MySQL 8.0+
- Qdrant 向量数据库
- Elasticsearch 8.x

### 2. 安装后端依赖

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置

复制示例配置文件，作为非敏感默认配置：

```bash
cp config/example.yaml backend/conf/app_config.yaml
```

真实连接信息和密钥放在 `.env` 中，由服务启动时通过环境变量覆盖：

```bash
cp .env.example .env
```

编辑 `.env`，填写 MySQL、Qdrant、Elasticsearch、Embedding、LLM 等真实配置。`.env` 已被 `.gitignore` 忽略，不会被提交。

`backend/conf/app_config.yaml` 和 `.env` 支持以下配置：

| 配置项 | 说明 |
|--------|------|
| `db_meta` | 元数据库连接（存储表/字段/指标元数据） |
| `db_dw` | 数据仓库连接（存储业务数据） |
| `qdrant` | Qdrant 向量数据库连接 |
| `embedding` | Embedding 服务配置（用于文本向量化） |
| `es` | Elasticsearch 连接（用于字段取值召回） |
| `llm` | LLM 大语言模型配置 |
| `security` | SQL 安全配置（最大行数、表黑白名单） |

常用 `.env` 变量包括：

```bash
DB_META_HOST=127.0.0.1
DB_META_USER=root
DB_META_PASSWORD=change-me
DB_DW_HOST=127.0.0.1
DB_DW_USER=root
DB_DW_PASSWORD=change-me
QDRANT_HOST=127.0.0.1
ES_HOST=127.0.0.1
EMBEDDING_API_KEY=change-me
LLM_API_KEY=change-me
```

### 4. 初始化数据库

```bash
# 创建数据仓库并导入示例数据
mysql -u <user> -p < sql/dw.sql

# 创建元数据库
mysql -u <user> -p < sql/meta.sql
```

### 5. 构建元数据知识库

```bash
cd backend
python -m app.scripts.build_meta_knowledge -c conf/app_config.yaml
```

此脚本会：
- 将表/字段/指标元数据写入元数据库
- 将字段信息向量化并存入 Qdrant
- 将字段取值同步到 Elasticsearch

### 6. 启动后端

```bash
cd backend
python main.py
```

后端将在 `http://localhost:8000` 启动。

### 7. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端将在 `http://localhost:5173` 启动，并自动代理 API 请求到后端。

### 8. 访问应用

打开浏览器访问 `http://localhost:5173`，输入业务问题开始查询。

## 示例问题

### 示例 1：简单聚合

**问题**：统计各地区的销售总额

**参考 SQL**：
```sql
SELECT r.region_name, SUM(f.order_amount) AS total_sales
FROM fact_order f
JOIN dim_region r ON f.region_id = r.region_id
GROUP BY r.region_name
ORDER BY total_sales DESC
LIMIT 1000
```

### 示例 2：多表关联

**问题**：按商品品类统计各省份的订单数量

**参考 SQL**：
```sql
SELECT r.province, p.category, COUNT(f.order_id) AS order_count
FROM fact_order f
JOIN dim_region r ON f.region_id = r.region_id
JOIN dim_product p ON f.product_id = p.product_id
GROUP BY r.province, p.category
ORDER BY order_count DESC
LIMIT 1000
```

### 示例 3：时间范围查询

**问题**：查询 2025 年 1 月各商品品牌的月度销售额

**参考 SQL**：
```sql
SELECT p.brand, d.month, SUM(f.order_amount) AS monthly_sales
FROM fact_order f
JOIN dim_product p ON f.product_id = p.product_id
JOIN dim_date d ON f.date_id = d.date_id
WHERE d.year = 2025 AND d.month = 1
GROUP BY p.brand, d.month
ORDER BY monthly_sales DESC
LIMIT 1000
```

## 恶意输入防护

系统具备多层安全防护机制：

### 用户意图预检

系统会在发送给 LLM 之前检查用户输入是否包含明显的危险意图：

```
输入：DROP TABLE fact_order
输出：检测到危险意图: DROP。系统仅支持只读查询，不支持数据修改或结构变更操作。
```

### SQL 安全校验

LLM 生成的 SQL 会经过确定性安全校验：

| 检查项 | 说明 |
|--------|------|
| 语句类型 | 仅允许 SELECT |
| 危险关键字 | 阻止 DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/TRUNCATE 等 |
| 多语句注入 | 阻止分号分隔的多条 SQL |
| 注释绕过 | 去除注释后检查关键字 |
| 表访问控制 | 支持白名单和黑名单，不区分大小写 |
| 行数限制 | 自动添加或修正 LIMIT |

```
输入：DELETE FROM fact_order WHERE order_id = 1
输出：安全检查未通过: 检测到危险关键字: DELETE，仅允许只读查询
```

## 项目结构

```
jidiaotingyun_text2sql/
├── README.md                  # 项目说明
├── requirements.txt           # Python 依赖
├── config/example.yaml        # 配置示例
├── docs/design.md             # 设计文档
├── sql/                       # 数据库初始化脚本
│   ├── dw.sql                 # 数据仓库 DDL + 示例数据
│   └── meta.sql               # 元数据库 DDL
├── backend/                   # 后端（Python/FastAPI/LangGraph）
│   ├── main.py                # 入口
│   ├── app/
│   │   ├── agent/             # LangGraph Agent 流程
│   │   ├── api/               # FastAPI 路由
│   │   ├── security/          # SQL 安全模块
│   │   ├── services/          # 业务逻辑
│   │   └── ...                # 客户端、仓库、配置等
│   ├── conf/                  # 配置文件
│   └── prompts/               # LLM Prompt 模板
├── frontend/                  # 前端（Vue 3 + Vite）
│   ├── src/App.vue            # 主界面
│   └── ...
└── tests/                     # 测试
    └── test_sql_safety.py     # SQL 安全模块测试
```

## 运行测试

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行 SQL 安全模块测试
python -m pytest tests/test_sql_safety.py -v
```

## AI 使用说明

本项目使用了以下 AI 能力：

1. **LLM（大语言模型）**：用于关键词扩展、表/字段过滤、SQL 生成和 SQL 校正
2. **Embedding（文本向量化）**：用于将关键词、字段描述、指标描述向量化，支持语义召回
3. **RAG（检索增强生成）**：通过 Qdrant 向量检索和 Elasticsearch 全文检索，为 LLM 提供准确的 Schema 上下文

Agent 流程采用 LangGraph 编排，包含 12 个节点的有向无环图，支持并行召回和条件分支。

## License

MIT
