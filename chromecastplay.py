#!/usr/bin/env python3
import itertools
import argparse
import socket
import curses
import atexit
import time
import re
import os
from tempfile import NamedTemporaryFile
from multiprocessing import Process
from subprocess import Popen
import pychromecast
import chardet
from twisted.web.server import Site, Request
from twisted.web.resource import Resource
from twisted.internet import reactor, endpoints
from twisted.web.static import File, Data


VIDEO_PATH = 'video'
SUB_PATH = 'sub'

DEFAULT_MIME = 'video/mp4'

TRANSCODER_BITRATE = '6000k'
TRANSCODER_BUFSIZE = 60000000


def read_sub(filename):
    contents = read_contents(filename)
    if not filename.endswith('.vtt'):
        # if extension is not .vtt, assume format is srt
        contents = srt2vtt(contents)
    return contents.encode('utf-8')


def read_contents(filename):
    with open(filename, 'rb') as f:
        result = chardet.detect(f.read())
        encoding = result['encoding']
    with open(filename, 'rU', encoding=encoding) as f:
        return f.read()


def srt2vtt(contents):
    def convert_cue(cue):
        m = re.search(r'(\d+:\d+:\d+)(?:,(\d+))?\s*--?>'
                      r'\s*(\d+:\d+:\d+)(?:,(\d+))?\s*(.*)',
                      cue,
                      re.DOTALL)
        if m:
            return '{}.{} --> {}.{}\n{}'\
                   .format(m.group(1), m.group(2) or '000',
                           m.group(3), m.group(4) or '000',
                           m.group(5).strip())
        return ''

    cues = contents.split('\n\n')
    return '\n\n'.join(
        itertools.chain(['WEBVTT'],
                        (convert_cue(cue) for cue in cues)))


def serve(port, video_path, vtt_data, interface='', growable=False):
    fileFactory = GrowableFile if growable else File
    root = Resource()
    root.putChild(SUB_PATH.encode('utf-8'),
                  Data(vtt_data, 'text/vtt'))
    root.putChild(VIDEO_PATH.encode('utf-8'),
                  fileFactory(video_path, defaultType=DEFAULT_MIME))
    endpoint = endpoints.TCP4ServerEndpoint(reactor, port, interface=interface)
    endpoint.listen(Site(root, requestFactory=CORSRequest))
    reactor.run()


class CORSRequest(Request):
    def process(self):
        self.setHeader(b'Access-Control-Allow-Origin', b'*')
        super().process()


class GrowableFile(File):
    def getsize(self):
        self.restat()  # Invalidate cache
        return super().getsize()

    def _contentRange(self, offset, size):
        return b'bytes %d-%d/*' % (
            offset, offset + size - 1)


def get_src_ip_addr(dest_addr='8.8.8.8', dest_port=53):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((dest_addr, dest_port))
    src_addr, _src_port = s.getsockname()
    return src_addr


def find_cast(friendly_name=None):
    chromecasts = pychromecast.get_chromecasts()
    return next(cc for cc in chromecasts
                if not friendly_name or
                cc.device.friendly_name == friendly_name)


def start_transcoder(infile):
    tempfile = NamedTemporaryFile(suffix='.mp4', delete=False)
    outfile = tempfile.name
    atexit.register(lambda: os.remove(outfile))
    transcoder = Popen(['ffmpeg',
                        '-y', '-nostdin',
                        '-i', infile,
                        '-preset', 'ultrafast',
                        '-f', 'mp4',
                        '-frag_duration', '3000',
                        '-b:v', TRANSCODER_BITRATE,
                        '-loglevel', 'error',
                        outfile])

    while (os.path.getsize(outfile) < TRANSCODER_BUFSIZE and
           transcoder.poll() is None):
        time.sleep(1)

    return transcoder, outfile


def play(cast, video_url, sub_url=None):
    cast.wait()
    mc = cast.media_controller
    mc.play_media(video_url,
                  DEFAULT_MIME,
                  subtitles=sub_url)
    mc.block_until_active()
    control_loop(cast, mc)


def control_loop(cast, mc):
    # Based on https://github.com/stefanor/chromecastplayer
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.nodelay(True)

    started = False

    try:
        while True:
            c = stdscr.getch()
            if c == curses.ERR:
                time.sleep(1)
            elif c == ord(' '):
                if mc.status.player_state == 'PAUSED':
                    mc.play()
                else:
                    mc.pause()
            elif c == ord('q'):
                mc.stop()
                break
            elif c == curses.KEY_RIGHT:
                mc.seek(mc.status.current_time + 10)
            elif c == curses.KEY_LEFT:
                mc.seek(max(mc.status.current_time - 10, 0))
            elif c == curses.KEY_PPAGE:
                mc.seek(mc.status.current_time + 60)
            elif c == curses.KEY_NPAGE:
                mc.seek(max(mc.status.current_time - 60, 0))
            elif c == curses.KEY_UP:
                cast.set_volume(min(cast.status.volume_level + 0.1, 1))
            elif c == curses.KEY_DOWN:
                cast.set_volume(max(cast.status.volume_level - 0.1, 0))
            if mc.status:
                stdscr.addstr(0, 0, mc.status.player_state)
                stdscr.clrtoeol()
                minutes, seconds = divmod(mc.status.current_time, 60)
                hours, minutes = divmod(minutes, 60)
                stdscr.addstr(1, 0, "%02i:%02i:%02i"
                                    % (hours, minutes, seconds))
                idle_state = mc.status.player_state == 'IDLE'
                if not idle_state:
                    started = True
                if started and idle_state:
                    break
                mc.update_status()
            stdscr.move(2, 0)
            stdscr.refresh()
    finally:
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--video', required=True,
                        help='Video file')
    parser.add_argument('-t', '--transcode', action='store_true',
                        help='Transcode to mp4 using ffmpeg')
    parser.add_argument('-g', '--growable', action='store_true',
                        help='Use if file is not completely downloaded yet')
    parser.add_argument('-s', '--subtitles',
                        help='Subtitle file (.vtt or .srt)')
    parser.add_argument('-p', '--port', type=int, default=7000,
                        help='Port to listen')
    parser.add_argument('-i', '--ip',
                        help='IPv4 address to listen')
    parser.add_argument('-d', '--device',
                        help='ChromeCast device name')
    args = parser.parse_args()

    cast = find_cast(friendly_name=args.device)

    port = args.port
    ip = args.ip or get_src_ip_addr()
    subtitles = args.subtitles and read_sub(args.subtitles)

    video = args.video
    growable = args.growable or args.transcode
    transcoder = None

    if args.transcode:
        transcoder, video = start_transcoder(video)

    base_url = 'http://{}:{}'.format(ip, port)
    video_url = '{}/{}'.format(base_url, VIDEO_PATH)
    sub_url = subtitles and '{}/{}'.format(base_url, SUB_PATH)

    server = Process(target=serve,
                     args=(port,
                           video,
                           subtitles,
                           ip,
                           growable))
    server.start()
    play(cast, video_url, sub_url=sub_url)

    server.terminate()
    if transcoder:
        transcoder.kill()


if __name__ == '__main__':
    main()
