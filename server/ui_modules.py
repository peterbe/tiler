import urlparse
import datetime
import tornado.web
import tornado.escape
from tornado_utils.timesince import smartertimesince


class ThumbnailURL(tornado.web.UIModule):

    def render(self, fileid, width, extension):
        if extension == 'image/jpeg':
            extension = 'jpg'
        elif extension == 'image/png':
            extension = 'png'
        return self.handler.make_thumbnail_url(
            fileid,
            width,
            extension=extension
        )


def sizeof_fmt(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0 and num > -1024.0:
            return "%3.1f%s" % (num, x)
        num /= 1024.0
    return "%3.1f%s" % (num, 'TB')


class ShowFileSize(tornado.web.UIModule):

    def render(self, size):
        return sizeof_fmt(size)


class TimeSince(tornado.web.UIModule):
    def render(self, date, date2=None):
        assert date
        if date2 is None:
            date2 = datetime.datetime.utcnow()
        return smartertimesince(date, date2)


def commafy(s):
    r = []
    for i, c in enumerate(reversed(str(s))):
        if i and (not (i % 3)):
            r.insert(0, ',')
        r.insert(0, c)
    return ''.join(r)


class Thousands(tornado.web.UIModule):

    def render(self, number):
        return commafy(str(number))


class LinkTags(tornado.web.UIModule):

    def render(self, *uris):
        if self.handler.application.settings['optimize_static_content']:
            module = self.handler.application.ui_modules['Static'](self.handler)
            return module.render(*uris)

        html = []
        for each in uris:
            html.append('<link href="%s" rel="stylesheet" type="text/css">' %
                         self.handler.static_url(each))
        return '\n'.join(html)


class ScriptTags(tornado.web.UIModule):

    def render(self, *uris, **attrs):
        if self.handler.application.settings['optimize_static_content']:
            module = self.handler.application.ui_modules['Static'](self.handler)
            return module.render(*uris, **attrs)

        html = []
        for each in uris:
            tag = '<script '
            if attrs.get('async'):
                tag += 'async '
            tag += 'src="%s"></script>' % self.handler.static_url(each)
            html.append(tag)
        return '\n'.join(html)


class Truncate(tornado.web.UIModule):

    def render(self, text, max_length):
        if len(text) > max_length:
            return ('%s&hellip;' %
                    tornado.escape.xhtml_escape(text[:max_length]))
        else:
            return tornado.escape.xhtml_escape(text)


class ShortenURL(tornado.web.UIModule):

    def render(self, url, just_domain=False):
        if just_domain:
            parsed = urlparse.urlparse(url)
            return parsed.netloc

        return url
