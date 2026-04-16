#!/usr/bin/python3

import glob
import os
import subprocess
import time

import gpiod

LINE_SHUTDOWN = 4


def _candidate_chip_paths():
	preferred = []
	try:
		command = ["/usr/bin/gpiofind", "GPIO4"]
		result = subprocess.run(command, check=False, capture_output=True, text=True)
		if result.returncode == 0:
			fields = result.stdout.strip().split()
			if fields:
				chip_name = fields[0]
				if not chip_name.startswith("/dev/"):
					chip_name = f"/dev/{chip_name}"
				preferred.append(chip_name)
	except Exception:
		pass

	for path in ("/dev/gpiochip0", "/dev/gpiochip4"):
		if path not in preferred and os.path.exists(path):
			preferred.append(path)

	for path in sorted(glob.glob("/dev/gpiochip*")):
		if path not in preferred:
			preferred.append(path)

	return preferred


def _line_value(lineobj, lineid=None):
	if lineid is None:
		value = lineobj.get_value()
	else:
		value = lineobj.get_value(lineid)

	if hasattr(gpiod, "line") and hasattr(gpiod.line, "Value"):
		return 0 if value == gpiod.line.Value.INACTIVE else 1
	return 0 if value == 0 else 1


def _request_legacy_events(chip, lineid):
	line = chip.get_line(lineid)
	line.request(consumer="argon", type=gpiod.LINE_REQ_EV_BOTH_EDGES)
	return line


def _monitor_v1(logger, queue):
	last_error = None
	for chippath in _candidate_chip_paths():
		try:
			chip = gpiod.Chip(chippath)
			line = _request_legacy_events(chip, LINE_SHUTDOWN)
		except Exception as exc:
			last_error = exc
			continue

		logger.info("Monitoring power button on %s line %s", chippath, LINE_SHUTDOWN)
		try:
			while True:
				if not line.event_wait(10):
					continue
				event = line.event_read()
				if event.type != gpiod.LineEvent.RISING_EDGE:
					continue

				start = time.monotonic()
				while _line_value(line) == 1:
					time.sleep(0.001)
				hold_ms = (time.monotonic() - start) * 1000

				if 15 <= hold_ms <= 35:
					queue.put("REBOOT")
					return
				if 35 < hold_ms <= 55:
					queue.put("SHUTDOWN")
					return
		finally:
			line.release()
			chip.close()

	if last_error is not None:
		raise last_error
	raise RuntimeError("No usable gpiochip device found for GPIO4")


def _monitor_v2(logger, queue):
	config = {
		LINE_SHUTDOWN: gpiod.LineSettings(
			direction=gpiod.line.Direction.INPUT,
			edge_detection=gpiod.line.Edge.BOTH,
		)
	}

	last_error = None
	for chippath in _candidate_chip_paths():
		try:
			request = gpiod.request_lines(chippath, consumer="argon", config=config)
		except Exception as exc:
			last_error = exc
			continue

		logger.info("Monitoring power button on %s line %s", chippath, LINE_SHUTDOWN)
		with request:
			while True:
				if not request.wait_edge_events(timeout=10):
					continue

				for event in request.read_edge_events():
					if event.event_type != event.Type.RISING_EDGE:
						continue

					start = time.monotonic()
					while _line_value(request, event.line_offset) == 1:
						time.sleep(0.001)
					hold_ms = (time.monotonic() - start) * 1000

					if 15 <= hold_ms <= 35:
						queue.put("REBOOT")
						return
					if 35 < hold_ms <= 55:
						queue.put("SHUTDOWN")
						return

	if last_error is not None:
		raise last_error
	raise RuntimeError("No usable gpiochip device found for GPIO4")


def argonpowerbutton_monitor(logger, queue):
	try:
		if hasattr(gpiod, "request_lines"):
			_monitor_v2(logger, queue)
		else:
			_monitor_v1(logger, queue)
	except Exception as exc:
		logger.error("GPIO monitor initialization failed: %s", exc)
