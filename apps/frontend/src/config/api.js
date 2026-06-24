/**
 * API配置文件
 * 包含API基础URL和AI问答功能所需的API参数
 */

// API基础URL配置
// 统一从 Vite 环境变量 VITE_API_BASE_URL 读取（单一来源），默认指向 unified 后端 8030。
// 配置方式：复制 .env.example 为 .env 并按需修改 VITE_API_BASE_URL。
export const apiConfig = {
  // 后端API基础URL
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8030',
}

// AI 问答已改为走后端 Agent 网关（/api/ai/chat），
// 模型调用、API Key 全部收归后端 .env，前端不再存放任何密钥。
export const aiChatConfig = {
  endpoint: `${apiConfig.baseURL}/api/ai/chat`,
}
