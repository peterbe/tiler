import os
import stat
import urllib
import json
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
from utils import (
mkdir, make_tile, make_tiles, make_thumbnail, delete_image, count_all_tiles)
from optimizer import optimize_images, optimize_thumbnails
from awsuploader import upload_tiles, upload_original
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
        if 'page_on' not in options:
            page_on = self.request.path.split('/')[-1]
            if not page_on:
                page_on = '/'
            options['page_on'] = page_on
        options['PROJECT_TITLE'] = settings.PROJECT_TITLE
        return super(BaseHandler, self).render(template, **options)

    def _get_gravatar_url(self, email):
        d_url = self.static_url('images/anonymous_32.png')
        if d_url.startswith('//'):
            default = '%s:%s' % (self.request.protocol, d_url)
        else:
            default = '%s://%s%s' % (self.request.protocol,
                                     self.request.host,
                                     d_url)
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

    def static_url(self, path, **kwargs):
        if self.application.settings['embed_static_url_timestamp']:
            ui_module = self.application.ui_modules['StaticURL'](self)
            try:
                return ui_module.render(path, **kwargs)
            except OSError:
                logging.debug("%r does not exist" % path)
        return super(BaseHandler, self).static_url(path)

    def get_cdn_prefix(self):
        """return something that can be put in front of the static filename
        E.g. if filename is '/static/image.png' and you return
        '//cloudfront.com' then final URL presented in the template becomes
        '//cloudfront.com/static/image.png'
        """
        return self.application.settings.get('cdn_prefix')



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
            if len(row) == 3:
                data['recent_images_rows'].append(row)
                row = []
        if row:
            data['recent_images_rows'].append(row)
        self.render('index.html', **data)


@route('/(\w{9})', 'image')
class ImageHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
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

        metadata_key = 'metadata:%s' % fileid
        metadata = self.redis.get(metadata_key)
        #metadata=None;self.redis.delete('uploading:%s' % fileid)

        if metadata and 'width' not in metadata:
            # legacy
            metadata = None

        if metadata is not None:
            metadata = json.loads(metadata)
            content_type = metadata['content_type']
            owner = metadata['owner']
            title = metadata['title']
            age = metadata['age']
            width = metadata['width']
            cdn_domain = metadata.get('cdn_domain')
        else:
            logging.info("Meta data cache miss (%s)" % fileid)
            document = yield motor.Op(
                self.db.images.find_one,
                {'fileid': fileid}
            )
            if not document:
                raise tornado.web.HTTPError(404, "File not found")

            content_type = document['contenttype']
            owner = document['user']
            title = document.get('title', '')
            width = document['width']
            cdn_domain = document.get('cdn_domain', None)
            # datetime.timedelta.total_seconds() is only in py2.6
            #age = int((datetime.datetime.utcnow() -
            #           document['date']).total_seconds())
            _diff = datetime.datetime.utcnow() - document['date']
            age = _diff.days * 60 * 60 * 24 + _diff.seconds
            #age+=4000

            metadata = {
                'content_type': content_type,
                'owner': owner,
                'title': title,
                'age': age,
                'width': width,
                'cdn_domain': cdn_domain,
            }
            self.redis.setex(
                metadata_key,
                json.dumps(metadata),
                60 * 60 * 24
            )

        ranges = []
        _range = self.DEFAULT_RANGE_MIN
        while True:
            ranges.append(_range)
            range_width = 256 * (2 ** _range)
            if range_width > width or _range >= self.DEFAULT_RANGE_MAX:
                break
            _range += 1

        can_edit = self.get_current_user() == owner

        if content_type == 'image/jpeg':
            extension = 'jpg'
        elif content_type == 'image/png':
            extension = 'png'
        else:
            print "Guessing extension :("
            extension = self.DEFAULT_EXTENSION
        extension = self.get_argument('extension', extension)
        assert extension in ('png', 'jpg'), extension

        if age > 60 and not cdn_domain:
            # it might be time to upload this to S3
            lock_key = 'uploading:%s' % fileid
            if not self.redis.get(lock_key):
                # we're ready to upload it
                _no_tiles =  count_all_tiles(
                    fileid,
                    self.application.settings['static_path']
                )
                self.redis.setex(lock_key, 1, 60 * 60 * 24)
                priority = self.application.settings['debug'] and 'default' or 'low'
                q = Queue(priority, connection=self.redis)
                logging.info("About to upload %s tiles" % _no_tiles)
                # bulk the queue workers with 100 each
                for i in range(_no_tiles / 100 + 1):
                    q.enqueue(
                        upload_tiles,
                        fileid,
                        self.application.settings['static_path'],
                        max_count=100
                    )

                # upload the original
                q.enqueue(
                    upload_original,
                    fileid,
                    extension,
                    self.application.settings['static_path'],
                    settings.ORIGINALS_BUCKET_ID
                )

        self.render(
            'image.html',
            page_title=title or '/%s' % fileid,
            image_filename=image_filename,
            ranges=ranges,
            default_zoom=default_zoom,
            extension=extension,
            can_edit=can_edit,
            age=age,
            prefix=cdn_domain and '//' + cdn_domain or '',
        )


@route('/(\w{9})/metadata', 'image_metadata')
class ImageMetadataHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        data = {
            'title': document.get('title'),
            'description': document.get('description'),
        }
        self.write(data)
        self.finish()


@route('/(\w{9})/edit', 'image_edit')
class ImageEditHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self, fileid):
        current_user = self.get_current_user()
        if not current_user:
            raise tornado.web.HTTPError(403, "Not logged in")

        title = self.get_argument('title', u'')
        description = self.get_argument('description', u'')
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if document['user'] != current_user:
            raise tornado.web.HTTPError(403, "Not yours to edit")

        data = {
            'title': title,
            'description': description
        }
        yield motor.Op(
            self.db.images.update,
            {'_id': document['_id']},
            {'$set': data}
        )

        metadata_key = 'metadata:%s' % fileid
        self.redis.delete(metadata_key)

        self.write(data)
        self.finish()


@route('/(\w{9})/delete', 'image_delete')
class ImageDeleteHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self, fileid):
        current_user = self.get_current_user()
        if not current_user:
            raise tornado.web.HTTPError(403, "Not logged in")
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if document['user'] != current_user:
            raise tornado.web.HTTPError(403, "Not yours to edit")

        yield motor.Op(
            self.db.images.remove,
            {'_id': document['_id']}
        )
        metadata_key = 'metadata:%s' % fileid
        self.redis.delete(metadata_key)

        priority = self.application.settings['debug'] and 'default' or 'low'
        q = Queue(priority, connection=self.redis)
        image_split = (
            fileid[:1] +
            '/' +
            fileid[1:3] +
            '/' +
            fileid[3:]
        )
        q.enqueue(
            delete_image,
            image_split,
            self.application.settings['static_path']
        )

        self.write("Deleted")
        self.finish()

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
            self.finish()
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
                if content_type == 'text/html':
                    self.write({'error': "URL not an image. It's a web page"})
                    self.finish()
                    return
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
            width = size[0]

            image_split = fileid[:1] + '/' + fileid[1:3] + '/' + fileid[3:]

            if self.application.settings['debug']:
                q_high = Queue('default', connection=self.redis)
                q_default = Queue('default', connection=self.redis)
                q_low = Queue('default', connection=self.redis)
            else:
                q_high = Queue('high', connection=self.redis)
                q_default = Queue('default', connection=self.redis)
                q_low = Queue('default', connection=self.redis)

            ranges = []
            _range = self.DEFAULT_RANGE_MIN
            while True:
                ranges.append(_range)
                range_width = 256 * (2 ** _range)
                if range_width > width or _range >= self.DEFAULT_RANGE_MAX:
                    break
                _range += 1

            # since zoom level 3 is the default, make sure that's
            # prepared first
            ranges.remove(self.DEFAULT_ZOOM)
            ranges.insert(0, self.DEFAULT_ZOOM)
            extension = destination.split('.')[-1]

            # The priority is important because the first impression is
            # important.
            # So...
            #  1. make resize for default zoom level
            #  2. load all tiles for default zoom level
            #  3. make resize for all other zoom levels
            #  4. make tiles for all other zoom levels
            #  5. make the thumbnail(s)
            #  6. optimize all created tiles

            for second in range(2):
                first = not second

                for zoom in ranges:
                    if ((first and zoom == self.DEFAULT_ZOOM) or
                        (second and zoom != self.DEFAULT_ZOOM)):
                        q_high.enqueue(make_resize, destination, zoom)

                for zoom in ranges:
                    if ((first and zoom == self.DEFAULT_ZOOM) or
                        (second and zoom != self.DEFAULT_ZOOM)):
                        width = 256 * (2 ** zoom)
                        cols = rows = width / 256
                        q_default.enqueue(
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
            q_high.enqueue(
                make_thumbnail,
                image_split,
                100,
                'png',
                self.application.settings['static_path']
            )

            # pause for 2 seconds just to be sure enough images have been
            # created before we start optimizing
            ioloop_instance = tornado.ioloop.IOLoop.instance()
            yield tornado.gen.Task(
                ioloop_instance.add_timeout,
                time.time() + 2
            )

            # once that's queued up we can start optimizing
            for zoom in ranges:
                q_low.enqueue(
                    optimize_images,
                    image_split,
                    zoom,
                    extension,
                    self.application.settings['static_path']
                )

            # lastly, optimize the thumbnail too
            q_low.enqueue(
                optimize_thumbnails,
                image_split,
                'png',
                self.application.settings['static_path']
            )

            self.write({
                'url': self.reverse_url('image', fileid),
            })
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
    """Tiles are supposed to be created with a queue. This handler is a
    fallback for when tiles weren't created by queue.
    So if this is called and needed perhaps not all tiles were uploaded
    to S3.
    """

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
            self.set_header(
                'Cache-Control',
                'max-age=%d, public' % (60 * 60 * 24)
            )
            self.write(open(save_filepath, 'rb').read())
            priority = self.application.settings['debug'] and 'default' or 'low'
            fileid = image.replace('/', '')
            q = Queue(priority, connection=self.redis)
            q.enqueue(
                upload_tiles,
                fileid,
                self.application.settings['static_path'],
                max_count=10,
                only_if_no_cdn_domain=True
            )
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
        delay = 0.1
        thumbnail_filepath = None
        while True:
            yield tornado.gen.Task(
                ioloop_instance.add_timeout,
                time.time() + delay
            )
            delay *= 2
            if job.result is not None:
                thumbnail_filepath = job.result
                break
            elif delay > 2:
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
                'file_broken.png'
            )
        else:
            self.set_header(
                'Cache-Control',
                'max-age=%d, public' % (60 * 60 * 24)
            )
        self.write(open(thumbnail_filepath, 'rb').read())
        self.finish()


@route(r'/preload-urls/(?P<fileid>\w{9})', 'preload-urls')
class PreloadURLsHandler(BaseHandler):

    def get(self, fileid):
        root = self.application.settings['static_path']
        path = os.path.join(root, 'tiles')
        image_filename = (
            fileid[:1] +
            '/' +
            fileid[1:3] +
            '/' +
            fileid[3:]
        )
        path = os.path.join(path, image_filename)
        path = os.path.join(path, '256', str(self.DEFAULT_ZOOM))

        urls = []
        if os.path.isdir(path):
            for f in os.listdir(path):
                urls.append(os.path.join(path, f).replace(
                    self.application.settings['static_path'],
                    ''
                ))

        self.write({'urls': urls})

@route(r'/about', 'about')
class AboutHandler(BaseHandler):

    def get(self):
        self.render('about.html')


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
