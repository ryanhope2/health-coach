// Drives the coach chat widget (app/templates/coach/_widget.html) — used both
// by the full /coach/ page and the dashboard's embedded compact version, since
// both render the same element IDs. Submits via fetch instead of a plain form
// post so the user's own message and a "Thinking..." placeholder show up
// immediately, instead of the whole exchange only appearing once Claude replies.
(function () {
  var el = document.getElementById('chatMessages');
  var form = document.getElementById('chatForm');
  if (!el || !form) return;

  el.scrollTop = el.scrollHeight;

  var sendBtn = document.getElementById('chatSendBtn');
  var input = document.getElementById('chatInput');
  var submitting = false;

  function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
      return marked.parse(text, { breaks: true });
    }
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function appendBubble(role, text) {
    var emptyState = document.getElementById('chatEmptyState');
    if (emptyState) emptyState.remove();
    var div = document.createElement('div');
    div.className = 'chat-bubble ' + role;
    if (text) div.innerHTML = renderMarkdown(text);
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
    return div;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || submitting) return;

    submitting = true;
    appendBubble('user', text);
    input.value = '';
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';

    var thinking = appendBubble('assistant thinking', 'Thinking…');

    fetch(form.action, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: 'message=' + encodeURIComponent(text),
    })
      .then(function (res) {
        if (!res.ok) throw new Error('request failed (' + res.status + ')');
        return res.json();
      })
      .then(function (data) {
        thinking.innerHTML = renderMarkdown(data.reply);
        thinking.classList.remove('thinking');
      })
      .catch(function () {
        thinking.textContent = "Sorry, that didn't go through. Try sending it again.";
        thinking.classList.remove('thinking');
        thinking.classList.add('error');
      })
      .finally(function () {
        submitting = false;
        input.disabled = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="bi bi-send"></i>';
        input.focus();
        el.scrollTop = el.scrollHeight;
      });
  });
})();
