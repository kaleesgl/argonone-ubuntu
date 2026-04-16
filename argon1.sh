#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_DIR="$SCRIPT_DIR/payload"
INSTALLATIONFOLDER="/etc/argon"
CONFIG_FILE=""
REBOOT_REQUIRED=0

log() {
	echo "[argonone] $*"
}

warn() {
	echo "[argonone] WARNING: $*" >&2
}

fail() {
	echo "[argonone] ERROR: $*" >&2
	exit 1
}

sudo_install_file() {
	local mode="$1"
	local source="$2"
	local target="$3"
	sudo install -m "$mode" "$source" "$target"
}

detect_boot_config() {
	if [ -f "/boot/firmware/config.txt" ]; then
		CONFIG_FILE="/boot/firmware/config.txt"
	elif [ -f "/boot/config.txt" ]; then
		CONFIG_FILE="/boot/config.txt"
	else
		fail "Unable to find Raspberry Pi boot config.txt"
	fi
}

ensure_exact_line() {
	local line="$1"
	local replace_pattern="${2:-}"

	if sudo grep -Eq "^[[:space:]]*${line}[[:space:]]*$" "$CONFIG_FILE"; then
		return
	fi

	if [ -n "$replace_pattern" ] && sudo grep -Eq "$replace_pattern" "$CONFIG_FILE"; then
		sudo sed -i.bak -E "s|$replace_pattern|${line}|" "$CONFIG_FILE"
	else
		echo "$line" | sudo tee -a "$CONFIG_FILE" >/dev/null
	fi

	REBOOT_REQUIRED=1
	log "Updated $CONFIG_FILE with $line"
}

install_package() {
	local package_name="$1"
	if dpkg-query -W -f='${Status}\n' "$package_name" 2>/dev/null | grep -q "installed"; then
		return
	fi
	sudo apt-get install -y "$package_name"
}

install_first_available_package() {
	local description="$1"
	shift

	local candidate
	for candidate in "$@"; do
		if apt-cache show "$candidate" >/dev/null 2>&1; then
			install_package "$candidate"
			log "Installed $description package: $candidate"
			return
		fi
	done

	fail "Unable to find a package for $description. Tried: $*"
}

verify_payload() {
	local required_files=(
		"$PAYLOAD_DIR/argononed.py"
		"$PAYLOAD_DIR/argonregister.py"
		"$PAYLOAD_DIR/argonsysinfo.py"
		"$PAYLOAD_DIR/argonpowerbutton.py"
		"$PAYLOAD_DIR/argononed.service"
		"$PAYLOAD_DIR/argonone-fanconfig.sh"
	)

	local curfile
	for curfile in "${required_files[@]}"; do
		[ -f "$curfile" ] || fail "Missing payload file: $curfile"
	done
}

install_payload() {
	sudo install -d -m 755 "$INSTALLATIONFOLDER"
	sudo_install_file 755 "$PAYLOAD_DIR/argononed.py" "$INSTALLATIONFOLDER/argononed.py"
	sudo_install_file 644 "$PAYLOAD_DIR/argonregister.py" "$INSTALLATIONFOLDER/argonregister.py"
	sudo_install_file 644 "$PAYLOAD_DIR/argonsysinfo.py" "$INSTALLATIONFOLDER/argonsysinfo.py"
	sudo_install_file 644 "$PAYLOAD_DIR/argonpowerbutton.py" "$INSTALLATIONFOLDER/argonpowerbutton.py"
	sudo_install_file 755 "$PAYLOAD_DIR/argonone-fanconfig.sh" "$INSTALLATIONFOLDER/argonone-fanconfig.sh"
	sudo_install_file 644 "$PAYLOAD_DIR/argononed.service" "/etc/systemd/system/argononed.service"
}

ensure_default_configs() {
	if [ ! -f "/etc/argononed.conf" ]; then
		cat <<'EOF' | sudo tee /etc/argononed.conf >/dev/null
# Argon Fan Speed Configuration (CPU)
55=30
60=55
65=100
EOF
		sudo chmod 644 /etc/argononed.conf
	fi

	if [ ! -f "/etc/argonunits.conf" ]; then
		cat <<'EOF' | sudo tee /etc/argonunits.conf >/dev/null
# Argon Units Configuration
temperature=C
EOF
		sudo chmod 644 /etc/argonunits.conf
	fi
}

install_command_links() {
	sudo install -d -m 755 /usr/local/bin
	sudo ln -sf "$INSTALLATIONFOLDER/argonone-fanconfig.sh" /usr/local/bin/argonone-config
	sudo ln -sf "$INSTALLATIONFOLDER/argonone-fanconfig.sh" /usr/local/bin/argon-config
}

check_os() {
	if [ ! -f "/etc/os-release" ]; then
		fail "Cannot determine operating system"
	fi

	# shellcheck disable=SC1091
	source /etc/os-release
	if [ "${ID:-}" != "ubuntu" ]; then
		warn "This installer is tuned for Ubuntu Server on Raspberry Pi. Detected ID=${ID:-unknown}."
	fi
}

install_dependencies() {
	log "Installing dependencies..."
	sudo apt-get update
	install_package "python3-smbus"
	install_package "i2c-tools"
	install_first_available_package "GPIO Python bindings" "python3-libgpiod" "python3-gpiod"
	if apt-cache show gpiod >/dev/null 2>&1; then
		install_package "gpiod"
	fi
	if apt-cache show smartmontools >/dev/null 2>&1; then
		sudo apt-get install -y smartmontools || warn "Unable to install smartmontools; HDD temperature support will be unavailable."
	fi
}

check_device_nodes() {
	if [ ! -e "/dev/i2c-1" ]; then
		fail "I2C device /dev/i2c-1 is missing. Reboot after the boot config change, then rerun this installer."
	fi

	if ! compgen -G "/dev/gpiochip*" >/dev/null; then
		fail "No /dev/gpiochip* device nodes found. GPIO button handling will not work on this system."
	fi
}

probe_argon_mcu() {
	if command -v i2cdetect >/dev/null 2>&1; then
		if sudo i2cdetect -y 1 2>/dev/null | grep -qi "1a"; then
			log "Detected Argon controller on I2C address 0x1a"
		else
			warn "Did not detect the Argon controller on I2C address 0x1a. Fan control may still fail until the hardware connection is verified."
		fi
	fi
}

start_service() {
	log "Starting argononed.service..."
	sudo systemctl daemon-reload
	sudo systemctl enable argononed.service

	if [ "$REBOOT_REQUIRED" -eq 1 ]; then
		warn "Skipping service start until after reboot because boot configuration changed."
		return
	fi

	if ! sudo systemctl restart argononed.service; then
		warn "Service start failed. Useful diagnostics:"
		warn "  systemctl status argononed"
		warn "  journalctl -u argononed -b"
		exit 1
	fi
}

main() {
	echo "*************"
	echo " Argon Setup "
	echo "*************"

	check_os
	verify_payload
	detect_boot_config
	ensure_exact_line "dtparam=i2c_arm=on" "^[[:space:]]*dtparam=i2c_arm=.*$"

	install_dependencies
	install_payload
	ensure_default_configs
	install_command_links

	if [ "$REBOOT_REQUIRED" -eq 1 ]; then
		warn "Boot configuration changed. Reboot is required before the hardware interfaces may appear."
	fi

	if [ "$REBOOT_REQUIRED" -eq 0 ]; then
		check_device_nodes
		probe_argon_mcu
	fi
	start_service

	echo
	echo "*********************"
	echo " Setup Completed"
	echo "*********************"
	echo "Use 'argonone-config' to configure fan thresholds."
	if [ "$REBOOT_REQUIRED" -eq 1 ]; then
		echo "Reboot the system now if this is the first install or if the service cannot see /dev/i2c-1."
	fi
}

main "$@"
