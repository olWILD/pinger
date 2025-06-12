import os
import sys
import json
import time
import statistics
import argparse
import signal
from datetime import datetime
from socket import gethostbyname
from ping3 import ping
 
 
def get_base_dir():
    # If bundled by PyInstaller, use the executable's directory to avoid AppData\Temp
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.dirname(__file__))





def save_results(stats: dict, path: str) -> None:
    entries = []
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = [entries]
        except json.JSONDecodeError:
            entries = []
    entries.append(stats)
    with open(path, 'w') as f:
        json.dump(entries, f, indent=2)
    print(f"Results saved to {path}")



def load_history(path: str, target: str) -> list:
    try:
        with open(path, 'r') as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            entries = [entries]
        return [e for e in entries if e.get('target') == target]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def print_comparison(current: dict, history: list) -> None:
    if not history:
        print("No previous data for comparison.")
        return
    print("\n=== Historical Comparison ===")
    for idx, prev in enumerate(history, 1):
        print(f"\nComparison #{idx} ({prev['timestamp']}):")
        for field in ['loss_percent', 'min', 'max', 'avg']:
            cur = current.get(field)
            old = prev.get(field)
            if cur is None or old is None:
                print(f"{field.replace('_', ' ').title()}: No data available.")
            else:
                diff = cur - old
                unit = '%' if field == 'loss_percent' else 'ms'
                print(f"{field.replace('_', ' ').title()}: {old:.2f}{unit} -> {cur:.2f}{unit} ({diff:+.2f}{unit})")


def print_current_results(stats: dict) -> None:
    print("\n=== Current Test Results ===")
    print(f"Target: {stats['target']}")
    print(f"Timestamp: {stats['timestamp']}")
    print(f"Packets: Sent={stats['sent']}, Received={stats['received']}")
    print(f"Packet Loss: {stats['loss_percent']:.1f}%")
    if stats['min'] is not None:
        print(f"Latency: Min={stats['min']:.2f}ms, Max={stats['max']:.2f}ms, Avg={stats['avg']:.2f}ms")
    else:
        print("Latency: No data available.")

# -- Graceful interrupt handler --
save_on_interrupt = {'stats': None, 'save_path': None, 'history': None}

def sigint_handler(signum, frame):
    current = save_on_interrupt.get('stats')
    if current:
        print("\nInterrupted by user. Saving results...")
        save_results(current, save_on_interrupt['save_path'])
        print_comparison(current, save_on_interrupt['history'])
        print_current_results(current)
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)

# -- Interactive validators --
def validate_int(prompt, default=None, min_value=1):
    val = input(prompt).strip()
    if not val:
        return default
    if val.isdigit() and int(val) >= min_value:
        return int(val)
    print(f"Invalid input, using default {default}.")
    return default


def validate_float(prompt, default):
    val = input(prompt).strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        print(f"Invalid input, using default {default}.")
        return default


def validate_filename(prompt, default):
    name = input(prompt).strip()
    if not name:
        return default
    if '/' in name or '\0' in name:
        print(f"Invalid filename, using default {default}.")
        return default
    if not name.lower().endswith('.json'):
        name += '.json'
    return name


def validate_directory(prompt):
    path = input(prompt).strip()
    if not path:
        return get_base_dir()
    if os.path.isdir(path):
        return path
    print(f"Directory does not exist, using script directory.")
    return get_base_dir()

# -- Main ping logic using ping3 with interim stats update --
def run_ping(target: str, count: int, timeout: float, packet_size: int) -> dict:
    times, lost, sent = [], 0, 0

    def update_interim():
        stats = {
            'target': target,
            'timestamp': datetime.now().isoformat(),
            'sent': sent,
            'received': sent - lost,
            'loss_percent': (lost / sent) * 100 if sent > 0 else 100
        }
        if times:
            stats.update({'min': min(times), 'max': max(times), 'avg': statistics.mean(times)})
        else:
            stats.update({'min': None, 'max': None, 'avg': None})
        save_on_interrupt['stats'] = stats

    try:
        if count is None:
            while True:
                result = ping(target, timeout=timeout, size=packet_size)
                sent += 1
                if result is None:
                    print("Request timed out.")
                    lost += 1
                else:
                    ms = result * 1000
                    print(f"Reply from {target}: time={ms:.2f}ms")
                    times.append(ms)
                update_interim()
                time.sleep(1)
        else:
            for _ in range(count):
                result = ping(target, timeout=timeout, size=packet_size)
                sent += 1
                if result is None:
                    print("Request timed out.")
                    lost += 1
                else:
                    ms = result * 1000
                    print(f"Reply from {target}: time={ms:.2f}ms")
                    times.append(ms)
                update_interim()
                time.sleep(1)
    except KeyboardInterrupt:
        pass

    # --- Granted final stats ---
    final_stats = {
        'target': target,
        'timestamp': datetime.now().isoformat(),
        'sent': sent,
        'received': sent - lost,
        'loss_percent': (lost / sent) * 100 if sent > 0 else 100
    }
    if times:
        final_stats.update({'min': min(times), 'max': max(times), 'avg': statistics.mean(times)})
    else:
        final_stats.update({'min': None, 'max': None, 'avg': None})
    save_on_interrupt['stats'] = final_stats
    return final_stats

# -- Argument parsing --
def parse_args():
    p = argparse.ArgumentParser(description='Ping tool using ping3 with history and stats')
    p.add_argument('target', nargs='?', help='Target host or IP')
    p.add_argument('-c', '--count', type=int, default=None, help='Packets to send')
    p.add_argument('-t', '--timeout', type=float, default=4.0, help='Timeout per ping')
    p.add_argument('-s', '--packet-size', type=int, default=56, help='ICMP payload size')
    p.add_argument('-o', '--output', default='ping_history.json', help='Output JSON file')
    p.add_argument('-d', '--directory', default=None, help='Output directory')
    p.add_argument('-C', '--compare', default=None, help='Comparison JSON file')
    return p.parse_args()


def main():
    args = parse_args()
    # interactive if no target
    if not args.target:
        print("For help rin pinger.py/.exe -h")
        args.target = input("Enter host to ping (or Enter to exit): ").strip()
        if not args.target:
            print("Exiting.")
            sys.exit(0)
        args.count = validate_int("Number of packets (empty=continuous): ", default=None)
        args.timeout = validate_float(f"Timeout in seconds (default {args.timeout}): ", default=args.timeout)
        args.packet_size = validate_int(f"Packet size bytes (default {args.packet_size}): ", default=args.packet_size)
        args.output = validate_filename(f"Results filename (default {args.output}): ", default=args.output)
        args.directory = validate_directory("Directory to save (default script dir): ")
        args.compare = validate_filename(f"Comparison filename (default same): ", default=(args.compare or args.output))

    
    try:
        dest = gethostbyname(args.target)
    except Exception:
        print(f"Error resolving host {args.target}.")
        sys.exit(1)

    base_dir = args.directory or get_base_dir()
    out_file = args.output if args.output.endswith('.json') else args.output + '.json'
    save_path = os.path.join(base_dir, out_file)
    comp = args.compare if args.compare else out_file
    comp = comp if comp.endswith('.json') else comp + '.json'
    comp_path = os.path.join(base_dir, comp)

    history = load_history(comp_path, dest)
    save_on_interrupt.update({'save_path': save_path, 'history': history})

    # --- ping in try/except, for any error to save ---
    try:
        stats = run_ping(dest, args.count, args.timeout, args.packet_size)
    except Exception as e:
        print(f"\nError during pinging: {e}")
        stats = save_on_interrupt.get('stats')
        if stats:
            print("\nAttempting to save partial results due to error...")
            save_results(stats, save_path)
            print_comparison(stats, history)
            print_current_results(stats)
        else:
            print("No stats collected; nothing to save.")
        sys.exit(1)

    print("\nFinal results:")
    save_results(stats, save_path)
    print_comparison(stats, history)
    print_current_results(stats)


if __name__ == '__main__':
    main()
