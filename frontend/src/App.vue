<template>
  <div class="chat-page">
    <!-- 消息区 -->
    <div ref="messagesEl" class="messages">
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :class="['message-row', msg.role]"
      >
        <div v-if="msg.role === 'assistant'" class="avatar">🤖</div>

        <div class="bubble">
          <!-- 文本 -->
          <div v-if="msg.type === 'text'">
            {{ msg.content }}
          </div>

          <!-- 进度步骤 -->
          <div v-else-if="msg.type === 'steps'" class="steps">
            <div v-for="(step, sIdx) in msg.steps" :key="sIdx" class="step">
              <span class="dot" :class="step.status"></span>
              <span>{{ step.text }}</span>
            </div>
          </div>

          <!-- SQL 预览 -->
          <div v-else-if="msg.type === 'preview'" class="preview-block">
            <div class="preview-header">
              <span class="preview-title">SQL 预览</span>
              <span :class="['safety-badge', msg.safety_status]">
                {{ msg.safety_status === 'safe' ? '✅ 安全' : '🚫 已拦截' }}
              </span>
            </div>

            <pre class="sql-preview"><code>{{ msg.sql }}</code></pre>

            <div v-if="msg.explanation" class="explanation">
              <strong>生成说明：</strong>{{ msg.explanation }}
            </div>

            <div v-if="msg.involved_tables.length" class="meta-info">
              <span><strong>涉及表：</strong>{{ msg.involved_tables.join(', ') }}</span>
            </div>

            <div v-if="msg.involved_columns.length" class="meta-info">
              <span><strong>涉及字段：</strong>{{ msg.involved_columns.join(', ') }}</span>
            </div>

            <div v-if="msg.error_message" class="error-text">
              {{ msg.error_message }}
            </div>

            <div v-if="msg.executable" class="confirm-area">
              <button class="confirm-btn" @click="executeQuery(msg.query_id)" :disabled="executing">
                {{ executing ? '执行中...' : '确认执行' }}
              </button>
            </div>
          </div>

          <!-- 表格结果 -->
          <div v-else-if="msg.type === 'table'" class="table-block">
            <div class="table-header">
              <span>查询结果（{{ msg.row_count }} 行）</span>
              <button class="csv-btn" @click="exportCSV(msg)">📥 导出 CSV</button>
            </div>
            <div class="table-wrap">
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

          <!-- 错误 -->
          <div v-else-if="msg.type === 'error'" class="error-text">
            {{ msg.content }}
          </div>
        </div>

        <div v-if="msg.role === 'user'" class="avatar">🧑</div>
      </div>
      <div class="messages-bottom-spacer"></div>
    </div>

    <!-- 悬浮输入框 -->
    <div class="input-wrapper">
      <div class="input-box">
        <input
          v-model="question"
          @keyup.enter="sendQuestion"
          placeholder="请输入你的问题，例如：统计各地区的销售总额"
        />
        <button @click="sendQuestion" :disabled="loading">
          {{ loading ? '生成中...' : '发送' }}
        </button>
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
/* 覆盖 Vite 默认居中 */
:global(html),
:global(body) {
  height: 100%;
  margin: 0;
}

:global(body) {
  display: block !important;
  place-items: unset !important;
}

:global(#app) {
  height: 100%;
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
}

/* 页面 */
.chat-page {
  height: 100%;
  overflow: hidden;
  background: #f0f2f5;
  color: #1a1a1a;
}

/* 消息区 */
.messages {
  height: 100%;
  overflow-y: auto;
  padding: 20px 20% 160px;
}

.message-row {
  display: flex;
  margin-bottom: 14px;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #e0e0e0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 10px;
  font-size: 16px;
}

.bubble {
  max-width: min(820px, 72%);
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.message-row.user .bubble {
  background: #409eff;
  color: #fff;
}

/* 步骤 */
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

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot.running {
  background: #f1c40f;
}

.dot.success {
  background: #2ecc71;
}

.dot.error {
  background: #e74c3c;
}

/* SQL 预览 */
.preview-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-title {
  font-weight: 600;
  font-size: 15px;
}

.safety-badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.safety-badge.safe {
  background: #d4edda;
  color: #155724;
}

.safety-badge.blocked {
  background: #f8d7da;
  color: #721c24;
}

.sql-preview {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px 14px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}

.sql-preview code {
  font-family: "Fira Code", "Consolas", monospace;
}

.explanation {
  font-size: 13px;
  color: #555;
  line-height: 1.5;
}

.meta-info {
  font-size: 12px;
  color: #777;
}

/* 确认按钮 */
.confirm-area {
  margin-top: 8px;
}

.confirm-btn {
  padding: 8px 24px;
  border-radius: 8px;
  border: none;
  background: linear-gradient(135deg, #67c23a, #85ce61);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.confirm-btn:hover {
  opacity: 0.9;
}

.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 表格 */
.table-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #555;
}

.csv-btn {
  padding: 4px 12px;
  border-radius: 6px;
  border: 1px solid #ddd;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s;
}

.csv-btn:hover {
  background: #f5f5f5;
}

.table-wrap {
  max-width: 100%;
  overflow-x: auto;
}

.result-table {
  width: max-content;
  min-width: 100%;
  table-layout: auto;
  border-collapse: collapse;
}

.result-table th,
.result-table td {
  border: 1px solid #ddd;
  padding: 6px 12px;
  white-space: nowrap;
  font-size: 13px;
  text-align: left;
}

.result-table th {
  background: #fafafa;
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 1;
}

/* 错误 */
.error-text {
  color: #e74c3c;
  font-weight: 600;
}

/* 悬浮输入框 */
.input-wrapper {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 24px;
  display: flex;
  justify-content: center;
  padding: 0 16px;
  pointer-events: none;
}

.input-box {
  pointer-events: auto;
  width: 100%;
  max-width: 720px;
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
}

.input-box input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
}

.input-box button {
  padding: 8px 18px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #409eff, #66b1ff);
  color: #fff;
  cursor: pointer;
}

.input-box button:disabled {
  opacity: 0.5;
}

.messages-bottom-spacer {
  height: 200px;
}
</style>
