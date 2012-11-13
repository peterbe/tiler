var Utils = (function() {
  return {
    preload_image: function(url, callback) {
      var i = $('<img>');
      if (callback) {
        i.ready(callback);
      }
      i.attr('src', url);
    },
    preload_images: function(urls, synchronous, callback) {
      if (synchronous) {
        var url = urls.shift();
        if (url) {
          Utils.preload_image(url, function() {
            Utils.preload_images(urls, true, callback); // "recurse"
          });
        } else {
          callback();
        }
      } else {
        $.each(urls, function(i, url) {
          Utils.preload_image(url);
        });
        callback();
      }
    }
  };
})();

var Download = (function() {
  var _progress_interval;
  var _fileid;
  var _preload_timer;
  var _preload_urls = [];
  var _loaded_urls = [];
  var preload_interval = 1;
  var _has_completed = false;
  var _preload_count = 0;
  var _progress_load_count = 0;
  var _xsrf = $('input[name="_xsrf"]').val();

  function show_error(message) {
    $('#preprogress, #progress, #terms').hide();
    $('#errormessage').text(message);
    $('#error').fadeIn(300);
    $('button, input').removeAttr('disabled', 'disabled');
  }

  function preload() {
    $.getJSON('/preload-urls/' + _fileid, function(response) {
      $.each(response.urls, function(i, url) {
        if ($.inArray(url, _loaded_urls) == -1) {
          // not been loaded before
          _preload_urls.push(url);
        }
      });
      if (_preload_urls.length) {
        _do_preload();
      }
      if (_loaded_urls.length) {
        // it has begun
        preload_interval *= 2;
      }
      _preload_count++;
      if (_preload_count < 20) {
        start_preloading();
      }
    });
  }

  function _do_preload() {
    $.each(_preload_urls, function(i, url) {
      _loaded_urls.push(url);
    });
    Utils.preload_images(_preload_urls, true, function() {
      _preload_urls = [];
      if (!_has_completed) {
        _has_completed = true;
        $('#precomplete').hide();
        $('#complete').hide().fadeIn(1000);
      }
    });
  }

  function start_preloading() {
    _preload_timer = setTimeout(function() {
      preload(_fileid);
    }, preload_interval * 1000);
  }

  function _really_post_success(response) {
    clearInterval(_progress_interval);
    $('#progress').hide();
    $('#progress-giveup').hide();
    if (response.error) {
      return show_error(response.error);
    }
    if (response.email) {
      $('#email .email').text(response.email);
      $('#email').show();
    } else {
      var base_url = location.href.replace(location.pathname, '');
      $('#url').text(base_url + response.url).attr('href', response.url);
      $('#precomplete').show();
      start_preloading();
    }
  }

  function _really_post_error(xhr, status, error_thrown) {
    clearInterval(_progress_interval);
    $('button, input').removeAttr('disabled', 'disabled');
    $('#progress').hide();
    $('#progress-giveup').hide();
    var msg = status;
    if (xhr.responseText) {
      msg += ': ' + xhr.responseText;
    }
    alert(msg);
  }

  function _progress_post_success(response) {
    $('#downloaded').text(humanize.filesize(response.done));
    var total = $('#expected_size').data('total');
    if (total) {
      var percentage = Math.round(response.done / total * 100);
      if (percentage >= 100) {
        $('#progress .progress-image-action').text('Processing');
      } else {
        $('#progress .progress-image-action').text('Downloading');
      }

      $('#left').text(humanize.filesize(total - response.done));
      $('#percentage').text(percentage + '%');
      $('#progress .bar').css('width', percentage + '%');
    }
  }

  function _progress_give_up() {
    clearInterval(_progress_interval);
    $('button, input').attr('disabled', 'disabled');
    $('#progress').hide();
    $('#progress-giveup').show(100);
  }

  function _preview_post_success(response) {
      if (response.error) {
        return show_error(response.error);
      }
      if (!response.fileid) {
          return show_error("Failed to download the image for unknown reason :(");
      }

      $('button, input').attr('disabled', 'disabled');
      $('#preprogress').hide();
      $('#progress').show(100);
      _fileid = response.fileid;

      $('#expected_size, #left')
        .text(humanize.filesize(response.expected_size))
          .data('total', response.expected_size);
      if (!response.expected_size) {
        $('#expected_size, #left')
          .text('not known :(');
      }
      $('#content_type').text(response.content_type);

      $.ajax({
         type: 'POST',
        url: REALLY_URL,
        data: {fileid: _fileid, _xsrf: _xsrf},
        success: _really_post_success,
        error: _really_post_error
      });

      _progress_interval = setInterval(function() {
        $.getJSON(PROGRESS_URL, {fileid: _fileid}, _progress_post_success);
        _progress_load_count++;
        if (_progress_load_count >= 60) {
          _progress_give_up();
        }
      }, 1000);
  }

  function _preview_post_error(xhr, status, error_thrown) {
    $('#preprogress').hide();
    $('button, input').removeAttr('disabled', 'disabled');
    var msg = status;
    if (xhr.responseText) {
      msg += ': ' + xhr.responseText;
    }
    alert(msg);
  }

  function start(url) {
    $('#terms').fadeOut(100);
    $('#preprogress').show(100);
    $.ajax({
       type: 'POST',
      url: PREVIEW_URL,
      data: {url: url, _xsrf: _xsrf},
      success: _preview_post_success,
      error: _preview_post_error
    });
  }

  function setup() {

    // in case it got stuck last time
    $('button, input').removeAttr('disabled');

    $('form').submit(function() {
      var url = $.trim($('input[name="url"]').val());
      if (!url) {
        return;
      }
      start(url);
      return false;
    });
  }
  return {setup: setup, start: start};
})();


function files_picked(files) {
  $.each(files, function(i, each) {
    Download.start(each.url);
  });
}

$(function() {
  Download.setup();
  $('#terms').on('click', function() {
    $(this).toggleClass('faded');
  });
});
