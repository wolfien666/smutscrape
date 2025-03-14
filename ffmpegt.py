import subprocess
print(subprocess.check_output(["which", "ffmpeg"]).decode().strip())
