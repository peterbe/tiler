import stat
import warnings
import random
import os
import motor
import pymongo
from boto.s3.connection import Location, S3Connection
from boto.s3.key import Key
from tornado import gen
from tornado.ioloop import IOLoop
import settings
from utils import find_all_tiles, find_original


def upload_original(fileid, extension, static_path, bucket_id):
    conn = S3Connection(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_KEY)
    bucket = conn.lookup(bucket_id) or conn.create_bucket(bucket_id, location=Location.EU)

    db_connection = motor.MotorConnection().open_sync()
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


@gen.engine
def upload_all_tiles(fileid, static_path, bucket_id, max_count=0,
                     only_if_no_cdn_domain=False):
    log_file = os.path.join(static_path, 'upload.%s.txt' % fileid)

    conn = S3Connection(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_KEY)
    bucket = conn.lookup(bucket_id) or conn.create_bucket(bucket_id, location=Location.EU)
    #bucket.set_acl('public-read')

    db_connection = motor.MotorConnection().open_sync()
    db = db_connection[settings.DATABASE_NAME]

    document = yield motor.Op(
        db.images.find_one,
        {'fileid': fileid}
    )

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
                print "uploading", relative_path
                k.set_contents_from_filename(
                    each,
                    # because we sometimes reset and thus might
                    # upload it again
                    replace=False,
                    reduced_redundancy=True
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

    finally:
        print "# done", count
        IOLoop.instance().stop()



def upload_tiles(fileid, static_path, max_count=10,
                 only_if_no_cdn_domain=False):
    upload_all_tiles(
        fileid,
        static_path,
        settings.TILES_BUCKET_ID,
        max_count=max_count,
        only_if_no_cdn_domain=only_if_no_cdn_domain
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
