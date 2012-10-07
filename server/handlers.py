import os
import stat
import urllib
import uuid
import functools
import logging
import hashlib
import time
import datetime
from pprint import pprint

import tornado.web
import tornado.gen
import tornado.httpclient
import tornado.curl_httpclient
import tornado.ioloop
from PIL import Image
from tornado_utils.routes import route
from rq import Queue
import motor
from utils import mkdir, make_tile, make_tiles, make_thumbnail
from optimizer import optimize_images
from resizer import make_resize
import settings


def sample_queue_job():
    # used to check that the queue workers are awake
    return "OK"


class BaseHandler(tornado.web.RequestHandler):

    DEFAULT_RANGE_MIN = 2
    DEFAULT_RANGE_MAX = 5
    DEFAULT_ZOOM = 3
    DEFAULT_EXTENSION = 'png'

    @property
    def redis(self):
        return self.application.redis

    @property
    def db(self):
        return self.application.db

    @property
    def queue(self):
        return self.application.queue

    def get_current_user(self):
        return self.get_secure_cookie('user')

    def render(self, template, **options):
        options['user'] = self.get_current_user()
        options['debug'] = self.application.settings['debug']
        if options['user']:
            options['gravatar_url'] = self._get_gravatar_url(options['user'])
        return super(BaseHandler, self).render(template, **options)

    def _get_gravatar_url(self, email):
        base_url = '%s://%s' % (self.request.protocol, self.request.host)
        default = base_url + self.static_url('images/anonymous_32.png')
        size = 32

        # construct the url
        gravatar_url = (
            "http://www.gravatar.com/avatar/" +
            hashlib.md5(email.lower()).hexdigest() +
            "?" +
            urllib.urlencode({
                'd': default,
                's': str(size)
            })
        )

        return gravatar_url


@route('/', name='home')
class HomeHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self):
        data = {}
        data['recent_images_rows'] = []
        cursor = self.db.images.find().sort([('date', -1)]).limit(12)
        image = yield motor.Op(cursor.next_object)
        row = []
        while image:
            row.append(image)
            image = yield motor.Op(cursor.next_object)
            if len(row) == 4:
                data['recent_images_rows'].append(row)
                row = []
        if row:
            data['recent_images_rows'].append(row)
        self.render('index.html', **data)


@route('/(\w{9})', 'image')
class ImageHandler(BaseHandler):
    def get(self, fileid):
        image_filename = (
            fileid[:1] +
            '/' +
            fileid[1:3] +
            '/' +
            fileid[3:]
        )
        # we might want to read from a database what the most
        # appropriate numbers should be here.
        ranges = [self.DEFAULT_RANGE_MIN, self.DEFAULT_RANGE_MAX]
        default_zoom = self.DEFAULT_ZOOM
        content_type = self.redis.get('contenttype:%s' % fileid)
        if content_type == 'image/jpeg':
            extension = 'jpg'
        elif content_type == 'image/png':
            extension = 'png'
        else:
            extension = self.DEFAULT_EXTENSION
        extension = self.get_argument('extension', extension)
        assert extension in ('png', 'jpg'), extension
        self.render(
            'image.html',
            page_title='/%s' % fileid,
            image_filename=image_filename,
            ranges=ranges,
            default_zoom=default_zoom,
            extension=extension,
        )


@route('/upload', 'upload')
class UploadHandler(BaseHandler):

    def get(self):
        self.render('upload.html')

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
        # so far, it's the directory
        mkdir(destination)
        # this is the full file path
        destination += '/%s' % fileid[3:]
        content_type = self.redis.get('contenttype:%s' % fileid)
        # complete it with the extension
        if content_type == 'image/png':
            destination += '.png'
        else:
            assert content_type == 'image/jpeg', content_type
            destination += '.jpg'

        return destination


@route('/upload/preview', 'upload_preview')
class PreviewUploadHandler(UploadHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        url = self.get_argument('url')
        if not self.get_current_user():
            raise tornado.web.HTTPError(403, "You must be logged in")
        http_client = tornado.httpclient.AsyncHTTPClient()
        head_response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            method='HEAD'
        )
        if not head_response.code == 200:
            self.write({'error': head_response.body})
            return
        content_type = head_response.headers['Content-Type']
        if content_type not in ('image/jpeg', 'image/png'):
            if ((url.lower().endswith('.jpg') or url.lower().endswith('.png'))
                and head_response.headers.get('Content-Length')):
                logging.warning("Possibly not an image")

                if url.lower().endswith('.jpg'):
                    content_type = 'image/jpeg'
                elif url.lower().endswith('.png'):
                    content_type = 'image/png'
                else:
                    content_type = 'unknown'
            else:
                raise tornado.web.HTTPError(
                    400,
                    "Unrecognized content type '%s'" % content_type
                )
        try:
            expected_size = int(head_response.headers['Content-Length'])
        except KeyError:
            # sometimes images don't have a Content-Length but still work
            logging.warning("No Content-Length (content-encoding:%r)" %
                            head_response.headers.get('Content-Encoding', ''))
            expected_size = 0

        fileid = uuid.uuid4().hex[:9]
        document = {
            'fileid': fileid,
            'source': url,
            'date': datetime.datetime.utcnow()
        }
        document['user'] = self.get_current_user()
        self.redis.setex(
            'contenttype:%s' % fileid,
            content_type,
            60 * 60
        )
        document['contenttype'] = content_type
        self.redis.setex(
            'expectedsize:%s' % fileid,
            expected_size,
            60 * 60
        )
        if expected_size:
            document['size'] = expected_size
        yield motor.Op(self.db.images.insert, document, safe=False)
        #print repr(result), type(result)
        #print "Result", repr(result)
        #print dir(result)
        self.write({
            'fileid': fileid,
            'content_type': content_type,
            'expected_size': expected_size,
        })
        self.finish()


@route('/upload/progress', 'upload_progress')
class ProgressUploadHandler(UploadHandler):

    def get(self):
        if not self.get_current_user():
            raise tornado.web.HTTPError(403, "You must be logged in")
        fileid = self.get_argument('fileid')
        destination = self.make_destination(fileid)
        data = {
            'done': 0
        }

        if os.path.isfile(destination):
            size = os.stat(destination)[stat.ST_SIZE]
            data['done'] = size
        self.write(data)


def my_streaming_callback(destination_file, data):
    destination_file.write(data)


@route('/upload/download', 'upload_download')
class DownloadUploadHandler(UploadHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        if not self.get_current_user():
            raise tornado.web.HTTPError(403, "You must be logged in")
        fileid = self.get_argument('fileid')
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        url = document['source']
        tornado.httpclient.AsyncHTTPClient.configure(
            tornado.curl_httpclient.CurlAsyncHTTPClient
        )
        http_client = tornado.httpclient.AsyncHTTPClient()
        destination = self.make_destination(fileid)
        destination_file = open(destination, 'wb')
        response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            headers={},
            request_timeout=200.0,  # 20.0 is the default
            streaming_callback=functools.partial(my_streaming_callback,
                                                 destination_file)
        )
        destination_file.close()
        if response.code == 200:
            size = Image.open(destination).size
            yield motor.Op(
                self.db.images.update,
                {'_id': document['_id']},
                {'$set': {'width': size[0], 'height': size[1]}}
            )

            image_split = fileid[:1] + '/' + fileid[1:3] + '/' + fileid[3:]
            q = Queue(connection=self.redis)

            ranges = range(
                self.DEFAULT_RANGE_MIN,
                self.DEFAULT_RANGE_MAX + 1
            )
            # since zoom level 3 is the default, make sure that's
            # prepared first
            ranges.remove(self.DEFAULT_ZOOM)
            ranges.insert(0, self.DEFAULT_ZOOM)
            for zoom in ranges:
                q.enqueue(make_resize, destination, zoom)

            extension = destination.split('.')[-1]
            for zoom in ranges:
                width = 256 * (2 ** zoom)
                cols = rows = width / 256
                q.enqueue(
                    make_tiles,
                    image_split,
                    256,
                    zoom,
                    rows,
                    cols,
                    extension,
                    self.application.settings['static_path']
                )

            # it's important to know how the thumbnail needs to be generated
            # and it's important to do the thumbnail soon since otherwise
            # it might severly delay the home page where the thumbnail is shown
            q.enqueue(
                make_thumbnail,
                image_split,
                100,
                'png',
                self.application.settings['static_path']
            )

            # once that's queued up we can start optimizing
            for zoom in ranges:
                q.enqueue(
                    optimize_images,
                    image_split,
                    zoom,
                    extension,
                    self.application.settings['static_path']
                )

            self.write({'url': '/%s' % fileid})  # reverse_url()
        else:
            try:
                os.remove(destination)
            except:
                logging.error("Unable to remove %s" % destination,
                              exc_info=True)
            self.write({
                'error': "FAILED TO DOWNLOAD\n%s\n%s\n" %
                         (response.code, response.body)
            })
        self.finish()


@route('/auth/signout/', 'signout')
class SignoutHandler(BaseHandler):
    def get(self):
        self.write("Must use POST")

    def post(self):
        self.clear_cookie('user')
        self.redirect('/')


@route('/auth/browserid/', 'browserid')
class BrowserIDAuthLoginHandler(BaseHandler):

    def check_xsrf_cookie(self):
        pass

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        assertion = self.get_argument('assertion')
        http_client = tornado.httpclient.AsyncHTTPClient()
        url = 'https://browserid.org/verify'
        data = {
            'assertion': assertion,
            'audience': settings.BROWSERID_DOMAIN,
        }
        response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            method='POST',
            body=urllib.urlencode(data),
        )
        if 'email' in response.body:
            # all is well
            struct = tornado.escape.json_decode(response.body)
            assert struct['email']
            email = struct['email']
            self.set_secure_cookie('user', email, expires_days=90)
        else:
            struct = {'error': 'Email could not be verified'}
        self.write(struct)
        self.finish()


@route(r'/tiles/(?P<image>\w{1}/\w{2}/\w{6})/(?P<size>\d+)'
       r'/(?P<zoom>\d+)/(?P<row>\d+),(?P<col>\d+)'
       r'.(?P<extension>jpg|png)',
       name='tile')
class TileHandler(BaseHandler):

    def get(self, image, size, zoom, row, col, extension):
        if extension == 'png':
            self.set_header('Content-Type', 'image/png')
        else:
            self.set_header('Content-Type', 'image/jpeg')
        size = int(size)
        if size != 256:
            raise tornado.web.HTTPError(400, 'size must be 256')

        try:
            save_filepath = make_tile(image, size, zoom, row, col, extension,
                                      self.application.settings['static_path'])
        except IOError, msg:
            raise tornado.web.HTTPError(404, msg)
        try:
            self.write(open(save_filepath, 'rb').read())
        except IOError:
            self.set_header('Content-Type', 'image/png')
            broken_filepath = os.path.join(
                self.application.settings['static_path'],
                'images',
                'broken.png'
            )
            self.write(open(broken_filepath, 'rb').read())


@route(r'/thumbnails/(?P<image>\w{1}/\w{2}/\w{6})/(?P<width>\w{1,3})'
       r'.(?P<extension>png|jpg)',
       name='thumbail')
class ThumbnailHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, image, width, extension):
        width = int(width)
        assert width > 0 and width < 1000, width

        # stick it on a queue
        q = Queue(connection=self.redis)

        job = q.enqueue(
            make_thumbnail,
            image,
            width,
            extension,
            self.application.settings['static_path']
        )
        ioloop_instance = tornado.ioloop.IOLoop.instance()
        while True:
            yield tornado.gen.Task(
                ioloop_instance.add_timeout,
                time.time() + 1
            )
            if job.result is not None:
                thumbnail_filepath = job.result
                break

        if extension == 'png':
            self.set_header('Content-Type', 'image/png')
        elif extension == 'jpg':
            self.set_header('Content-Type', 'image/jpeg')
        else:
            raise ValueError(extension)

        if not thumbnail_filepath:
            self.set_header('Content-Type', 'image/png')
            thumbnail_filepath = os.path.join(
                self.application.settings['static_path'],
                'images',
                'broken.png'
            )
        self.write(open(thumbnail_filepath, 'rb').read())
        self.finish()


# this handler gets automatically appended last to all handlers inside app.py
class PageNotFoundHandler(BaseHandler):

    def get(self):
        path = self.request.path
        page = path[1:]
        if page.endswith('/'):
            page = page[:-1]
        page = page.split('/')[-1]
        if not path.endswith('/'):
            new_url = '%s/' % path
            if self.request.query:
                new_url += '?%s' % self.request.query
            self.redirect(new_url)
            return
        raise tornado.web.HTTPError(404, path)
