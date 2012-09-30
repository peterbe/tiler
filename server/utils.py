import time
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


def scale_and_crop(path, requested_size, row, col, zoom=None, image=None):
    im = Image.open(path)
    x, y = [float(v) for v in im.size]
    xr, yr = [float(v) for v in requested_size]
    r = min(xr / x, yr / y)

    w, h = int(round(x * r)), int(round(y * r))
    _cache_key = '%s-%s-%s-%s' % (image, zoom, w, h)
    pathname, extension = os.path.splitext(path)

    _resized_file = path.replace(
        extension,
        '-%s-%s-%s%s' % (zoom, w, h, extension)
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
            print "Need to resize..."
            im = im.resize((w, h),
                           resample=Image.ANTIALIAS)
            logging.debug("SAVE RESIZED TO %s" % _resized_file)
            #print "SAVE RESIZED TO", _resized_file
            im.save(_resized_file)


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
    box = (256 * row, 256 * col, 256 * (row + 1), 256 * (col + 1))
    im = im.crop(box)

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

    width = size * (2 ** zoom)
    save_filepath = save_root
    for p in (image, str(size), str(zoom)):
        save_filepath = os.path.join(save_filepath, p)
        if not os.path.isdir(save_filepath):
            mkdir(save_filepath)
    save_filepath = os.path.join(
        save_filepath,
        '%s,%s.%s' % (row, col, extension)
    )

    if not os.path.isfile(save_filepath):
        image = scale_and_crop(
            path,
            (width, width),
            row, col,
            zoom=zoom,
            image=image,
        )
        image.save(save_filepath)

    return save_filepath
