$(function() {
  $('a.permalink').on('mouseover', function() {
    $(this).attr('href', location.href);
  }).on('click', function() {
    $(this).hide();
    $('a.upload').hide();
    $('input[name="permalink"]').val(location.href).show().focus().select();
    $('a.close-permalink').show();
    return false;
  });

  $('a.close-permalink').on('click', function() {
    $('input[name="permalink"]').hide();
    $(this).hide();
    $('a.permalink').show();
    $('a.upload').show();
    return false;
  });

});
