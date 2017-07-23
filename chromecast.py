import argparse
import socket
import curses
import time
from multiprocessing import Process
import pychromecast
from twisted.web.server import Site, Request
from twisted.web.resource import Resource
from twisted.internet import reactor, endpoints
from twisted.web.static import File, Data


class CORSRequest(Request):
    def process(self):
        self.setHeader(b'Access-Control-Allow-Origin', b'*')
        super().process()


def get_src_ip_addr(dest_addr='8.8.8.8', dest_port=53):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((dest_addr, dest_port))
    src_addr, _src_port = s.getsockname()
    return src_addr


def serve(port, video_path, vtt_data, interface=''):
    root = Resource()
    root.putChild(b'sub',
                  Data(vtt_data, 'text/vtt'))
    root.putChild(b'video',
                  File(video_path, defaultType='video/webm'))
    endpoint = endpoints.TCP4ServerEndpoint(reactor, port, interface=interface)
    endpoint.listen(Site(root, requestFactory=CORSRequest))
    reactor.run()


def play(base_url):
    cast = pychromecast.get_chromecasts()[0]
    cast.wait()
    mc = cast.media_controller
    mc.play_media('%s/video' % base_url, "video/webm")
    mc.block_until_active()
    control_loop(cast, mc)


def control_loop(cast, mc):
    # https://github.com/stefanor/chromecastplayer/blob/master/chromeplay.py
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
    port = 7000
    ip = None
    video_path = 'video.mkv'

    ip = ip or get_src_ip_addr()
    base_url = 'http://%s:%d' % (ip, port)

    server = Process(target=serve,
                     args=(port,
                           video_path,
                           b'',
                           ip))
    server.start()
    play(base_url)
    server.terminate()


if __name__ == '__main__':
    main()
