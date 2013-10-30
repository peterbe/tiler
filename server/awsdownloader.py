import os

from boto.s3.connection import Location, S3Connection
from boto.s3.key import Key

import settings


def download_original(relative_path, static_path, bucket_id):
    conn = S3Connection(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_KEY)
    bucket = conn.get_bucket(bucket_id)
    k = Key(bucket)
    k.key = relative_path
    destination = os.path.abspath(os.path.join(static_path, relative_path))
    k.get_contents_to_filename(destination)
