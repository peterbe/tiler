var Commenting = (function() {
  var map, fileid;
  var pathname;
  var container = $('#comment-modal');

  function _opener() {
    container.modal({
       backdrop: false,
      keyboard: true
    }).modal('show');
    $('#comment-modal .label-success').hide();
  }

  // Close edit modal
  $('a.closer', container).click(function() {
    var p = $(this).parents('.modal');
    p.modal('hide');
    return false;
  });

  function _prefill_form() {
    $.getJSON(pathname + '/commenting', function(response) {
      if (response.name) {
        $('input[name="name"]', container).val(response.name);
      }
      _load_comments(response.comments);
      $('.comments-hider a.show strong', container).text(response.count);
      $('h3.comments strong', container).text(response.count);
      if (!response.signed_in) {
        $('.comments-hider a.show', container).click();
        $('form', container).hide();
        $('.not-signed-in', container).show();
      }
    });
  }

  function _load_comments(comments) {
    var c = $('.comments-outer', container);
    $('div', c).remove();
    var inner = $('<div>');
    $.each(comments, function(i, each) {
      var d = $('<div>').addClass('comment');
      $('<blockquote>')
        .html(each.html)
          .appendTo(d);
      $('<a href="#">show where this was posted</a>')
        .addClass('pan-to')
        .data('center', each.center)
        .click(function() {
          map.panTo($(this).data('center'));
          $('a.closer', container).click();
          return false;
        })
        .appendTo(d);

      $('<p>')
        .html('By: <strong>' + each.name + '</strong> ' + each.ago + ' ago')
          .appendTo(d);
      d.appendTo(inner);
    });
    inner.appendTo(c);
  }

  // Saving comment modal
  $('a.btn-primary', container).click(function() {
    var data = {
      name: $('input[name="name"]', container).val(),
      comment: $('textarea[name="comment"]', container).val(),
      zoom: map.getZoom(),
      lat: map.getCenter().lat,
      lng: map.getCenter().lng,
      _xsrf: $('input[name="_xsrf"]', container).val()
    };
    if (!$.trim(data.name)) {
      $('input[name="name"]', container)
        .addClass('error')
          .change(function() {
            $(this)
              .removeClass('error')
                .off('change');
          });
      return false;
    }
    if (!$.trim(data.comment)) {
      $('textarea[name="comment"]', container)
        .addClass('error')
          .change(function() {
            $(this)
              .removeClass('error')
                .off('change');
          });
      return false;
    }
    $.post(pathname + '/commenting', data, function(response) {
      $('textarea[name="comment"]', container).val('');
      $('.label-success', container).show(100);
      setTimeout(function() {
        $('.label-success:visible', container).fadeOut('slow');
        $.getJSON(pathname + '/commenting', function(response) {
          _load_comments(response.comments);
          $('.comments-hider a.show strong', container).text(response.count);
          $('h3.comments strong', container).text(response.count);
          $('.comments-hider a.show', container).click();
        });
      }, 3 * 1000);
    });
    return false;
  });

  $('#comment-modal form').submit(function() {
    $('#comment-modal a.btn-primary').click();
    return false;
  });

  function _setup_show_comments_toggle() {
    $('.comments-hider a.show', container)
      .click(function() {
        $('form', container).hide();
        $('.comments-outer', container).show();
        $('.comments-hider a.hide', container).show();
        $('.comments-hider a.show', container).hide();
        $('a.btn-primary', container).hide();
        $('h3.comments', container).show();
        $('h3.comment', container).hide();
        return false;
      });
    $('.comments-hider a.hide', container)
      .click(function() {
        $('.comments-outer', container).hide();
        $('form', container).show();
        $('.comments-hider a.hide', container).hide();
        $('.comments-hider a.show', container).show();
        $('a.btn-primary', container).show();
        $('h3.comments', container).hide();
        $('h3.comment', container).show();
        return false;
      });
  }

  return {
     open: function() {
       _opener();
     },
     setup: function(_map, _fileid) {
       map = _map;
       fileid = _fileid;
       pathname = '/' + fileid;
       _prefill_form();
       _setup_show_comments_toggle();
       $('a.leaflet-control-custom-comment').show();
   }
  };
})();
