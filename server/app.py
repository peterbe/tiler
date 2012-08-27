import os
import time
import urllib
from collections import defaultdict
from PIL import Image
import tornado.httpclient
import tornado.httpserver
import tornado.ioloop
import tornado.web
from tornado.options import define, options
import redis.client
import settings


define("debug", default=False, help="run in debug mode", type=bool)
define("port", default=8000, help="run on the given port", type=int)

class BaseHandler(tornado.web.RequestHandler):
    pass

class HomeHandler(BaseHandler):
    def get(self):
        image_filename = self.get_argument('filename', 'united_states_wall_2002_us.jpg')
        self.render('index.html', image_filename=image_filename)


class SignoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie('user')
        self.redirect('/')


class BrowserIDAuthLoginHandler(BaseHandler):

    def check_xsrf_cookie(self):
        pass

    @tornado.web.asynchronous
    def post(self):
        assertion = self.get_argument('assertion')
        http_client = tornado.httpclient.AsyncHTTPClient()
        domain = self.request.host
        url = 'https://browserid.org/verify'
        data = {
          'assertion': assertion,
          'audience': domain,
        }
        response = http_client.fetch(
          url,
          method='POST',
          body=urllib.urlencode(data),
          callback=self.async_callback(self._on_response)
        )

    def _on_response(self, response):
        if 'email' in response.body:
            # all is well
            struct = tornado.escape.json_decode(response.body)
            assert struct['email']
            email = struct['email']

            self.set_secure_cookie('user', email, expires_days=10)
        self.write(struct)
        self.finish()


class TileHandler(BaseHandler):

    def get(self, size, zoom, row, col):
        self.set_header('Content-Type', 'image/png')
        image = self.get_argument('image')
        size = int(size)
        zoom = int(zoom)
        row = int(row)
        col = int(col)

        if size != 256: raise tornado.web.HTTPError(400)

        root = os.path.join(self.application.settings['static_path'], 'uploads')
        if not os.path.isdir(root):
            os.mkdir(root)
        save_root = os.path.join(self.application.settings['static_path'], 'tiles')
        if not os.path.isdir(save_root):
            os.mkdir(save_root)
        path = os.path.join(root, image)
        if not os.path.isfile(path):
            raise tornado.web.HTTPError(404, image)

        width = size * (2 ** zoom)
        #filename = os.path.join(image, str(size), str(zoom), '%s,%s.png' % (row, col))
        #save_filepath = os.path.join(save_root, filename)
        save_filepath = save_root
        for p in (image, str(size), str(zoom)):
            save_filepath = os.path.join(save_filepath, p)
            if not os.path.isdir(save_filepath):
                os.mkdir(save_filepath)
        save_filepath = os.path.join(save_filepath, '%s,%s.png' % (row, col))
        #print "WIDTH", width
        #print "ROW", row
        #print "COL", col
        #print "SIZE", size

        if not os.path.isfile(save_filepath):
            original = Image.open(path)
            image = scale_and_crop(
                original,
                (width, width),
                row, col,
                zoom=zoom,
                image=image,
            )

            image.save(save_filepath)

        self.write(open(save_filepath, 'rb').read())

_RESIZES = {}

def scale_and_crop(im, requested_size, row, col, zoom=None, image=None):
    x, y = [float(v) for v in im.size]
    xr, yr = [float(v) for v in requested_size]
    r = min(xr / x, yr / y)

    _cache_key = '%s-%s-%s-%s' % (image, zoom, int(round(x * r)), int(round(y * r)))
    # this is going to memory bloat, consider adding a timestamp too and afterwards potentially
    # clean up all that are getting old and not used
    (already, use_count) = _RESIZES.get(_cache_key, (None, 0))
    if not use_count:
        im = im.resize((int(round(x * r)), int(round(y * r))),
                       resample=Image.ANTIALIAS)
    else:
        im = already
    _RESIZES[_cache_key] = (im, use_count + 1)

    # convert (width, height, x, y) into PIL crop box
    box = (256 * row, 256 * col, 256 * (row + 1), 256 * (col + 1))
    im = im.crop(box)
    return im

class Application(tornado.web.Application):

    _redis = None

    @property
    def redis(self):
        if not self._redis:
            self._redis = redis.client.Redis(settings.REDIS_HOST,
                                             settings.REDIS_PORT)
        return self._redis


def app():
    app_settings = dict(
      static_path=os.path.join(os.path.dirname(__file__), 'static'),
      template_path=os.path.join(os.path.dirname(__file__), 'templates'),
      debug=options.debug,
      cookie_secret=settings.COOKIE_SECRET,
    )

    return Application([
        (r'/', HomeHandler),
        #(r'/manifest.webapp', ManifestHandler),
        (r'/browserid/', BrowserIDAuthLoginHandler),
        (r'/signout/', SignoutHandler),
        (r'/tiles/(?P<size>\d+)/(?P<zoom>\d+)/(?P<row>\d+),(?P<col>\d+).png', TileHandler),
    ], **app_settings)


if __name__ == '__main__':
    tornado.options.parse_command_line()
    app().listen(options.port)
    print 'Running on port', options.port
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
        pass
