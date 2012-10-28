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


var Annotations = (function() {
  var annotations = {};
  return {
     new_annotation: function(annotation) {
       annotations[annotation.options.id] = annotation;
     },
     edit: function(id) {
       Drawing.edit_annotation(annotations[id]);
       return false;
     },
     delete_: function(id) {
       Drawing.delete_annotation(annotations[id]);
       delete annotations[id];
       return false;
     },
     init: function(map) {
       $.getJSON(location.pathname + '/annotations', function(response) {
         $.each(response.annotations, function(i, each) {
           var options = {draggable: each.yours, title: each.title, id: each.id};
           options.weight = each.yours && 4 || 2;
           var annotation;
           if (each.type == 'circle') {
             annotation = L[each.type](each.latlngs[0], each.radius, options);
           } else if (each.type == 'marker') {
             options.icon = MARKER_ICON;
             annotation = L[each.type](each.latlngs[0], options);
           } else {
             annotation = L[each.type](each.latlngs, options);
           }
           annotation
             .addTo(map)
               .bindPopup(each.html);

           Annotations.new_annotation(annotation);

           if (each.yours && each.type == 'marker') {
             // means you can edit it
             annotation.on('dragend', function(event) {
               var data = {
                  id: event.target.options.id,
                 lat: event.target.getLatLng().lat,
                 lng: event.target.getLatLng().lng
               };
               $.post(location.pathname + '/annotations/move', data, function() {
                 Title.change_temporarily("Marker moved", 2, true);
               });
             });
           }
         });
       });
     }
  };
})();


var Title = (function() {
  var current_title;
  var timer;
  var locked = false;

  return {
     change_temporarily: function (msg, msec, animate) {
       if (locked) {
         clearTimeout(timer);
       }
       current_title = document.title;
       msec = typeof(msec) !== 'undefined' ? msec : 2500;
       if (msec < 100) msec *= 1000;
       if (timer) {
         clearTimeout(timer);
       }
       document.title = msg;
       locked = true;
       timer = setTimeout(function() {
         if (animate) {
           var interval = setInterval(function() {
             document.title = document.title.substring(1, document.title.length);
             if (!document.title.length) {
               clearInterval(interval);
               locked = false;
               document.title = current_title;
             }
           }, 40);
         } else {
           document.title = current_title;
           locked = false;
         }
       }, msec);
     }
  }
})();

var MARKER_ICON = L.icon({
  iconUrl: MARKER_ICON_URL,
  shadowUrl: MARKER_SHADOW_URL,
  iconSize: new L.Point(25, 41),
  iconAnchor: new L.Point(13, 41),
  popupAnchor: new L.Point(1, -34),
  shadowSize: new L.Point(41, 41)
});

// when we can't rely on using MARKER_ICON (such as in draw)
// we have to set a default
L.Icon.Default.imagePath = '/static/libs/images';


$(function() {

  var $body = $('body');
  var image = $body.data('image');
  var range_min = $body.data('range-min');
  var range_max = $body.data('range-max');
  var default_zoom = $body.data('default-zoom');
  var extension = $body.data('extension');
  var prefix = $body.data('prefix');


  var tiles_url = prefix + '/tiles/' + image + '/256/{z}/{x},{y}.' + extension;
  var map_layer = new L.TileLayer(tiles_url, {
      minZoom: range_min,
      maxZoom: range_max,
      zoomControl: range_max > range_min
    });
  var map = new L.Map('map', {
     layers: [map_layer],
  });

  map
    .attributionControl
    .setPrefix('Powered by <a href="http://hugepic.io/">HUGEpic.io</a>');

/*  var bounds=[[-16.63619187839765, -135.703125], [15.284185114076445, -135.703125],
              [15.284185114076445, 88.24218749999999], [-16.63619187839765, -88.24218749999999], {lat:-16.63619187839765, lng:-135.703125}];
 */
  //var bounds = [[-19.973348786110602, -134.6484375], [13.923403897723347, -82.265625]];
  //L.rectangle(bounds, {color: "#ff7800", weight: 3}).addTo(map);

/*  L.Icon.L.Icon.extend({
			options: {
				shadowUrl: '../docs/images/leaf-shadow.png',
			}
		});*/

  Hashing.setup(map, default_zoom);
  Annotations.init(map);

  if (typeof map_loaded_callback !== 'undefined') {
    map_loaded_callback(map);
  }
});
