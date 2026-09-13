// Guess a meal type from local device time — always just a default, fully overridable.
// Shared by the dashboard's quick-meal modal, /meals/new, and the Meals page's
// quick-log buttons, so the six time boundaries only need to be correct in one place.
function guessMealType() {
  var minutes = new Date().getHours() * 60 + new Date().getMinutes();
  var ranges = [
    [6 * 60, 10 * 60 + 30, 'breakfast'],
    [10 * 60 + 30, 12 * 60, 'snack'],
    [12 * 60, 14 * 60, 'lunch'],
    [14 * 60, 17 * 60, 'snack'],
    [17 * 60, 20 * 60, 'dinner'],
  ];
  for (var i = 0; i < ranges.length; i++) {
    if (minutes >= ranges[i][0] && minutes < ranges[i][1]) return ranges[i][2];
  }
  return 'snack'; // 8pm-6am
}
