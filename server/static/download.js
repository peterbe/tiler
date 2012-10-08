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

  function show_error(message) {
    $('#errormessage').text(message);
    $('#error').fadeIn(300);
  }

  function preload() {
    //console.log('--fetching--', preload_interval);
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
      start_preloading();
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

  function start(url) {
      $('#preprogress').show(100);
      $.post(PREVIEW_URL, {url: url}, function(response) {

        if (response.error) {
          return show_error(response.error);
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
           data: {fileid: _fileid},
          success: function(response) {
            clearInterval(_progress_interval);
            $('#progress').hide();
            if (response.error) {
              return show_error(response.error);
            }
            var base_url = location.href.replace(location.pathname, '');
            $('#url').text(base_url + response.url).attr('href', response.url);
            $('#precomplete').show();
            start_preloading();
          },
          error: function(xhr, status, error_thrown) {
            clearInterval(_progress_interval);
            $('button, input').removeAttr('disabled', 'disabled');
            $('#progress').hide();
            var msg = status;
            if (xhr.responseText) {
              msg += ': ' + xhr.responseText;
            }
            alert(msg);
          }
        });

        _progress_interval = setInterval(function() {
          $.getJSON(PROGRESS_URL, {fileid: _fileid}, function(response) {
            $('#downloaded').text(humanize.filesize(response.done));
            var total = $('#expected_size').data('total');
            if (total) {
              var percentage = Math.round(response.done / total * 100);
              $('#left').text(humanize.filesize(total - response.done));
              $('#percentage').text(percentage + '%');
              $('#progress .bar').css('width', percentage + '%');
            }
          });
        }, 1000);
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
});
