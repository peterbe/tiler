var Download = (function() {
  var _progress_interval;
  var _fileid;

  function show_error(message) {
    $('#errormessage').text(response.error);
    $('#error').fadeIn(300);
  }

  function setup() {

    // in case it got stuck last time
    $('button, input').removeAttr('disabled');

    $('form').submit(function() {
      var url = $.trim($('input[name="url"]').val());
      if (!url) {
        return;
      }
      $.post('/download/preview', {url: url}, function(response) {

        if (response.error) {
          return show_error(response.error);
        }

        $('button, input').attr('disabled', 'disabled');
        $('#progress').show(300);
        _fileid = response.fileid;
        $('#expected_size, #left').text(response.expected_size);
        $('#content_type').text(response.content_type);

        $.post('/download/download', {fileid: _fileid}, function(response) {
          console.log("DOWNLOADED", response);
          clearInterval(_progress_interval);
          $('#progress').hide(900);
          if (response.error) {
            return show_error(response.error);
          }
          $('#url').text(response.url).attr('href', response.url);
          $('#complete').fadeIn(300);
        });

        _progress_interval = setInterval(function() {
          $.getJSON('/download/progress', {fileid: _fileid}, function(response) {
            $('#left').text(response.left);
            $('#downloaded').text(response.done);
          });
        }, 300);  // should be 1000
      });
      return false;
    });
  }
  return {setup: setup};
})();

$(function() {
  Download.setup();
});
