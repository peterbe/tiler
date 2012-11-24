var Embed = (function() {
  var iframe = $('#preview');
  var last_position = null;
  var last_size = null;

  function resize_choice(size) {
    iframe.attr('width', size[0]).attr('height', size[1]);
    $('input[name="width"]').val(size[0]);
    $('input[name="height"]').val(size[1]);
    last_size = size;
    preview_html();
  }

  function valid_number(number) {
    if (isNaN(number)) return false;
    if (number > 10000 || number < 100) return false;
    return true;
  }

  function update_custom_numbers() {
    var width = parseInt($('input[name="width"]').val().replace(/[^0-9]/g, ''));
    var height = parseInt($('input[name="height"]').val().replace(/[^0-9]/g, ''));
    if (valid_number(width) && valid_number(height)) {
      resize_choice([width, height]);
    }
  }

  function pluck_position() {
    var url = iframe[0].contentWindow.location.href;
    var numbers = url.match(/\/([0-9\.]+)\/([-0-9\.]+)\/([-0-9\.]+)/g)[0];
    var zoom = parseFloat(numbers.split('/')[1]);
    var lat = parseFloat(numbers.split('/')[2]);
    var lng = parseFloat(numbers.split('/')[3]);
    if (!last_position || last_position[0] !== zoom ||
        last_position[1] !== lat || last_position[2] !== lng) {
      last_position = [zoom, lat, lng];
      preview_html();
    }
  }

  function preview_html(url) {
    if (!url) {
      url = iframe[0].contentWindow.location.href;
    }
    if (last_size === null) {
      last_size = [parseInt(iframe.attr('width')), parseInt(iframe.attr('height'))];
    }
    var size = last_size;
    var html = '<iframe width="' + size[0] + '" height="' + size[1] + '" ';
    html += 'src="' + url + '" frameborder="0"></iframe>';
    $('.preview').text(html);
  }

  function toggle_hide_annotations() {
    var url = iframe[0].contentWindow.location.href;
    if (url.search(/hide_annotations=\d/) == -1) {
      var new_url = url + '&hide_annotations=0';
    } else {
      var new_url = url.replace('&hide_annotations=0', '');
    }
    iframe[0].contentWindow.location.href = new_url;
    preview_html(new_url);
  }

  function toggle_hide_download_counter() {
    var url = iframe[0].contentWindow.location.href;
    if (url.search(/hide_download_counter=\d/) == -1) {
      var new_url = url + '&hide_download_counter=0';
    } else {
      var new_url = url.replace('&hide_download_counter=0', '');
    }
    iframe[0].contentWindow.location.href = new_url;
    preview_html(new_url);
  }

  return {
     setup: function() {
       $('.sizes a').click(function() {
         $('.sizes a.chosen').removeClass('chosen');
         $(this).addClass('chosen');
         resize_choice($(this).data('size'));
         return false;
       });
       $('input[name="show_annotations"]').change(function() {
         toggle_hide_annotations();
       });
       if ($('input[name="show_annotations"]:checked').size()) {
         toggle_hide_annotations();
       }

       $('input[name="show_download_counter"]').change(function() {
         toggle_hide_download_counter();
       });
       if ($('input[name="show_download_counter"]:checked').size()) {
         toggle_hide_download_counter();
       }

       $('input[name="width"], input[name="height"]').change(update_custom_numbers);
       $('input[name="width"]').val(iframe.attr('width'));
       $('input[name="height"]').val(iframe.attr('height'));
       preview_html();
       setInterval(pluck_position, 2 * 1000);
     }
  };
})();


$(Embed.setup);
