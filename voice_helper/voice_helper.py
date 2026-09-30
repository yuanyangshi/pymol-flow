"""Cross-platform Python voice recorder with silence detection for PyMOL Flow."""

from __future__ import annotations

import math
import os
import struct
import sys
import time
import wave
from pathlib import Path


class VoiceDetector:
    """Detect voice activity and silence intervals."""

    def __init__(self) -> None:
        self.reset_at(0.0)

    def reset_at(self, now: float) -> None:
        self.started_at = now
        self.last_voice_at = 0.0
        self.noise_floor = 0.003
        self.consecutive_voice = 0
        self.heard_speech = False

    def observe(self, level: float, now: float) -> None:
        elapsed = now - self.started_at
        threshold = max(0.014, self.noise_floor * 3.2)
        if elapsed < 0.35 and not self.heard_speech:
            self.noise_floor = min(0.01, max(self.noise_floor, level))
            return
        if level >= threshold:
            self.consecutive_voice += 1
            if self.consecutive_voice >= 2:
                self.heard_speech = True
                self.last_voice_at = now
        else:
            self.consecutive_voice = 0
            if not self.heard_speech:
                self.noise_floor = self.noise_floor * 0.92 + level * 0.08

    def stop_reason_at(self, now: float) -> str | None:
        elapsed = now - self.started_at
        if self.heard_speech and now - self.last_voice_at >= 1.15:
            return "silence"
        if elapsed >= 30.0:
            return "maximum"
        if not self.heard_speech and elapsed >= 8.0:
            return "no_speech"
        return None


def run_self_test() -> None:
    detector = VoiceDetector()
    detector.reset_at(0.0)
    detector.observe(0.1, 0.5)
    detector.observe(0.1, 0.6)
    assert detector.heard_speech, "Speech was not detected"
    assert detector.stop_reason_at(1.5) is None, "Stopped too soon"
    assert detector.stop_reason_at(1.8) == "silence", "Silence was not detected"
    print("voice detector self-test passed")


def record(output_file: str, stop_file: str | None = None) -> int:
    QtCore = None
    QtMultimedia = None
    try:
        from PyQt5 import QtCore, QtMultimedia
    except ImportError:
        try:
            from pymol.Qt import QtCore
            from PyQt5 import QtMultimedia
        except ImportError:
            import importlib
            try:
                pyside2 = importlib.import_module("PySide2")
                QtCore = getattr(pyside2, "QtCore", None)
                QtMultimedia = getattr(pyside2, "QtMultimedia", None)
            except Exception:
                pass

    if QtCore is None or QtMultimedia is None:
        sys.stderr.write("QtMultimedia is required for voice recording.\n")
        sys.stderr.flush()
        return 1

    app = QtCore.QCoreApplication.instance()
    owns_app = False
    if app is None:
        app = QtCore.QCoreApplication(sys.argv)
        owns_app = True

    default_device = QtMultimedia.QAudioDeviceInfo.defaultInputDevice()
    if default_device.isNull():
        sys.stderr.write("No microphone input device is available.\n")
        sys.stderr.flush()
        return 1

    fmt = QtMultimedia.QAudioFormat()
    fmt.setSampleRate(16000)
    fmt.setChannelCount(1)
    fmt.setSampleSize(16)
    fmt.setCodec("audio/pcm")
    fmt.setByteOrder(QtMultimedia.QAudioFormat.LittleEndian)
    fmt.setSampleType(QtMultimedia.QAudioFormat.SignedInt)

    if not default_device.isFormatSupported(fmt):
        fmt = default_device.nearestFormat(fmt)

    sample_rate = fmt.sampleRate()
    channel_count = fmt.channelCount()
    sample_size = fmt.sampleSize()
    sample_type = fmt.sampleType()

    if sample_rate <= 0 or channel_count <= 0:
        sys.stderr.write("No supported microphone input format is available.\n")
        sys.stderr.flush()
        return 1

    audio_input = QtMultimedia.QAudioInput(default_device, fmt)
    io_dev = audio_input.start()
    if not io_dev:
        sys.stderr.write("Could not start microphone recording.\n")
        sys.stderr.flush()
        return 1

    detector = VoiceDetector()
    detector.reset_at(time.monotonic())

    all_raw_data = bytearray()
    stopping = False

    # Signal that recording has started
    print("recording")
    sys.stdout.flush()

    timer = QtCore.QTimer()

    def finish(reason: str):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        timer.stop()
        audio_input.stop()

        if reason == "no_speech":
            sys.stderr.write("No speech detected. Click the microphone and try again.\n")
            sys.stderr.flush()
            if owns_app:
                app.exit(1)
            return

        try:
            temp_path = output_file + ".tmp"
            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(channel_count)
                wf.setsampwidth(max(1, sample_size // 8))
                wf.setframerate(sample_rate)
                wf.writeframes(all_raw_data)
            if os.path.exists(output_file):
                os.remove(output_file)
            os.replace(temp_path, output_file)
        except Exception as exc:
            sys.stderr.write(f"Could not write microphone audio: {exc}\n")
            sys.stderr.flush()
            if owns_app:
                app.exit(1)
            return

        print("done")
        sys.stdout.flush()
        if owns_app:
            app.exit(0)

    def pump():
        if stopping:
            return
        now = time.monotonic()

        # Check manual stop file
        if stop_file and os.path.exists(stop_file):
            finish("manual")
            return

        # Read available audio bytes
        chunk = bytes(io_dev.readAll())
        if chunk:
            all_raw_data.extend(chunk)
            if sample_size == 16 and sample_type == QtMultimedia.QAudioFormat.SignedInt:
                usable = len(chunk) - (len(chunk) % 2)
                if usable >= 2:
                    sample_count = usable // 2
                    unpacked = struct.unpack(f"<{sample_count}h", chunk[:usable])
                    sum_sq = sum((s / 32768.0) ** 2 for s in unpacked)
                    rms = math.sqrt(sum_sq / sample_count)
                    detector.observe(rms, now)
            else:
                detector.observe(0.05, now)

        reason = detector.stop_reason_at(now)
        if reason:
            finish(reason)

    timer.setInterval(50)
    timer.timeout.connect(pump)
    timer.start()

    if owns_app:
        return app.exec_()
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        run_self_test()
        return 0

    if len(sys.argv) not in (2, 3):
        sys.stderr.write("Usage: voice_helper.py <output.wav> [stop-file]\n")
        sys.stderr.flush()
        return 1

    output_path = sys.argv[1]
    stop_path = sys.argv[2] if len(sys.argv) == 3 else None
    return record(output_path, stop_path)


if __name__ == "__main__":
    sys.exit(main())
