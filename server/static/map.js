
$(function() {
  var $body = $('body');
  var image = $body.data('image');
  var range_min = $body.data('range-min');
  var range_max = $body.data('range-max');
  var default_zoom = $body.data('default-zoom');
  var extension = $body.data('extension');
  var po = org.polymaps;

  var map = po.map()
      .container(document.getElementById("map").appendChild(po.svg("svg")))
      .center({lat: 0.0, lon: 0.0})
      .zoomRange([range_min, range_max])
      .zoom(default_zoom)
      .add(po.interact())
      .add(po.hash());

  map.add(po.image()
      .url(po.url("/tiles/" + image + "/256/{Z}/{X},{Y}." + extension)
      ));

  map.add(po.compass()
      .pan("none"));

});
