// Meal-type picker for the quick-meal buttons (dashboard modal + Meals page).
// Each quick-meal form carries a hidden `.quick-meal-type` field; the page's single
// `.quick-meal-type-select` drives all of them. It starts at guessMealType() (see
// guess-meal-type.js) and the user can override it before tapping a meal.
// Requires guess-meal-type.js to be loaded first.
(function () {
  var select = document.querySelector('.quick-meal-type-select');
  if (!select) return;
  var touched = false;

  function sync() {
    document.querySelectorAll('.quick-meal-type').forEach(function (el) {
      el.value = select.value;
    });
  }

  select.addEventListener('change', function () { touched = true; sync(); });

  // Re-guess whenever the dashboard modal opens (the page may have sat open for hours),
  // unless the user already picked something.
  var modal = select.closest('.modal');
  if (modal) {
    modal.addEventListener('show.bs.modal', function () {
      if (!touched) { select.value = guessMealType(); sync(); }
    });
  }

  select.value = guessMealType();
  sync();
})();
