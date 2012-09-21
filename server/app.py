#!/usr/bin/env python

import os
import tornado.httpserver
import tornado.ioloop
from tornado.options import define, options
import redis.client
import settings
from resizer import main as resizer_main
import handlers

define("debug", default=False, help="run in debug mode", type=bool)
define("port", default=8000, help="run on the given port", type=int)


class Application(tornado.web.Application):

    _redis = None

    @property
    def redis(self):
        if not self._redis:
            self._redis = redis.client.Redis(
                settings.REDIS_HOST,
                settings.REDIS_PORT
            )
        return self._redis


def app():
    app_settings = dict(
        static_path=os.path.join(os.path.dirname(__file__), 'static'),
        template_path=os.path.join(os.path.dirname(__file__), 'templates'),
        debug=options.debug,
        cookie_secret=settings.COOKIE_SECRET,
    )

    return Application([
        (r'/',
         handlers.HomeHandler),
        (r'/download',
         handlers.DownloadHandler),
        (r'/download/preview',
         handlers.PreviewDownloadHandler),
        (r'/download/progress',
         handlers.ProgressDownloadHandler),
        (r'/download/download',
         handlers.ReallyDownloadHandler),
        (r'/dropbox',
         handlers.DropboxHandler),
        (r'/(\w{9})',
         handlers.ImageHandler),
        (r'/browserid/',
         handlers.BrowserIDAuthLoginHandler),
        (r'/signout/',
         handlers.SignoutHandler),
        (r'/tiles/(?P<image>\w{1}/\w{2}/\w{6})/(?P<size>\d+)'
         r'/(?P<zoom>\d+)/(?P<row>\d+),(?P<col>\d+).png',
         handlers.TileHandler),
    ], **app_settings)


if __name__ == '__main__':

    # it's lazy to run resizer as a thread but convenient
    # so I don't have to run a separate supervisor processor
    import threading
    t = threading.Thread(target=resizer_main)
    t.setDaemon(True)
    t.start()

    tornado.options.parse_command_line()
    app().listen(options.port)
    print 'Running on port', options.port
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
        pass
