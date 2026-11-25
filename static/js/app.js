(() => {
  const $ = (id) => document.getElementById(id);

  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  const state = {
    mode: 'roleplay',
    conversations: {
      roleplay: null,
      normal: null
    },
    busy: false,
    retry: null
  };

  const messagesEl = $('messages');
  const input = $('messageInput');

  // نشانگر فکر کردن در شروع مخفی باشد
  $('thinking').hidden = true;

  async function api(url, options = {}) {
    const headers = { ...(options.headers || {}) };

    if (options.method && options.method !== 'GET') {
      headers['X-CSRF-Token'] = csrf;
    }

    if (options.body) {
      headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
      credentials: 'same-origin',
      ...options,
      headers
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const err = new Error(data.error || `HTTP ${response.status}`);
      err.status = response.status;
      err.retryable = data.retryable;
      throw err;
    }

    return data;
  }

  function showError(message, retryable = false) {
    $('errorText').textContent = message;
    $('errorBanner').hidden = false;
    $('retryBtn').hidden = !retryable || !state.retry;
  }

  function hideError() {
    $('errorBanner').hidden = true;
  }

  // فقط هنگام ارسال واقعی درخواست، حالت فکر کردن نمایش داده شود
  function setBusy(value) {
    state.busy = value;

    $('sendBtn').disabled = value;
    input.disabled = value;

    $('thinking').hidden = !value;

    if (!value) {
      input.focus();
    }
  }

  function scrollBottom() {
    $('chatArea').scrollTop = $('chatArea').scrollHeight;
  }

  function addMessage(role, content) {
    $('welcome').hidden = true;

    const article = document.createElement('article');
    article.className = `message ${role}`;

    const label = document.createElement('div');
    label.className = 'message-label';
    label.textContent = role === 'user'
      ? 'YOU //'
      : 'COLOSSUS //';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = content;

    article.append(label, bubble);

    messagesEl.appendChild(article);

    scrollBottom();

    return article;
  }

  function setMode(mode) {
    if (!['roleplay', 'normal'].includes(mode) || state.busy) {
      return;
    }

    state.mode = mode;

    document.querySelectorAll('.mode-btn').forEach(btn => {
      btn.classList.toggle(
        'active',
        btn.dataset.mode === mode
      );
    });

    $('welcome').hidden = false;
    messagesEl.replaceChildren();

    hideError();

    loadCurrentConversation();
  }

  async function loadCurrentConversation() {
    const id = state.conversations[state.mode];

    if (!id) {
      $('welcome').hidden = false;
      return;
    }

    try {
      const data = await api(
        `/api/conversations/${encodeURIComponent(id)}`
      );

      messagesEl.replaceChildren();

      $('welcome').hidden = data.messages.length > 0;

      data.messages.forEach(m => {
        addMessage(m.role, m.content);
      });

      await refreshArchive();

    } catch (err) {
      state.conversations[state.mode] = null;
      showError(err.message);
    }
  }

  async function refreshArchive() {
    try {
      const data = await api('/api/conversations');

      const list = $('conversationList');

      list.replaceChildren();

      if (!data.conversations.length) {
        const empty = document.createElement('div');

        empty.className = 'empty-archive';
        empty.textContent = 'هنوز ردپایی ثبت نشده.';

        list.append(empty);
        return;
      }

      data.conversations.forEach(conv => {
        const button = document.createElement('button');

        button.className = 'archive-item';

        const title = document.createElement('span');
        title.textContent = conv.title;

        const mode = document.createElement('small');
        mode.textContent = conv.mode === 'roleplay'
          ? 'RP'
          : 'AI';

        button.append(title, mode);

        button.classList.toggle(
          'active',
          state.conversations[state.mode] === conv.id
        );

        button.addEventListener('click', async () => {
          if (state.busy) return;

          state.mode = conv.mode;
          state.conversations[conv.mode] = conv.id;

          document.querySelectorAll('.mode-btn').forEach(b => {
            b.classList.toggle(
              'active',
              b.dataset.mode === conv.mode
            );
          });

          messagesEl.replaceChildren();

          $('welcome').hidden = false;

          hideError();

          await loadCurrentConversation();

          if (innerWidth <= 760) {
            $('sidebar').classList.remove('open');
          }
        });

        list.append(button);
      });

    } catch (_) {
      // خطای آرشیو نباید مانع چت شود
    }
  }

  async function sendMessage(text, isRetry = false) {
    if (state.busy || !text.trim()) return;

    hideError();

    const message = text.trim();

    if (!isRetry) {
      addMessage('user', message);
    }

    // شروع نمایش فکر کردن دقیقاً هنگام ارسال درخواست
    setBusy(true);

    state.retry = { message };

    try {
      const data = await api('/api/chat', {
        method: 'POST',

        body: JSON.stringify({
          message,
          mode: state.mode,
          conversation_id: state.conversations[state.mode]
        })
      });

      state.conversations[state.mode] = data.conversation_id;

      addMessage('assistant', data.reply);

      state.retry = null;

      await refreshArchive();

    } catch (err) {
      showError(err.message, Boolean(err.retryable));

    } finally {
      // بعد از دریافت پاسخ یا خطا، فکر کردن متوقف شود
      setBusy(false);
    }
  }

  $('chatForm').addEventListener('submit', event => {
    event.preventDefault();

    if (state.busy) return;

    const value = input.value;

    if (!value.trim()) return;

    input.value = '';
    input.style.height = 'auto';

    sendMessage(value);
  });

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      $('chatForm').requestSubmit();
    }
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';

    input.style.height =
      `${Math.min(input.scrollHeight, 150)}px`;
  });

  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      setMode(btn.dataset.mode);
    });
  });

  $('newChatBtn').addEventListener('click', () => {
    if (state.busy) return;

    state.conversations[state.mode] = null;

    messagesEl.replaceChildren();

    $('welcome').hidden = false;

    hideError();

    refreshArchive();

    if (innerWidth <= 760) {
      $('sidebar').classList.remove('open');
    }

    input.focus();
  });

  $('clearBtn').addEventListener('click', async () => {
    if (state.busy) return;

    const id = state.conversations[state.mode];

    if (!id) {
      messagesEl.replaceChildren();
      $('welcome').hidden = false;
      return;
    }

    try {
      await api(
        `/api/conversations/${encodeURIComponent(id)}`,
        { method: 'DELETE' }
      );

      state.conversations[state.mode] = null;

      messagesEl.replaceChildren();

      $('welcome').hidden = false;

      hideError();

      await refreshArchive();

    } catch (err) {
      showError(err.message);
    }
  });

  $('retryBtn').addEventListener('click', () => {
    if (state.retry && !state.busy) {
      sendMessage(state.retry.message, true);
    }
  });

  $('mobileMenu').addEventListener('click', () => {
    $('sidebar').classList.toggle('open');
  });

  async function checkStatus() {
    try {
      const data = await api('/api/status');

      $('statusDot').classList.toggle(
        'online',
        data.connected
      );

      $('statusDot').classList.toggle(
        'offline',
        !data.connected
      );

      $('statusText').textContent = data.connected
        ? 'اتصال API آماده‌ست'
        : 'کلید API تنظیم نشده';

      $('modelName').textContent = data.model.toUpperCase();

    } catch (_) {
      $('statusText').textContent = 'وضعیت اتصال نامشخص';
    }
  }

  // راه‌اندازی اولیه برنامه
  (async () => {
    await checkStatus();
    await refreshArchive();
    await loadCurrentConversation();
  })();

})();
