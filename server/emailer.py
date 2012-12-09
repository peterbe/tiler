import datetime
import logging
from tornado_utils.send_mail import send_multipart_email, send_email
from html2text import html2text
import settings


def _get_backend(debug=False):
    if debug:
        return 'tornado_utils.send_mail.backends.console.EmailBackend'
    else:
        return 'tornado_utils.send_mail.backends.smtp.EmailBackend'


def send_url(url, fileid, recipient, html_body, plain_body=None, debug=False):
    backend = _get_backend(debug)
    from_ = 'HUGEPic <noreply@hugepic.io>'
    subject = "Your HUGE upload has finished"
    if not plain_body:
        plain_body = html2text(html_body)
    logging.info('Sending email to %s', recipient)
    send_multipart_email(
        backend,
        plain_body,
        html_body,
        subject,
        [recipient],
        from_,
        bcc=getattr(settings, 'BCC_EMAIL', None)
    )


def send_feedback(document, debug=False):
    from_ = 'HUGEPic <noreply@hugepic.io>'
    subject = "Feedback on HUGEpic"
    body = ''
    for key in ('name', 'email', 'type', 'comment', 'current_user'):
        body += '%s: %s\n' % (key.capitalize(), document.get(key, '--'))
    body += 'Date: %s\n' % datetime.datetime.utcnow()
    send_email(
        _get_backend(debug),
        subject,
        body,
        from_,
        [settings.ADMIN_EMAILS[0]],
    )


def send_newsletter(recipient, subject, html_body, plain_body=None, debug=False):
    from_ = 'HUGEPic <noreply@hugepic.io>'
    logging.info('Sending email to %s', recipient)
    send_multipart_email(
        _get_backend(debug),
        plain_body,
        html_body,
        subject,
        [recipient],
        from_,
#        bcc=getattr(settings, 'BCC_EMAIL', None)
    )
