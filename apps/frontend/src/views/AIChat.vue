<template>
  <div class="ai-chat-container">
    <van-nav-bar title="AI问答" fixed />

    <div class="chat-content">
      <div class="messages-container" ref="messagesContainer" @click="handleMessageClick">
        <div
          v-for="(message, index) in messages"
          :key="index"
          :class="['message', message.role === 'user' ? 'user-message' : 'ai-message']"
        >
          <div class="message-content">
            <div v-if="message.role === 'assistant' && message.content === ''" class="typing-indicator">
              <span></span>
              <span></span>
              <span></span>
            </div>
            <div v-else v-html="formatMessage(message.content)"></div>
          </div>
        </div>
      </div>

      <div class="input-container">
        <van-field
          v-model="userInput"
          rows="1"
          autosize
          type="textarea"
          placeholder="请输入问题..."
          class="chat-input"
          @keypress.enter.prevent="sendMessage"
        />
        <van-button
          type="primary"
          class="send-button"
          :disabled="isLoading || !userInput.trim()"
          @click="sendMessage"
        >
          发送
        </van-button>
      </div>
    </div>

    <evidence-detail-popup
      v-model:show="showEvidencePopup"
      :evidence-id="selectedEvidenceId"
    />

    <tab-bar />
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue';
import TabBar from '../components/TabBar.vue';
import EvidenceDetailPopup from '../components/EvidenceDetailPopup.vue';
import { showToast } from 'vant';
import * as marked from 'marked';
import DOMPurify from 'dompurify';
import { apiConfig } from '../config/api';
import { useUserStore } from '../store/user';

// evidence_id 仅含 [A-Za-z0-9:_-]，不含可破坏 HTML 的字符
const CITATION_REGEX = /\[news:[A-Za-z0-9:_-]+\]/g;
// 代码块/内联代码/链接内部不渲染 citation：既避免误渲染，也避免嵌套可点击元素
const CITATION_SKIP_TAGS = new Set(['CODE', 'PRE', 'A']);

// 聊天消息
const messages = ref([
  { role: 'assistant', content: '你好！我是AI助手，有什么可以帮助你的吗？' }
]);
const userInput = ref('');
const messagesContainer = ref(null);
const isLoading = ref(false);

// Evidence detail popup state
const showEvidencePopup = ref(false);
const selectedEvidenceId = ref('');

// 后端 Agent 网关：携带登录 Token，维护会话 ID 以支持多轮
const userStore = useUserStore();
const sessionId = ref(null);

// 仅在「已净化 DOM」的文本节点上包裹 citation，绝不碰属性值。
// 这样可避免把 span 注入到 href/title 等属性里破坏 HTML，也不会引入 XSS。
const decorateCitations = (root) => {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const targets = [];
  let node;
  while ((node = walker.nextNode())) {
    if (!node.nodeValue || node.nodeValue.indexOf('[news:') === -1) continue;
    let inSkip = false;
    for (let p = node.parentElement; p && p !== root; p = p.parentElement) {
      if (CITATION_SKIP_TAGS.has(p.tagName)) { inSkip = true; break; }
    }
    if (!inSkip) targets.push(node);
  }
  for (const textNode of targets) {
    const text = textNode.nodeValue;
    const frag = document.createDocumentFragment();
    let lastIndex = 0;
    let m;
    CITATION_REGEX.lastIndex = 0;
    while ((m = CITATION_REGEX.exec(text)) !== null) {
      if (m.index > lastIndex) {
        frag.appendChild(document.createTextNode(text.slice(lastIndex, m.index)));
      }
      const span = document.createElement('span');
      span.className = 'evidence-citation';
      span.setAttribute('data-evidence-id', m[0].slice(1, -1));
      span.textContent = m[0];
      frag.appendChild(span);
      lastIndex = m.index + m[0].length;
    }
    if (lastIndex < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
    textNode.parentNode.replaceChild(frag, textNode);
  }
};

// 格式化消息内容（Markdown 净化 + citation 高亮）
const formatMessage = (content) => {
  if (!content) return '';
  // 1) marked 解析 → 2) DOMPurify 净化 → 3) 仅在文本节点上包裹 citation
  const clean = DOMPurify.sanitize(marked.parse(content));
  const container = document.createElement('div');
  container.innerHTML = clean;
  decorateCitations(container);
  return container.innerHTML;
};

// Event delegation: handle citation clicks
const handleMessageClick = (event) => {
  const citation = event.target.closest('.evidence-citation');
  if (!citation) return;
  const evidenceId = citation.dataset.evidenceId;
  if (!evidenceId) return;
  selectedEvidenceId.value = evidenceId;
  showEvidencePopup.value = true;
};

// 发送消息
const sendMessage = async () => {
  if (!userInput.value.trim() || isLoading.value) return;

  // 需登录后携带 Token 使用
  if (!userStore.token) {
    showToast('请先登录后再使用 AI 问答');
    return;
  }

  // 添加用户消息
  const userMessage = userInput.value.trim();
  messages.value.push({ role: 'user', content: userMessage });
  userInput.value = '';

  // 添加AI消息占位
  messages.value.push({ role: 'assistant', content: '' });

  // 滚动到底部
  await nextTick();
  scrollToBottom();

  // 发送请求
  isLoading.value = true;
  try {
    await fetchAIResponse(userMessage);
  } catch (error) {
    console.error('Error fetching AI response:', error);
    // 更新最后一条消息为错误信息
    messages.value[messages.value.length - 1].content = `发生错误: ${error.message || '请检查网络连接和API设置'}`;
  } finally {
    isLoading.value = false;
    await nextTick();
    scrollToBottom();
  }
};

// 获取AI响应（使用SSE）
const fetchAIResponse = async (userMessage) => {
  try {
    // 调用后端 Agent 网关（鉴权 + 维护会话）
    const response = await fetch(`${apiConfig.baseURL}/api/ai/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': userStore.token
      },
      body: JSON.stringify({
        message: userMessage,
        sessionId: sessionId.value
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || error.message || `HTTP error! status: ${response.status}`);
    }

    // 处理后端 SSE 流：{delta} / {event:'done',sessionId} / [DONE] / {event:'error',detail}
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let aiResponse = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') continue;

        try {
          const json = JSON.parse(data);
          if (json.delta) {
            aiResponse += json.delta;
            messages.value[messages.value.length - 1].content = aiResponse;
            await nextTick();
            scrollToBottom();
          } else if (json.event === 'done') {
            if (json.sessionId) sessionId.value = json.sessionId;
          } else if (json.event === 'error') {
            messages.value[messages.value.length - 1].content = '生成失败：' + (json.detail || '请稍后再试');
          }
        } catch (e) {
          console.error('Error parsing SSE data:', e);
        }
      }
    }

    if (!aiResponse) {
      messages.value[messages.value.length - 1].content = '抱歉，我无法生成回复。请稍后再试。';
    }
  } catch (error) {
    console.error('Fetch error:', error);
    throw error;
  }
};

// 滚动到底部
const scrollToBottom = () => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

// 监听消息变化，自动滚动
watch(messages, () => {
  nextTick(scrollToBottom);
}, { deep: true });

// 组件挂载时滚动到底部
onMounted(() => {
  scrollToBottom();
});
</script>

<style scoped>
.ai-chat-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding-top: 46px;
  padding-bottom: 50px;
  box-sizing: border-box;
}

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.message {
  margin-bottom: 10px;
  max-width: 80%;
}

.user-message {
  margin-left: auto;
}

.ai-message {
  margin-right: auto;
}

.message-content {
  padding: 10px;
  border-radius: 10px;
  word-break: break-word;
}

.user-message .message-content {
  background-color: #007aff;
  color: white;
}

.ai-message .message-content {
  background-color: #f2f2f2;
  color: #333;
}

.input-container {
  display: flex;
  padding: 10px;
  border-top: 1px solid #eee;
  background-color: #fff;
}

.chat-input {
  flex: 1;
  margin-right: 10px;
}

.send-button {
  align-self: flex-end;
}

/* Markdown 样式 */
.message-content pre {
  background-color: #f8f8f8;
  padding: 10px;
  border-radius: 5px;
  overflow-x: auto;
}

.message-content code {
  background-color: rgba(0, 0, 0, 0.05);
  padding: 2px 4px;
  border-radius: 3px;
}

.message-content img {
  max-width: 100%;
}

/* Citation 样式 */
:deep(.evidence-citation) {
  display: inline;
  color: #1989fa;
  background-color: rgba(25, 137, 250, 0.08);
  border-radius: 3px;
  padding: 1px 4px;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
  transition: background-color 0.2s;
  font-size: 0.9em;
}

:deep(.evidence-citation:hover) {
  background-color: rgba(25, 137, 250, 0.18);
}

:deep(.evidence-citation:active) {
  background-color: rgba(25, 137, 250, 0.28);
}

/* 打字指示器 */
.typing-indicator {
  display: flex;
  padding: 5px;
}

.typing-indicator span {
  height: 8px;
  width: 8px;
  background-color: #999;
  border-radius: 50%;
  margin: 0 2px;
  display: inline-block;
  animation: bounce 1.5s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 60%, 100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-5px);
  }
}

/* Markdown样式 */
:deep(pre) {
  background-color: #f0f0f0;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
}

:deep(code) {
  font-family: monospace;
  background-color: #f0f0f0;
  padding: 2px 4px;
  border-radius: 4px;
}

:deep(p) {
  margin: 8px 0;
}

:deep(ul), :deep(ol) {
  padding-left: 20px;
}

:deep(a) {
  color: #1989fa;
  text-decoration: none;
}
</style>
