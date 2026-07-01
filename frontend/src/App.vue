<template>
  <div class="app-layout">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <h1 class="header-title">自然语言转 SQL 助手</h1>
        <p class="header-sub">基调听云 AI 研发工程师实操题 · 题目二</p>
      </div>
      <div class="header-right">
        <div class="header-candidate">候选人：姜萌</div>
        <div class="header-tags">
          <span class="htag">SELECT only</span>
          <span class="htag">LIMIT enforced</span>
          <span class="htag">Manual confirm</span>
          <span class="htag">CSV export</span>
        </div>
      </div>
    </header>

    <!-- Main -->
    <div class="main-area">
      <!-- Messages -->
      <div ref="messagesEl" class="messages">
        <!-- Empty state -->
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-icon">SQL</div>
          <p class="empty-title">输入自然语言问题，自动生成 SQL 并查询</p>
          <p class="empty-desc">支持中文 / 英文，自动 Schema 召回、安全校验、预览确认</p>
        </div>

        <div
          v-for="(msg, index) in messages"
          :key="index"
          :class="['message-row', msg.role]"
        >
          <div v-if="msg.role === 'assistant'" class="avatar assistant-avatar">AI</div>

          <div class="bubble">
            <!-- Text -->
            <div v-if="msg.type === 'text'" class="text-content">
              {{ msg.content }}
            </div>

            <!-- Steps -->
            <div v-else-if="msg.type === 'steps'" class="steps">
              <div v-for="(step, sIdx) in msg.steps" :key="sIdx" class="step">
                <span class="dot" :class="step.status"></span>
                <span class="step-label">{{ step.text }}</span>
              </div>
            </div>

            <!-- SQL Preview -->
            <div v-else-if="msg.type === 'preview'" class="preview-card">
              <div class="preview-top">
                <span class="preview-label">SQL Preview</span>
                <span :class="['status-tag', msg.safety_status]">
                  {{ msg.safety_status === 'safe' ? 'SAFE' : msg.safety_status === 'blocked' ? 'BLOCKED' : 'PENDING' }}
                </span>
              </div>

              <pre class="sql-block"><code>{{ msg.sql }}</code></pre>

              <div v-if="msg.explanation" class="preview-meta">
                <span class="meta-label">生成说明</span>
                <span class="meta-value">{{ msg.explanation }}</span>
              </div>

              <div v-if="msg.involved_tables.length" class="preview-meta">
                <span class="meta-label">涉及表</span>
                <span class="chip-list">
                  <span class="chip" v-for="t in msg.involved_tables" :key="t">{{ t }}</span>
                </span>
              </div>

              <div v-if="msg.involved_columns.length" class="preview-meta">
                <span class="meta-label">涉及字段</span>
                <span class="chip-list">
                  <span class="chip" v-for="c in msg.involved_columns" :key="c">{{ c }}</span>
                </span>
              </div>

              <div v-if="msg.error_message" class="error-card">
                <span class="error-icon">!</span>
                <span>{{ msg.error_message }}</span>
              </div>

              <div v-if="msg.executable" class="confirm-area">
                <button class="confirm-btn" @click="executeQuery(msg.query_id)" :disabled="executing">
                  {{ executing ? '执行中...' : '确认执行' }}
                </button>
              </div>
            </div>

            <!-- Table Result -->
            <div v-else-if="msg.type === 'table'" class="table-card">
              <div class="table-top">
                <span class="table-label">查询结果（{{ msg.row_count }} 行）</span>
                <button class="csv-btn" @click="exportCSV(msg)">CSV 导出</button>
              </div>
              <div class="table-scroll">
                <table class="result-table">
                  <thead>
                    <tr>
                      <th v-for="col in msg.columns" :key="col">{{ col }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in msg.rows" :key="rIdx">
                      <td v-for="(col, cIdx) in msg.columns" :key="col">{{ row[cIdx] }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Error -->
            <div v-else-if="msg.type === 'error'" class="error-card">
              <span class="error-icon">!</span>
              <span>{{ msg.content }}</span>
            </div>
          </div>

          <div v-if="msg.role === 'user'" class="avatar user-avatar">U</div>
        </div>
        <div class="messages-bottom-spacer"></div>
      </div>

      <!-- Input Area -->
      <div class="input-area">
        <div class="quick-btns">
          <button
            v-for="q in quickQuestions"
            :key="q"
            class="quick-btn"
            @click="question = q; sendQuestion()"
            :disabled="loading"
          >{{ q }}</button>
        </div>
        <div class="input-box">
          <input
            v-model="question"
            @keyup.enter="sendQuestion"
            placeholder="输入自然语言问题，例如：统计各地区的销售总额"
          />
          <button class="send-btn" @click="sendQuestion" :disabled="loading">
            {{ loading ? '生成中...' : '发送' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from "vue";

const PREVIEW_URL = "/api/query/preview";
const EXECUTE_URL = "/api/query/execute";

const question = ref("");
const loading = ref(false);
const executing = ref(false);
const messages = ref([]);
const messagesEl = ref(null);

const quickQuestions = [
  "统计所有订单的销售总额",
  "按地区统计销售总额",
  "统计2025年1月各商品品牌的销售额",
  "DROP TABLE fact_order",
];

function scrollToBottom() {
  const el = messagesEl.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

async function sendQuestion() {
  if (!question.value || loading.value) return;

  const q = question.value;
  question.value = "";
  loading.value = true;

  messages.value.push({ role: "user", type: "text", content: q });

  // steps 容器
  const stepIndex =
    messages.value.push({
      role: "assistant",
      type: "steps",
      steps: [],
    }) - 1;

  await nextTick();
  scrollToBottom();

  try {
    const response = await fetch(PREVIEW_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
    });

    if (!response.body) throw new Error("服务器未返回流");

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();

      for (const evt of events) {
        const line = evt.trim();
        if (!line.startsWith("data:")) continue;

        let data;
        try {
          data = JSON.parse(line.replace(/^data:\s*/, ""));
        } catch {
          continue;
        }

        // progress event
        if (data.type === "progress") {
          const steps = messages.value[stepIndex].steps;
          let step = steps.find((s) => s.text === data.step);
          if (!step) {
            step = { text: data.step, status: data.status };
            steps.push(step);
          } else {
            step.status = data.status;
          }
        }

        // preview result
        else if (data.type === "preview_result") {
          // Mark steps as all done
          const steps = messages.value[stepIndex].steps;
          for (const s of steps) {
            if (s.status === "running") s.status = "success";
          }

          messages.value.push({
            role: "assistant",
            type: "preview",
            query_id: data.query_id,
            sql: data.sql || "",
            explanation: data.explanation || "",
            involved_tables: data.involved_tables || [],
            involved_columns: data.involved_columns || [],
            safety_status: data.safety_status || "pending",
            executable: data.executable || false,
            error_message: data.error_message || null,
          });
        }

        // error
        else if (data.type === "error") {
          messages.value.push({
            role: "assistant",
            type: "error",
            content: data.message || "发生错误",
          });
        }

        await nextTick();
        scrollToBottom();
      }
    }
  } catch (e) {
    messages.value.push({
      role: "assistant",
      type: "error",
      content: e?.message || "请求失败",
    });
  } finally {
    loading.value = false;
    await nextTick();
    scrollToBottom();
  }
}

async function executeQuery(queryId) {
  if (executing.value) return;
  executing.value = true;

  try {
    const response = await fetch(EXECUTE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query_id: queryId }),
    });

    const result = await response.json();

    if (result.error_message) {
      messages.value.push({
        role: "assistant",
        type: "error",
        content: result.error_message,
      });
    } else if (result.rows && result.rows.length > 0) {
      messages.value.push({
        role: "assistant",
        type: "table",
        columns: result.columns || [],
        rows: result.rows,
        row_count: result.row_count || 0,
        executed_sql: result.executed_sql || "",
      });
    } else {
      messages.value.push({
        role: "assistant",
        type: "text",
        content: `查询执行成功，返回 0 行数据。`,
      });
    }
  } catch (e) {
    messages.value.push({
      role: "assistant",
      type: "error",
      content: e?.message || "执行失败",
    });
  } finally {
    executing.value = false;
    await nextTick();
    scrollToBottom();
  }
}

function escapeCSV(val) {
  const str = String(val ?? "");
  if (str.includes(",") || str.includes('"') || str.includes("\n")) {
    return '"' + str.replace(/"/g, '""') + '"';
  }
  return str;
}

function exportCSV(msg) {
  if (!msg.columns || !msg.rows) return;

  const header = msg.columns.map(escapeCSV).join(",");
  const body = msg.rows
    .map((row) => row.map(escapeCSV).join(","))
    .join("\n");
  const csv = header + "\n" + body;

  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `query_result_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
</script>

<style scoped>
/* ===== Layout ===== */
.app-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f6f8;
  color: #1a1a1a;
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

/* ===== Header ===== */
.app-header {
  height: 64px;
  padding: 0 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8e9ec;
  flex-shrink: 0;
}

.header-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #1a1a1a;
  letter-spacing: 0.5px;
}

.header-sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: #8c8c8c;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.header-candidate {
  font-size: 13px;
  color: #555;
  font-weight: 500;
}

.header-tags {
  display: flex;
  gap: 6px;
}

.htag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f0f1f3;
  color: #666;
  border: 1px solid #e2e3e6;
  font-weight: 500;
}

/* ===== Main ===== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ===== Messages ===== */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20% 20px;
}

.messages-bottom-spacer {
  height: 200px;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 60%;
  text-align: center;
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: #e8e9ec;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 700;
  color: #999;
  margin-bottom: 16px;
  font-family: "Consolas", "Fira Code", monospace;
}

.empty-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.empty-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: #999;
}

/* ===== Message Row ===== */
.message-row {
  display: flex;
  margin-bottom: 16px;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-row.user {
  justify-content: flex-end;
}

/* ===== Avatar ===== */
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 10px;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.assistant-avatar {
  background: #1a1a1a;
  color: #fff;
}

.user-avatar {
  background: #409eff;
  color: #fff;
}

/* ===== Bubble ===== */
.bubble {
  max-width: min(780px, 72%);
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  border: 1px solid #e8e9ec;
}

.message-row.user .bubble {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
  box-shadow: 0 1px 4px rgba(64, 158, 255, 0.2);
}

.text-content {
  font-size: 14px;
  line-height: 1.6;
}

/* ===== Steps ===== */
.steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.step-label {
  color: #555;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot.running {
  background: #faad14;
}

.dot.success {
  background: #52c41a;
}

.dot.error {
  background: #ff4d4f;
}

/* ===== Preview Card ===== */
.preview-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.preview-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-label {
  font-size: 13px;
  font-weight: 600;
  color: #333;
}

.status-tag {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.status-tag.safe {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
}

.status-tag.blocked {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffa39e;
}

.status-tag.pending {
  background: #fffbe6;
  color: #d48806;
  border: 1px solid #ffe58f;
}

.sql-block {
  margin: 0;
  padding: 14px 16px;
  background: #1b1b1f;
  color: #e0e0e0;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
  font-family: "Consolas", "Fira Code", "Courier New", monospace;
  border: 1px solid #2d2d30;
}

.preview-meta {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
}

.meta-label {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: #8c8c8c;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding-top: 2px;
}

.meta-value {
  color: #555;
  line-height: 1.5;
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 4px;
  background: #f0f1f3;
  color: #555;
  border: 1px solid #e2e3e6;
}

/* ===== Error Card ===== */
.error-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #fff2f0;
  border: 1px solid #ffa39e;
  border-radius: 8px;
  color: #cf1322;
  font-size: 13px;
  font-weight: 500;
}

.error-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ff4d4f;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

/* ===== Confirm ===== */
.confirm-area {
  margin-top: 4px;
}

.confirm-btn {
  padding: 8px 28px;
  border-radius: 6px;
  border: none;
  background: #52c41a;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.confirm-btn:hover {
  background: #73d13d;
}

.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== Table Card ===== */
.table-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.table-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.table-label {
  font-size: 13px;
  font-weight: 600;
  color: #333;
}

.csv-btn {
  padding: 4px 14px;
  border-radius: 6px;
  border: 1px solid #d9d9d9;
  background: #fff;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  color: #555;
  transition: all 0.2s;
}

.csv-btn:hover {
  border-color: #409eff;
  color: #409eff;
}

.table-scroll {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid #e8e9ec;
  border-radius: 8px;
}

.result-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
}

.result-table th,
.result-table td {
  padding: 8px 14px;
  white-space: nowrap;
  font-size: 13px;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
}

.result-table th {
  background: #fafafa;
  font-weight: 600;
  color: #333;
  position: sticky;
  top: 0;
  z-index: 1;
  border-bottom: 1px solid #e8e9ec;
}

.result-table tbody tr:hover {
  background: #f5f7fa;
}

.result-table td {
  color: #555;
}

/* ===== Input Area ===== */
.input-area {
  flex-shrink: 0;
  padding: 12px 20% 20px;
  background: linear-gradient(to top, #f5f6f8 60%, transparent);
}

.quick-btns {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  justify-content: center;
}

.quick-btn {
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid #d9d9d9;
  background: #fff;
  font-size: 12px;
  color: #555;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.quick-btn:hover {
  border-color: #409eff;
  color: #409eff;
  background: #f0f7ff;
}

.quick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-box {
  display: flex;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #d9d9d9;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  transition: border-color 0.2s;
}

.input-box:focus-within {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.12);
}

.input-box input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  color: #1a1a1a;
}

.input-box input::placeholder {
  color: #bfbfbf;
}

.send-btn {
  padding: 6px 20px;
  border-radius: 6px;
  border: none;
  background: #409eff;
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.send-btn:hover {
  background: #66b1ff;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .app-header {
    height: auto;
    padding: 12px 16px;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .header-right {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }

  .header-tags {
    flex-wrap: wrap;
  }

  .messages {
    padding: 16px 12px 16px;
  }

  .input-area {
    padding: 10px 12px 16px;
  }

  .bubble {
    max-width: 85%;
  }

  .quick-btns {
    gap: 6px;
  }

  .quick-btn {
    font-size: 11px;
    padding: 4px 10px;
  }
}
</style>
