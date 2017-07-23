# Command Line ChromeCast media player

chromecastplay is a modern, easy-to-use, full-featured yet simple command line
application for streaming video to a ChromeCast.


# Features

 * Embedded webserver for streaming local files to the ChromeCast.
 * Supports streaming incomplete files. Useful for watching a video still being download by Torrent, MEGAsync or other means.
 * Optional real-time video transcoding when you need to play a video codec not [supported by ChromeCast](https://developers.google.com/cast/docs/media).
 * Supports subtitles supplied by an external file (e.g. SRT format) or embedded in a video file (e.g. MKV format). Automatically converts [several subtitle formats](https://trac.ffmpeg.org/wiki/ExtractSubtitles) to the WebVTT format supported by ChromeCast.
 * Allows the user to control video playback (seek, volume, pause and resume).


# Prerequisites

You need Python3 and pip:

```bash
sudo apt install python3-minimal
wget https://bootstrap.pypa.io/get-pip.py
sudo -H python3 get-pip.py
```

You also need to install some required Python packages:

```bash
sudo -H python3 -m pip install -r pip-requirements.txt
```

In order to use the subtitles and video transcoding features, you need to install [FFmpeg](http://www.ffmpeg.org):

```bash
sudo apt install ffmpeg
```


# Common use cases

## Play a video file

```bash
./chromecastplay.py -v videofile.mp4
```

**Note**: If the video file was encoded with a codec not
[supported by ChromeCast](https://developers.google.com/cast/docs/media),
playback will abort before starting without any further notice. In this case,
try the `-t` option presented below.

## Play a video file encoded with a codec not supported by ChromeCast

```bash
./chromecastplay.py -t -v videofile.mkv
```

**Note**: When real-time transcoding is enabled, the video stream will
be unseekable.

## Play a video file with embedded subtitles

```bash
./chromecastplay.py -v videofile.mkv
```

## Play a video file with external subtitles

```bash
./chromecastplay.py -v videofile.mp4 -s subtitles.srt
```

## Play an incomplete video file (still being downloaded)

```bash
./chromecastplay.py -c -v videofile.mkv
```

**Note**: When playing an incomplete file, the video stream will
be unseekable.

## Full help message

Take a look at the full help message to learn about other command line options:

```bash
./chromecastplay.py -h
```


# Keyboard shortcuts

| Key             | Purpose                 |
|-----------------|-------------------------|
| **Space bar**   | Pause/resume playback   |
| **q**           | Stop playback and quit  |
| **Left arrow**  | Seek back 10 seconds    |
| **Right arrow** | Seek forward 10 seconds |
| **Page down**   | Seek back 60 seconds    |
| **Page up**     | Seek forward 60 seconds |
| **Up arrow**    | Increase volume         |
| **Down arrow**  | Decrease volume         |


# Acknowledges

The playback control feature was based on code from the
[chromecastplayer](https://github.com/stefanor/chromecastplayer/)
project by Stefano Rivera.
