/* global WANNA_DRAW_HTML */

var Hashing = (function() {

  var DEFAULT_LAT = 0, DEFAULT_LNG = 0;

  function setHash(zoom, lat, lng) {
    var precision = Math.max(0, Math.ceil(Math.log(zoom) / Math.LN2));
    location.hash = '#' + zoom.toFixed(2) + '/' +
                    lat.toFixed(precision) + '/' + lng.toFixed(precision);
  }

  return {
     setup: function(map, default_zoom) {

       var hash = location.hash.substring(1);
       var args = hash.split("/").map(Number);
       if (args.length < 3 || args.some(isNaN)) {
         args = null;
       }
       if (args) {
         map.setView([args[1], args[2]], args[0]);
       } else {
         // Default!
         map.setView([DEFAULT_LAT, DEFAULT_LNG], default_zoom);
         setHash(default_zoom, DEFAULT_LAT, DEFAULT_LNG);
       }

       // set up the event
       map.on('move', function(event) {
         var c = event.target.getCenter();
         setHash(event.target.getZoom(), c.lat, c.lng);
       });
     }
  };
})();


$(function() {
  var $body = $('body');
  var image = $body.data('image');
  var range_min = $body.data('range-min');
  var range_max = $body.data('range-max');
  var default_zoom = $body.data('default-zoom');
  var extension = $body.data('extension');
  var prefix = $body.data('prefix');

  var map = L.map('map');

  L.tileLayer(prefix + "/tiles/" + image + "/256/{z}/{x},{y}." + extension, {
    //attribution: 'Map data &copy; <a href="http://openstreetmap.org">OpenStreetMap</a> contributors, <a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, Imagery © <a href="http://cloudmade.com">CloudMade</a>',
     minZoom: range_min,
    maxZoom: range_max,
      zoomControl: range_max > range_min
  }).addTo(map);

  Hashing.setup(map, default_zoom);

  if (typeof map_loaded_callback !== 'undefined') {
    map_loaded_callback(map);
  }
});
