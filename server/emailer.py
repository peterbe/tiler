from tornado_utils.send_mail import send_multipart_email
from html2text import html2text
import settings


def send_url(url, fileid, recipient, html_body, debug=False):
    if debug:
        backend = 'tornado_utils.send_mail.backends.console.EmailBackend'
    else:
        backend = 'tornado_utils.send_mail.backends.smtp.EmailBackend'
    from_ = 'HUGEPic <noreply@hugepic.io>'
    subject = "Your HUGE upload has finished"
    text_body = html2text(html_body)
    send_multipart_email(
        backend,
        text_body,
        html_body,
        subject,
        [recipient],
        from_,
        bcc=getattr(settings, 'BCC_EMAIL', None)
    )
