import subprocess
import platform
import os
from flask import Flask, jsonify, render_template

app = Flask(__name__)


# ── helpers ──────────────────────────────────────────────────────────

def _try_cmd(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _in_range(val, lo=0, hi=120):
    return lo < val < hi


# ── CPU temperature ──────────────────────────────────────────────────

def _cpu_windows():
    # Method 1: MSAcpi_ThermalZoneTemperature (root/wmi)
    out = _try_cmd([
        'powershell', '-NoProfile', '-Command',
        '(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature).CurrentTemperature'
    ])
    if out:
        for line in out.split('\n'):
            line = line.strip()
            if line:
                try:
                    t = round(float(line) / 10 - 273.15, 1)
                    if _in_range(t):
                        return t
                except ValueError:
                    pass

    # Method 2: Win32_PerfFormattedData_Counters_ThermalZoneInformation
    out = _try_cmd([
        'powershell', '-NoProfile', '-Command',
        'Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_Counters_ThermalZoneInformation | Select-Object -ExpandProperty Temperature'
    ])
    if out:
        for line in out.split('\n'):
            line = line.strip()
            if line and line.isdigit():
                val = int(line)
                t = round(val / 10 - 273.15, 1)
                if _in_range(t):
                    return t
                t = round(val / 10, 1)
                if _in_range(t):
                    return t

    # Method 3: wmic fallback
    out = _try_cmd([
        'wmic', '/namespace:\\\\root\\wmi', 'path',
        'MSAcpi_ThermalZoneTemperature', 'get', 'CurrentTemperature', '/value'
    ])
    if out:
        for line in out.split('\n'):
            line = line.strip()
            if line.startswith('CurrentTemperature='):
                try:
                    t = round(float(line.split('=', 1)[1]) / 10 - 273.15, 1)
                    if _in_range(t):
                        return t
                except ValueError:
                    pass

    # Method 4: MS_Processor_Temperature (rare)
    out = _try_cmd([
        'powershell', '-NoProfile', '-Command',
        '(Get-CimInstance -Namespace root/hardware -ClassName MS_Processor_Temperature).Temperature'
    ])
    if out and out.isdigit():
        t = int(out) / 10
        if _in_range(t):
            return t

    return None


def _cpu_linux():
    # Read thermal zones from sysfs (millidegrees Celsius)
    try:
        base = '/sys/class/thermal'
        if os.path.isdir(base):
            zones = sorted(os.listdir(base))
            # Prefer x86_pkg_temp or cpu-thermal zones
            preferred = [z for z in zones if 'x86_pkg' in z or 'cpu-thermal' in z]
            for z in preferred + zones:
                path = os.path.join(base, z, 'temp')
                if os.path.isfile(path):
                    with open(path) as f:
                        val = int(f.read().strip())
                        t = round(val / 1000, 1)
                        if _in_range(t):
                            return t
    except Exception:
        pass

    # Fallback: sensors -u
    out = _try_cmd(['sensors', '-u'])
    if out:
        for line in out.split('\n'):
            line = line.strip().lower()
            if 'temp1_input' in line:
                try:
                    parts = line.split(':')
                    if len(parts) == 2:
                        t = round(float(parts[1].strip()), 1)
                        if _in_range(t):
                            return t
                except ValueError:
                    pass

    return None


def _cpu_darwin():
    # Method 1: osx-cpu-temp (common third-party tool)
    out = _try_cmd(['osx-cpu-temp'])
    if out:
        for line in out.split('\n'):
            line = line.strip()
            if line and line.endswith('°C'):
                try:
                    t = float(line.rstrip('°C').strip())
                    if _in_range(t):
                        return round(t, 1)
                except ValueError:
                    pass

    # Method 2: ioreg (AppleSMC)
    out = _try_cmd([
        'ioreg', '-l', '-w0', '-r', '-c', 'AppleACPIPlatformExpert'
    ])
    if out:
        for line in out.split('\n'):
            if 'CPU Die Temperature' in line or 'CPU Temperature' in line:
                try:
                    # ioreg output: "CPU Die Temperature" = 45.5
                    val = line.split('=')[-1].strip()
                    t = float(val)
                    if _in_range(t):
                        return round(t, 1)
                except (ValueError, IndexError):
                    pass

    # Method 3: istats (alternative CLI tool)
    out = _try_cmd(['istats', 'cpu', 'temperature', '--value-only'])
    if out:
        try:
            t = float(out.strip().rstrip('°C').strip())
            if _in_range(t):
                return round(t, 1)
        except ValueError:
            pass

    return None


def get_cpu_temp():
    system = platform.system()
    if system == 'Windows':
        return _cpu_windows()
    elif system == 'Linux':
        return _cpu_linux()
    elif system == 'Darwin':
        return _cpu_darwin()
    return None


# ── GPU temperature ──────────────────────────────────────────────────

def _gpu_nvidia():
    out = _try_cmd([
        'nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'
    ])
    if out and out.isdigit():
        val = int(out)
        if _in_range(val):
            return val
    return None


def _gpu_linux():
    # Try DRM hwmon sysfs (AMD amdgpu / Intel i915)
    try:
        base = '/sys/class/drm'
        if os.path.isdir(base):
            for card in sorted(os.listdir(base)):
                hwmon = os.path.join(base, card, 'device', 'hwmon')
                if os.path.isdir(hwmon):
                    for h in sorted(os.listdir(hwmon)):
                        temp_in = os.path.join(hwmon, h, 'temp1_input')
                        name_file = os.path.join(hwmon, h, 'name')
                        if os.path.isfile(temp_in):
                            name = ''
                            if os.path.isfile(name_file):
                                with open(name_file) as f:
                                    name = f.read().strip()
                            if 'amdgpu' in name or 'i915' in name:
                                with open(temp_in) as f:
                                    val = int(f.read().strip())
                                    t = round(val / 1000, 1)
                                    if _in_range(t):
                                        return t
    except Exception:
        pass
    return None


def _gpu_windows_amd():
    # Try AMD SMI CLI (recent AMD drivers include amd-smi)
    out = _try_cmd(['amd-smi', 'metric', '--temperature'])
    if out:
        for line in out.split('\n'):
            line = line.strip().lower()
            if 'temperature' in line or 'edge' in line:
                try:
                    # Parse "edge (temperature): 45.0 C" or similar
                    parts = line.split(':')
                    if len(parts) >= 2:
                        val_str = parts[-1].strip().split()[0]
                        t = float(val_str)
                        if _in_range(t):
                            return round(t, 1)
                except (ValueError, IndexError):
                    pass

    # WMI fallback for AMD/Intel GPUs on Windows
    out = _try_cmd([
        'powershell', '-NoProfile', '-Command',
        'Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapter | Select-Object -ExpandProperty Temperature'
    ])
    if out and out.isdigit():
        val = int(out)
        if _in_range(val):
            return val

    return None


def _gpu_darwin():
    # system_profiler sometimes provides GPU temperature on Apple Silicon
    out = _try_cmd([
        'system_profiler', 'SPDisplaysDataType'
    ])
    if out:
        for line in out.split('\n'):
            line = line.strip().lower()
            if 'temperature' in line:
                try:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        val_str = parts[-1].strip().split()[0]
                        t = float(val_str)
                        if _in_range(t):
                            return round(t, 1)
                except (ValueError, IndexError):
                    pass
    return None


def get_gpu_temp():
    # NVIDIA works on all platforms
    t = _gpu_nvidia()
    if t is not None:
        return t

    system = platform.system()
    if system == 'Windows':
        return _gpu_windows_amd()
    elif system == 'Linux':
        return _gpu_linux()
    elif system == 'Darwin':
        return _gpu_darwin()
    return None


# ── Routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/temps')
def temps():
    cpu = get_cpu_temp()
    gpu = get_gpu_temp()
    return jsonify(cpu=cpu, gpu=gpu)


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
