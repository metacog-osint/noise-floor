/* Time button (The Intelligence Company shared settings, tic-time.js). A change reloads the page so every
   chart and table redraws in the newly chosen zone. */
(function () {
  var holder = document.getElementById("time-settings");
  if (!window.TicTime || !holder) return;
  window.TicTime.mountSettings(holder);
  window.TicTime.onChange(function () { location.reload(); });
})();
