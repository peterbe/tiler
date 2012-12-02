import re
import logging
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


class Thousands(tornado.web.UIModule):

    def render(self, number):
        return format(number, ',')


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


extra_html_regex = re.compile('<!--extra:(\w+)-->')


class ShowMetaData(tornado.web.UIModule):

    @property
    def redis(self):
        return self.handler.application.redis

    def render(self, image):
        rendered = self.redis.hget(
            'metadata-rendered',
            image['fileid']
        )
        if rendered is None:
            logging.warning(
                'Cache miss on metadata-rendered %s',
                image['fileid']
            )
            extras = self.get_extras(image['fileid'])
            rendered = self.render_string(
                '_meta.html',
                image=image,
                extras=extras,
            )
            self.redis.hset('metadata-rendered', image['fileid'], rendered)
        return rendered

    def get_extras(self, fileid):
        _now = datetime.datetime.utcnow()

        hit_key = 'hits:%s' % fileid
        hit_month_key = (
            'hits:%s:%s:%s' %
            (_now.year, _now.month, fileid)
        )
        hits = self.redis.get(hit_key)
        hits_this_month = (
            self.redis.get(hit_month_key)
        )
        extras = []
        if hits:
            hits = int(hits)
            if hits == 1:
                h = '1 hit'
            else:
                h = '%s hits' % format(hits, ',')
            if hits_this_month and int(hits_this_month) != hits:
                hits_this_month = int(hits_this_month)
                if hits_this_month == 1:
                    h += ' (1 hit this month)'
                else:
                    h += (
                        ' (%s hits this month)' %
                        format(hits_this_month, ',')
                    )
            extras.append(h)

        comments = self.redis.hget('comments', fileid)
        if comments is not None:
            comments = int(comments)
            if comments == 1:
                comments = '1 comment'
            else:
                comments = '%d comments' % comments
            extras.append(comments)
        return extras
