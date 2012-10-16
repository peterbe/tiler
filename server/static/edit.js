var Drawing = (function() {
  var popup;
  return {
     setup: function(map) {
       popup = L.popup();
       map.on('click', function(event) {
         popup
           .setLatLng(event.latlng)
             .setContent($('#wanna-edit').html())
               .openOn(map);
         $('#map').on('keypress', function(e) {
           e.which == 0 && popup._close();
         });
       });

     }
  };
})();



var Editing = (function() {

  // Adding an 'Edit' link
  $('#topnav ul')
    .append($('<li>')
            .append($('<a href="#">Edit</a>')
                    .addClass('edit')
                    .data('toggle', 'modal')
                    .data('target', '#edit-modal')
                    .click(_clicked_edit)
                   )
           );

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
      description: $('#edit-modal textarea[name="description"]').val()
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
    $.post(location.pathname + '/delete', function() {
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
      if (age < 60) {
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
     }
  };

})();
