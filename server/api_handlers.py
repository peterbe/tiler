import uuid
import tornado.web
import tornado.gen
from tornado_utils.routes import route
from handlers import (
    BaseHandler,
    PreviewMixin,
    DownloadMixin,
    TileMakerMixin,
    ProgressMixin,
    ImageMetadataMixin
)


class APIKeyMixin(object):

    def generate_new_key(self):
        return uuid.uuid4().hex

    def set_new_key(self, user):
        your_key = self.generate_new_key()
        self.redis.hset('api:users', your_key, user)
        self.redis.hset('api:keys', user, your_key)
        return your_key

    def get_key(self, user):
        return self.redis.hget('api:keys', user)

    def get_user(self, key):
        return self.redis.hget('api:users', key)


@route('/api/$', name='api')
class APIHandler(BaseHandler, APIKeyMixin):

    def get(self):
        user = self.get_current_user()
        if user:
            your_key = self.get_key(user)
            if your_key is None:
                your_key = self.new_key(user)
        else:
            your_key = None

        base_url = (
            '%s://%s' %
            (self.request.protocol, self.request.host)
        )
        data = {
            'your_key': your_key,
            'base_url': base_url,
        }
        self.render('api.html', **data)


class APIBaseHandler(BaseHandler, APIKeyMixin):

    def check_xsrf_cookie(self):
        pass

    def get_error_html(self, status_code, **kwargs):
        exception = kwargs['exception']
        return {'code': status_code, 'error': exception.log_message}


@route('/api/upload$', name='api_upload')
class APIUploadHandler(APIBaseHandler,
                       PreviewMixin,
                       DownloadMixin,
                       APIKeyMixin,
                       TileMakerMixin):

    def get_current_user(self):
        return self.user

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        url = self.get_argument('url')
        key = self.get_argument('key')
        self.user = self.get_user(key)
        if not self.user:
            raise tornado.web.HTTPError(403, "Key not recognized")
        response = yield tornado.gen.Task(self.run_preview, url)
        if 'error' in response:
            self.write(response)
        else:
            fileid = response['fileid']
            second_response = yield tornado.gen.Task(
                self.run_download,
                fileid,
                add_delay=False,
            )
            #print "\tSECOND_RESPONSE", second_response
            if 'error' in second_response:
                self.write(second_response)
            else:
                self.write(response)
        self.finish()


@route('/api/upload/(?P<fileid>\w{9})$', name='api_upload_progress')
class APIUploadProgressHandler(APIBaseHandler, ProgressMixin):

    def get(self, fileid):
        content_type = self.redis.get('contenttype:%s' % fileid)
        if content_type is None:
            raise tornado.web.HTTPError(
                410,
                'Elvis has already left the building'
            )
        expected_size = self.redis.get('expectedsize:%s' % fileid)

        data = self.get_progress(fileid, content_type=content_type)
        # data will only contain `done` to say how much has been saved,
        # let's make it a bit richer
        if expected_size is not None:
            data['left'] = int(expected_size) - data['done']
            data['percentage'] = (
                round(100.0 * data['done'] / int(expected_size), 1)
            )

        sizeinfo = self.redis.get('sizeinfo:%s' % fileid)
        if sizeinfo is not None:
            sizeinfo = tornado.escape.json_decode(sizeinfo)
            for key in ('width', 'height'):
                if key in sizeinfo:
                    data[key] = sizeinfo[key]
            base_url = (
                '%s://%s' %
                (self.request.protocol, self.request.host)
            )
            data['url'] = base_url + self.reverse_url('image', fileid)
        self.write(data)


@route('/api/(?P<fileid>\w{9})$', name='api_image')
class APIImageHandler(APIBaseHandler, ImageMetadataMixin):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def put(self, fileid):
        key = self.get_argument('key')
        self.user = self.get_user(key)
        if not self.user:
            raise tornado.web.HTTPError(403, "Key not recognized")

        data = yield tornado.gen.Task(
            self.run_edit,
            fileid,
            self.user
        )
        self.write(data)
        self.finish()
