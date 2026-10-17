// Blood pressure log form: a typed or dictated "128 over 82 pulse 64" in the systolic field
// is split into systolic/diastolic/pulse on blur, so you see exactly what will be saved
// before hitting Save. Same rules as bp_trends.parse_bp_text() (which also runs server-side
// as a fallback). The time field is refreshed to "now" on focus-in of the form if untouched,
// so a page left open since morning doesn't log an evening reading at the morning's time.
// "Read from photo" shrinks the picture in the browser (phone photos are several MB; the digits
// read fine at 1600px), sends it to /bp/read-photo, and fills the fields the same way — nothing
// is saved until Save.
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

  var MAX_SIDE = 1600;
  function shrink(file) {
    return createImageBitmap(file).then(function (img) {
      var scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
      var canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      return new Promise(function (resolve) { canvas.toBlob(resolve, 'image/jpeg', 0.85); });
    }).catch(function () { return file; });  // can't decode here — let the server try the original
  }

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

    var photo = form.querySelector('.bp-photo');
    var photoBtn = form.querySelector('.bp-photo-btn');
    var status = form.querySelector('.bp-photo-status');
    if (photo) photo.addEventListener('change', function () {
      var file = photo.files[0];
      if (!file) return;
      photoBtn.classList.add('disabled');
      status.className = 'small text-muted bp-photo-status';
      status.textContent = 'Reading…';
      shrink(file).then(function (blob) {
        var body = new FormData();
        body.append('photo', blob, 'bp.jpg');
        return fetch(photo.dataset.url, {method: 'POST', body: body, headers: {'X-Requested-With': 'XMLHttpRequest'}});
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.error) throw new Error(data.error);
        sys.value = data.systolic;
        dia.value = data.diastolic;
        pulse.value = data.pulse === null ? '' : data.pulse;
        status.className = 'small text-success bp-photo-status';
        status.textContent = 'Read ' + data.systolic + '/' + data.diastolic +
          (data.pulse ? ' ♥' + data.pulse : '') + ' — check, then Save.';
      }).catch(function (err) {
        status.className = 'small text-danger bp-photo-status';
        status.textContent = err.message || "Couldn't read the photo.";
      }).finally(function () {
        photoBtn.classList.remove('disabled');
        photo.value = '';
      });
    });

    time.addEventListener('change', function () { timeTouched = true; });
    form.addEventListener('focusin', function () {
      if (timeTouched) return;
      var now = new Date();
      time.value = pad(now.getHours()) + ':' + pad(now.getMinutes());
    });
  });
})();
