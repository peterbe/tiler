var Hashing = (function() {
  var _map;
  var _fileid;
  var _hashing_on = true;

  var DEFAULT_LAT = 70.0, DEFAULT_LNG = 0;

  function getHashByMap(map) {
    var zoom = map.getZoom(),
      center = map.getCenter(),
      lat = center.lat,
      lng = center.lng;
    return getHash(zoom, lat, lng);
  }

  function getHash(zoom, lat, lng) {
    var precision = Math.max(0, Math.ceil(Math.log(zoom) / Math.LN2));
    return zoom.toFixed(2) + '/' +
           lat.toFixed(precision) + '/' + lng.toFixed(precision);
  }

  function getURL(zoom, lat, lng) {
    var url = '/' + _fileid + '/' + getHash(zoom, lat, lng);
    var qs = location.search;
    var hash = location.hash;
    if (qs) url += qs;
    if (hash) url += hash;
    return url;
  }

  function setHash(zoom, lat, lng) {
    var state = {zoom: zoom, lat: lat, lng: lng};
    //var state = {};

    history.replaceState(state, 'page', getURL(zoom, lat, lng));
  }

  return {
     showPermalink: function() {
       if ($('#permalink:visible').size()) {
         $('#permalink a.close-permalink').click();
         return;
       }
       var container = $('#permalink');
       $('input[name="permalink"]', container)
         .val(location.protocol + '//' + location.host + getHashByMap(_map));
       container.slideDown(300);
       $('input[name="permalink"]', container)
         .show().focus().select();
     },
     setup: function(map, fileid, default_zoom, default_location) {
       _map = map;
       _fileid = fileid;
       if (default_location) {
         map.setView([default_location[0], default_location[1]], default_zoom);
       } else {
         // Default!
         map.setView([DEFAULT_LAT, DEFAULT_LNG], default_zoom);
       }

       // set up the event
       map.on('move', function(event) {
         if (!_hashing_on) return;
         var c = event.target.getCenter();
         setHash(event.target.getZoom(), c.lat, c.lng);
       });

       $('#permalink a.close-permalink').on('click', function() {
         $('#permalink').slideUp(100);
         return false;
       });

     }
  };
})();


var Annotations = (function() {
  var pathname;
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
     init: function(map, fileid) {
       pathname = '/' + fileid;
       $.getJSON(pathname + '/annotations', function(response) {
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
               $.post(pathname + '/annotations/move', data, function() {
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


var TrackKeeper = (function() {
  var urls = [];
  var new_urls = [];
  var total_bytes = 0;
  var locked = false;
  var extension = null;
  var pathname;

  function path(url) {
    return url.match(/\d\/\d+,\d+/g)[0];
  }

  function humanize_size(filesize) {
    var kilo = 1024;
    var units = ['bytes', 'Kb', 'Mb', 'Gb', 'Tb', 'Pb'];
    if (filesize < kilo) { return filesize.toFixed() + ' ' + units[0]; }
    var thresholds = [1];
    for (var i = 1; i < units.length; i++) {
      thresholds[i] = thresholds[i-1] * kilo;
      if (filesize < thresholds[i]) {
        return (filesize / thresholds[i-1]).toFixed(1) + ' ' + units[i-1];
      }
    }
  }

  function update_new_urls() {
    var url = pathname + '/weight';
    var data = {urls: new_urls.join('|'), extension: extension};
    $.post(url, data, function(response) {
      total_bytes += response.bytes;
      $('#track-stats').show();
      $('#track-stats span').text(humanize_size(total_bytes));
    });
    new_urls = [];
  }

  return {
     setup: function(fileid) {
       pathname = '/' + fileid;
     },
     notice: function(url) {
       var p = path(url);
       if (!extension) {
         extension = url.match(/\.[a-z]+$/g)[0];
       }
       if ($.inArray(p, urls) === -1) {
         urls.push(p);
         new_urls.push(p);
         if (!locked) {
           locked = true;
           setTimeout(function() {
             update_new_urls();
             locked = false;
           }, 2 * 1000);
         }
       }
     }
  };
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



var CustomButtons = (function() {

  function launchFullScreen(element) {
    if(element.requestFullScreen) {
      element.requestFullScreen();
    } else if(element.mozRequestFullScreen) {
      element.mozRequestFullScreen();
    } else if(element.webkitRequestFullScreen) {
      element.webkitRequestFullScreen();
    }
  }

  function cancelFullscreen() {
    if(document.cancelFullScreen) {
      document.cancelFullScreen();
    } else if(document.mozCancelFullScreen) {
      document.mozCancelFullScreen();
    } else if(document.webkitCancelFullScreen) {
      document.webkitCancelFullScreen();
    }
  }

  function make_button(container, classname, title, href, handler, visible) {
    var link = L.DomUtil.create('a', classname, container);
    link.href = href;
    link.title = title;
    if (!visible) {
      link.style['display'] = 'none';
    }

    L.DomEvent
      .on(link, 'click', L.DomEvent.stopPropagation)
        .on(link, 'mousedown', L.DomEvent.stopPropagation)
          .on(link, 'dblclick', L.DomEvent.stopPropagation)
            .on(link, 'click', L.DomEvent.preventDefault)
              .on(link, 'click', handler);
    return link;
  }

  var custom_button_class = L.Control.extend({
     options: {
        position: 'topright'
     },
    initialize: function (options) {
        L.Util.extend(this.options, options);
    },

    onAdd: function(map) {
      this._map = map;
      var container = L.DomUtil.create('div', 'leaflet-control-custom');

      var home_link = L.DomUtil.create('a', 'leaflet-control-custom-home', container);
      home_link.href = '/';
      home_link.title = "Go back to the Home page";

      make_button(container,
                  'leaflet-control-custom-permalink',
                  "Permanent link to this view",
                  '#',
                  this.handle_permalink,
                  true);

      make_button(container,
                  'leaflet-control-custom-fullscreen',
                  "Fullscreen",
                  '#',
                  this.handle_fullscreen,
                 true);

      make_button(container,
                  'leaflet-control-custom-unfullscreen',
                  "Exit fullscreen",
                  '#',
                  this.handle_unfullscreen,
                  false);

      make_button(container,
                  'leaflet-control-custom-edit',
                  "Edit information about picture",
                  '#',
                  this.handle_edit,
                  false);

      make_button(container,
                  'leaflet-control-custom-comment',
                  "Submit a comment about what you see",
                  '#',
                  this.handle_comment,
                  true);

      return container;
    },
    handle_fullscreen: function() {
      $('a.leaflet-control-custom-fullscreen').hide();
      $('a.leaflet-control-custom-unfullscreen').show();
      launchFullScreen(document.documentElement);
      return false;
    },
    handle_unfullscreen: function() {
      cancelFullscreen();
      $('a.leaflet-control-custom-unfullscreen').hide();
      $('a.leaflet-control-custom-fullscreen').show();
      return false;
    },
    handle_permalink: function() {
      Hashing.showPermalink();
      return false;
    },
    handle_edit: function() {
      Editing.open();
      return false;
    },
    handle_comment: function() {
      Commenting.open();
      return false;
    }

  });

  return {
     setup: function(map) {
       var buttons = new custom_button_class();
       buttons.addTo(map);
     }
  };
})();


$(function() {

  var $body = $('body');
  var fileid = $body.data('fileid');
  var image = $body.data('image');
  var range_min = $body.data('range-min');
  var range_max = $body.data('range-max');
  var default_zoom = $body.data('default-zoom');
  var extension = $body.data('extension');
  var prefix = $body.data('prefix');
  var embedded = $body.data('embedded');
  var hide_download_counter = $body.data('hide-download-counter');
  var hide_annotations = $body.data('hide-annotations');
  var default_location = $body.data('default-location');

  var tiles_url = prefix + '/tiles/' + image + '/256/{z}/{x},{y}.' + extension;
  var map_layer = new L.TileLayer(tiles_url, {
      minZoom: range_min,
      maxZoom: range_max,
      zoomControl: range_max > range_min
    });

  if (!hide_download_counter) {
    TrackKeeper.setup(fileid);
    map_layer.on('tileload', function(e) {
      TrackKeeper.notice(e.url);
    });
  }

  var map = new L.Map('map', {
     layers: [map_layer],
  });

  var attribution_url = 'http://hugepic.io/';
  if (embedded) {
    attribution_url = 'http://hugepic.io/' + fileid;
  }
  map
    .attributionControl
    .setPrefix('Powered by <a href="' + attribution_url + '" target="_blank">HUGEpic.io</a>');

  Hashing.setup(map, fileid, default_zoom, default_location);
  if (!embedded) {
    CustomButtons.setup(map);
  }
  if (!hide_annotations) {
    Annotations.init(map, fileid);
  }

  setTimeout(function() {
    $.post('/' + fileid + '/hit', {'_xsrf': $('input[name="_xsrf"]').val()});
  }, 1000);

  if (typeof map_loaded_callback !== 'undefined') {
    map_loaded_callback(map);
  }
});
