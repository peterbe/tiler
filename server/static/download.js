var Download = (function() {
  var _progress_interval;
  var _fileid;

  function show_error(message) {
    $('#errormessage').text(message);
    $('#error').fadeIn(300);
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
            .text('not known :(')
        }
        $('#content_type').text(response.content_type);

        $.ajax({
           type: 'POST',
           url: REALLY_URL,
           data: {fileid: _fileid},
          success: function(response) {
            clearInterval(_progress_interval);
            $('#progress').fadeOut(300);
            if (response.error) {
              return show_error(response.error);
            }
            var base_url = location.href.replace(location.pathname, '');
            $('#url').text(base_url + response.url).attr('href', response.url);
            $('#complete').fadeIn(900);
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
