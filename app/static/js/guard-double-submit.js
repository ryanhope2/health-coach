// Prevents a plain (non-AJAX) <form> from being submitted a second time before
// the resulting page navigation completes. Real bug hit in prod: no visual
// feedback after tapping Save made a normal network delay look like nothing
// happened, so a second tap fired a second POST — for routes that create a
// new row (exercise, measurements, goals, quick meals) that's a literal
// duplicate entry, not just a wasted request.
//
// Usage: add class="guard-double-submit" to any <form>, including ones
// rendered in a loop (e.g. one per saved meal) — querySelectorAll picks up
// all of them.
//
// Disabling the button is deferred a tick (setTimeout 0), not done
// synchronously in the submit handler — doing it synchronously can cancel
// the very submission it's reacting to (hit this exact bug once already,
// on the coach chat's pre-fetch send button).
(function () {
  function guard(form) {
    var submitBtn = form.querySelector('button[type="submit"], button:not([type])');
    form.addEventListener('submit', function (e) {
      if (form.dataset.submitting === 'true') {
        e.preventDefault();
        return;
      }
      form.dataset.submitting = 'true';
      setTimeout(function () {
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Saving…';
        }
      }, 0);
    });
  }

  document.querySelectorAll('form.guard-double-submit').forEach(guard);
})();
