import re
import cStringIO
import functools
import pycurl


def download(url, destination,
            follow_redirects=True, request_timeout=600):
    _error = _effective_url = None
    with open(destination, 'wb') as destination_file:
        hdr = cStringIO.StringIO()
        c = pycurl.Curl()
        c.setopt(pycurl.URL, str(url))
        c.setopt(pycurl.FOLLOWLOCATION, follow_redirects)
        c.setopt(pycurl.HEADERFUNCTION, hdr.write)
        c.setopt(pycurl.WRITEFUNCTION, destination_file.write)
        c.setopt(pycurl.TIMEOUT_MS, int(1000 * request_timeout))
        c.perform()
        code = c.getinfo(pycurl.HTTP_CODE)
        _effective_url = c.getinfo(pycurl.EFFECTIVE_URL)
        if _effective_url == url:
            _effective_url = None
        code = c.getinfo(pycurl.HTTP_CODE)
        if code != 200:
            status_line = hdr.getvalue().splitlines()[0]
            for each in re.findall(r'HTTP\/\S*\s*\d+\s*(.*?)\s*$', status_line):
                _error = each

    response = {'code': code}
    if _error:
        response['body'] = _error
    if _effective_url:
        response['url'] = _effective_url
    return response


if __name__ == '__main__':
    import sys
    import os
    url = sys.argv[1]
    assert '://' in url
    destination = sys.argv[2]
    assert os.path.isdir(os.path.dirname(destination))
    from pprint import pprint
    pprint(download(url, destination))
