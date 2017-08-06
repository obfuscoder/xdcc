import socket
import os
import thread
import time
import random
import re
from datetime import datetime
from collections import deque

DEBUG = 0

SERVERS = [
    {
        'network': 'scenep2p', 'host': 'irc.scenep2p.net', 'port': 6667,
        'channels': ['#THE.SOURCE']
    },
    {
        'network': 'abjects', 'host': 'irc.abjects.net', 'port': 6667,
        'channels': ['#beast-xdcc', '#beast-chat', '#moviegods', '#mg-chat']
    },
]


QUEUE = deque()

NICK = "habi%i" % random.randint(1, 500)


def load_queue():
    f = open('queue.txt', 'r')
    while 1:
        l = f.readline().strip()
        if l == '':
            break
        (network, nick, number, filename) = l.split("\t")[:4]
        QUEUE.append({'network': network, 'nick': nick, 'number': long(number), 'filename': filename, 'status': 'new'})
    f.close()


class Xdcc:
    def __init__(self, config):
        self.network = config['network']
        self.host = config['host']
        self.port = config['port']
        self.channels = config['channels']

    def start(self):
        thread.start_new_thread(self.run, ())

    def log(self, message):
        print "%s\t%s\t%s" % (datetime.now(), self.network, message)

    def failed(self, qe):
        self.append('failed.txt', qe)

    def done(self, qe):
        qe['status'] = 'done'
        self.append('done.txt', qe)
        QUEUE.remove(qe)
        store_queue()

    def offer(self, channel, nick, number, filename, gets, size):
        filename = self.strip_format_codes(filename)
        line = "%s\t%s\t%s\t%s\t%i\t%s\t%i\t%s\n" % (datetime.now(), self.network, channel, nick, number, filename, gets, size)
        f = open('offers.txt', 'a')
        f.write(line)
        f.close()

    def strip_format_codes(self, str):
        regex = re.compile("\x1f|\x02|\x12|\x0f|\x16|\x03(?:\d{1,2}(?:,\d{1,2})?)?", re.UNICODE)
        return regex.sub("", str)

    def append(self, filename, qe):
        f = open(filename, 'a')
        f.write("%s\t%s" % (datetime.now(), entry_to_line(qe)))
        f.close()

    def store_queue(self):
        write_collection(QUEUE, 'queue.txt', 'w')

    def send(self, f, msg):
        if DEBUG == 1:
            self.log("SEND: %s" % msg)
        f.write(msg)
        f.write('\r\n')
        f.flush()

    def download(self, qe, filename, addr_number, port, size):
        qe['status'] = 'downloading'
        store_queue()
        self.log("Downloading %s which is %i Bytes in size" % (filename, long(size)))
        ip_address = '%i.%i.%i.%i' % (addr_number / 2 ** 24, addr_number % 2 ** 24 / 2 ** 16, addr_number % 2 ** 16 / 256, addr_number % 256)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((ip_address, port))
        source = s.makefile()
        destination = open(filename, 'ab')
        bufsize = 2**20
        while 1:
            position = os.path.getsize(filename)
            if position >= size:
                break
            self.log("%s - %i / %i (%i%%)" % (filename, position, size, position * 100 / size))
            try:
                data = source.read(min(size - position, bufsize))
            except socket.error as e:
                self.log('Error downloading.')
                break
            if len(data) == 0:
                break
            destination.write(data)
            destination.flush()
        self.log("Download of %s finished" % qe['filename'])
        source.close()
        s.close()
        destination.close()
        actual_file_size = os.path.getsize(filename)
        if actual_file_size < size:
            self.fail_with_status(qe, 'file_too_short')
        else:
            self.done(qe)

    def run(self):
        sf = self.connect()
        self.send_user_info(sf)

        ip_address = 0
        size = 0
        active = 0
        joining = 0

        while 1:
            qe = None
            for item in QUEUE:
                if item['network'] == self.network:
                    qe = item
                    break
            if active and qe is not None:
                if qe['status'] == 'new' or (qe['status'] == 'requested' and qe['time'] + 5*60 < time.time()):
                    self.send_request(sf, qe)
            line = sf.readline().strip()
            if line == '':
                continue
            if DEBUG == 1:
                self.log("RECV: %s" % line)
            (source, rest) = line.split(' ', 1)
            if source == 'ERROR':
                self.log('RECEIVED ERROR. Exiting!')
                break
            if source == 'PING':
                self.send(sf, 'PONG %s' % rest)
                continue
            if (source == ":%s" % NICK or rest.find('MODE %s' % NICK) >= 0) and joining == 0:
                self.join_channels(sf)
                joining = 1
                continue
            if rest.find('366') == 0:  # end of names list
                active = 1
            m = re.match(':(.+)!.+@.+', source)
            if m is not None:
                nick = m.group(1)
                (action, trail) = rest.split(' ', 1)
                # :<botname>!xxxxxxx PRIVMSG #<channel> :#<number>  <downloads>x [<size>] <filename>
                if action == 'PRIVMSG':
                    (target, data) = trail.split(' ', 1)
                    if target in self.channels:
                        m = re.match('.*?#(\d+).*? +(\d+)x \[(.*?)] (.*)', data)
                        if m is not None:
                            number = long(m.group(1))
                            gets = long(m.group(2))
                            size = m.group(3)
                            filename = m.group(4)
                            self.offer(target, nick, number, filename, gets, size)
                        continue
            if qe is None:
                continue
            if rest.find('401 %s %s' % (NICK, qe['nick'])) == 0:
                self.fail_with_offline(qe)
                continue
            if source.find(':%s!' % qe['nick']) == 0:
                (message, nick, rest) = rest.split(' ', 2)
                if message == 'NOTICE' and nick == NICK:
                    self.log("Received notice from %s: %s" % (qe['nick'], rest))
                    if rest.find('Invalid Pack Number') >= 0:
                        self.fail_with_invalid(qe)
                        continue
                    if rest.find('You already requested that pack') >= 0:
                        self.requested(qe)
                    if rest.find('All Slots Full') >= 0:
                        if rest.find('Added you to the main queue') >= 0 or rest.find('You already have that item queued') >= 0:
                            self.queued(qe)
                    continue
                if message == 'PRIVMSG' and nick == NICK:
                    self.log("RECV: %s" % line)
                    if rest.find("\1DCC SEND") >= 0:
                        dcc_params, filename, ip_address, port, size = self.parse_dcc_send_message(rest)
                        if port == 0 and len(dcc_params) == 7:
                            self.fail_with_reverse_dcc(filename, qe, sf)
                            continue
                        if filename != qe['filename']:
                            self.fail_with_wrong_file_name(filename, qe, sf)
                            continue
                        if os.path.isfile(filename) and os.path.getsize(filename) > 0:
                            filesize = os.path.getsize(filename)
                            if filesize >= size:
                                self.abort_resend_and_move_to_done(filename, qe, sf)
                            else:
                                self.send_resume(filename, filesize, port, qe, sf)
                        else:
                            thread.start_new_thread(self.download, (qe, filename, ip_address, port, size))
                        continue
                    if rest.find('DCC ACCEPT') > 0:
                        self.start_dcc_download(ip_address, qe, rest, size)
                        continue

    def parse_dcc_send_message(self, message):
        (lead, dcc_info, trail) = message.split("\1")
        dcc_params = dcc_info.split(' ')
        filename = dcc_params[2]
        ip_address = long(dcc_params[3])
        port = long(dcc_params[4])
        size = long(dcc_params[5])
        return dcc_params, filename, ip_address, port, size

    def start_dcc_download(self, ip_address, qe, rest, size):
        (lead, dccinfo, trail) = rest.split("\1")
        (dcc, accept, filename, port, position) = dccinfo.split(' ')
        thread.start_new_thread(self.download, (qe, filename, ip_address, long(port), size))

    def send_resume(self, filename, filesize, port, qe, sf):
        self.log("Resuming %s which is %i Bytes in size" % (filename, filesize))
        self.send(sf, "PRIVMSG %s :\1DCC RESUME %s %i %i\1" % (qe['nick'], filename, port, filesize))

    def abort_resend_and_move_to_done(self, filename, qe, sf):
        self.log("Aborting resend of done %s" % filename)
        self.done(qe)
        self.send(sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
        self.send(sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])

    def fail_with_wrong_file_name(self, filename, qe, sf):
        self.log("Failed download from %s. Expected file %s but received %s" % (qe['nick'], qe['filename'], filename))
        self.fail_with_status(qe, 'wrong_filename')
        self.send(sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
        self.send(sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])

    def fail_with_reverse_dcc(self, filename, qe, sf):
        self.log("Failed download from %s for %s. Revere DCC not supported." % (qe['nick'], filename))
        self.fail_with_status(qe, 'reverse_dcc_required')
        self.send(sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
        self.send(sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])

    def fail_with_invalid(self, qe):
        self.log("Failed download from %s for %s. Invalid packet number." % (qe['nick'], qe['filename']))
        self.fail_with_status(qe, 'invalid')

    def fail_with_status(self, qe, status):
        qe['status'] = status
        QUEUE.remove(qe)
        self.failed(qe)
        store_queue()

    def fail_with_offline(self, qe):
        self.log("Failed download from %s for %s. Bot offline." % (qe['nick'], qe['filename']))
        self.fail_with_status(qe, 'offline')

    def join_channels(self, sf):
        for channel in self.channels:
            self.log("Joining %s" % channel)
            self.send(sf, 'JOIN %s' % channel)

    def send_request(self, sf, qe):
        self.log("Requesting packet %i (%s) from %s" % (qe['number'], qe['filename'], qe['nick']))
        self.send(sf, "PRIVMSG %s :xdcc send #%i" % (qe['nick'], qe['number']))
        self.requested(qe)

    def requested(self, qe):
        qe['status'] = 'requested'
        qe['time'] = time.time()
        store_queue()

    def queued(self, qe):
        self.log("Request of %s has been queued by %s" % (qe['filename'], qe['nick']))
        qe['status'] = 'queued'
        qe['time'] = time.time()
        store_queue()

    def connect(self):
        self.log("Connecting to %s ..." % self.host)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((self.host, self.port))
        return s.makefile()

    def send_user_info(self, sf):
        self.send(sf, 'NICK %s' % NICK)
        self.send(sf, 'USER %s 0 * :%s' % (NICK, NICK))


def xdcc(servers):
    load_queue()
    for server in servers:
        Xdcc(server).start()
    while 1:
        time.sleep(5)
        add()


def add():
    files = [f for f in os.listdir('add') if os.path.isfile(os.path.join('add', f))]
    for file in files:
        p = os.path.join('add', file)
        f = open(p, 'r')
        while 1:
            l = f.readline().strip()
            if l == '':
                break
            (network, nick, number, filename) = l.split("\t")[:4]
            QUEUE.append({'network': network, 'nick': nick, 'number': long(number), 'filename': filename, 'status': 'new'})
            store_queue()
        f.close()
        os.remove(p)


def store_queue():
    write_collection(QUEUE, 'queue.txt', 'w')


def entry_to_line(qe):
    return "%s\t%s\t%i\t%s\t%s\n" % (qe['network'], qe['nick'], qe['number'], qe['filename'], qe['status'])


def write_collection(queue, filename, mode):
    f = open(filename, mode)
    for qe in queue:
        f.write(entry_to_line(qe))
    f.close()


xdcc(SERVERS)
