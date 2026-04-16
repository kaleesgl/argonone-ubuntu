#!/usr/bin/python3

import os
import shutil
import subprocess


def argonsysinfo_getcputemp():
	try:
		with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as handle:
			return float(int(handle.readline().strip()) / 1000)
	except Exception:
		return 0.0


def argonsysinfo_gethddtemp():
	hddtempcmd = shutil.which("smartctl") or "/usr/sbin/smartctl"
	if not os.path.exists(hddtempcmd):
		return {}

	try:
		lsblk = subprocess.run(
			["lsblk", "-dn", "-o", "NAME,TYPE"],
			check=True,
			capture_output=True,
			text=True,
		)
	except Exception:
		return {}

	output = {}
	for line in lsblk.stdout.splitlines():
		parts = line.split()
		if len(parts) != 2 or parts[1] != "disk":
			continue
		device = parts[0]
		if not device.startswith(("sd", "hd")):
			continue
		temp = argonsysinfo_getdevhddtemp(device)
		if temp > 0:
			output[device] = temp
	return output


def argonsysinfo_getdevhddtemp(device):
	try:
		command = [
			shutil.which("smartctl") or "/usr/sbin/smartctl",
			"-d",
			"sat",
			"-A",
			f"/dev/{device}",
		]
		result = subprocess.run(command, check=False, capture_output=True, text=True)
		for line in result.stdout.splitlines():
			if "Temperature_Celsius" not in line:
				continue
			fields = line.split()
			if not fields:
				continue
			return float(fields[-1])
	except Exception:
		return -1


def argonsysinfo_getmaxhddtemp():
	max_temp = 0.0
	for _, value in argonsysinfo_gethddtemp().items():
		if value > max_temp:
			max_temp = value
	return max_temp
