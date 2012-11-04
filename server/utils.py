import time
import shutil
import os
from PIL import Image
import logging


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


_RESIZES = {}
_TIMESTAMPS = {}


def scale_and_crop(path, requested_size, row, col, zoom, image):
    im = Image.open(path)
    x, y = [float(v) for v in im.size]
    xr, yr = [float(v) for v in requested_size]
    r = min(xr / x, yr / y)

    box = (256 * row, 256 * col, 256 * (row + 1), 256 * (col + 1))

    w, h = int(round(x * r)), int(round(y * r))
    _cache_key = '%s-%s-%s' % (image, zoom, w)
    pathname, extension = os.path.splitext(path)

    _resized_file = path.replace(
        extension,
        '-%s-%s%s' % (zoom, w, extension)
    )

    already = _RESIZES.get(_cache_key)
    if already:
        im = already
    else:
        if os.path.isfile(_resized_file):
            print "REUSING", _resized_file
            logging.debug('REUSING %s' % _resized_file)
            im = Image.open(_resized_file)
            #print "Assert?", (im.size, (w,h))
        else:
            print "Need to resize... FAIL!"
            t0 = time.time()
            im = im.resize((w, h),
                           resample=Image.ANTIALIAS)
            t1 = time.time()
            logging.debug("SAVE RESIZED TO %s" % _resized_file)
            im.save(_resized_file)
            print "SAVE RESIZED TO", _resized_file
            print "\t", round(t1 - t0, 2), "seconds to resize"

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
    return im.crop(box)


def make_thumbnail(*args, **kwargs):  # wrapper on _make_thumbnail()
    t0 = time.time()
    result = _make_thumbnail(*args, **kwargs)
    t1 = time.time()
    #logging.warning("%s seconds to make thumbnail for %s" % (t1-t0, args[0]))
    print "%s seconds to make thumbnail for %s" % (t1-t0, args[0])
    return result


def _make_thumbnail(image, width, extension, static_path,
                    raise_error_if_not_found=False):
    root = os.path.join(
        static_path,
        'uploads'
    )
    save_root = os.path.join(
        static_path,
        'thumbnails'
    )
    if not os.path.isdir(save_root):
        os.mkdir(save_root)

    path = os.path.join(root, image)
    for i in ('.png', '.jpg'):
        path = os.path.join(root, image + i)
        if os.path.isfile(path):
            break
    else:
        if raise_error_if_not_found:
            raise IOError(image)
        else:
            return

    save_filepath = save_root
    save_filepath = os.path.join(save_filepath, image)
    if not os.path.isdir(save_filepath):
        mkdir(save_filepath)

    save_filepath = os.path.join(
        save_filepath,
        '%s.%s' % (width, extension)
    )
    if not os.path.isfile(save_filepath):
        thumbnail_image = _resize_thumbnail(
            path,
            width,
        )
        if thumbnail_image is not None:
            #print "Created", save_filepath
            thumbnail_image.save(save_filepath)

    return save_filepath

def _resize_thumbnail(path, width):
    t0 = time.time()
    im = Image.open(path)
    x, y = [float(v) for v in im.size]
    xr, yr = [float(v) for v in (width, width)]
    r = min(xr / x, yr / y)
    w, h = int(round(x * r)), int(round(y * r))
    im = im.resize((w, h),
                   resample=Image.ANTIALIAS)
    t1 = time.time()
    print "Took", round(t1 - t0, 2), "seconds to resize thumbnail", path
    return im



def make_tile(image, size, zoom, row, col, extension, static_path):

    size = int(size)
    zoom = int(zoom)
    row = int(row)
    col = int(col)

    assert size == 256, size

    root = os.path.join(
        static_path,
        'uploads'
    )
    if not os.path.isdir(root):
        os.mkdir(root)
    save_root = os.path.join(
        static_path,
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
        raise IOError(image)

    save_filepath = save_root
    for p in (image, str(size), str(zoom)):
        save_filepath = os.path.join(save_filepath, p)
        if not os.path.isdir(save_filepath):
            try:
                mkdir(save_filepath)
            except OSError:
                # because this function is called concurrently by the queue
                # workers this is not thread safe so it might raise an OSError
                # even though the file already exists
                from time import sleep
                sleep(0.1)
                if not os.path.isdir(save_filepath):
                    raise
    save_filepath = os.path.join(
        save_filepath,
        '%s,%s.%s' % (row, col, extension)
    )
    if not os.path.isfile(save_filepath):
        #print "From", image, "make", '%s,%s.%s' % (row, col, extension)
        width = size * (2 ** zoom)
        cropped_image = scale_and_crop(
            path,
            (width, width),
            row, col,
            zoom=zoom,
            image=image,
        )
        if cropped_image is not None:
            #print "Created", save_filepath
            cropped_image.save(save_filepath)

    return save_filepath


def make_tiles(image, size, zoom, rows, cols, extension, static_path):
    # this is an "optimization" over make_tile() since we make one Image
    # instance and re-use it for every row and every column.
    for row in range(rows + 1):
        for col in range(cols + 1):
            make_tile(image, size, zoom, row, col, extension, static_path)


def delete_image(image, static_path):
    uploads_root = os.path.join(
        static_path,
        'uploads'
    )

    bits = image.split('/')
    fileid = bits.pop()
    uploads = os.path.join(uploads_root, '/'.join(bits))
    for f in os.listdir(uploads):
        if fileid in f:
            os.remove(os.path.join(uploads, f))

    thumbnails_root = os.path.join(
        static_path,
        'thumbnails'
    )
    tiles_root = os.path.join(
        static_path,
        'tiles'
    )

    for root in (thumbnails_root, tiles_root):
        dir_ = os.path.join(root, image)
        shutil.rmtree(dir_)


def find_original(fileid, static_path, extension):
    image = fileid[:1] + '/' + fileid[1:3] + '/' + fileid[3:]
    root = os.path.join(
        static_path,
        'uploads'
    )
    path = os.path.join(root, image + '.' + extension)
    return os.path.isfile(path) and path or None


def count_all_tiles(fileid, static_path):
    return len(list(find_all_tiles(fileid, static_path)))


def find_all_tiles(fileid, static_path):
    image = fileid[:1] + '/' + fileid[1:3] + '/' + fileid[3:]
    tiles_root = os.path.join(
        static_path,
        'tiles'
    )

    def walk(in_):
        here = []
        for f in os.listdir(in_):
            p = os.path.join(in_, f)
            if os.path.isdir(p):
                here.extend(walk(p))
            elif os.path.isfile(p):
                here.append(p)
        return here

    dir_ = os.path.join(tiles_root, image)
    if os.path.isdir(dir_):
        for each in walk(dir_):
            yield each
