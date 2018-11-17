#!/usr/bin/env python3
import itertools
import argparse
import socket
import curses
import time
from multiprocessing import Process
from subprocess import Popen, PIPE, DEVNULL
import pychromecast
import chardet
from twisted.web import http
from twisted.web.server import Site, Request, NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.internet import reactor, endpoints
from twisted.web.static import File, Data, NoRangeStaticProducer
from twisted.python.compat import networkString


VIDEO_PATH = 'video'
SUB_PATH = 'sub'
DEFAULT_MIME = 'video/mp4'
DEFAULT_BITRATE = '6000k'


def to_webvtt(sub_file, video_file=None):
    encoding = None
    if sub_file:
        encoding = detect_encoding(sub_file)
    sub_transcoder = Popen(['ffmpeg',
                            '-y', '-nostdin'] +
                           (['-sub_charenc', encoding] if encoding else []) +
                           ['-i', sub_file or video_file,
                            '-map', 's?',
                            '-f', 'webvtt',
                            '-loglevel', 'error',
                            '-'],
                           stdout=PIPE,
                           stderr=DEVNULL)
    return sub_transcoder.stdout.read()


def detect_encoding(filename):
    with open(filename, 'rb') as f:
        result = chardet.detect(f.read())
        return result['encoding']


def serve(port, video_path, vtt_data, interface='',
          chunked=False, transcode_bitrate=None):
    if transcode_bitrate:
        video = ChunkedPipe(get_transcoder(video_path, transcode_bitrate))
    elif chunked:
        video = ChunkedFile(video_path,
                            defaultType=DEFAULT_MIME)
    else:
        video = File(video_path, defaultType=DEFAULT_MIME)

    root = Resource()
    root.putChild(SUB_PATH.encode('utf-8'), Data(vtt_data, 'text/vtt'))
    root.putChild(VIDEO_PATH.encode('utf-8'), video)
    endpoint = endpoints.TCP4ServerEndpoint(reactor, port, interface=interface)
    endpoint.listen(Site(root, requestFactory=CORSRequest))
    reactor.run()


class CORSRequest(Request):
    def process(self):
        self.setHeader(b'Access-Control-Allow-Origin', b'*')
        super().process()


class ChunkedFile(File):
    def makeProducer(self, request, fileForReading):
        self._setContentHeaders(request)
        request.setResponseCode(http.OK)
        return NoRangeStaticProducer(request, fileForReading)

    def render_GET(self, request):
        res = super().render_GET(request)
        request.responseHeaders.removeHeader(b'accept-ranges')
        request.responseHeaders.removeHeader(b'content-length')
        return res


class ChunkedPipe(ChunkedFile):
    def __init__(self, fileForReading, defaultType=DEFAULT_MIME):
        Resource.__init__(self)
        self.fileForReading = fileForReading
        self.type = self.defaultType = defaultType

    def render_GET(self, request):
        if request.method == b'HEAD':
            self._setContentHeaders(request)
            return b''
        producer = self.makeProducer(request, self.fileForReading)
        producer.start()
        return NOT_DONE_YET

    def _setContentHeaders(self, request, size=None):
        if self.type:
            request.setHeader(b'content-type', networkString(self.type))


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


def get_transcoder(infile, video_bitrate):
    transcoder = Popen(['ffmpeg',
                        '-y', '-nostdin',
                        '-i', infile,
                        '-preset', 'ultrafast',
                        '-f', 'mp4',
                        '-frag_duration', '3000',
                        '-b:v', video_bitrate,
                        '-loglevel', 'error',
                        '-vcodec', 'h264',
                        '-acodec', 'aac',
                        '-'],
                       stdout=PIPE)
    return transcoder.stdout


def play(cast, video_url, sub_url=None, unseekable=False):
    cast.wait()
    mc = cast.media_controller
    mc.play_media(video_url,
                  DEFAULT_MIME,
                  subtitles=sub_url)
    mc.block_until_active()
    control_loop(cast, mc, unseekable=unseekable)


def control_loop(cast, mc, unseekable=False):
    # Based on https://github.com/stefanor/chromecastplayer
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.nodelay(True)

    started = False

    try:
        while True:
            try:
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
                elif c == curses.KEY_RIGHT and not unseekable:
                    mc.seek(mc.status.current_time + 10)
                elif c == curses.KEY_LEFT and not unseekable:
                    mc.seek(max(mc.status.current_time - 10, 0))
                elif c == curses.KEY_PPAGE and not unseekable:
                    mc.seek(mc.status.current_time + 60)
                elif c == curses.KEY_NPAGE and not unseekable:
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
            except pychromecast.error.UnsupportedNamespace:
                pass
    finally:
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--video', required=True,
                        help='Video file')
    parser.add_argument('-c', '--chunked', action='store_true',
                        help='Unseekable stream using chunked-encoding '
                        '(for incomplete files)')
    parser.add_argument('-t', '--transcode', action='store_true',
                        help='Transcode to mp4 using ffmpeg (implies -c)')
    parser.add_argument('-b', '--bitrate',
                        help='Video bitrate for transcoding (implies -t)')
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

    video = args.video
    transcode = args.transcode or args.bitrate
    chunked = transcode or args.chunked
    transcode_bitrate = transcode and (args.bitrate or DEFAULT_BITRATE)
    subtitles = to_webvtt(args.subtitles, video)

    base_url = 'http://{}:{}'.format(ip, port)
    video_url = '{}/{}'.format(base_url, VIDEO_PATH)
    sub_url = subtitles and '{}/{}'.format(base_url, SUB_PATH)

    server = Process(target=serve,
                     args=(port,
                           video,
                           subtitles,
                           ip,
                           chunked,
                           transcode_bitrate))
    server.start()
    play(cast, video_url, sub_url=sub_url, unseekable=chunked)
    server.terminate()


if __name__ == '__main__':
    main()
