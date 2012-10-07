import tornado.web
from tornado_utils.timesince import smartertimesince


class ThumbnailURL(tornado.web.UIModule):

    def render(self, fileid, width, extension='png'):
        return '/thumbnails/%s/%s/%s/%s.%s' % (
            fileid[:1],
            fileid[1:3],
            fileid[3:],
            width,
            extension
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
