from tornado_utils.send_mail import send_email
import settings


def send_url(url, fileid, recipient, debug=False):
    if debug:
        backend = 'tornado_utils.send_mail.backends.console.EmailBackend'
    else:
        backend = 'tornado_utils.send_mail.backends.smtp.EmailBackend'
    from_ = 'HUGEPic <noreply+%s@hugepic.io>' % fileid
    subject = "Your HUGE upload has finished"
    body = (
        "Hi,\n"
        "\n"
        "The wonderful picture you uploaded is now fully processed.\n"
        "\n"
        "You can view at:\n"
        "\t" + url +
        "\n\n"
        "--\n"
        "HUGEpic.io"
    )
    send_email(
        backend,
        subject,
        body,
        from_,
        [recipient],
        bcc=getattr(settings, 'BCC_EMAIL', None)
    )
