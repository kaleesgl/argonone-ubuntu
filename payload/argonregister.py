#!/usr/bin/python3

import os
import time

import smbus

ADDR_ARGONONE = 0x1A
REG_DUTY_CYCLE = 0x80
REG_CONTROL = 0x86


def argonregister_initializebusobj():
	for bus_number in (1,):
		if not os.path.exists(f"/dev/i2c-{bus_number}"):
			continue
		try:
			return smbus.SMBus(bus_number)
		except Exception:
			continue
	return None


def argonregister_checksupport(busobj):
	if busobj is None:
		return False
	try:
		original = argonregister_getbyte(busobj, REG_DUTY_CYCLE)
		test_value = 98 if original >= 99 else original + 1
		argonregister_setbyte(busobj, REG_DUTY_CYCLE, test_value)
		current = argonregister_getbyte(busobj, REG_DUTY_CYCLE)
		argonregister_setbyte(busobj, REG_DUTY_CYCLE, original)
		return current != original
	except Exception:
		return False


def argonregister_getbyte(busobj, register):
	if busobj is None:
		return 0
	return busobj.read_byte_data(ADDR_ARGONONE, register)


def argonregister_setbyte(busobj, register, value):
	if busobj is None:
		return
	busobj.write_byte_data(ADDR_ARGONONE, register, value)
	time.sleep(0.05)


def argonregister_setfanspeed(busobj, speed, regsupport=None):
	if busobj is None:
		return

	speed = max(0, min(100, int(speed)))
	if regsupport is None:
		regsupport = argonregister_checksupport(busobj)

	if regsupport:
		argonregister_setbyte(busobj, REG_DUTY_CYCLE, speed)
	else:
		busobj.write_byte(ADDR_ARGONONE, speed)
		time.sleep(0.05)


def argonregister_signalpoweroff(busobj):
	if busobj is None:
		return

	if argonregister_checksupport(busobj):
		argonregister_setbyte(busobj, REG_CONTROL, 1)
	else:
		busobj.write_byte(ADDR_ARGONONE, 0xFF)
