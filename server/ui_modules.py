import tornado.web


class ThumbnailURL(tornado.web.UIModule):

    def render(self, fileid, width, extension='png'):
        return '/thumbnails/%s/%s/%s/%s.%s' % (
            fileid[:1],
            fileid[1:3],
            fileid[3:],
            width,
            extension
        )
