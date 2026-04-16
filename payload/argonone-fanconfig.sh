#!/bin/bash

set -euo pipefail

daemonconfigfile=/etc/argononed.conf
unitconfigfile=/etc/argonunits.conf
fanmode="CPU"

if [ "${1:-}" = "hdd" ]; then
	daemonconfigfile=/etc/argononed-hdd.conf
	fanmode="HDD"
fi

temperature="C"
if [ -f "$unitconfigfile" ]; then
	# shellcheck disable=SC1090
	. "$unitconfigfile"
fi

write_config() {
	local tempfile rc
	tempfile="$(mktemp)"
	cat >"$tempfile"
	rc=0
	sudo install -m 644 "$tempfile" "$daemonconfigfile" || rc=$?
	rm -f "$tempfile"
	return "$rc"
}

get_number() {
	local curnumber
	read curnumber
	if [ -z "$curnumber" ]; then
		echo "-2"
		return
	fi
	if [[ $curnumber =~ ^[+-]?[0-9]+$ ]]; then
		if [ "$curnumber" -lt 0 ] || [ "$curnumber" -gt 212 ]; then
			echo "-1"
			return
		fi
		echo "$curnumber"
		return
	fi
	echo "-1"
}

echo "------------------------------------------"
echo " Argon Fan Speed Configuration Tool ($fanmode)"
echo "------------------------------------------"
echo "WARNING: This will replace the existing configuration."
echo -n "Press Y to continue:"
read -r -n 1 confirm
echo

if [ "${confirm^^}" != "Y" ]; then
	echo "Cancelled."
	exit 0
fi

while true; do
	echo
	echo "Select fan mode:"
	echo "  1. Always on"
	if [ "$fanmode" = "HDD" ]; then
		if [ "$temperature" = "C" ]; then
			echo "  2. Adjust to temperatures (35C, 40C, and 45C)"
		else
			echo "  2. Adjust to temperatures (95F, 104F, and 113F)"
		fi
	else
		if [ "$temperature" = "C" ]; then
			echo "  2. Adjust to temperatures (55C, 60C, and 65C)"
		else
			echo "  2. Adjust to temperatures (131F, 140F, and 149F)"
		fi
	fi
	echo "  3. Customize temperature cut-offs"
	echo
	echo "  0. Exit"
	echo "NOTE: You can also edit $daemonconfigfile directly"
	echo -n "Enter Number (0-3):"
	newmode="$(get_number)"

	if [ "$newmode" -eq 0 ]; then
		break
	elif [ "$newmode" -eq 1 ]; then
		while true; do
			echo -n "Please provide fan speed (30-100 only):"
			curfan="$(get_number)"
			if [ "$curfan" -ge 30 ] && [ "$curfan" -le 100 ]; then
				write_config <<EOF
# Argon Fan Speed Configuration $fanmode
1=$curfan
EOF
				sudo systemctl restart argononed.service
				echo "Fan always on."
				break
			fi
		done
	elif [ "$newmode" -eq 2 ]; then
		curtemp=55
		maxtemp=70
		if [ "$fanmode" = "HDD" ]; then
			curtemp=35
			maxtemp=50
		fi

		config_lines=()
		while [ "$curtemp" -lt "$maxtemp" ]; do
			while true; do
				displaytemp="$curtemp"
				if [ "$temperature" = "F" ]; then
					displaytemp=$(( (curtemp * 9 / 5) + 32 ))
				fi
				echo -n "$displaytemp$temperature (30-100 only):"
				curfan="$(get_number)"
				if [ "$curfan" -ge 30 ] && [ "$curfan" -le 100 ]; then
					config_lines+=("$curtemp=$curfan")
					break
				fi
			done
			curtemp=$((curtemp + 5))
		done

		{
			echo "# Argon Fan Speed Configuration $fanmode"
			printf '%s\n' "${config_lines[@]}"
		} | write_config
		sudo systemctl restart argononed.service
		echo "Configuration updated."
	elif [ "$newmode" -eq 3 ]; then
		config_lines=()
		while true; do
			echo "(Leave the temperature blank to finish.)"
			echo -n "Provide minimum temperature of $fanmode (in $temperature):"
			curtemp="$(get_number)"
			if [ "$curtemp" -eq -2 ]; then
				break
			fi
			if [ "$curtemp" -lt 0 ]; then
				continue
			fi

			while true; do
				echo -n "Provide fan speed for $curtemp$temperature (30-100):"
				curfan="$(get_number)"
				if [ "$curfan" -eq -2 ]; then
					break 2
				fi
				if [ "$curfan" -ge 30 ] && [ "$curfan" -le 100 ]; then
					break
				fi
			done

			storetemp="$curtemp"
			if [ "$temperature" = "F" ]; then
				storetemp=$(( (curtemp - 32) * 5 / 9 ))
			fi
			config_lines+=("$storetemp=$curfan")
		done

		if [ "${#config_lines[@]}" -gt 0 ]; then
			{
				echo "# Argon Fan Speed Configuration $fanmode"
				printf '%s\n' "${config_lines[@]}"
			} | write_config
			sudo systemctl restart argononed.service
			echo "Configuration updated."
		else
			echo "Cancelled, no data saved."
		fi
	fi
done
