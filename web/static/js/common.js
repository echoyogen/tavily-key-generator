/**
 * 公共工具函数 - Alpine.js 应用共享
 */

const API_BASE = '';

// ─── Token 管理 ────────────────────────────────────────────────────────────

function getToken() {
  return localStorage.getItem('access_token');
}

function setToken(token) {
  localStorage.setItem('access_token', token);
}

function clearToken() {
  localStorage.removeItem('access_token');
}

function isLoggedIn() {
  return !!getToken();
}

function requireLogin() {
  if (!isLoggedIn()) {
    window.location.href = '/login';
  }
}

// ─── HTTP 工具 ─────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(API_BASE + path, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new Error('未授权，请重新登录');
  }

  return res;
}

async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

// ─── 时间格式化 ─────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function fmtDateShort(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

// ─── 剪贴板 ────────────────────────────────────────────────────────────────

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // 降级方案
    const el = document.createElement('textarea');
    el.value = text;
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);
    return true;
  }
}

// ─── Toast 通知 ─────────────────────────────────────────────────────────────

function showToast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container') || (() => {
    const el = document.createElement('div');
    el.id = 'toast-container';
    el.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2';
    document.body.appendChild(el);
    return el;
  })();

  const colors = {
    info: 'bg-blue-600',
    success: 'bg-green-600',
    error: 'bg-red-600',
    warning: 'bg-yellow-600',
  };

  const toast = document.createElement('div');
  toast.className = `${colors[type] || colors.info} text-white px-4 py-2 rounded shadow-lg text-sm max-w-xs transition-opacity duration-300`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ─── 状态标签 ───────────────────────────────────────────────────────────────

function validLabel(isValid) {
  const map = {
    0: { text: '失效', cls: 'bg-red-100 text-red-700' },
    1: { text: '有效', cls: 'bg-green-100 text-green-700' },
    2: { text: '未验证', cls: 'bg-gray-100 text-gray-600' },
  };
  const info = map[isValid] ?? map[2];
  return `<span class="px-2 py-0.5 rounded text-xs font-medium ${info.cls}">${info.text}</span>`;
}

function taskStatusLabel(status) {
  const map = {
    pending: { text: '等待中', cls: 'bg-yellow-100 text-yellow-700' },
    running: { text: '运行中', cls: 'bg-blue-100 text-blue-700 animate-pulse' },
    done: { text: '已完成', cls: 'bg-green-100 text-green-700' },
    cancelled: { text: '已取消', cls: 'bg-gray-100 text-gray-600' },
    failed: { text: '失败', cls: 'bg-red-100 text-red-700' },
  };
  const info = map[status] ?? { text: status, cls: 'bg-gray-100 text-gray-600' };
  return `<span class="px-2 py-0.5 rounded text-xs font-medium ${info.cls}">${info.text}</span>`;
}

// ─── 服务名称映射 ────────────────────────────────────────────────────────────

const SERVICE_LABELS = {
  tavily: 'Tavily',
  firecrawl: 'Firecrawl',
  exa: 'Exa',
  you: 'You.com',
  serper: 'Serper',
  valyu: 'Valyu',
};

const SERVICE_COLORS = {
  tavily: 'blue',
  firecrawl: 'orange',
  exa: 'purple',
  you: 'green',
  serper: 'red',
  valyu: 'indigo',
};
