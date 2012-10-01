$(function() {
  $('a.signin').click(function(e) {
    e.preventDefault();
    navigator.id.getVerifiedEmail(function(assertion) {
      if (assertion) {
        $.ajax({
           type: 'POST',
          url: '/auth/browserid/',
          data: {assertion: assertion},
          success: function(res, status, xhr) { window.location.reload(); },
          error: function(res, status, xhr) { alert("login failure" + res); }
        });
      } else {
        alert("Failed to log in");
      }
    });


  });

  $('a.signout').click(function(e) {
    e.preventDefault();
    navigator.id.logout();
    $.ajax({
       type: 'POST',
      url: '/auth/signout/',
      success: function(res, status, xhr) { window.location.reload(); },
      error: function(res, status, xhr) { alert("logout failure" + res); }
    });

  });

});
