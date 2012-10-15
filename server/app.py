#!/usr/bin/env python

import os
import re
import logging
from time import sleep
import tornado.httpserver
import tornado.ioloop
from tornado.options import define, options
from tornado_utils.routes import route
import redis.client
from rq import Queue
import motor
import settings
import handlers


define("debug", default=False, help="run in debug mode", type=bool)
define("port", default=8000, help="run on the given port", type=int)
define("dont_optimize_static_content", default=False,
       help="Don't combine static resources", type=bool)
define("dont_embed_static_url", default=False,
       help="Don't put embed the static URL in static_url()", type=bool)


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

    _db_connection = None

    @property
    def db(self):
        if not self._db_connection:
            self._db_connection = motor.MotorConnection().open_sync()
        return self._db_connection[settings.DATABASE_NAME]

    def __init__(self, database_name=None, optimize_static_content=None):
        ui_modules_map = {}
        for each in ('ui_modules',):
            _ui_modules = __import__(each, globals(), locals(),
                                     ['ui_modules'], -1)
            for name in [x for x in dir(_ui_modules)
                         if re.findall('[A-Z]\w+', x)]:
                thing = getattr(_ui_modules, name)
                try:
                    if issubclass(thing, tornado.web.UIModule):
                        ui_modules_map[name] = thing
                except TypeError:  # pragma: no cover
                    # most likely a builtin class or something
                    pass

        if optimize_static_content is None:
            optimize_static_content = not options.dont_optimize_static_content

        try:
            cdn_prefix = [x.strip() for x in open('cdn_prefix.conf')
                          if x.strip() and not x.strip().startswith('#')][0]
            logging.info("Using %r as static URL prefix" % cdn_prefix)
        except (IOError, IndexError):
            cdn_prefix = None

        from tornado_utils import tornado_static
        ui_modules_map['Static'] = tornado_static.Static
        ui_modules_map['StaticURL'] = tornado_static.StaticURL
        ui_modules_map['Static64'] = tornado_static.Static64
        if not optimize_static_content:
            ui_modules_map['Static'] = tornado_static.PlainStatic
            ui_modules_map['StaticURL'] = tornado_static.PlainStaticURL
        routed_handlers = route.get_routes()
        app_settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            cookie_secret=settings.COOKIE_SECRET,
            debug=options.debug,
            email_backend=options.debug and \
                 'tornado_utils.send_mail.backends.console.EmailBackend' \
              or 'tornado_utils.send_mail.backends.pickle.EmailBackend',
            admin_emails=settings.ADMIN_EMAILS,
            ui_modules=ui_modules_map,
            embed_static_url_timestamp=not options.dont_embed_static_url,
            optimize_static_content=not optimize_static_content,
            cdn_prefix=cdn_prefix,
            CLOSURE_LOCATION=os.path.join(os.path.dirname(__file__),
                                          "static", "compiler.jar"),
        )
        routed_handlers.append(
            tornado.web.url('/.*?',
                            handlers.PageNotFoundHandler,
                            name='page_not_found')
        )
        super(Application, self).__init__(routed_handlers, **app_settings)

        self.db  # property gets created


def main():  # pragma: no cover
    tornado.options.parse_command_line()

    q = Queue(connection=redis.client.Redis(
        settings.REDIS_HOST,
        settings.REDIS_PORT
    ))

    job = q.enqueue(handlers.sample_queue_job)
    for i in range(10):
        if job.result:
            break
        sleep(i / 10.0)
        if i > 0 and not i % 3:
            print "Waiting to see if Queue workers are awake..."
    else:
        raise SystemError("Queue workers not responding")

    http_server = tornado.httpserver.HTTPServer(Application())
    print "Starting tornado on port", options.port
    http_server.listen(options.port)
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
