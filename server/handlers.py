import os
import json
import stat
import time
import urllib
import uuid

import tornado.web
import tornado.gen
import tornado.httpclient
from PIL import Image


class BaseHandler(tornado.web.RequestHandler):

    @property
    def redis(self):
        return self.application.redis


class HomeHandler(BaseHandler):
    def get(self):
        self.render('index.html')


class DropboxHandler(BaseHandler):
    def get(self):
        self.render('dropbox.html')


class ImageHandler(BaseHandler):
    def get(self, filename):
        image_filename = (
            filename[:1] +
            '/' +
            filename[1:3] +
            '/' +
            filename[3:]
        )
        self.render('image.html', image_filename=image_filename)


class DownloadHandler(BaseHandler):

    def get(self):
        #assert self.get_secure_cookie('user'), "not logged in"
        self.render('download.html')

    def make_destination(self, fileid):
        root = os.path.join(
            self.application.settings['static_path'],
            'uploads'
        )
        if not os.path.isdir(root):
            os.mkdir(root)
        destination = os.path.join(
            root,
            fileid[:1],
            fileid[1:3],
        )
        mkdir(destination)
        #    fileid[3:]
        #)
        destination += '/%s' % fileid[3:]
        destination += '.jpg'  # XXX good enough?

        return destination


class PreviewDownloadHandler(DownloadHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        url = self.get_argument('url')
        #assert self.get_secure_cookie('user'), "not logged in"
        http_client = tornado.httpclient.AsyncHTTPClient()
        head_response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            method='HEAD'
        )
        # XXX can we find out if this was a image/jpeg or something?
        if not head_response.code == 200:
            self.write({'error': head_response.body})
            return

        expected_size = int(head_response.headers['Content-Length'])
        content_type = head_response.headers['Content-Type']

        fileid = uuid.uuid4().hex[:9]
        self.redis.set('fileid:%s' % fileid, url)
        self.redis.setex(
            'contenttype:%s' % fileid,
            content_type,
            60 * 60
        )
        self.redis.setex(
            'expectedsize:%s' % fileid,
            expected_size,
            60 * 60
        )
        self.write({
            'fileid': fileid,
            'content_type': content_type,
            'expected_size': expected_size,
        })
        self.finish()


class ProgressDownloadHandler(DownloadHandler):

    def get(self):
        fileid = self.get_argument('fileid')
        expected_size = int(self.redis.get('expectedsize:%s' % fileid))
        destination = self.make_destination(fileid)
        data = {
            'expected': expected_size,
            'left': expected_size,
            'done': 0
        }

        if os.path.isfile(destination):
            size = os.stat(destination)[stat.ST_SIZE]
            data['left'] -= size
            data['done'] = size
        self.write(data)


class ReallyDownloadHandler(DownloadHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        fileid = self.get_argument('fileid')
        url = self.redis.get('fileid:%s' % fileid)
        #assert self.get_secure_cookie('user'), "not logged in"
        http_client = tornado.httpclient.AsyncHTTPClient()
        response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            headers={}
        )
        print "pretending to be slow"
        time.sleep(5)
        print "cracking on"
        if response.code == 200:
            data = response.body

            destination = self.make_destination(fileid)

            with open(destination, 'wb') as f:
                f.write(data)
            #redis.Redis(settings.REDIS_HOST, settings.REDIS_PORT)
            data = {'path': destination, 'ranges': range(1, 6)}
            self.redis.publish(
                'resizer',
                json.dumps(data)
            )
            self.write({'url': '/%s' % fileid})  # reverse_url()
        else:
            self.write({
                'error': "FAILED TO DOWNLOAD\n%s\n%s\n" %
                         (response.code, response.body)
            })
        self.finish()


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
        http_client.fetch(
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


def mkdir(newdir):
    """works the way a good mkdir should :)
        - already exists, silently complete
        - regular file in the way, raise an exception
        - parent directory(ies) does not exist, make them as well
    """
    if os.path.isdir(newdir):
        return
    if os.path.isfile(newdir):
        raise OSError("a file with the same name as the desired "
                      "dir, '%s', already exists." % newdir)
    head, tail = os.path.split(newdir)
    if head and not os.path.isdir(head):
        mkdir(head)
    if tail:
        os.mkdir(newdir)


class TileHandler(BaseHandler):

    def get(self, image, size, zoom, row, col):
        self.set_header('Content-Type', 'image/png')
        size = int(size)
        zoom = int(zoom)
        row = int(row)
        col = int(col)

        if size != 256:
            raise tornado.web.HTTPError(400)

        root = os.path.join(
            self.application.settings['static_path'],
            'uploads'
        )
        if not os.path.isdir(root):
            os.mkdir(root)
        save_root = os.path.join(
            self.application.settings['static_path'],
            'tiles'
        )
        if not os.path.isdir(save_root):
            os.mkdir(save_root)
        path = os.path.join(root, image)
        for i in ('.png', '.jpg'):
            path = os.path.join(root, image + i)
            if os.path.isfile(path):
                break
        else:
            raise tornado.web.HTTPError(404, image)

        width = size * (2 ** zoom)
        save_filepath = save_root
        for p in (image, str(size), str(zoom)):
            save_filepath = os.path.join(save_filepath, p)
            if not os.path.isdir(save_filepath):
                mkdir(save_filepath)
        save_filepath = os.path.join(save_filepath, '%s,%s.png' % (row, col))

        if not os.path.isfile(save_filepath):
            image = scale_and_crop(
                path,
                (width, width),
                row, col,
                zoom=zoom,
                image=image,
            )

            image.save(save_filepath)

        self.write(open(save_filepath, 'rb').read())


_RESIZES = {}
_TIMESTAMPS = {}


def scale_and_crop(path, requested_size, row, col, zoom=None, image=None):
    im = Image.open(path)
    x, y = [float(v) for v in im.size]
    xr, yr = [float(v) for v in requested_size]
    r = min(xr / x, yr / y)

    w, h = int(round(x * r)), int(round(y * r))
    _cache_key = '%s-%s-%s-%s' % (image, zoom, w, h)
    _resized_file = path.replace(
        '.jpg',
        '-%s-%s-%s.jpg' % (zoom, w, h)
    )

    already = _RESIZES.get(_cache_key)
    if already:
        im = already
    else:
        if os.path.isfile(_resized_file):
            print "REUSING", _resized_file
            im = Image.open(_resized_file)
            #print "Assert?", (im.size, (w,h))
        else:
            im = im.resize((w, h),
                           resample=Image.ANTIALIAS)
            print "SAVE RESIZED TO", _resized_file
            im.save(_resized_file)

    _RESIZES[_cache_key] = im
    _TIMESTAMPS[_cache_key] = time.time()

    # to avoid memory bloat of `_RESIZES` getting too large, instead use the
    # `_TIMESTAMPS` dict to keep track of which Image instances are getting old
    _now = time.time()
    for key, timestamp in _TIMESTAMPS.items():
        age = _now - timestamp
        if age > 10:
            del _TIMESTAMPS[key]
            del _RESIZES[key]

    # convert (width, height, x, y) into PIL crop box
    box = (256 * row, 256 * col, 256 * (row + 1), 256 * (col + 1))
    im = im.crop(box)

    return im
