WIP av1an-style chunked encoding with python, requires ffmpeg.

![Example screenshot](screenshot.png)

Do not use for production. Currently very limited.

## Usage

- `-i` `-o`

File input and output.

- `-v` 

Video encoder options. Uses SVT-AV1-HDR default parameters for psy features that were merged into mainline, which can be removed by specifying "reset-all".

- `-a` 

Audio mapping options. Maps highest channel count audio first, uses ffmpeg syntax.
Supports auto bit rate when specifying libopus with "-c:a libopus"

- `-w` 

Worker count. Currently defaults to 1.

- `--low_power true/false`
Use background task policy for workers on macOS (default is false).
- `--ten_bit true/false`
Use 10 bit video encoding (default is true).
- `--hwaccel true/false`
Toggle hardware acceleration (default is true).
- `--auto-crop true/false`
Automatically crop input video (ffmpeg cropdetect).
- `--res WxH`
Resolution limit for video. Preserves aspect ratio and scales by longest axis. 

Example with 4 workers, automatic cropping and 1080p resolution

```sh
   python3 main.py -i "input.mp4" -o "output.mp4" -w 4 --autocrop --res 1920x1080
   ```

