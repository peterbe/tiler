import time
import os
from glob import glob
import subprocess
import stat


def optimize_images(image, zoom, extension, static_path):
    root = os.path.join(
        static_path,
        'tiles'
    )
    root = os.path.join(root, image, '256', str(zoom))
    total_before = 0
    search_path = os.path.join(root, '*.%s' % extension)
    files = glob(search_path)
    for each in files:
        size = os.stat(each)[stat.ST_SIZE]
        #print each, "IS", size
        total_before += size
    t0 = time.time()
    out, err = _optimize(files, extension)
    t1 = time.time()

    total_after = 0
    for each in files:
        total_after += os.stat(each)[stat.ST_SIZE]

    def kb(s):
        return "%.1fKb" % (s / 1000.0)

    print "Took", (t1 - t0), "seconds to optimize", len(files), "tiles"
    print "From", kb(total_before), "to", kb(total_after),
    print "saving", kb(total_before - total_after)

def optimize_thumbnails(image, extension, static_path):
    root = os.path.join(
        static_path,
        'thumbnails'
    )
    root = os.path.join(root, image)
    total_before = 0
    search_path = os.path.join(root, '*.%s' % extension)
    files = glob(search_path)
    for each in files:
        size = os.stat(each)[stat.ST_SIZE]
        print each, "IS", size
        total_before += size
    t0 = time.time()
    out, err = _optimize(files, extension)
    t1 = time.time()

    total_after = 0
    for each in files:
        total_after += os.stat(each)[stat.ST_SIZE]

    def kb(s):
        return "%.1fKb" % (s / 1000.0)

    print "Took", (t1 - t0), "seconds to optimize", len(files), "thumbnails"
    print "From", kb(total_before), "to", kb(total_after),
    print "Saving", kb(total_before - total_after)


def _optimize(files, extension):
    if extension == 'jpg':
        cmd = "jpegoptim --strip-all %s" % (' '.join(files))
    elif extension == 'png':
        cmd = "optipng %s" % (' '.join(files))
    else:
        raise NotImplementedError(extension)
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out, err = process.communicate()
    #print out
    #print 'ERRROR'
    #print err
    return (out, err)


if __name__ == '__main__':
    optimize_images('b/51/3acd3c', 3, 'png', './static')
