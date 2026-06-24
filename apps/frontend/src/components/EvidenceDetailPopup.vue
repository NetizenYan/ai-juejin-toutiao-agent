<template>
  <van-popup
    v-model:show="visible"
    position="bottom"
    round
    :style="{ maxHeight: '70vh' }"
    closeable
    close-icon-position="top-right"
  >
    <div class="evidence-detail">
      <div v-if="loading" class="evidence-status">
        <van-loading size="24px">正在查询证据详情...</van-loading>
      </div>

      <div v-else-if="error" class="evidence-status">
        <van-icon name="warning-o" size="40" color="#969799" />
        <p class="evidence-status-text">{{ error }}</p>
      </div>

      <div v-else-if="detail && detail.found" class="evidence-found">
        <h3 class="evidence-title">{{ detail.title || '无标题' }}</h3>
        <div class="evidence-meta">
          <van-icon name="newspaper-o" size="14" />
          <span>{{ detail.source || '未知来源' }}</span>
          <template v-if="detail.publish_time">
            <van-icon name="clock-o" size="14" />
            <span>{{ detail.publish_time }}</span>
          </template>
        </div>
        <div class="evidence-id-row">
          <span class="evidence-id-label">证据ID</span>
          <span class="evidence-id-value">{{ detail.evidence_id }}</span>
        </div>
        <div v-if="detail.snippet" class="evidence-section">
          <div class="evidence-section-title">摘要</div>
          <p class="evidence-section-content">{{ detail.snippet }}</p>
        </div>
        <div v-if="detail.content_excerpt" class="evidence-section">
          <div class="evidence-section-title">正文片段</div>
          <p class="evidence-section-content">{{ detail.content_excerpt }}</p>
        </div>
      </div>

      <div v-else class="evidence-status">
        <van-icon name="info-o" size="40" color="#969799" />
        <p class="evidence-status-text">未找到该证据详情</p>
      </div>
    </div>
  </van-popup>
</template>

<script setup>
import { ref, watch } from 'vue';
import { apiConfig } from '../config/api';
import { useUserStore } from '../store/user';

const props = defineProps({
  show: Boolean,
  evidenceId: String,
});

const emit = defineEmits(['update:show']);

const visible = ref(false);
const loading = ref(false);
const error = ref('');
const detail = ref(null);

const userStore = useUserStore();

watch(() => props.show, (val) => {
  visible.value = val;
  if (val && props.evidenceId) {
    fetchDetail(props.evidenceId);
  }
});

watch(visible, (val) => {
  emit('update:show', val);
});

const fetchDetail = async (evidenceId) => {
  loading.value = true;
  error.value = '';
  detail.value = null;

  try {
    if (!userStore.token) {
      error.value = '请先登录后查看证据详情';
      return;
    }

    const url = `${apiConfig.baseURL}/api/ai/evidence-detail?evidence_id=${encodeURIComponent(evidenceId)}`;
    const response = await fetch(url, {
      headers: { 'Authorization': userStore.token },
    });

    if (response.status === 401) {
      error.value = '登录已过期，请重新登录';
      return;
    }

    if (!response.ok) {
      error.value = '网络请求失败，请稍后重试';
      return;
    }

    const result = await response.json();

    if (result.code !== 200) {
      error.value = result.message || '获取证据详情失败';
      return;
    }

    detail.value = result.data;
  } catch (e) {
    console.error('Failed to fetch evidence detail:', e);
    error.value = '网络错误，请检查连接后重试';
  } finally {
    loading.value = false;
  }
};
</script>

<style scoped>
.evidence-detail {
  padding: 20px 16px;
  min-height: 200px;
}

.evidence-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  gap: 12px;
}

.evidence-status-text {
  color: #969799;
  font-size: 14px;
  margin: 0;
}

.evidence-found {
  padding-bottom: 20px;
}

.evidence-title {
  font-size: 17px;
  font-weight: 600;
  color: #323233;
  margin: 0 0 12px;
  line-height: 1.4;
}

.evidence-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #969799;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.evidence-meta .van-icon {
  margin-left: 8px;
}

.evidence-meta .van-icon:first-child {
  margin-left: 0;
}

.evidence-id-row {
  font-size: 11px;
  color: #c8c9cc;
  margin-bottom: 16px;
  display: flex;
  gap: 6px;
}

.evidence-id-label {
  flex-shrink: 0;
}

.evidence-id-value {
  word-break: break-all;
}

.evidence-section {
  margin-top: 14px;
}

.evidence-section-title {
  font-size: 14px;
  font-weight: 500;
  color: #323233;
  margin-bottom: 6px;
}

.evidence-section-content {
  font-size: 14px;
  color: #646566;
  line-height: 1.6;
  margin: 0;
  white-space: pre-wrap;
}
</style>
