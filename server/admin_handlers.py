import os
import tornado.web
import tornado.gen
from tornado_utils.routes import route
import motor

from handlers import BaseHandler, TileMakerMixin
from utils import count_all_tiles, find_all_tiles
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
        return count_all_tiles(
            image['fileid'],
            self.application.settings['static_path']
        )

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
            self.db.images.find()
            .sort([('date', -1)])
            .limit(page_size)
            .skip(skip)
        )
        image = yield motor.Op(cursor.next_object)
        images = []
        while image:
            image['found_tiles'] = self._count_tiles(image)
            image['ranges'] = image.get('ranges') or self._calculate_ranges(image)
            image['expected_tiles'] = self._expected_tiles(image)
            image['too_few_tiles'] = image['found_tiles'] < image['expected_tiles']
            images.append(image)
            image = yield motor.Op(cursor.next_object)

        data['images'] = images
        total_count = yield motor.Op(self.db.images.find().count)
        data['total_count'] = total_count

        self.render('admin/home.html', **data)



@route('/admin/(?P<fileid>\w{9})/tiles/', name='admin_tiles')
class AdminTilesHandler(AdminBaseHandler, TileMakerMixin):

    def check_xsrf_cookie(self):
        pass

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

        all_tiles = list(find_all_tiles(
            image['fileid'],
            self.application.settings['static_path']
        ))

        if image['contenttype'] == 'image/jpeg':
            extension = 'jpg'
        elif image['contenttype'] == 'image/png':
            extension = 'png'
        else:
            raise NotImplementedError

        image['found_tiles'] = self._count_tiles(image)
        image['ranges'] = image.get('ranges') or self._calculate_ranges(image)
        image['expected_tiles'] = self._expected_tiles(image)
        data = {
          'image_split': image_split,
          'ranges': image['ranges'],
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

        ranges = self._calculate_ranges(image)
        ranges.remove(self.DEFAULT_ZOOM)
        ranges.insert(0, self.DEFAULT_ZOOM)

        extension = destination.split('.')[-1]

        had_to_give_up = yield tornado.gen.Task(
            self.prepare_all_tiles,
            fileid,
            destination,
            ranges,
            extension,
        )

        url = self.reverse_url('admin_tiles', fileid)
        if had_to_give_up:
            url += '?had_to_give_up=1'
        self.redirect(url)
        #self.write({'had_to_give_up': had_to_give_up})
        #self.finish()
