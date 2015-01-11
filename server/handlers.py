import os
import stat
import urllib
import json
import uuid
import random
import logging
import hashlib
import time
import datetime
from pprint import pprint

import premailer
from bson.objectid import ObjectId
import tornado.web
import tornado.gen
import tornado.escape
import tornado.httpclient
import tornado.curl_httpclient
import tornado.ioloop
from PIL import Image
from tornado_utils.routes import route
from tornado_utils.timesince import smartertimesince as _smartertimesince
from rq import Queue
import motor
from utils import (
    mkdir, make_tile, make_tiles, make_thumbnail, delete_image,
    count_all_tiles
)
from optimizer import optimize_images, optimize_thumbnails
from awsuploader import upload_tiles, upload_original
from resizer import make_resize
from emailer import send_url, send_feedback
from downloader import download
import settings


def smartertimesince(d, now=None):
    if isinstance(d, (int, float)):
        d = datetime.datetime.utcnow() - datetime.timedelta(seconds=d)
    return _smartertimesince(d, now=now)


def sample_queue_job():
    # used to check that the queue workers are awake
    return "OK"


class BaseHandler(tornado.web.RequestHandler):

    DEFAULT_RANGE_MIN = 2
    DEFAULT_RANGE_MAX = 5
    DEFAULT_ZOOM = 3
    DEFAULT_LAT = 70.0
    DEFAULT_LNG = 00.0
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

            default = '%s%s' % (self.base_url, d_url)
        # nasty hack so that gravatar can serve a default
        # icon when on a local URL
        default = default.replace('http://tiler/', 'http://hugepic.io/')

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

    def reverse_url(self, name, *args, **kwargs):
        """Alias for `Application.reverse_url`."""
        url = super(BaseHandler, self).reverse_url(name, *args)
        if kwargs.get('absolute'):
            url = self.base_url + url
        return url

    def get_cdn_prefix(self):
        """return something that can be put in front of the static filename
        E.g. if filename is '/static/image.png' and you return
        '//cloudfront.com' then final URL presented in the template becomes
        '//cloudfront.com/static/image.png'
        """
        return self.application.settings.get('cdn_prefix')

    def make_thumbnail_url(self, fileid, width, extension='png',
                           absolute_url=False,
                           use_cdn=True):
        url = '/thumbnails/%s/%s/%s/%s.%s' % (
            fileid[:1],
            fileid[1:3],
            fileid[3:],
            width,
            extension
        )
        cdn_prefix = self.get_cdn_prefix()
        if cdn_prefix and use_cdn:
            url = cdn_prefix + url
        elif absolute_url:
            url = '%s%s' % (self.base_url, url)
        return url

    def clear_thumbnail_grid_cache(self):
        logging.warning('clear_thumbnail_grid_cache is deprecated')
        cache_keys_key = 'thumbnail_grid:keys'
        for key in self.redis.lrange(cache_keys_key, 0, -1):
            self.redis.delete(key)
        self.redis.delete(cache_keys_key)

    def remember_thumbnail_grid_cache_key(self, key):
        logging.warning('remember_thumbnail_grid_cache_key is deprecated')
        cache_keys_key = 'thumbnail_grid:keys'
        self.redis.lpush(cache_keys_key, key)

    def get_extra_rows_cols(self, zoom):
        if zoom == 2:
            return 0
        return 1  # default

    def make_destination(self, fileid, content_type=None):
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
        if content_type is None:
            content_type = self.redis.get('contenttype:%s' % fileid)
        # complete it with the extension

        if content_type == 'image/png':
            destination += '.png'
        else:
            assert content_type == 'image/jpeg', content_type
            destination += '.jpg'

        return destination

    @property
    def base_url(self):
        return '%s://%s' % (self.request.protocol, self.request.host)


class ThumbnailGridRendererMixin(object):

    @tornado.gen.engine
    def render_thumbnail_grid(self, search, page, page_size, callback):
        data = {
            'recent_images_rows': [],
        }
        skip = page_size * (page - 1)
        cursor = (
            self.db.images.find(search)
            .sort([('date', -1)])
            .limit(page_size)
            .skip(skip)
        )
        #image = yield motor.Op(cursor.next_object)
        row = []
        count = 0
        while (yield cursor.fetch_next):
            image = cursor.next_object()
            if image.get('width') and image.get('featured', True):
                row.append(image)
            elif not image.get('width'):
                print image

            count += 1
            #image = yield motor.Op(cursor.next_object)

            if len(row) == 3:
                data['recent_images_rows'].append(row)
                row = []
        if row:
            data['recent_images_rows'].append(row)

        callback((self.render_string('_thumbnail_grid.html', **data), count))


@route('/', name='home')
class HomeHandler(BaseHandler, ThumbnailGridRendererMixin):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self):
        data = {
            'yours': False
        }

        then = (
            datetime.datetime.utcnow() -
            datetime.timedelta(seconds=60 * 5)
        )
        search = {
            'date': {'$lt': then},
            'featured': True
        }

        if self.get_argument('user', None):
            search['user'] = self.get_argument('user')
            data['yours'] = True
        page = int(self.get_argument('page', 1))

        total_count = yield motor.Op(self.db.images.find(search).count)

        page_size = 15
        t0 = time.time()
        thumbnail_grid, count = yield tornado.gen.Task(
            self.render_thumbnail_grid,
            search, page, page_size
        )
        t1 = time.time()
        logging.debug('%s seconds to render thumbnail grid', t1 - t0)
        data['thumbnail_grid'] = thumbnail_grid

        pagination = None
        if total_count > count:
            # pagination in order!
            pagination = {
                'current_page': page,
                'range': range(1, total_count / page_size + 2)
            }
            if (page - 1) * page_size > 0:
                pagination['prev'] = page - 1
            if page * page_size < total_count:
                pagination['next'] = page + 1

        data['pagination'] = pagination
        data['show_hero_unit'] = self.get_argument('page', None) is None
        data['total_count'] = total_count
        if total_count:
            _cache_key = 'totalstats'
            value = self.redis.get(_cache_key)
            if value:
                stats = tornado.escape.json_decode(value)
            else:
                fileids = yield tornado.gen.Task(
                    self.get_all_fileids,
                    user=self.get_argument('user', None)
                )
                stats = self.get_stats_by_fileids(
                    fileids,
                    user=self.get_argument('user', None)
                )
                self.redis.setex(
                    _cache_key,
                    tornado.escape.json_encode(stats),
                    60
                )
            data['total_bytes_served'] = stats['total_bytes_served']
            data['total_hits'] = stats['total_hits']
            data['total_hits_this_month'] = stats['total_hits_this_month']

        data['featured_past'] = yield tornado.gen.Task(
            self.get_featured_past
        )

        self.render('index.html', **data)

    @tornado.gen.engine
    def get_featured_past(self, callback):
        cache_key = 'featured_past'
        fileid = self.redis.get(cache_key)
        if fileid is None:
            then = datetime.datetime.utcnow() - datetime.timedelta(days=30)
            search = {'title': {'$exists': True},
                      'date': {'$lt': then}}
            total_count = yield motor.Op(self.db.images.find(search).count)
            cursor = (
                self.db.images.find(search)
                .sort([('date', -1)])
                .limit(1)
                .skip(random.randint(0, total_count - 1))
            )
            (yield cursor.fetch_next)
            featured_past = cursor.next_object()
            fileid = featured_past['fileid']
            self.redis.setex(cache_key, fileid, 60 * 60)
        else:
            featured_past = yield motor.Op(
                self.db.images.find_one,
                {'fileid': fileid}
            )
        callback(featured_past)

    def get_stats_by_fileids(self, fileids, user=None):
        total_hits = total_hits_this_month = total_bytes_served = 0

        _now = datetime.datetime.utcnow()
        for fileid in fileids:
            hit_key = 'hits:%s' % fileid
            hit_month_key = (
                'hits:%s:%s:%s' %
                (_now.year, _now.month, fileid)
            )
            hits = self.redis.get(hit_key)
            if hits:
                total_hits += int(hits)
            hits = self.redis.get(hit_month_key)
            if hits:
                total_hits_this_month += int(hits)
            served = self.redis.hget('bytes_served', fileid)
            if served is not None:
                total_bytes_served += int(served)

        return {
            'total_hits': total_hits,
            'total_hits_this_month': total_hits_this_month,
            'total_bytes_served': total_bytes_served,
        }

    @tornado.gen.engine
    def get_all_fileids(self, callback, user=None):
        cache_key = 'allfileids'
        if user:
            cache_key += ':%s' % user
        fileids = self.redis.lrange(cache_key, 0, -1)
        if not fileids:
            # cache miss
            fileids = []  # in case it was None
            search = {}
            if user:
                search['user'] = user
            cursor = self.db.images.find(search, ('fileid',))
            #image = yield motor.Op(cursor.next_object)
            while (yield cursor.fetch_next):
                image = cursor.next_object()
                self.redis.lpush(cache_key, image['fileid'])
                fileids.append(image['fileid'])
                #image = yield motor.Op(cursor.next_object)
        callback(fileids)


@route('/(\w{9})', 'image')
class ImageHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid, zoom=None, lat=None, lng=None):
        image_filename = (
            fileid[:1] +
            '/' +
            fileid[1:3] +
            '/' +
            fileid[3:]
        )
        embedded = int(self.get_argument('embedded', 0))
        hide_annotations = int(
            self.get_argument('hide_annotations', embedded)
        )
        hide_download_counter = int(
            self.get_argument('hide_download_counter', embedded)
        )
        # we might want to read from a database what the most
        # appropriate numbers should be here.
        ranges = [self.DEFAULT_RANGE_MIN, self.DEFAULT_RANGE_MAX]
        default_zoom = self.DEFAULT_ZOOM
        if self.get_argument('zoom', zoom):
            try:
                default_zoom = int(self.get_argument('zoom', zoom))
                if default_zoom < ranges[0]:
                    raise ValueError
                if default_zoom > ranges[-1]:
                    raise ValueError
            except ValueError:
                self.write('Invalid zoom')
                self.finish()
                return

        metadata_key = 'metadata:%s' % fileid
        metadata = self.redis.get(metadata_key)
        #metadata=None;self.redis.delete('uploading:%s' % fileid)

        if metadata and 'description' not in metadata:
            # legacy
            metadata = None
        if metadata and 'width' not in metadata:
            # legacy (old)
            metadata = None
        if metadata and 'date_timestamp' not in metadata:
            # legacy (old)
            metadata = None

        if metadata is not None:
            metadata = json.loads(metadata)
            content_type = metadata['content_type']
            owner = metadata['owner']
            title = metadata['title']
            description = metadata['description']
            date_timestamp = metadata['date_timestamp']
            width = metadata['width']
            cdn_domain = metadata.get('cdn_domain')
            wrap = metadata.get('wrap', False)

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
            description = document.get('description', '')
            width = document['width']
            cdn_domain = document.get('cdn_domain', None)
            date_timestamp = time.mktime(document['date'].timetuple())
            wrap = document.get('wrap', False)

            metadata = {
                'content_type': content_type,
                'owner': owner,
                'title': title,
                'description': description,
                'date_timestamp': date_timestamp,
                'width': width,
                'cdn_domain': cdn_domain,
                'wrap': wrap,
            }
            if document.get('ranges'):
                metadata['ranges'] = document['ranges']
            self.redis.setex(
                metadata_key,
                json.dumps(metadata),
                60 * 60  # * 24
            )
        no_wrap = not wrap

        now = time.mktime(datetime.datetime.utcnow().timetuple())
        age = now - date_timestamp

        if metadata.get('ranges'):
            ranges = metadata.get('ranges')
        else:
            ranges = []
            _range = self.DEFAULT_RANGE_MIN
            while True:
                ranges.append(_range)
                range_width = 256 * (2 ** _range)
                if range_width > width or _range >= self.DEFAULT_RANGE_MAX:
                    break
                _range += 1

        can_edit = self.get_current_user() == owner and not embedded
        #can_comment = self.get_current_user() and not embedded
        # one day, perhaps make it depend on a setting on the picture
        can_comment = not embedded

        if content_type == 'image/jpeg':
            extension = 'jpg'
        elif content_type == 'image/png':
            extension = 'png'
        else:
            print "Guessing extension :("
            extension = self.DEFAULT_EXTENSION
        extension = self.get_argument('extension', extension)
        assert extension in ('png', 'jpg'), extension

        if age > 60 * 60 and not cdn_domain:
            # it might be time to upload this to S3
            lock_key = 'uploading:%s' % fileid
            if self.redis.get(lock_key):
                print "AWS uploading is locked"
            else:
                # we're ready to upload it
                _no_tiles = count_all_tiles(
                    fileid,
                    self.application.settings['static_path']
                )
                self.redis.setex(lock_key, time.time(), 60 * 60)
                q = Queue('low', connection=self.redis)
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

        thumbnail_url = full_url = meta_description = None
        # if the image is old enough to have been given a chance to generate a
        # thumbnail, then set that
        if age > 20 and not embedded:
            thumbnail_url = self.make_thumbnail_url(
                fileid,
                300,
                extension=extension,
                absolute_url=True,
            )
            if thumbnail_url.startswith('//'):
                # eg. //xxx.cloudfront.net/thumbnails/100.jpg
                # better be safe than sorry
                thumbnail_url = self.request.protocol + ':' + thumbnail_url

            full_url = self.base_url + self.reverse_url('image', fileid)
            if description:
                meta_description = description
            else:
                meta_description = 'Uploaded %s ago' % smartertimesince(age)

        if lat is not None and lng is not None:
            default_location = [lat, lng]
        else:
            default_location = None

        # so it becomes a element data boolean
        no_wrap = no_wrap and 'true' or 'false'

        self.render(
            'image.html',
            fileid=fileid,
            page_title=title or '/%s' % fileid,
            image_filename=image_filename,
            ranges=ranges,
            title=title,
            description=description,
            default_zoom=default_zoom,
            extension=extension,
            can_edit=can_edit,
            can_comment=can_comment,
            age=age,
            thumbnail_url=thumbnail_url,
            full_url=full_url,
            meta_description=meta_description,
            prefix=cdn_domain and '//' + cdn_domain or '',
            embedded=embedded,
            hide_annotations=hide_annotations,
            hide_download_counter=hide_download_counter,
            default_location=default_location,
            no_wrap=no_wrap,
            wrap=wrap,
        )


@route('/(\w{9})/([\d\.]+)/([-\d\.]+)/([-\d\.]+)', 'image_w_position')
class ImageWPositionHandler(ImageHandler):

    def get(self, fileid, zoom, lat, lng):
        super(ImageWPositionHandler, self).get(
            fileid,
            int(float(zoom)),
            float(lat),
            float(lng)
        )


@route('/(\w{9})/hit', 'image_hitcounter')
class ImageHitCounterHandler(BaseHandler):

    def post(self, fileid):

        # increment a hit counter
        _now = datetime.datetime.utcnow()
        hit_key = 'hits:%s' % fileid
        hit_month_key = (
            'hits:%s:%s:%s' %
            (_now.year, _now.month, fileid)
        )
        self.redis.incr(hit_key)
        self.redis.incr(hit_month_key)
        self.redis.hdel('metadata-rendered', fileid)

        self.write('OK')


@route('/(\w{9})/weight', 'image_weight')
class ImageWeightCounterHandler(BaseHandler):

    def check_xsrf_cookie(self):
        pass

    def post(self, fileid):
        urls = self.get_argument('urls')
        extension = self.get_argument('extension')
        root = os.path.join(
            self.settings['static_path'],
            'tiles',
            fileid[:1],
            fileid[1:3],
            fileid[3:],
            '256',
        )
        bytes = 0
        for each in urls.split('|'):
            path = os.path.join(root, each + extension)
            try:
                bytes += os.stat(path)[stat.ST_SIZE]
            except OSError:
                pass
        if bytes:
            # try self.redis.hget('bytes_served', fileid)
            # or self.redis.hgetall('bytes_served')
            try:
                self.redis.hincrby('bytes_served', fileid, bytes)
            except:
                if self.application.settings['debug']:
                    raise

        self.write({'bytes': bytes})


@route('/(\w{9})/metadata', 'image_metadata')
class ImageMetadataHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        cache_key = 'metadata:%s' % fileid
        metadata = self.redis.get(cache_key)
        if metadata is None:
            document = yield motor.Op(
                self.db.images.find_one,
                {'fileid': fileid},
            )
            title = document.get('title')
            description = document.get('description')
        else:
            metadata = tornado.escape.json_decode(metadata)
            title = metadata.get('title')
            description = metadata.get('description')

        data = {
            'title': title,
            'description': description,
        }
        self.write(data)
        self.finish()


@route('/(\w{9})/commenting', 'image_commenting')
class ImageCommentingHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        current_user = self.get_current_user()
        #if not current_user:
        #    raise tornado.web.HTTPError(403, "Not logged in")
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not document:
            raise tornado.web.HTTPError(404, "Image not found")

        data = {}
        if current_user:
            name = self.redis.hget('name', current_user)
            if name is not None:
                data['name'] = name
        data['comments'] = yield tornado.gen.Task(
            self.get_comments,
            document['_id'],
        )
        data['count'] = len(data['comments'])
        data['signed_in'] = bool(self.get_current_user())
        self.write(data)
        self.finish()

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
        if not document:
            raise tornado.web.HTTPError(404, "Image not found")

        name = self.get_argument('name').strip()
        comment = self.get_argument('comment').strip()
        zoom = int(self.get_argument('zoom'))
        lat = float(self.get_argument('lat'))
        lng = float(self.get_argument('lng'))

        comment_ = {
            'image': document['_id'],
            'user': current_user,
            'name': name,
            'comment': comment,
            'zoom': zoom,
            'center': [lat, lng],
            'approved': document['user'] == current_user,
            'date': datetime.datetime.utcnow(),
        }
        yield motor.Op(
            self.db.comments.insert,
            comment_,
        )
        self.redis.hincrby('comments', fileid, 1)
        self.redis.hset('name', current_user, name)
        comments = yield tornado.gen.Task(
            self.get_comments,
            document['_id'],
        )
        self.write({'comments': comments})
        self.finish()

    @tornado.gen.engine
    def get_comments(self, _id, callback):
        comments = []
        cursor = self.db.comments.find({'image': _id})
        #comment = yield motor.Op(cursor.next_object)
        _now = datetime.datetime.utcnow()
        while (yield cursor.fetch_next):
            comment = cursor.next_object()
            comments.append({
                'html': self.get_comment_html(comment),
                'center': comment['center'],
                'name': tornado.escape.xhtml_escape(comment['name']),
                'zoom': comment['zoom'],
                'ago': smartertimesince(comment['date'], _now),
            })
            #comment = yield motor.Op(cursor.next_object)
        callback(comments)

    def get_comment_html(self, comment):
        return tornado.escape.linkify(comment['comment'])


class ImageMetadataMixin(object):

    @tornado.gen.engine
    def run_edit(self, fileid, current_user, callback):
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not document:
            raise tornado.web.HTTPError(404, fileid)
        if document['user'] != current_user:
            raise tornado.web.HTTPError(403, "Not yours to edit")

        title = self.get_argument('title', u'')
        description = self.get_argument('description', u'')
        wrap = bool(int(self.get_argument('wrap', 0)))

        if len(title) > 200:
            raise tornado.web.HTTPError(400, "title max. 200 characters")
        if len(description) > 1000:
            raise tornado.web.HTTPError(400, "description max. 100 characters")

        data = {
            'title': title,
            'description': description,
            'wrap': wrap,
        }
        yield motor.Op(
            self.db.images.update,
            {'_id': document['_id']},
            {'$set': data}
        )

        metadata_key = 'metadata:%s' % document['fileid']
        self.redis.delete(metadata_key)
        self.redis.hdel('metadata-rendered', fileid)
        data['_needs_refresh'] = (
            document.get('wrap', False) != data['wrap']
        )
        callback(data)


@route('/(\w{9})/edit', 'image_edit')
class ImageEditHandler(BaseHandler, ImageMetadataMixin):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self, fileid):
        current_user = self.get_current_user()
        if not current_user:
            raise tornado.web.HTTPError(403, "Not logged in")

        data = yield tornado.gen.Task(
            self.run_edit,
            fileid,
            current_user
        )

        self.write(data)
        self.finish()


class AnnotationBaseHandler(BaseHandler):

    def get_annotation_html(self, annotation, yours):
        html = (
            '<p><strong>%s</strong></p>' %
            tornado.escape.linkify(annotation['title'])
        )
        if yours:
            html += (
                '<p><a href="#" onclick="return Annotations.edit(\'%s\')"'
                '>edit</a> &ndash; '
                '<a href="#" onclick="return Annotations.delete_(\'%s\')"'
                '>delete</a></p>' %
                (annotation['_id'], annotation['_id'])
            )
        return html


@route('/(\w{9})/annotations', 'image_annotations')
class ImageAnnotationsHandler(AnnotationBaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not document:
            raise tornado.web.HTTPError(404, "Not found")
        cursor = self.db.annotations.find({'image': document['_id']})
        #annotation = yield motor.Op(cursor.next_object)
        annotations = []
        current_user = self.get_current_user()

        while (yield cursor.fetch_next):
            annotation = cursor.next_object()
            yours = annotation['user'] == current_user
            data = {
                'id': str(annotation['_id']),
                'title': annotation['title'],
                'html': self.get_annotation_html(annotation, yours),
                'type': annotation['type'],
                'latlngs': annotation['latlngs'],
                'yours': yours,
            }
            if annotation.get('radius'):
                assert data['type'] == 'circle'
                data['radius'] = annotation['radius']

            annotations.append(data)
            #annotation = yield motor.Op(cursor.next_object)

        data = {'annotations': annotations}
        self.write(data)
        self.finish()

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
        if not document:
            raise tornado.web.HTTPError(404, "Not found")
        #if document['user'] != current_user:
        #    raise tornado.web.HTTPError(403, "Not yours to annotate")

        title = self.get_argument('title').strip()
        type_ = self.get_argument('type')
        _recognized_types = (
            'polyline',
            'rectangle',
            'polygon',
            'marker',
            'circle',
        )
        assert type_ in _recognized_types, type_
        latlngs_json = self.get_argument('latlngs')
        latlngs = tornado.escape.json_decode(latlngs_json)
        #pprint(latlngs)
        # example rectangle:
        # {u'_northEast': {u'lat': -47.1598400130443, u'lng': 81.5625},
        #  u'_southWest': {u'lat': -58.26328705248601, u'lng': 24.43359375}}
        if type_ == 'rectangle':
            # because rectangles used bounds instead
            latlngs = [latlngs['_southWest'], latlngs['_northEast']]
        if type_ == 'circle' or type_ == 'marker':
            latlngs = [latlngs]
        latlngs = [[x['lat'], x['lng']] for x in latlngs]

        options = {}
        if self.get_argument('options', None):
            options.update(
                tornado.escape.json_decode(self.get_argument('options'))
            )

        annotation = {
            'image': document['_id'],
            'latlngs': latlngs,
            'type': type_,
            'title': title,
            'user': current_user,
            'date': datetime.datetime.utcnow(),
            'approved': document['user'] == current_user,
            'options': options,
        }
        if type_ == 'circle':
            annotation['radius'] = float(self.get_argument('radius'))

        _id = yield motor.Op(
            self.db.annotations.insert,
            annotation,
        )
        annotation['_id'] = _id

        data = {
            'html': self.get_annotation_html(annotation, True),
            'id': str(_id),
            'title': title,
        }
        self.write(data)
        self.finish()


@route('/(\w{9})/annotations/move', 'image_annotations_move')
class ImageAnnotationsMoveHandler(AnnotationBaseHandler):

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
        if not document:
            raise tornado.web.HTTPError(404, "Not found")

        annotation = yield motor.Op(
            self.db.annotations.find_one,
            {'_id': ObjectId(self.get_argument('id'))}
        )
        if not annotation:
            raise tornado.web.HTTPError(404, "Marker not found")
        if annotation['user'] != current_user:
            raise tornado.web.HTTPError(403, "Not yours to annotate")

        lat = round(float(self.get_argument('lat')), 3)
        lng = round(float(self.get_argument('lng')), 3)
        data = {
            'latlngs': [[lat, lng]]
        }
        yield motor.Op(
            self.db.annotations.update,
            {'_id': annotation['_id']},
            {'$set': data}
        )

        self.write({'lat': lat, 'lng': lng})
        self.finish()


@route('/(\w{9})/annotations/edit', 'image_annotations_edit')
class ImageAnnotationsEditHandler(AnnotationBaseHandler):

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
        if not document:
            raise tornado.web.HTTPError(404, "Not found")

        annotation = yield motor.Op(
            self.db.annotations.find_one,
            {'_id': ObjectId(self.get_argument('id'))}
        )
        if not annotation:
            raise tornado.web.HTTPError(404, "annotation not found")
        if annotation['user'] != current_user:
            raise tornado.web.HTTPError(403, "Not yours to annotate")

        title = self.get_argument('title').strip()
        data = {
            'title': title
        }
        yield motor.Op(
            self.db.annotations.update,
            {'_id': annotation['_id']},
            {'$set': data}
        )
        annotation['title'] = title

        self.redis.hdel('metadata-rendered', fileid)

        yours = annotation['user'] == current_user
        html = self.get_annotation_html(annotation, yours)
        self.write({'html': html, 'title': title})
        self.finish()


@route('/(\w{9})/annotations/delete', 'image_annotations_delete')
class ImageAnnotationsDeleteHandler(AnnotationBaseHandler):

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
        if not document:
            raise tornado.web.HTTPError(404, "Not found")

        marker = yield motor.Op(
            self.db.annotations.find_one,
            {'_id': ObjectId(self.get_argument('id'))}
        )
        if not marker:
            raise tornado.web.HTTPError(404, "Marker not found")
        if marker['user'] != current_user:
            raise tornado.web.HTTPError(403, "Not yours")

        yield motor.Op(
            self.db.annotations.remove,
            {'_id': marker['_id']}
        )
        self.redis.hdel('metadata-rendered', fileid)
        self.write('OK')
        self.finish()


class DeleteImageMixin(object):

    @tornado.gen.engine
    def delete_image(self, document, callback):
        fileid = document['fileid']
        yield motor.Op(
            self.db.comments.remove,
            {'image': document['_id']}
        )
        yield motor.Op(
            self.db.images.remove,
            {'_id': document['_id']}
        )

        metadata_key = 'metadata:%s' % fileid
        self.redis.delete(metadata_key)
        self.redis.hdel('metadata-rendered', fileid)

        q = Queue(connection=self.redis)
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

        callback()


@route('/(\w{9})/delete', 'image_delete')
class ImageDeleteHandler(BaseHandler, DeleteImageMixin):

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
        if document:
            if document['user'] != current_user:
                raise tornado.web.HTTPError(403, "Not yours to edit")

            yield tornado.gen.Task(self.delete_image, document)

        self.write("Deleted")
        self.finish()


@route('/upload', 'upload')
class UploadHandler(BaseHandler):

    def get(self):

        self.render('upload.html')


class PreviewMixin(object):

    @tornado.gen.engine
    def run_preview(self, url, callback):
        http_client = tornado.httpclient.AsyncHTTPClient()
        head_response = yield tornado.gen.Task(
            http_client.fetch,
            url,
            method='HEAD'
        )

        if head_response.code == 599:
            message = (
                'Fetching the image timed out. '
                'Perhaps try again a little later.'
            )
            callback({'error': message})

        if not head_response.code == 200:
            callback({'error': head_response.body})
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
                    message = "URL not an image. It's a web page"

                    callback({'error': "URL not an image. It's a web page"})
                    return
                message = "Unrecognized content type '%s' " % content_type
                if content_type == 'application/octet-stream':
                    message += (
                        "\nThis likely to happen if the URL is not an image "
                        "but an application or something else only for "
                        "download."
                    )
                callback({'error': message})
                return
        try:
            expected_size = int(head_response.headers['Content-Length'])
            if expected_size == 1:
                # e.g. raw.github.com does this
                raise KeyError
        except KeyError:
            # sometimes images don't have a Content-Length but still work
            logging.warning("No Content-Length (content-encoding:%r)" %
                            head_response.headers.get('Content-Encoding', ''))
            expected_size = 0

        fileid = uuid.uuid4().hex[:9]
        _count = yield motor.Op(self.db.images.find({'fileid': fileid}).count)
        while _count:
            fileid = uuid.uuid4().hex[:9]
            _count = yield motor.Op(
                self.db.images.find({'fileid': fileid}).count
            )

        document = {
            'fileid': fileid,
            'source': url,
            'date': datetime.datetime.utcnow(),
            'user': self.get_current_user()
        }
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
        yield motor.Op(self.db.images.insert, document)

        callback({
            'fileid': fileid,
            'content_type': content_type,
            'expected_size': expected_size,
        })


@route('/upload/preview', 'upload_preview')
class PreviewUploadHandler(UploadHandler, PreviewMixin):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        url = self.get_argument('url')
        current_user = self.get_current_user()
        if not current_user:
            raise tornado.web.HTTPError(403, "You must be logged in")

        search = {'email': current_user}
        banned = yield motor.Op(self.db.banned.find(search).count)
        if banned:
            yield motor.Op(
                self.db.banned.update,
                {'email': current_user},
                {'$inc': {'upload_attempts': 1}}
            )
            raise tornado.web.HTTPError(412, "Banned")

        response = yield tornado.gen.Task(self.run_preview, url)
        self.write(response)
        self.finish()


class ProgressMixin(object):

    def get_progress(self, fileid, content_type=None):
        destination = self.make_destination(fileid, content_type=content_type)
        data = {
            'done': 0
        }
        if os.path.isfile(destination):
            size = os.stat(destination)[stat.ST_SIZE]
            data['done'] = size
        return data


@route('/upload/progress', 'upload_progress')
class ProgressUploadHandler(UploadHandler, ProgressMixin):

    def get(self):
        if not self.get_current_user():
            raise tornado.web.HTTPError(403, "You must be logged in")
        fileid = self.get_argument('fileid')
        data = self.get_progress(fileid)
        self.write(data)


class TileMakerMixin(object):

    @tornado.gen.engine
    def prepare_all_tiles(self, fileid, original, ranges, extension,
                          callback, add_delay=True):
        had_to_give_up = False
        image_split = fileid[:1] + '/' + fileid[1:3] + '/' + fileid[3:]

        q = Queue(connection=self.redis)
        jobs = []

        for zoom in ranges:
            jobs.append(q.enqueue(
                make_resize,
                original,
                zoom
            ))

            extra = self.get_extra_rows_cols(zoom)
            width = 256 * (2 ** zoom)
            cols = rows = extra + width / 256

            jobs.append(q.enqueue(
                make_tiles,
                image_split,
                256,
                zoom,
                rows,
                cols,
                extension,
                self.application.settings['static_path'],
            ))

        for width_ in (100, 300):
            jobs.append(q.enqueue(
                make_thumbnail,
                image_split,
                width_,
                extension,
                self.application.settings['static_path'],
            ))

        for zoom in ranges:
            q.enqueue(
                optimize_images,
                image_split,
                zoom,
                extension,
                self.application.settings['static_path'],
            )

        q.enqueue(
            optimize_thumbnails,
            image_split,
            extension,
            self.application.settings['static_path'],
        )

        lock_key = 'uploading:%s' % fileid
        self.redis.setex(lock_key, time.time(), 60 * 60)

        ioloop_instance = tornado.ioloop.IOLoop.instance()
        delay = 1
        total_delay = 0
        while add_delay:
            yield tornado.gen.Task(
                ioloop_instance.add_timeout,
                time.time() + delay
            )
            delay += 1
            total_delay += delay

            jobs_done = len([
                x for x in jobs
                if x.result is not None
            ])
            jobs_remaining = [
                x for x in jobs
                if x.result is None
            ]
            if not jobs_remaining:
                break
            if total_delay > 50:
                # if at least 2 jobs had been done,
                # it means the resizing and and tiles were made for
                # the default zoom level.
                # and it's a healthy sign it managed to do one more
                had_to_give_up = jobs_done > 2
                break

        callback(had_to_give_up)

    @tornado.gen.engine
    def email_about_upload(self, fileid, extension, email, callback):
        url = self.base_url + self.reverse_url('image', fileid)
        home_url = self.base_url + '/'

        unsub_key = uuid.uuid4().hex[:12]
        self.redis.setex(
            'unsubscribe:%s' % unsub_key,
            email,
            60 * 60 * 24 * 7
        )
        unsubscribe_url = self.base_url + self.reverse_url(
            'unsubscribe',
            unsub_key
        )

        thumbnail_url = self.make_thumbnail_url(
            fileid,
            100,
            extension=extension,
            absolute_url=True,
        )

        was_unsubscribed = self.redis.sismember('unsubscribed', email)

        html_email_body = self.render_string(
            '_email.html',
            url=url,
            fileid=fileid,
            thumbnail_url=thumbnail_url,
            home_url=home_url,
            unsubscribe_url=unsubscribe_url,
            was_unsubscribed=was_unsubscribed,
            email=email,
            host=self.request.host,
            name=self.redis.hget('name', email),
        )
        html_email_body = premailer.transform(
            html_email_body,
            base_url=self.base_url
        )

        email_body = self.render_string(
            '_email.txt',
            url=url,
            home_url=home_url,
            unsubscribe_url=unsubscribe_url,
            was_unsubscribed=was_unsubscribed,
            email=email,
            name=self.redis.hget('name', email),
        )

        q = Queue(connection=self.redis)
        logging.info('Enqueueing email to %s', email)
        job = q.enqueue(
            send_url,
            url,
            fileid,
            email,
            html_email_body,
            plain_body=email_body,
            debug=self.application.settings['debug']
        )
        callback(job)


class DownloadMixin(object):

    @tornado.gen.engine
    def run_download(self, fileid, callback,
                     add_delay=True):
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        url = document['source']
        tornado.httpclient.AsyncHTTPClient.configure(
            tornado.curl_httpclient.CurlAsyncHTTPClient
        )
        destination = self.make_destination(fileid)
        q = Queue(connection=self.redis)
        job = q.enqueue_call(
            func=download,
            args=(url, destination),
            kwargs={'request_timeout': 500},
            timeout=501,
        )
        delay = 1
        ioloop_instance = tornado.ioloop.IOLoop.instance()
        while job.result is None:
            yield tornado.gen.Task(
                ioloop_instance.add_timeout,
                time.time() + delay
            )

        response = job.result
        if response['code'] == 200:
            img = Image.open(destination)
            size = img.size
            if size[0] < 256 * (2 ** self.DEFAULT_RANGE_MIN):
                message = 'Picture too small (%sx%s)' % size
                callback({'error': message})

                # reverse the upload by deleting the record
                yield motor.Op(
                    self.db.images.remove,
                    {'_id': document['_id']}
                )
                os.remove(destination)
                return
            # img.histogram() is a long list of integers
            histogram_hash = hashlib.md5(
                ','.join(str(x) for x in img.histogram())
            ).hexdigest()

            data = {
                'width': size[0],
                'height': size[1],
                'histogramhash': histogram_hash,
                'featured': True,
            }

            replica_search = {
                'histogramhash': histogram_hash,
                'user': document['user'],
            }
            cursor = (
                self.db.images.find(replica_search)
                .limit(1)
            )
            #replica_image = yield motor.Op(cursor.next_object)
            if (yield cursor.fetch_next):
                replica_image = cursor.next_object()
                url = self.base_url + self.reverse_url(
                    'image',
                    replica_image['fileid']
                )
                message = 'Picture matches an identical upload %s' % url
                callback({'error': message})

                # reverse the upload by deleting the record
                yield motor.Op(
                    self.db.images.remove,
                    {'_id': document['_id']}
                )
                os.remove(destination)
                return

            if not document.get('size'):
                data['size'] = document['size'] = os.stat(destination)[stat.ST_SIZE]

            yield motor.Op(
                self.db.images.update,
                {'_id': document['_id']},
                {'$set': data}
            )
            self.redis.setex(
                'sizeinfo:%s' % fileid,
                tornado.escape.json_encode(data),
                60 * 60
            )
            area = size[0] * size[1]
            r = 1.0 * size[0] / size[1]

            # this is used for doing things like stats on all uploads
            all_fileids_key = 'allfileids'
            self.redis.lpush(all_fileids_key, fileid)
            all_fileids_key = ':%s' % document['user']
            self.redis.lpush(all_fileids_key, fileid)

            try:
                self.redis.incr('bytes_downloaded', amount=document['size'])
            except:
                if self.application.settings['debug']:
                    raise

            ranges = []
            _range = self.DEFAULT_RANGE_MIN
            while True:
                ranges.append(_range)
                range_width = 256 * (2 ** _range)
                range_height = range_width / r
                range_area = range_width * range_height
                if _range >= self.DEFAULT_RANGE_MAX:
                    break
                if range_area > area:
                    break
                _range += 1

            # since zoom level 3 is the default, make sure that's
            # prepared first
            ranges.remove(self.DEFAULT_ZOOM)
            ranges.insert(0, self.DEFAULT_ZOOM)
            extension = destination.split('.')[-1]

            #tiles_made = yield tornado.gen.Task(
            had_to_give_up = yield tornado.gen.Task(
                self.prepare_all_tiles,
                fileid,
                destination,
                ranges,
                extension,
                add_delay=add_delay,
            )
            if had_to_give_up:
                logging.warning(
                    "Had to give up when generating tiles %r"
                    % fileid
                )
                callback({
                    'email': document['user']
                })
            else:
                callback({
                    'url': self.reverse_url('image', fileid),
                })

            # only send an email if we had to give up or the user
            # has not unsubscribed
            if (had_to_give_up or not
                self.redis.sismember('unsubscribed', document['user'])):
                yield tornado.gen.Task(
                    self.email_about_upload,
                    fileid,
                    extension,
                    document['user'],
                )
            else:
                logging.info('Skipping to send email')
        else:
            yield motor.Op(
                self.db.images.remove,
                {'_id': document['_id']}
            )
            try:
                os.remove(destination)
            except:
                logging.error("Unable to remove %s" % destination,
                              exc_info=True)
            callback({
                'error': "FAILED TO DOWNLOAD\n%s\n%s\n" %
                         (response['code'], response['body'])
            })


@route('/upload/download', 'upload_download')
class DownloadUploadHandler(UploadHandler,
                            DownloadMixin,
                            TileMakerMixin):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        if not self.get_current_user():
            raise tornado.web.HTTPError(403, "You must be logged in")
        fileid = self.get_argument('fileid')
        response = yield tornado.gen.Task(
            self.run_download,
            fileid
        )
        self.write(response)
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
        url = 'https://verifier.login.persona.org/verify'
        if self.request.host != settings.BROWSERID_DOMAIN:
            logging.warning(
                "%r != %r" %
                (self.request.host, settings.BROWSERID_DOMAIN)
            )

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

            search = {'email': email}
            banned = yield motor.Op(self.db.banned.find(search).count)
            if banned:
                yield motor.Op(
                    self.db.banned.update,
                    {'email': email},
                    {'$inc': {'signin_attempts': 1}}
                )
                raise tornado.web.HTTPError(412, "Banned")

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

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, image, size, zoom, row, col, extension):
        if extension == 'png':
            self.set_header('Content-Type', 'image/png')
        else:
            self.set_header('Content-Type', 'image/jpeg')
        size = int(size)
        if size != 256:
            raise tornado.web.HTTPError(400, 'size must be 256')

        q = Queue(connection=self.redis)
        job = q.enqueue(
            make_tile,
            image,
            size,
            zoom,
            row,
            col,
            extension,
            self.application.settings['static_path']
        )
        ioloop_instance = tornado.ioloop.IOLoop.instance()
        delay = 0.1
        while True:
            yield tornado.gen.Task(
                ioloop_instance.add_timeout,
                time.time() + delay
            )
            delay *= 2
            if job.result is not None:
                save_filepath = job.result
                break

        try:
            _cache_seconds = 60 * 60 * 24
            self.set_header(
                'Cache-Control',
                'max-age=%d, public' % _cache_seconds
            )
            if _cache_seconds > 3600:
                _expires = (
                    datetime.datetime.utcnow() +
                    datetime.timedelta(seconds=_cache_seconds)
                )
                self.set_header(
                    'Expires',
                    _expires.strftime('%a, %d %b %Y %H:%M:%S GMT')
                )
            self.write(open(save_filepath, 'rb').read())
            fileid = image.replace('/', '')

            lock_key = 'uploading:%s' % fileid
            if not self.redis.get(lock_key):
                q = Queue(connection=self.redis)
                q.enqueue(
                    upload_tiles,
                    fileid,
                    self.application.settings['static_path'],
                    max_count=10,
                    only_if_no_cdn_domain=True
                )

        except IOError:
            self.set_header('Content-Type', 'image/png')
            self.set_header(
                'Cache-Control',
                'max-age=0'
            )
            broken_filepath = os.path.join(
                self.application.settings['static_path'],
                'images',
                'broken.png'
            )
            self.write(open(broken_filepath, 'rb').read())

        self.finish()


@route(r'/thumbnails/(?P<image>\w{1}/\w{2}/\w{6})/(?P<width>\w{1,3})'
       r'.(?P<extension>png|jpg)',
       name='thumbnail')
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
            self.set_header(
                'Cache-Control',
                'max-age=0'
            )
        else:
            _cache_seconds = 60 * 60 * 24
            self.set_header(
                'Cache-Control',
                'max-age=%d, public' % _cache_seconds
            )
            if _cache_seconds > 3600:
                _expires = (
                    datetime.datetime.utcnow() +
                    datetime.timedelta(seconds=_cache_seconds)
                )
                self.set_header(
                    'Expires',
                    _expires.strftime('%a, %d %b %Y %H:%M:%S GMT')
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


@route(r'/tweets', 'tweets')
class TweetsHandler(BaseHandler):

    def get(self):
        self.render('tweets.html')


@route(r'/privacy', 'privacy')
class PrivacyHandler(BaseHandler):

    def get(self):
        self.render('privacy.html')


@route(r'/gettingstarted', 'gettingstarted')
class GettingStartedHandler(BaseHandler):

    def get(self):
        self.render('gettingstarted.html')


@route(r'/embed/(?P<fileid>\w{9})', 'embed')
class EmbedHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        document = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not document:
            raise tornado.web.HTTPError(404, "File not found")

        search = {'image': document['_id']}
        count_annotations = yield motor.Op(
            self.db.annotations.find(search).count
        )
        data = {
            'fileid': fileid,
            'default_zoom': self.DEFAULT_ZOOM,
            'default_lat': self.DEFAULT_LAT,
            'default_lng': self.DEFAULT_LNG,
            'count_annotations': count_annotations,
        }
        self.render('embed.html', **data)


@route(r'/popularity', 'popularity')
class PopularityHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self):
        data = {}

        hits_key = 'popularity:hits'
        this_month_key = 'popularity:hits_this_month'
        served_key = 'popularity:served'

        v1 = self.redis.get(hits_key)
        v2 = self.redis.get(this_month_key)
        v3 = self.redis.get(served_key)
        if v1 is not None and v2 is not None and v3 is not None:
            hits = tornado.escape.json_decode(v1)
            this_month = tornado.escape.json_decode(v2)
            served = tornado.escape.json_decode(v3)
        else:
            lists = yield tornado.gen.Task(self._get_data)
            hits, this_month, served = lists
            self.redis.setex(
                hits_key,
                tornado.escape.json_encode(hits),
                60 * 60
            )
            self.redis.setex(
                this_month_key,
                tornado.escape.json_encode(this_month),
                60 * 60
            )
            self.redis.setex(
                served_key,
                tornado.escape.json_encode(served),
                60 * 60
            )

        data['this_month_hits'] = this_month
        data['hits'] = hits
        data['served'] = served
        self.render('popularity.html', **data)

    @tornado.gen.engine
    def _get_data(self, callback):
        _now = datetime.datetime.utcnow()

        this_month = []
        hits = []
        bytes = []
        cursor = self.db.images.find({}, ('fileid', 'title'))
        #image = yield motor.Op(cursor.next_object)
        while (yield cursor.fetch_next):
            image = cursor.next_object()
            image = {'fileid': image['fileid'],
                     'title': image.get('title')}
            fileid = image['fileid']
            hit_key = 'hits:%s' % fileid
            hit_month_key = (
                'hits:%s:%s:%s' %
                (_now.year, _now.month, fileid)
            )
            number = self.redis.get(hit_key)
            if number is not None:
                hits.append((int(number), image))
            number = self.redis.get(hit_month_key)
            if number is not None:
                this_month.append((int(number), image))
            number = self.redis.hget('bytes_served', fileid)
            if number is not None:
                bytes.append((int(number), image))
            #image = yield motor.Op(cursor.next_object)

        hits.sort(reverse=True)
        this_month.sort(reverse=True)
        bytes.sort(reverse=True)

        hits = hits[:10]
        this_month = this_month[:10]
        bytes = bytes[:10]

        callback((hits, this_month, bytes))


@route(r'/unsubscribe/(?P<unsub_key>\w{12})', 'unsubscribe')
class UnsubscribeHandler(BaseHandler):

    def get(self, unsub_key):
        email = self.redis.get('unsubscribe:%s' % unsub_key)
        if email:
            self.redis.sadd('unsubscribed', email)
        data = {
            'email': email,
        }
        self.render('unsubscribed.html', **data)


@route(r'/yourhelp/', 'yourhelp')
class YourHelpHandler(BaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self):
        data = {
            'yourtweets': [],
        }
        if self.get_current_user():
            cursor = self.db.images.find(
                {'user': self.get_current_user(),
                 'title': {'$exists': True}},
                ('fileid', 'title')
            )

            #image = yield motor.Op(cursor.next_object)
            while (yield cursor.fetch_next):
                image = cursor.next_object()
                if image['title']:
                    tweet = self.redis.hget('tweets', image['fileid'])
                    if tweet:
                        data['yourtweets'].append((
                            image['title'],
                            tweet,
                        ))
                #image = yield motor.Op(cursor.next_object)

        self.render('yourhelp.html', **data)


class HoneypotMixin(object):

    questions = {
        'What is one plus one?': ['2', 'two'],
        'What is two plus two?': ['4', 'four'],
        'Do cows eat fish every day?': ['no'],
        'What is two minus one?': ['1', 'one'],
        'What is 12 plus zero?': ['12', 'twelve'],
        'Which is bigger, Canada or Vatican?': ['canada'],
        'Which weighs more an elephant or an ant?': ['elephant'],
    }

    def get_random_question(self):
        return random.choice(self.questions.keys())

    def check_question_answer(self, question, answer):
        answer = answer.lower().strip()
        for alternative in self.questions[question]:
            if alternative == answer:
                return True
        return False


@route(r'/feedback/hp.json', 'feedback_honeypot')
class FeedbackHoneypotHandler(BaseHandler, HoneypotMixin):

    def get(self):
        self.write({'question': self.get_random_question()})


@route(r'/feedback/', 'feedback')
class FeedbackHandler(BaseHandler, HoneypotMixin):

    def get(self):
        user = self.get_current_user()
        name = ''
        if user:
            name = self.redis.hget('name', user)
        data = {
            'name': name,
            'posted': self.get_argument('posted', False),
        }
        self.render('feedback.html', **data)

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        if not self.get_argument('comment', None):
            self.write('No comment? Go back and try again')
            self.finish()
            return

        if not self.get_current_user():
            question = self.get_argument('hp-question')
            answer = self.get_argument('hp')
            if not self.check_question_answer(question, answer):
                raise tornado.web.HTTPError(400, "Failed the human test")

        document = {
            'comment': self.get_argument('comment').strip(),
            'name': self.get_argument('name', u'').strip(),
            'email': self.get_argument('email', u'').strip(),
            'type': self.get_argument('type', u'').strip(),
            'date': datetime.datetime.utcnow(),
        }
        yield motor.Op(self.db.feedback.insert, document)
        document['current_user'] = self.get_current_user()

        q = Queue(connection=self.redis)
        q.enqueue(
            send_feedback,
            document,
            debug=self.application.settings['debug']
        )
        self.redirect(self.reverse_url('feedback') + '?posted=1')


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
        raise tornado.web.HTTPError(404)
