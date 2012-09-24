import os
import json
import stat
import urllib
import uuid
import functools

import tornado.web
import tornado.gen
import tornado.httpclient
from tornado_utils.routes import route
from utils import scale_and_crop, mkdir


class BaseHandler(tornado.web.RequestHandler):

    @property
    def redis(self):
        return self.application.redis


@route('/', name='home')
class HomeHandler(BaseHandler):
    def get(self):
        data = {}
        data['recent_fileids'] = self.redis.lrange('fileids', 0, 4)
        self.render('index.html', **data)


class DropboxHandler(BaseHandler):
    def get(self):
        self.render('dropbox.html')


@route('/(\w{9})', 'image')
class ImageHandler(BaseHandler):
    def get(self, filename):
        image_filename = (
            filename[:1] +
            '/' +
            filename[1:3] +
            '/' +
            filename[3:]
        )
        ranges = [2, 6]
        default_zoom = 3
        self.render(
            'image.html',
            image_filename=image_filename,
            ranges=ranges,
            default_zoom=default_zoom
        )


@route('/upload', 'upload')
class UploadHandler(BaseHandler):

    def get(self):
        #assert self.get_secure_cookie('user'), "not logged in"
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
        #assert self.get_secure_cookie('user'), "not logged in"
        http_client = tornado.httpclient.AsyncHTTPClient()
        head_response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            method='HEAD'
        )
        if not head_response.code == 200:
            self.write({'error': head_response.body})
            return
        # XXX can we find out if this was a image/jpeg or something?
        expected_size = int(head_response.headers['Content-Length'])
        content_type = head_response.headers['Content-Type']
        print "What about content_type", repr(content_type)

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


@route('/upload/progress', 'upload_progress')
class ProgressUploadHandler(UploadHandler):

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


def my_streaming_callback(destination_file, data):
    destination_file.write(data)


@route('/upload/download', 'upload_download')
class DownloadUploadHandler(UploadHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        fileid = self.get_argument('fileid')
        url = self.redis.get('fileid:%s' % fileid)
        #assert self.get_secure_cookie('user'), "not logged in"
        import tornado.curl_httpclient
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
            streaming_callback=functools.partial(my_streaming_callback,
                                                 destination_file)
        )
        destination_file.close()
        if response.code == 200:

            self.redis.lpush('fileids', fileid)
            #data = response.body
            #with open(destination, 'wb') as f:
            #    f.write(data)

            ranges = range(1, 6)
            # since zoom level 3 is the default, make sure that's prepared first
            ranges.remove(3)
            ranges.insert(0, 3)
            data = {'path': destination, 'ranges': ranges}
            self.redis.publish(
                'resizer',
                json.dumps(data)
            )
            self.write({'url': '/%s' % fileid})  # reverse_url()
        else:
            try:
                os.remove(destination)
            except:
                logging.error("Unable to remove %s" % destination, exc_info=True)
            self.write({
                'error': "FAILED TO DOWNLOAD\n%s\n%s\n" %
                         (response.code, response.body)
            })
        self.finish()


@route('/signout/', 'signout')
class SignoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie('user')
        self.redirect('/')


@route('/browserid/', 'browserid')
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


@route(r'/tiles/(?P<image>\w{1}/\w{2}/\w{6})/(?P<size>\d+)'
       r'/(?P<zoom>\d+)/(?P<row>\d+),(?P<col>\d+).png',
       name='tile')
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
