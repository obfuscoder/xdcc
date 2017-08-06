import socket
import os
import thread
import time
import random
import re
from datetime import datetime
from collections import deque

DEBUG=0

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


def log(network, message):
    print "%s\t%s\t%s" % (datetime.now(), network, message)


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


def entry_to_line(qe):
    return "%s\t%s\t%i\t%s\t%s\n" % (qe['network'], qe['nick'], qe['number'], qe['filename'], qe['status'])


def write_collection(queue, filename, mode):
    f = open(filename, mode)
    for qe in queue:
        f.write(entry_to_line(qe))
    f.close()


def failed(qe):
    append('failed.txt', qe)


def done(qe):
    append('done.txt', qe)


def offer(network, channel, nick, number, filename, gets, size):
    filename = strip_format_codes(filename)
    line = "%s\t%s\t%s\t%s\t%i\t%s\t%i\t%s\n" % (datetime.now(), network, channel, nick, number, filename, gets, size)
    f = open('offers.txt', 'a')
    f.write(line)
    f.close()


def strip_format_codes(str):
    regex = re.compile("\x1f|\x02|\x12|\x0f|\x16|\x03(?:\d{1,2}(?:,\d{1,2})?)?", re.UNICODE)
    return regex.sub("", str)


def append(filename, qe):
    f = open(filename, 'a')
    f.write("%s\t%s" % (datetime.now(), entry_to_line(qe)))
    f.close()


def load_queue():
    f = open('queue.txt', 'r')
    while 1:
        l = f.readline().strip()
        if l == '':
            break
        (network, nick, number, filename) = l.split("\t")[:4]
        QUEUE.append({'network': network, 'nick': nick, 'number': long(number), 'filename': filename, 'status': 'new'})
    f.close()


def store_queue():
    write_collection(QUEUE, 'queue.txt', 'w')


def send(network, f, msg):
    if DEBUG == 1:
        log(network, "SEND: %s" % msg)
    f.write(msg)
    f.write('\r\n')
    f.flush()


def download(qe, filename, addrnumber, port, size):
    qe['status'] = 'downloading'
    store_queue()
    log(qe['network'], "Downloading %s which is %i Bytes in size" % (filename, long(size)))
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
        log(qe['network'], "%s - %i / %i (%i%%)" % (filename, position, size, position * 100 / size))
        try:
            data = source.read(min(size - position, bufsize))
        except socket.error as e:
            log(qe['network'], 'Error downloading.')
            break
        if len(data) == 0:
            break
        destination.write(data)
        destination.flush()
    log(qe['network'], "Download of %s finished" % qe['filename'])
    source.close()
    s.close()
    destination.close()
    actual_file_size = os.path.getsize(filename)
    QUEUE.remove(qe)
    if actual_file_size < size:
        qe['status'] = 'file_too_short'
        failed(qe)
    else:
        qe['status'] = 'done'
        done(qe)
    store_queue()


def xdcc(servers):
    log('', "Using nick %s" % NICK)
    load_queue()
    for server in servers:
        thread.start_new_thread(run, (server,))
    while 1:
        time.sleep(5)
        add()


def run(server):
    sf = connect(server['network'], server['host'], server['port'])
    send_user_info(server['network'], sf, NICK)

    ipaddress = 0
    size = 0
    active = 0
    joining = 0

    while 1:
        qe = None
        # next((qe for qe in QUEUE if qe['network'] == server['network']), None)
        for item in QUEUE:
            if item['network'] == server['network']:
                qe = item
                break
        if active and qe is not None:
            if qe['status'] == 'new' or (qe['status'] == 'requested' and qe['time'] + 5*60 < time.time()):
                send_request(sf, qe)
        line = sf.readline().strip()
        if line == '':
            continue
        if DEBUG == 1:
            log(server['network'], "RECV: %s" % line)
        (source, rest) = line.split(' ', 1)
        if source == 'ERROR':
            log(server['network'], 'RECEIVED ERROR. Exiting!')
            break
        if source == 'PING':
            send(server['network'], sf, 'PONG %s' % rest)
            continue
        if (source == ":%s" % NICK or rest.find('MODE %s' % NICK) >= 0) and joining == 0:
            join_channels(server['network'], sf, server['channels'])
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
                if target in server['channels']:
                    m = re.match('.*?#(\d+).*? +(\d+)x \[(.*?)] (.*)', data)
                    if m is not None:
                        number = long(m.group(1))
                        gets = long(m.group(2))
                        size = m.group(3)
                        filename = m.group(4)
                        offer(server['network'], target, nick, number, filename, gets, size)
                    continue
        if qe is None:
            continue
        if rest.find('401 %s %s' % (NICK, qe['nick'])) == 0:
            fail_with_offline(qe)
            continue
        if source.find(':%s!' % qe['nick']) == 0:
            (message, nick, rest) = rest.split(' ', 2)
            if message == 'NOTICE' and nick == NICK:
                log(server['network'], "Received notice from %s: %s" % (qe['nick'], rest))
                if rest.find('Invalid Pack Number') >= 0:
                    fail_with_invalid(qe)
                    continue
                if rest.find('You already requested that pack') >= 0:
                    requested(qe)
                if rest.find('All Slots Full') >= 0:
                    if rest.find('Added you to the main queue') >= 0 or rest.find('You already have that item queued') >= 0:
                        queued(qe)
                continue
            if message == 'PRIVMSG' and nick == NICK:
                log(server['network'], "RECV: %s" % line)
                if rest.find("\1DCC SEND") >= 0:
                    dcc_params, filename, ipaddress, port, size = parse_dcc_send_message(rest)
                    if port == 0 and len(dcc_params) == 7:
                        fail_with_reverse_dcc(filename, qe, sf)
                        continue
                    if filename != qe['filename']:
                        fail_with_wrong_file_name(filename, qe, sf)
                        continue
                    if os.path.isfile(filename) and os.path.getsize(filename) > 0:
                        filesize = os.path.getsize(filename)
                        if filesize >= size:
                            abort_resend_and_move_to_done(filename, qe, sf)
                        else:
                            send_resume(filename, filesize, port, qe, sf)
                    else:
                        thread.start_new_thread(download, (qe, filename, ipaddress, port, size))
                    continue
                if rest.find('DCC ACCEPT') > 0:
                    start_dcc_download(ipaddress, qe, rest, size)
                    continue


def parse_dcc_send_message(message):
    (lead, dccinfo, trail) = message.split("\1")
    dcc_params = dccinfo.split(' ')
    filename = dcc_params[2]
    ipaddress = long(dcc_params[3])
    port = long(dcc_params[4])
    size = long(dcc_params[5])
    return dcc_params, filename, ipaddress, port, size


def start_dcc_download(ipaddress, qe, rest, size):
    (lead, dccinfo, trail) = rest.split("\1")
    (dcc, accept, filename, port, position) = dccinfo.split(' ')
    thread.start_new_thread(download, (qe, filename, ipaddress, long(port), size))


def send_resume(filename, filesize, port, qe, sf):
    log(qe['network'], "Resuming %s which is %i Bytes in size" % (filename, filesize))
    send(qe['network'], sf, "PRIVMSG %s :\1DCC RESUME %s %i %i\1" % (qe['nick'], filename, port, filesize))


def abort_resend_and_move_to_done(filename, qe, sf):
    log(qe['network'], "Aborting resend of done %s" % filename)
    qe['status'] = 'done'
    QUEUE.remove(qe)
    done(qe)
    store_queue()
    send(qe['network'], sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
    send(qe['network'], sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])


def fail_with_wrong_file_name(filename, qe, sf):
    log(qe['network'], "Failed download from %s. Expected file %s but received %s" % (qe['nick'], qe['filename'], filename))
    qe['status'] = 'wrong_filename'
    QUEUE.remove(qe)
    failed(qe)
    store_queue()
    send(qe['network'], sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
    send(qe['network'], sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])


def fail_with_reverse_dcc(filename, qe, sf):
    log(qe['network'], "Failed download from %s for %s. Revere DCC not supported." % (qe['nick'], filename))
    qe['status'] = 'reverse_dcc_required'
    QUEUE.remove(qe)
    failed(qe)
    store_queue()
    send(qe['network'], sf, "NOTICE %s :\1DCC REJECT SEND %s\1" % (qe['nick'], filename))
    send(qe['network'], sf, "PRIVMSG %s :XDCC CANCEL" % qe['nick'])


def fail_with_invalid(qe):
    log(qe['network'], "Failed download from %s for %s. Invalid packet number." % (qe['nick'], qe['filename']))
    qe['status'] = 'invalid'
    QUEUE.remove(qe)
    failed(qe)
    store_queue()


def fail_with_offline(qe):
    log(qe['network'], "Failed download from %s for %s. Bot offline." % (qe['nick'], qe['filename']))
    qe['status'] = 'offline'
    QUEUE.remove(qe)
    failed(qe)
    store_queue()


def join_channels(network, sf, channels):
    for channel in channels:
        log(network, "Joining %s" % channel)
        send(network, sf, 'JOIN %s' % channel)


def send_request(sf, qe):
    log(qe['network'], "Requesting packet %i (%s) from %s" % (qe['number'], qe['filename'], qe['nick']))
    send(qe['network'], sf, "PRIVMSG %s :xdcc send #%i" % (qe['nick'], qe['number']))
    requested(qe)


def requested(qe):
    qe['status'] = 'requested'
    qe['time'] = time.time()
    store_queue()


def queued(qe):
    log(qe['network'], "Request of %s has been queued by %s" % (qe['filename'], qe['nick']))
    qe['status'] = 'queued'
    qe['time'] = time.time()
    store_queue()


def connect(network, host, port):
    log(network, "Connecting to %s ..." % host)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s.makefile()


def send_user_info(network, sf, nick):
    send(network, sf, 'NICK %s' % nick)
    send(network, sf, 'USER %s 0 * :%s' % (nick, nick))


xdcc(SERVERS)
