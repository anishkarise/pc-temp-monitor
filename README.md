# PC Temp Monitor

A lightweight web dashboard that displays CPU and GPU temperatures in real time.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 in your browser. The dashboard refreshes every 2 seconds.

## How it detects temperatures

### CPU

| OS | Method |
|----|--------|
| Windows | WMI (`MSAcpi_ThermalZoneTemperature`, `Win32_PerfFormattedData_Counters_ThermalZoneInformation`), `wmic` |
| Linux | `/sys/class/thermal/thermal_zone*/temp`, `sensors -u` |
| macOS | `osx-cpu-temp`, `ioreg` (AppleSMC), `istats` |

### GPU

| GPU | Method |
|-----|--------|
| NVIDIA (all OS) | `nvidia-smi --query-gpu=temperature.gpu` |
| AMD (Linux) | `/sys/class/drm/*/device/hwmon/*/temp1_input` |
| AMD (Windows) | `amd-smi metric --temperature`, WMI GPU counters |
| Intel (Linux) | `/sys/class/drm/*/device/hwmon/*/temp1_input` |
| Apple (macOS) | `system_profiler SPDisplaysDataType` |

If a temperature source requires extra tools that aren't installed, the card shows `N/A` instead of crashing.

## Notes

- Windows: some WMI classes need admin rights or may be absent on certain builds — the code falls back through multiple approaches automatically.
- Linux: for `sensors` support, install `lm-sensors` (`sudo apt install lm-sensors` / `sudo pacman -S lm_sensors`).
- macOS: `osx-cpu-temp` is a [third-party tool](https://github.com/lavoiesl/osx-cpu-temp) that provides CPU temperature without sudo.
- The server binds to `0.0.0.0:5000` by default. For a production setup, use a proper WSGI server behind a reverse proxy.
