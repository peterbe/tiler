import stat
import warnings
import datetime
import random
import os
import time
import email
import motor
import pymongo
import logging
from boto.s3.connection import Location, S3Connection
from boto.s3.key import Key
from tornado import gen
from tornado.ioloop import IOLoop
import redis.client
import settings
from utils import find_all_tiles, find_original


def upload_original(fileid, extension, static_path, bucket_id):
    conn = S3Connection(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_KEY)
    bucket = conn.lookup(bucket_id) or conn.create_bucket(bucket_id, location=Location.EU)

    db_connection = motor.MotorClient().open_sync()
    db = db_connection[settings.DATABASE_NAME]

    original = find_original(fileid, static_path, extension)
    if original:
        relative_path = original.replace(static_path, '')
        k = Key(bucket)
        k.key = relative_path
        print "Uploading original", original
        s = os.stat(original)[stat.ST_SIZE]
        print "%.1fKb" % (s / 1024.)
        # reduced because I'm a cheapskate
        k.set_contents_from_filename(original, reduced_redundancy=True)
        print "Original uploaded"
    else:
        print "Original can't be found", repr(original)


def update_tiles_metadata(tile_paths, years=1, max_updates=10, suffix=None):
    conn = S3Connection(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_KEY)
    bucket = conn.lookup(settings.TILES_BUCKET_ID)

    for tile_path in tile_paths:
        key = bucket.get_key(tile_path)
        if key is None:
            logging.warning("%r is not found as a key" % tile_path)
            return

        aggressive_headers = _get_aggressive_cache_headers(key, years)
        key.copy(
            settings.TILES_BUCKET_ID,
            key,
            metadata=aggressive_headers,
            preserve_acl=True
        )
        print key, "DONE"


def _get_aggressive_cache_headers(key, years):
    metadata = key.metadata

    metadata['Content-Type'] = key.content_type

    # HTTP/1.0
    metadata['Expires'] = '%s GMT' %\
        (email.Utils.formatdate(
            time.mktime((datetime.datetime.now() +
            datetime.timedelta(days=365 * years)).timetuple())))

    # HTTP/1.1
    metadata['Cache-Control'] = 'max-age=%d, public' % (3600 * 24 * 360 * years)

    return metadata


@gen.engine
def upload_all_tiles(fileid, static_path, bucket_id, max_count=0,
                     only_if_no_cdn_domain=False,
                     replace=True):
    log_file = os.path.join(static_path, 'upload.%s.txt' % fileid)

    conn = S3Connection(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_KEY)
    bucket = conn.lookup(bucket_id) or conn.create_bucket(bucket_id, location=Location.EU)
    #bucket.set_acl('public-read')

    db_connection = motor.MotorClient().open_sync()
    db = db_connection[settings.DATABASE_NAME]

    document = yield motor.Op(
        db.images.find_one,
        {'fileid': fileid}
    )
    if not document:
        logging.warning("Image %r does not exist" % fileid)
        IOLoop.instance().stop()
        return

    if document.get('cdn_domain'):
        if only_if_no_cdn_domain:
            IOLoop.instance().stop()
            return
        else:
            warnings.warn("%s already has a cdn_domain (%s)" %
                          (fileid, document['cdn_domain']))

    try:
        count = 0
        all_done = True
        all_tiles = list(find_all_tiles(fileid, static_path))
        random.shuffle(all_tiles)
        #if len(all_tiles) > max_count:
        #    total = max_count
        #else:
        #    total = len(all_tiles)
        total = len(all_tiles)
        aggressive_headers = get_aggressive_headers()
        for each in all_tiles:
            # load which ones we've done every time to prevent
            # parallel workers uploading the same file more than once
            try:
                done = [x.strip() for x in open(log_file) if x.strip()]
            except IOError:
                done = []
            if each not in done:
                done.append(each)
                relative_path = each.replace(static_path, '')
                k = Key(bucket)
                k.key = relative_path
                # docs:
                # http://boto.cloudhackers.com/en/latest/ref/s3.html#boto.s3.\
                #   key.Key.set_contents_from_filename
                print "uploading", relative_path,
                try:
                    count_done = set(x.strip() for x in open(log_file))
                except IOError:
                    count_done = []
                print "(%d of %d)" % (len(count_done), total)
                k.set_contents_from_filename(
                    each,
                    replace=replace,
                    reduced_redundancy=True,
                    headers=aggressive_headers,
                )
                k.make_public()
                open(log_file, 'a').write(each + '\n')
                count += 1
                if max_count > 0 and count >= max_count:
                    print "STOPPING @", count
                    all_done = False
                    break

        if all_done:
            data = {'cdn_domain': settings.DEFAULT_CDN_TILER_DOMAIN}
            print "Updating document finally"
            yield motor.Op(
                db.images.update,
                {'_id': document['_id']},
                {'$set': data}
            )
            # invalidate some redis keys
            _redis = redis.client.Redis(
                settings.REDIS_HOST,
                settings.REDIS_PORT
            )
            lock_key = 'uploading:%s' % fileid
            _redis.delete(lock_key)
            metadata_key = 'metadata:%s' % fileid
            # make it expire in a minute
            data = _redis.get(metadata_key)
            if data:
                # this gives all workers a chance to finish
                # any leftover jobs such as optimizations
                _redis.setex(metadata_key, data, 60)

    finally:
        print "# done", count
        IOLoop.instance().stop()


def get_aggressive_headers(years=1):
    cache_control = 'max-age=%d, public' % (3600 * 24 * 360 * years)
    _delta = datetime.timedelta(days=365 * years)
    expires = email.Utils.formatdate(
        time.mktime((datetime.datetime.utcnow() + _delta).timetuple())
    )

    return {
        'Cache-Control': cache_control,
        'Expires': expires,
    }


def upload_tiles(fileid, static_path, max_count=10,
                 only_if_no_cdn_domain=False,
                 replace=True):
    upload_all_tiles(
        fileid,
        static_path,
        settings.TILES_BUCKET_ID,
        max_count=max_count,
        only_if_no_cdn_domain=only_if_no_cdn_domain,
        replace=replace
    )
    IOLoop.instance().start()


def run(*fileids):
    static_path = os.path.join(os.path.abspath(os.curdir), 'static')
    for fileid in fileids:
        upload_original(fileid, 'jpg', static_path, settings.ORIGINALS_BUCKET_ID)

        #upload_all_tiles(fileid, static_path, settings.TILES_BUCKET_ID,
        #                 max_count=3)
        #IOLoop.instance().start()


if __name__ == '__main__':
    import sys
    run(*sys.argv[1:])
