#!/usr/bin/python3

import logging
import queue
import signal
import subprocess
import sys
import threading

sys.path.append("/etc/argon")

from argonpowerbutton import argonpowerbutton_monitor
from argonregister import argonregister_checksupport
from argonregister import argonregister_initializebusobj
from argonregister import argonregister_setfanspeed
from argonsysinfo import argonsysinfo_getcputemp
from argonsysinfo import argonsysinfo_getmaxhddtemp

CONFIG_FILE = "/etc/argononed.conf"
HDD_CONFIG_FILE = "/etc/argononed-hdd.conf"
DEFAULT_CONFIG = ["65=100", "60=55", "55=30"]
POLL_SECONDS = 30

LOG = logging.getLogger("argononed")
STOP_EVENT = threading.Event()


def configure_logging():
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s %(levelname)s %(name)s: %(message)s",
	)


def get_fanspeed(tempval, configlist):
	for curconfig in configlist:
		tempcfg_raw, fancfg_raw = curconfig.split("=")
		tempcfg = float(tempcfg_raw)
		fancfg = int(float(fancfg_raw))
		if tempval >= tempcfg:
			if fancfg < 1:
				return 0
			if fancfg < 25:
				return 25
			return fancfg
	return 0


def load_config(fname):
	config = []
	try:
		with open(fname, "r", encoding="utf-8") as handle:
			for line in handle:
				entry = line.strip()
				if not entry or entry.startswith("#"):
					continue
				parts = entry.split("=")
				if len(parts) != 2:
					continue
				try:
					temp = float(parts[0])
					speed = int(float(parts[1]))
				except ValueError:
					continue
				if not (0 <= temp <= 100 and 0 <= speed <= 100):
					continue
				config.append("{:5.1f}={}".format(temp, speed))
	except FileNotFoundError:
		return []
	except Exception as exc:
		LOG.warning("Unable to load %s: %s", fname, exc)
		return []

	if config:
		config.sort(reverse=True)
	return config


def load_fan_configs():
	cpu_config = load_config(CONFIG_FILE) or list(DEFAULT_CONFIG)
	hdd_config = load_config(HDD_CONFIG_FILE)
	if not hdd_config:
		hdd_config = []
	return cpu_config, hdd_config


def set_fan_speed(bus, regsupport, speed, prev_speed=0):
	# Kick-start to 100% only when spinning up from stopped to overcome stiction,
	# not on every speed change.
	if speed > 0 and not prev_speed:
		argonregister_setfanspeed(bus, 100, regsupport)
	argonregister_setfanspeed(bus, speed, regsupport)


def run_command(command):
	try:
		subprocess.run(command, check=False)
	except Exception as exc:
		LOG.error("Failed to execute %s: %s", command, exc)


def temp_loop():
	bus = None
	regsupport = False
	prevspeed = None
	while not STOP_EVENT.is_set():
		if bus is None:
			bus = argonregister_initializebusobj()
			if bus is None:
				LOG.warning("I2C bus /dev/i2c-1 is not available yet; retrying in %ss", POLL_SECONDS)
				STOP_EVENT.wait(POLL_SECONDS)
				continue

			try:
				regsupport = argonregister_checksupport(bus)
			except Exception as exc:
				LOG.error("I2C probe failed: %s", exc)
				try:
					bus.close()
				except Exception:
					pass
				bus = None
				STOP_EVENT.wait(POLL_SECONDS)
				continue

			LOG.info("I2C bus initialized. Register mode support: %s", regsupport)

		cpu_config, hdd_config = load_fan_configs()
		cpu_temp = argonsysinfo_getcputemp()
		target_speed = get_fanspeed(cpu_temp, cpu_config)

		hdd_temp = argonsysinfo_getmaxhddtemp()
		if hdd_config:
			target_speed = max(target_speed, get_fanspeed(hdd_temp, hdd_config))

		if prevspeed == target_speed:
			STOP_EVENT.wait(POLL_SECONDS)
			continue

		if prevspeed is not None and target_speed < prevspeed:
			if STOP_EVENT.wait(POLL_SECONDS):
				break

		try:
			set_fan_speed(bus, regsupport, target_speed, prevspeed or 0)
			LOG.info(
				"Applied fan speed %s%% (cpu=%.1fC, hdd=%.1fC)",
				target_speed,
				cpu_temp,
				hdd_temp,
			)
			prevspeed = target_speed
			STOP_EVENT.wait(POLL_SECONDS)
		except Exception as exc:
			LOG.error("Fan write failed: %s", exc)
			try:
				bus.close()
			except Exception:
				pass
			bus = None
			STOP_EVENT.wait(60)


def button_loop():
	event_queue = queue.Queue()
	while not STOP_EVENT.is_set():
		argonpowerbutton_monitor(LOG, event_queue)
		try:
			event = event_queue.get(timeout=1)
		except queue.Empty:
			if STOP_EVENT.wait(5):
				return
			continue

		if event == "REBOOT":
			LOG.warning("Power button requested reboot")
			run_command(["reboot"])
			return
		if event == "SHUTDOWN":
			LOG.warning("Power button requested shutdown")
			run_command(["shutdown", "now", "-h"])
			return


def handle_signal(signum, _frame):
	LOG.info("Received signal %s, stopping", signum)
	STOP_EVENT.set()


def main():
	configure_logging()
	signal.signal(signal.SIGTERM, handle_signal)
	signal.signal(signal.SIGINT, handle_signal)

	LOG.info("Starting Argon ONE daemon")

	fan_thread = threading.Thread(target=temp_loop, name="argon-fan", daemon=True)
	fan_thread.start()

	button_thread = threading.Thread(target=button_loop, name="argon-button", daemon=True)
	button_thread.start()

	while not STOP_EVENT.wait(1):
		pass

	fan_thread.join(timeout=5)
	button_thread.join(timeout=5)
	LOG.info("Argon ONE daemon stopped")


if __name__ == "__main__":
	main()
