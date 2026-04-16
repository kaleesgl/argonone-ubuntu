# Argon ONE Ubuntu

A Linux daemon and control utility for the **Argon ONE Raspberry Pi case** — an active-cooling case with a PWM fan, power button, and hardware MCU. Targets **Ubuntu Server on Raspberry Pi** (Raspberry Pi 4/5).

The official Argon ONE installer targets Raspberry Pi OS only. This project provides a clean, systemd-native alternative for Ubuntu users.

---

## Features

- Fan speed control via temperature thresholds (CPU and optional HDD/SSD)
- Power button support: short press = reboot, longer press = shutdown
- Automatically restarts on failure via systemd
- Interactive TUI for configuring fan curves
- Supports both `python3-libgpiod` (v1) and `python3-gpiod` (v2) GPIO APIs
- Supports both legacy and register-mode Argon MCU firmware

---

## Requirements

| Requirement | Details |
|-------------|---------|
| Hardware | Argon ONE case (M.2 edition supported) |
| Board | Raspberry Pi 4 or 5 |
| OS | Ubuntu Server 22.04 / 24.04 (64-bit) |
| Interface | I2C enabled, GPIO accessible |

---

## Installation

Clone the repository to your Raspberry Pi and run the installer as a regular user (it will use `sudo` when needed):

```bash
git clone https://github.com/your-username/argonone-ubuntu.git
cd argonone-ubuntu
bash argon1.sh
```

The installer will:

1. Detect and enable `dtparam=i2c_arm=on` in your boot config if needed
2. Install Python and GPIO dependencies
3. Copy the daemon and helper files to `/etc/argon/`
4. Create default fan configuration files
5. Enable and start the `argononed` systemd service

> **If this is a fresh Ubuntu installation**, the installer may need to enable I2C in the boot config. In that case it will print a reboot notice — reboot the Pi and run the installer again to complete setup.

---

## Quick-start: configuring the fan

```bash
argonone-config
```

This launches an interactive menu to set your fan curve. You can also edit the config file directly:

```
/etc/argononed.conf
```

Format — one `temperature=fanspeed` pair per line, temperature in °C, fan speed as a percentage (0–100):

```ini
# Argon Fan Speed Configuration (CPU)
55=30
60=55
65=100
```

The daemon re-reads this file on every poll cycle (every 30 seconds), so changes take effect without restarting the service.

---

## HDD/SSD temperature control

If you have a drive in the Argon ONE M.2 slot, you can configure a separate fan curve for it:

```bash
argonone-config hdd
```

This writes to `/etc/argononed-hdd.conf`. When both CPU and HDD curves are configured, the daemon picks the **higher** of the two fan speeds at any given moment.

HDD temperature monitoring requires `smartmontools`. The installer attempts to install it automatically, but it is optional — HDD monitoring is silently skipped if `smartctl` is not available.

---

## Fan speed logic

- Thresholds are evaluated from highest to lowest temperature; the first one where `current_temp >= threshold` wins.
- A fan speed of 0 means off.
- Any non-zero speed below 25% is raised to 25% (minimum effective duty cycle to spin the fan).
- When the fan spins up from stopped, it briefly kicks to 100% to overcome stiction before settling at the target speed.
- Speed only decreases after a full 30-second hysteresis delay, preventing rapid oscillation.

---

## Power button behavior

The Argon ONE power button sends short GPIO pulses. The daemon interprets hold duration:

| Hold time | Action |
|-----------|--------|
| 15–35 ms | Reboot |
| 35–55 ms | Shutdown |

---

## Temperature units

The fan configuration tool reads `/etc/argonunits.conf` to display temperatures in Celsius or Fahrenheit. The config file itself always stores values in Celsius.

```ini
# /etc/argonunits.conf
temperature=C   # or F
```

---

## Service management

```bash
# Status and logs
sudo systemctl status argononed
sudo journalctl -u argononed -f

# Restart after config changes (usually not needed — daemon auto-reloads)
sudo systemctl restart argononed

# Stop / disable
sudo systemctl stop argononed
sudo systemctl disable argononed
```

---

## File layout (after install)

```
/etc/argon/
    argononed.py            Main daemon
    argonregister.py        I2C helpers (MCU at address 0x1A)
    argonsysinfo.py         CPU and HDD temperature readers
    argonpowerbutton.py     GPIO power button monitor
    argonone-fanconfig.sh   Fan curve configuration TUI

/etc/argononed.conf         CPU fan curve
/etc/argononed-hdd.conf     HDD fan curve (optional)
/etc/argonunits.conf        Temperature unit preference

/etc/systemd/system/argononed.service

/usr/local/bin/argonone-config -> /etc/argon/argonone-fanconfig.sh
/usr/local/bin/argon-config    -> /etc/argon/argonone-fanconfig.sh
```

---

## Troubleshooting

### Service fails to start

```bash
sudo journalctl -u argononed -b --no-pager
```

Common causes:

- **I2C not enabled** — check `/boot/firmware/config.txt` for `dtparam=i2c_arm=on`; reboot if you just added it
- **`/dev/i2c-1` missing** — I2C kernel module not loaded; try `sudo modprobe i2c-dev`
- **Argon MCU not detected** — run `sudo i2cdetect -y 1` and look for address `1a`
- **GPIO package missing** — ensure `python3-libgpiod` or `python3-gpiod` is installed

### Fan not spinning

- Confirm the MCU is detected: `sudo i2cdetect -y 1` should show `1a`
- Check the fan curve — the current temperature may be below all thresholds
- Check CPU temp: `cat /sys/class/thermal/thermal_zone0/temp` (divide by 1000 for °C)

### Power button not responding

- Check that `/dev/gpiochip*` devices exist
- Run `sudo gpiofind GPIO4` — it should return a chip and line number
- Check logs for `GPIO monitor initialization failed`

### HDD temperature not showing

- Install `smartmontools`: `sudo apt-get install smartmontools`
- Verify the drive is visible: `lsblk -dn -o NAME,TYPE`
- Test manually: `sudo smartctl -d sat -A /dev/sda`

---

## Development

There is no build step. Edit files in `payload/` and redeploy with the installer.

**Syntax check Python files:**

```bash
python3 -m py_compile payload/argononed.py
python3 -m py_compile payload/argonregister.py
python3 -m py_compile payload/argonsysinfo.py
python3 -m py_compile payload/argonpowerbutton.py
```

**Test on device:**

```bash
bash argon1.sh
sudo journalctl -u argononed -f
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
