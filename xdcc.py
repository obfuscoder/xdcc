import socket
import os
import thread
import time
import random
from datetime import datetime
from collections import deque

HOST = 'irc.abjects.net'
PORT = 6667
CHANS = ('#beast-xdcc', '#beast-chat', '#moviegods', '#mg-chat')
QUEUE = deque()
DONE = deque()

def log(message):
	print "%s\t%s" % (datetime.now(), message)

	
def add():
    files = [f for f in os.listdir('add') if os.path.isfile(os.path.join('add', f))]
    for file in files:
        p = os.path.join('add', file)
        f = open(p, 'r')
        while 1:
            l = f.readline().strip()
            if l == '':
                break
            (nick, number, filename) = l.split("\t")[:3]
            QUEUE.append({'nick': nick, 'number': long(number), 'filename': filename, 'status': 'new'})
            store()
        f.close()
        os.remove(p)


def entry_to_line(qe):
    return "%s\t%i\t%s\t%s\n" % (qe['nick'], qe['number'], qe['filename'], qe['status'])


def write_collection(queue, filename, mode):
    f = open(filename, mode)
    for qe in queue:
        f.write(entry_to_line(qe))
    f.close()


def failed(qe):
    append('failed.txt', qe)


def done(qe):
    append('done.txt', qe)


def append(filename, qe):
    f = open(filename, 'a')
    f.write("%s\t%s" % (datetime.now(), entry_to_line(qe)))
    f.close()


def load():
    f = open('queue.txt', 'r')
    while 1:
        l = f.readline().strip()
        if l == '':
            break
        (nick, number, filename) = l.split("\t")[:3]
        QUEUE.append({'nick': nick, 'number': long(number), 'filename': filename, 'status': 'new'})
    f.close()


def store():
    write_collection(QUEUE, 'queue.txt', 'w')


def send(f, msg):
    log("SEND: %s" % msg)
    f.write(msg)
    f.write('\r\n')
    f.flush()


def download(qe, filename, addrnumber, port, size):
    qe['status'] = 'downloading'
    store()
    log("Downloading %s which is %i Bytes in size" % (filename, size))
    ipaddress = '%i.%i.%i.%i' % (addrnumber / 2**24, addrnumber % 2**24 / 2**16, addrnumber % 2**16 / 256, addrnumber % 256)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((ipaddress, port))
    source = s.makefile()
    destination = open(filename, 'ab')
    bufsize = 2**20
    while 1:
        position = os.path.getsize(filename)
        if position >= size:
            break
        log("%s - %i / %i (%i%%)" % (filename, position, size, position * 100 / size))
        try:
            data = source.read(min(size - position, bufsize))
        except socket.error as e:
            log('Error downloading.')
            break
        if len(data) == 0:
            break
        destination.write(data)
        destination.flush()
    log("Download finished")
    source.close()
    s.close()
    destination.close()
    actual_file_size = os.path.getsize(filename)
    QUEUE.popleft()
    if actual_file_size < size:
        qe['status'] = 'file_too_short'
        failed(qe)
    else:
        qe['status'] = 'done'
        done(qe)
    store()


load()
log("Connecting to %s ..." % HOST)
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))
sf = s.makefile()
my_nick = "habi%i" % random.randint(1, 500)
my_nick_tag = ':%s' % my_nick
send(sf, 'NICK %s' % my_nick)
send(sf, 'USER %s 0 * %s' % (my_nick, my_nick_tag))

ipaddress = 0
size = 0
active = 0
joining = 0

while 1:
    add()
    qe = None
    if len(QUEUE) > 0:
        qe = QUEUE[0]
    if active and qe is not None:
        if qe['status'] == 'new' or (qe['status'] != 'downloading' and qe['time'] + 5*60 < time.time()):
            send(sf, "PRIVMSG %s :xdcc send #%i" % (qe['nick'], qe['number']))
            qe['status'] = 'requested'
            qe['time'] = time.time()
            store()
            continue
    line = sf.readline().strip()
    if line == '':
        continue
    log("RECV: %s" % line)
    (source, rest) = line.split(' ', 1)
    if source == 'ERROR':
        break
    if source == 'PING':
        send(sf, 'PONG %s' % rest)
    if (source == my_nick_tag or rest.find('MODE %s' % my_nick) >= 0) and joining == 0:
        joining = 1
        for channel in CHANS:
            send(sf, 'JOIN %s' % channel)
    if rest.find('366') == 0:  # end of names list
        active = 1
    if qe is None:
        continue
    if rest.find('401 %s %s' % (my_nick, qe['nick'])) == 0:
        qe['status'] = 'offline'
        QUEUE.popleft()
        failed(qe)
        store()
        continue
    if source.find(':%s!' % qe['nick']) == 0:
        (message, nick, rest) = rest.split(' ', 2)
        if message == 'NOTICE' and nick == my_nick:
            if rest.find('Invalid Pack Number') >= 0:
                qe['status'] = 'invalid'
                QUEUE.popleft()
                failed(qe)
                store()
                continue
        if message == 'PRIVMSG' and nick == my_nick:
            if rest.find("\1DCC SEND") >= 0:
                (lead, dccinfo, trail) = rest.split("\1")
                dcc_params = dccinfo.split(' ')
                filename = dcc_params[2]
                ipaddress = long(dcc_params[3])
                port = long(dcc_params[4])
                size = long(dcc_params[5])
                if port == 0 and len(dcc_params) == 7:
                    qe['status'] = 'reverse_dcc_required'
                    QUEUE.popleft()
                    failed(qe)
                    store()
                    send(sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
                    send(sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])
                    continue
                if filename != qe['filename']:
                    qe['status'] = 'wrong_filename'
                    QUEUE.popleft()
                    failed(qe)
                    store()
                    send(sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
                    send(sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])
                    continue
                if os.path.isfile(filename) and os.path.getsize(filename) > 0:
                    filesize = os.path.getsize(filename)
                    if filesize >= size:
                        qe['status'] = 'done'
                        QUEUE.popleft()
                        done(qe)
                        store()
                        send(sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
                        send(sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])
                        continue
                    else:
                        send(sf, "PRIVMSG %s :\1DCC RESUME %s %i %i\1" % (qe['nick'], filename, port, filesize))
                else:
                    thread.start_new_thread(download, (qe, filename, ipaddress, port, size))
            if rest.find('DCC ACCEPT') > 0:
                (lead, dccinfo, trail) = rest.split("\1")
                (dcc, accept, filename, port, position) = dccinfo.split(' ')
                thread.start_new_thread(download, (qe, filename, ipaddress, long(port), size))

