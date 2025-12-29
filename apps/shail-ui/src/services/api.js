import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * API service for Shail backend endpoints
 */

/**
 * Submit a new task
 * @param {string} text - User's request text
 * @param {string} mode - Optional mode (auto|code|bio|robo|plasma|research)
 * @returns {Promise<{task_id: string, status: string, message: string}>}
 */
export async function submitTask(text, mode = 'auto') {
  const response = await api.post('/tasks', {
    text,
    mode,
  });
  return response.data;
}

/**
 * Get a single task by ID
 * @param {string} taskId - Task ID
 * @returns {Promise<object>} TaskResult object
 */
export async function getTask(taskId) {
  const response = await api.get(`/tasks/${taskId}`);
  return response.data;
}

/**
 * Get all tasks
 * @param {number} limit - Maximum number of tasks (default: 100)
 * @param {number} offset - Pagination offset (default: 0)
 * @returns {Promise<Array>} Array of task objects
 */
export async function getAllTasks(limit = 100, offset = 0) {
  const response = await api.get('/tasks/all', {
    params: { limit, offset },
  });
  return response.data;
}

/**
 * Approve a task permission request
 * @param {string} taskId - Task ID
 * @returns {Promise<{status: string, message: string, task_id: string}>}
 */
export async function approveTask(taskId) {
  const response = await api.post(`/tasks/${taskId}/approve`);
  return response.data;
}

/**
 * Deny a task permission request
 * @param {string} taskId - Task ID
 * @returns {Promise<{status: string, message: string, task_id: string}>}
 */
export async function denyTask(taskId) {
  const response = await api.post(`/tasks/${taskId}/deny`);
  return response.data;
}

/**
 * Check health status
 * @returns {Promise<{status: string, service: string}>}
 */
export async function checkHealth() {
  const response = await api.get('/health');
  return response.data;
}

export default api;

