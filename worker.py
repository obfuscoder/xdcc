import json
import urllib2
import httplib
import time
import socket
import os
from datetime import datetime

url = 'http://localhost:4567/job'

while True:
    try:
        while True:
            response = urllib2.urlopen(url).read()
            if response != '':
                break
            time.sleep(30)

        job = json.loads(response)
        print job

        filename = job['name']
        current_file_size = 0
        if os.path.isfile(filename):
            current_file_size = os.path.getsize(filename)

        job_url = url + '/%d' % job['id']
        job_start_url = job_url + '/%d' % current_file_size

        start_request = urllib2.Request(job_start_url)
        start_request.get_method = lambda: 'POST'
        response = urllib2.urlopen(start_request).read()
        print json.loads(response)

        while True:
            time.sleep(5)
            response = urllib2.urlopen(job_url).read()
            job = json.loads(response)
            if job['status'] == 'started' or job['status'] == 'resume_accepted':
                break

        print job

        filename = job['name']
        size = job['size']
        ip_address = job['ip']
        port = job['port']

        print("Downloading %s which is %i Bytes in size" % (filename, size))
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(60)
        s.connect((ip_address, port))
        source = s.makefile()
        with open(filename, 'ab') as destination:

            bufsize = 2**22

            start = None
            total_start = datetime.now()
            bandwidth = '?'
            while True:
                position = os.path.getsize(filename)
                position_url = job_url + '/%i' % position
                position_request = urllib2.Request(position_url)
                position_request.get_method = lambda: 'PATCH'
                response = urllib2.urlopen(position_request).read()

                if position >= size:
                    break
                if start is not None:
                    now = datetime.now()
                    elapsed = now - start
                    bandwidth = "%.1f" % (bufsize / elapsed.total_seconds() / 1000)
                total_elapsed = datetime.now() - total_start
                average_bandwidth = "%.1f" % (position / total_elapsed.total_seconds() / 1000)
                print("%s - %i / %i (%i%%) at %s KB/s (avg %s KB/s)" % (filename, position, size, position * 100 / size, bandwidth, average_bandwidth))
                try:
                    start = datetime.now()
                    data = source.read(min(size - position, bufsize))
                except socket.error as e:
                    print 'Error downloading.'
                    print e
                    break
                if len(data) == 0:
                    break
                destination.write(data)
                destination.flush()

            actual_file_size = os.path.getsize(filename)
            position_url = job_url + '/%i' % actual_file_size
            position_request = urllib2.Request(position_url)
            position_request.get_method = lambda: 'POST'
            response = urllib2.urlopen(position_request).read()

            print("Download of %s finished" % filename)
            source.close()
            s.close()
            destination.close()

            if actual_file_size < size:
                print("file too short")
                continue

            finished_request = urllib2.Request(job_url)
            finished_request.get_method = lambda: 'DELETE'
            response = urllib2.urlopen(finished_request).read()
    except (urllib2.URLError, httplib.HTTPException, urllib2.HTTPError, socket.timeout) as error:
        print("!!!")
        print(error)
        time.sleep(10)
