// Blood pressure log form: a typed or dictated "128 over 82 pulse 64" in the systolic field
// is split into systolic/diastolic/pulse on blur, so you see exactly what will be saved
// before hitting Save. Same rules as bp_trends.parse_bp_text() (which also runs server-side
// as a fallback). The time field is refreshed to "now" on focus-in of the form if untouched,
// so a page left open since morning doesn't log an evening reading at the morning's time.
(function () {
  function parse(text) {
    var nums = (text.match(/\d{2,3}/g) || []).map(Number);
    if (nums.length < 2) return null;
    var s = nums[0], d = nums[1], p = nums.length > 2 ? nums[2] : null;
    if (!(s >= 70 && s <= 260 && d >= 40 && d <= 150 && s > d)) return null;
    if (p !== null && !(p >= 30 && p <= 220)) return null;
    return {s: s, d: d, p: p};
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  document.querySelectorAll('.bp-log-form').forEach(function (form) {
    var sys = form.querySelector('.bp-systolic');
    var dia = form.querySelector('.bp-diastolic');
    var pulse = form.querySelector('.bp-pulse');
    var time = form.querySelector('.bp-time');
    var timeTouched = false;

    sys.addEventListener('change', function () {
      if (!/\D/.test(sys.value.trim())) return;  // just a number — nothing to split
      var r = parse(sys.value);
      if (!r) return;
      sys.value = r.s;
      dia.value = r.d;
      if (r.p !== null) pulse.value = r.p;
    });

    time.addEventListener('change', function () { timeTouched = true; });
    form.addEventListener('focusin', function () {
      if (timeTouched) return;
      var now = new Date();
      time.value = pad(now.getHours()) + ':' + pad(now.getMinutes());
    });
  });
})();
