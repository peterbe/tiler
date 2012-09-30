#!/usr/bin/env python

import os
import tornado.httpserver
import tornado.ioloop
from tornado.options import define, options
from tornado_utils.routes import route
import redis.client
import settings
import handlers


define("debug", default=False, help="run in debug mode", type=bool)
define("port", default=8000, help="run on the given port", type=int)


class Application(tornado.web.Application):

    _redis = None
    _queue = None

    @property
    def redis(self):
        if not self._redis:
            self._redis = redis.client.Redis(
                settings.REDIS_HOST,
                settings.REDIS_PORT
            )
        return self._redis

    @property
    def queue(self):
        if not self._queue:
            self._queue = Queue(connection=self.redis)
        return self._queue


def app():
    app_settings = dict(
        static_path=os.path.join(os.path.dirname(__file__), 'static'),
        template_path=os.path.join(os.path.dirname(__file__), 'templates'),
        debug=options.debug,
        cookie_secret=settings.COOKIE_SECRET,
    )

    routed_handlers = route.get_routes()
    routed_handlers.append(
          tornado.web.url(
              '/.*?',
              handlers.PageNotFoundHandler,
              name='page_not_found')
    )

    return Application(routed_handlers, **app_settings)


if __name__ == '__main__':

    # it's lazy to run resizer as a thread but convenient
    # so I don't have to run a separate supervisor processor
#    import threading
#    t = threading.Thread(target=resizer_main)
#    t.setDaemon(True)
#    t.start()

    tornado.options.parse_command_line()
    app().listen(options.port)
    print 'Running on port', options.port
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
        pass
