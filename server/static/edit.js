var Drawing = (function() {
  var popup;
  var map;
  var original_title;
  var drawn_items;

  function drawn(annotation, type) {
    drawn_items.addLayer(annotation);
    annotation.bindPopup($('#annotate-add').html()).openPopup();
    var title_input = $('input.annotation-title:visible');
    if (!title_input.size()) {
      console.log($('input.annotation-title'));
      throw "No title input";
    }
    var form = title_input.parents('form');
    title_input.focus().select();
    $('input[name="type"]', form).val(type);
    if (type == 'circle') {
      $('input[name="radius"]', form).val(annotation.getRadius());
      $('input[name="latlngs"]', form).val(JSON.stringify(annotation.getLatLng()));
    } else if (type == 'marker') {
      $('input[name="latlngs"]', form).val(JSON.stringify(annotation.getLatLng()));
    } else if (type == 'rectangle') {
      $('input[name="latlngs"]', form).val(JSON.stringify(annotation.getBounds()));
    } else {
      $('input[name="latlngs"]', form).val(JSON.stringify(annotation.getLatLngs()));
    }
    var options = {};
    if (annotation.options.color) {
      options.color = annotation.options.color;
    }
    if (annotation.options.weight) {
      options.weight = annotation.options.weight;
    }
    $('input[name="options"]', form).val(JSON.stringify(options));
    form.submit(function() {
      var url = location.pathname + '/annotations';
      $.post(url, $(this).serializeObject(), function(response) {
        annotation.bindPopup(response.html).openPopup();
        annotation.options.title = response.title;
        annotation.options.id = response.id;
        Annotations.new_annotation(annotation);
        Title.change_temporarily("Annotation saved", 3, true);
      });
      return false;
    });
  }

  return {
     edit_annotation: function(annotation) {
       annotation.bindPopup($('#annotate-edit').html()).openPopup();
       $('#id-annotate-title-edit')
         .val(annotation.options.title)
           .focus()
             .select();
       var form = $('#id-annotate-title-edit').parents('form');
       $('input[name="id"]', form).val(annotation.options.id);
       form.submit(function() {
         var url = location.pathname + '/annotations/edit';
         $.post(url, $(this).serializeObject(), function(response) {
           annotation.options.title = response.title;
           annotation.bindPopup(response.html).openPopup();
         });
         return false;
       });
     },
    delete_annotation: function(annotation) {
      var previous_html = annotation._popup._content;  // hackish :(
      annotation.bindPopup($('#annotate-delete').html()).openPopup();
      var form = $('form.form-delete:visible');
      $('input[name="id"]', form).val(annotation.options.id);
      $('input[name="cancel"]', form).click(function() {
        annotation.bindPopup(previous_html);
        map.closePopup();
      });
      form.submit(function() {
        map.closePopup();
        var url = location.pathname + '/annotations/delete';
        $.post(url, $(this).serializeObject(), function(response) {
          map.removeLayer(annotation);
          Title.change_temporarily("Annotation deleted", 2, true);
        });
        return false;
      });
    },
    setup: function(_map) {
      map = _map;

       var drawControl = new L.Control.Draw({
          polygon: {
             allowIntersection: false,
              shapeOptions: {
                 color: '#bada55'
              }
          }
       });
       map.addControl(drawControl);

       drawn_items = new L.LayerGroup();

       map.on('draw:poly-created', function (e) {
         drawn(e.poly, e.poly.options.fill && 'polygon' || 'polyline');
       });
       map.on('draw:rectangle-created', function (e) {
         drawn(e.rect, 'rectangle');
       });
       map.on('draw:circle-created', function (e) {
         drawn(e.circ, 'circle');
       });
       map.on('draw:marker-created', function (e) {
         e.marker.options.icon = MARKER_ICON;
         drawn(e.marker, 'marker');
       });
       map.addLayer(drawn_items);
     }
  };
})();


$.fn.serializeObject = function() {
  var o = {};
  var a = this.serializeArray();
  $.each(a, function() {
    if (o[this.name] !== undefined) {
      if (!o[this.name].push) {
        o[this.name] = [o[this.name]];
      }
      o[this.name].push(this.value || '');
    } else {
      o[this.name] = this.value || '';
    }
  });
  return o;
};



var Editing = (function() {

  // bind some events
  $('#topnav a.edit').click(_clicked_edit);

  function _clicked_closer() {
    $('#topnav li.hidden').removeClass('hidden');
    $(this).parents('li').addClass('hidden');
    $('#topnav li.drawtool').addClass('hidden');
    return false;
  }

  function _clicked_edit() {
    $('#edit-modal').modal({
       backdrop: false,
      keyboard: true
    }).modal('show');
    $('#edit-modal .label-success').hide();
    return false;
  }

  // Close edit modal
  $('.modal a.closer').click(function() {
    var p = $(this).parents('.modal');
    p.modal('hide');
    return false;
  });

  // title input to document title
  var _original_title = document.title;
  var _title_input = $('#edit-modal input[name="title"]');
  _title_input.on('keyup', function() {
    if ($.trim($(this).val())) {
      document.title = $.trim($(this).val());
    } else {
      document.title = _original_title;
    }
  });
  if ($.trim(_title_input.val())) {
    document.title = $.trim(_title_input.val());
  }

  // Saving edit modal
  $('.modal a.btn-primary').click(function() {
    var data = {
       title: _title_input.val(),
      description: $('#edit-modal textarea[name="description"]').val(),
      _xsrf: $('#edit-modal input[name="_xsrf"]').val()
    };
    $.post(location.pathname + '/edit', data, function(response) {
      $('#edit-modal .label-success').show(100);
      setTimeout(function() {
        $('#edit-modal .label-success:visible').fadeOut('slow');
      }, 3 * 1000);
    });
    return false;
  });

  // link to delete modal
  $('#edit-modal a.delete').click(function() {
    var p = $(this).parents('.modal');
    p.modal('hide');
    $('#delete-modal').modal({
       backdrop: false,
      keyboard: true
    }).modal('show');
    return false;
  });

  // confirm deletion
  $('#delete-modal a.cancel').click(function() {
    var p = $(this).parents('.modal');
    p.modal('hide');
  });

  $('#delete-modal a.confirm').click(function() {
    var data = {_xsrf: $('#edit-modal input[name="_xsrf"]').val()};
    $.post(location.pathname + '/delete', data, function() {
      location.href = '/';
    });
  });

  $('#edit-modal form').submit(function() {
    $('#edit-modal a.btn-primary').click();
    return false;
  });

  // prefill form
  $.getJSON(location.pathname + '/metadata', function(response) {
    var c = $('#edit-modal');
    if (response.title) {
      $('[name="title"]', c).val(response.title);
    } else {
      var age = $('body').data('age');
      if (age < (60 * 60)) {
        $('a.edit').click();
      }
    }
    if (response.description) {
      $('[name="description"]', c).val(response.description);
    }

  });

  return {
     setup: function(map) {
       Drawing.setup(map);
     },
    reset_drawing: function() {
      $('#topnav li.closer a').click();
    }
  };

})();
