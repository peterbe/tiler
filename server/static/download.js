var Download = (function() {
  var _progress_interval;
  var _fileid;

  function show_error(message) {
    $('#errormessage').text(message);
    $('#error').fadeIn(300);
  }

  function start(url) {
      $.post(PREVIEW_URL, {url: url}, function(response) {

        if (response.error) {
          return show_error(response.error);
        }

        $('button, input').attr('disabled', 'disabled');
        $('#progress').show(300);
        _fileid = response.fileid;
        $('#expected_size, #left')
          .text(response.expected_size)
          .data('total', response.expected_size);
        $('#content_type').text(response.content_type);

        $.ajax({
           type: 'POST',
           url: REALLY_URL,
           data: {fileid: _fileid},
          success: function(response) {
            clearInterval(_progress_interval);
            $('#progress').hide(900);
            if (response.error) {
              return show_error(response.error);
            }
            var base_url = location.href.replace(location.pathname, '');
            $('#url').text(base_url + response.url).attr('href', response.url);
            $('#complete').fadeIn(300);
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
            var total = $('#expected_size').data('total');
            var percentage = Math.round(response.done / total * 100);
            $('#left').text(total - response.done);
            $('#downloaded').text(response.done);
            $('#percentage').text(percentage + '%');
          });
        }, 500);
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
