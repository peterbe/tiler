$(function() {
  if ($('input[name="hp"]').size()) {
    $.getJSON('/feedback/hp.json', function(response) {
      $('span.hp-question').text(response.question);
      $('input.hp-question').val(response.question);
    });
    $('form').submit(function() {
      if (!$.trim($('input[name="hp"]').val())) {
        $('input[name="hp"]')
          .addClass('error')
            .on('change', function() {
              $(this)
                .removeClass('error')
                  .off('change');
            });
        alert("Please fill in the human test question. Sorry");
        return false;
      }
      return true;
    });
  }
});
