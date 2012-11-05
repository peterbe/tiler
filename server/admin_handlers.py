import datetime
import urllib
import time
import os
import tornado.web
import tornado.gen
from PIL import Image
from tornado_utils.routes import route
import motor

from handlers import BaseHandler, TileMakerMixin
from utils import count_all_tiles, find_original
import settings


class AdminBaseHandler(BaseHandler):

    def prepare(self):
        user = self.get_current_user()
        if not user:
            self.redirect('/')
        if not self.is_admin(user):
            raise tornado.web.HTTPError(403)

    def is_admin(self, user=None):
        if user is None:
            user = self.get_current_user()
        if not user:
            return False
        return user in settings.ADMIN_EMAILS

    def _count_tiles(self, image):
        count_key = 'count_all_tiles:%s' % image['fileid']
        count = self.redis.get(count_key)
        if count is None:
            count = count_all_tiles(
                image['fileid'],
                self.application.settings['static_path']
            )
            self.redis.setex(
                count_key,
                count,
                60 * 60
            )
        return count

    def _calculate_ranges(self, image):
        ranges = []
        _range = self.DEFAULT_RANGE_MIN

        area = image['width'] * image['height']
        r = 1.0 * image['width'] / image['height']

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
        return ranges

    def _expected_tiles(self, image):
        count = 0
        for zoom in image['ranges']:
            extra = self.get_extra_rows_cols(zoom)
            width = 256 * (2 ** zoom)
            cols = rows = extra + width / 256
            count += (cols * rows)
        return count

    def attach_tiles_info(self, image):
        image['found_tiles'] = self._count_tiles(image)
        _ranges = image.get('ranges')
        if _ranges:
            _ranges = [int(x) for x in _ranges]
        image['ranges'] = (
            _ranges or self._calculate_ranges(image)
        )
        image['expected_tiles'] = self._expected_tiles(image)
        image['too_few_tiles'] = (
            image['found_tiles'] < image['expected_tiles']
        )

    def attach_hits_info(self, image):
        _now = datetime.datetime.utcnow()
        fileid = image['fileid']
        hit_key = 'hits:%s' % fileid
        hit_month_key = (
            'hits:%s:%s:%s' %
            (_now.year, _now.month, fileid)
        )
        image['hits'] = self.redis.get(hit_key)
        image['hits_this_month'] = self.redis.get(hit_month_key)


@route('/admin/', name='admin_home')
class AdminHomeHandler(AdminBaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self):
        data = {}
        page = int(self.get_argument('page', 1))
        page_size = 100
        skip = page_size * (page - 1)
        cursor = (
            self.db.images.find({'width': {'$exists': True}})
            .sort([('date', -1)])
            .limit(page_size)
            .skip(skip)
        )
        image = yield motor.Op(cursor.next_object)
        images = []
        while image:
            if not image.get('width'):
                if image['contenttype'] == 'image/jpeg':
                    extension = 'jpg'
                elif image['contenttype'] == 'image/png':
                    extension = 'png'
                else:
                    raise NotImplementedError
                original = find_original(
                    image['fileid'],
                    self.application.settings['static_path'],
                    extension,
                )
                if not original:
                    image = yield motor.Op(cursor.next_object)
                    continue

                size = Image.open(original).size
                data = {
                    'width': size[0],
                    'height': size[1]
                }
                yield motor.Op(
                    self.db.images.update,
                    {'_id': image['_id']},
                    {'$set': data}
                )
                image['width'] = data['width']
                image['height'] = data['height']

            self.attach_tiles_info(image)
            images.append(image)
            image = yield motor.Op(cursor.next_object)

        data['images'] = images
        total_count = yield motor.Op(self.db.images.find().count)
        data['total_count'] = total_count

        self.render('admin/home.html', **data)


@route('/admin/(?P<fileid>\w{9})/', name='admin_image')
class AdminImageHandler(AdminBaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        image = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not image:
            raise tornado.web.HTTPError(404, "File not found")

        self.attach_tiles_info(image)
        self.attach_hits_info(image)

        data = {
            'image': image,
        }

        self.render('admin/image.html', **data)



@route('/admin/(?P<fileid>\w{9})/tiles/', name='admin_tiles')
class AdminTilesHandler(AdminBaseHandler):

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self, fileid):
        image = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not image:
            raise tornado.web.HTTPError(404, "File not found")

        image_split = (
            fileid[:1] +
            '/' +
            fileid[1:3] +
            '/' +
            fileid[3:]
        )

        if image['contenttype'] == 'image/jpeg':
            extension = 'jpg'
        elif image['contenttype'] == 'image/png':
            extension = 'png'
        else:
            raise NotImplementedError

        image['found_tiles'] = self._count_tiles(image)
        _ranges = image.get('ranges')
        if _ranges:
            _ranges = [int(x) for x in _ranges]
        image['ranges'] = _ranges or self._calculate_ranges(image)
        image['expected_tiles'] = self._expected_tiles(image)
        _tiles_before = self.get_argument('before', None)
        if _tiles_before is not None and _tiles_before != image['found_tiles']:
            if image.get('cdn_domain'):
                yield motor.Op(
                    self.db.images.update,
                    {'_id': image['_id']},
                    {'$unset': {'cdn_domain': 1}}
                )
                image['cdn_domain'] = None
                lock_key = 'uploading:%s' % fileid
                # locking it from aws upload for 1 hour
                self.redis.setex(lock_key, time.time(), 60 * 60)

        data = {
            'image_split': image_split,
            'ranges': image['ranges'],
            'found_tiles_before': _tiles_before,
        }
        data['image'] = image
        _cols = {}
        _rows = {}
        tiles = {}
        root = self.application.settings['static_path']
        for zoom in image['ranges']:
            extra = self.get_extra_rows_cols(zoom)
            tiles[zoom] = {}
            width = 256 * (2 ** zoom)
            cols = rows = extra + width / 256
            _cols[zoom] = cols
            _rows[zoom] = rows
            for row in range(rows):
                for col in range(cols):
                    key = '%s,%s' % (row, col)
                    filename = os.path.join(
                        root,
                        'tiles',
                        image_split,
                        '256',
                        str(zoom),
                        key + '.' + extension
                    )
                    tiles[zoom][key] = os.path.isfile(filename)
        data['rows'] = _rows
        data['cols'] = _cols
        data['tiles'] = tiles

        self.render('admin/tiles.html', **data)


@route('/admin/(?P<fileid>\w{9})/tiles/prepare_all/',
       name='admin_prepare_all_tiles')
class AdminPrepareAllTilesHandler(AdminBaseHandler, TileMakerMixin):

    def check_xsrf_cookie(self):
        pass

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self, fileid):
        image = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not image:
            raise tornado.web.HTTPError(404, "File not found")

        destination = self.make_destination(
            fileid,
            content_type=image['contenttype']
        )

        count_before = self._count_tiles(image)

        _ranges = image.get('ranges')
        if _ranges:
            _ranges = [int(x) for x in _ranges]
        ranges = _ranges or self._calculate_ranges(image)

        extension = destination.split('.')[-1]

        had_to_give_up = yield tornado.gen.Task(
            self.prepare_all_tiles,
            fileid,
            destination,
            ranges,
            extension,
        )

        count_key = 'count_all_tiles:%s' % image['fileid']
        self.redis.delete(count_key)

        url = self.reverse_url('admin_tiles', fileid)
        data = {
            'before': str(count_before),
        }
        if had_to_give_up:
            data['had_to_give_up'] = 'true'

        self.redirect(url + '?' + urllib.urlencode(data))


@route('/admin/(?P<fileid>\w{9})/tiles/featured/',
       name='admin_toggle_featured')
class AdminToggleFeaturedHandler(AdminBaseHandler):

    def check_xsrf_cookie(self):
        pass

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self, fileid):
        image = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not image:
            raise tornado.web.HTTPError(404, "File not found")

        featured = image.get('featured', True)
        yield motor.Op(
            self.db.images.update,
            {'_id': image['_id']},
            {'$set': {'featured': not featured}}
        )

        url = self.reverse_url('admin_image', fileid)
        self.redirect(url)


@route('/admin/(?P<fileid>\w{9})/tiles/unset-cdn_domain/',
       name='admin_unset_cdn')
class AdminUnsetCDNHandler(AdminBaseHandler):

    def check_xsrf_cookie(self):
        pass

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self, fileid):
        image = yield motor.Op(
            self.db.images.find_one,
            {'fileid': fileid}
        )
        if not image:
            raise tornado.web.HTTPError(404, "File not found")

        featured = image.get('featured', True)
        yield motor.Op(
            self.db.images.update,
            {'_id': image['_id']},
            {'$unset': {'cdn_domain': 1}}
        )

        lock_key = 'uploading:%s' % fileid
        # locking it from aws upload for 1 hour
        self.redis.setex(lock_key, time.time(), 60 * 60)

        upload_log = os.path.join(
            self.application.settings['static_path'],
            'upload.%s.txt' % fileid
        )
        if os.path.isfile(upload_log):
            os.remove(upload_log)
        else:
            print "couldn't remove", upload_log

        url = self.reverse_url('admin_image', fileid)
        self.redirect(url)
