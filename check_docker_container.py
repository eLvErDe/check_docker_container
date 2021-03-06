#!/usr/bin/python3

import sys
import os
import shutil
import stat
import time
import argparse
import json
from ast import literal_eval
try:
    import docker
except ImportError:
    print('UNKNWON: python3-docker package is not installed')
    sys.exit(3)
from distutils.version import LooseVersion
if LooseVersion(docker.version) < LooseVersion('1.0.0'):
   print('UNKNWON: python3-docker is too old (%s < 1.0.0', docker.version)
   sys.exit(3)
from functools import wraps

STATS_FILE = '/tmp/check_docker_container_py_%s.stats'


# Argument parser
# My own ArgumentParser with single-line stdout output and unknown state Nagios retcode
class NagiosArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stdout.write('UNKNOWN: Bad arguments (see --help): %s\n' % message)
        sys.exit(3)

# Nagios unknown exit decorator in case of TB
debug = False
def tb2unknown(method):
    @wraps(method)
    def wrapped(*args, **kw):
        try:
            f_result = method(*args, **kw)
            return f_result
        except Exception as e:
            print('UNKNOWN: Got exception while running %s: %s' % (method.__name__, e))
            if debug:
                raise
            sys.exit(3)
    return wrapped

# Check if a file is a socket
@tb2unknown
def issocket(path):
    mode = os.stat(path).st_mode
    return stat.S_ISSOCK(mode)

# Arguments handler
@tb2unknown
def parse_args():
    # Raise terminal size, See https://bugs.python.org/issue13041
    os.environ['COLUMNS'] = str(shutil.get_terminal_size().columns)

    argparser = NagiosArgumentParser(description='Check container state and perfdatas', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparser.add_argument('-C', '--container', type=str, required=True, help='Container name to request')
    argparser.add_argument('-S', '--socket',    type=str, default='/var/run/docker.sock', help='Docker daemon unix socket')
    argparser.add_argument('-D', '--debug', action='store_true', help='Debug mode: re raise Exception (do not use in production)')
    args = argparser.parse_args()

    if not os.path.exists(args.socket):
        raise argparse.ArgumentError(None, "Docker socket file does not exist")
    if not issocket(args.socket):
        raise argparse.ArgumentError(None, "Docker socket file is not a socket")
    if not os.access(args.socket, os.R_OK):
        raise argparse.ArgumentError(None, "I don't have read access to docker socket")
    if not os.access(args.socket, os.W_OK):
        raise argparse.ArgumentError(None, "I don't have write access to docker socket")

    return args

@tb2unknown
def get_stats(socket, container):

    if hasattr(docker, "APIClient"):
        docker_cli = docker.APIClient(base_url='unix:/%s' % socket, version='auto')
    else:
        docker_cli = docker.Client(base_url='unix:/%s' % socket, version='auto')

    containers = docker_cli.containers(all=True)
    containers = [ x for x in containers if '/%s' % container in x['Names']  ]
    if not containers:
        print("CRITICAL: There's no %s container" % container)
        sys.exit(2)

    state = containers[0]['Status']
    if not state.startswith('Up '):
        print("CRITICAL: Container %s is not running: %s" % (container, state))
        sys.exit(2)

    # I should be able to use stream=False but it doesn't seem to work properly
    stats = docker_cli.stats(container)
    for x in stats:
        stats = json.loads(str(x, 'utf-8'))
        break

    now = int(round(time.time()))

    memory_usage_mb = int(round(stats['memory_stats']['usage'] / 1000 / 1000))

    # Newer dockerd
    # TODO FIXME: Handle multiple interfaces
    if 'networks' in stats:
        network_in_kb_counter = int(round(stats['networks']['eth0']['rx_bytes'] / 1024))
        network_out_kb_counter = int(round(stats['networks']['eth0']['tx_bytes'] / 1024))
    else:
        network_in_kb_counter = int(round(stats['network']['rx_bytes'] / 1024))
        network_out_kb_counter = int(round(stats['network']['tx_bytes'] / 1024))

    container_cpu_cycles_counter = int(round(stats['cpu_stats']['cpu_usage']['total_usage']))
    total_cpu_cycles_counter =  int(round(stats['cpu_stats']['system_cpu_usage']))

    io_kb_counters = {}
    try:
        io_service_bytes_recursive = stats['blkio_stats']['io_service_bytes_recursive']
        for io_stat in io_service_bytes_recursive:
            op = io_stat['op'].lower()
            if op not in [ 'read', 'write' ]:
                continue
            value = int(round(io_stat['value'] / 1024))
            major = io_stat['major']
            minor = io_stat['minor']
            device = os.path.basename(os.path.realpath(os.path.join('/sys/dev/block', '%s:%s' % (major, minor))))
            io_kb_counters['%s_%s' % (op, device)] = value
    except KeyError:
        pass

    # TODO FIXME
    # Handle io_queue_recursive

    statuses = { 'timestamp': now,
                 'network_in_kb_counter': network_in_kb_counter,
                 'network_out_kb_counter': network_out_kb_counter,
                 'container_cpu_cycles_counter': container_cpu_cycles_counter,
                 'total_cpu_cycles_counter': total_cpu_cycles_counter,
                 'io_kb_counters': io_kb_counters,
               }

    status_file = '/tmp/check_docker_container_py_%s.stats' % container

    if os.path.exists(status_file):
        with open(status_file, 'r+') as previous_status_fh:
            previous_statuses = literal_eval(previous_status_fh.read())
            previous_status_fh.seek(0)
            previous_status_fh.write(str(statuses))
            previous_status_fh.truncate()
    else:
        with open(status_file, 'w') as previous_status_fh:
            previous_status_fh.seek(0)
            previous_status_fh.write(str(statuses))
            previous_status_fh.truncate()
        raise Exception("First executation, creating buffer...")

    # Compute stats with previous and current values
    now = int(statuses['timestamp'])
    previous_now = int(previous_statuses['timestamp'])
    network_in_kb_delta = statuses['network_in_kb_counter'] - previous_statuses['network_in_kb_counter']
    network_out_kb_delta = statuses['network_out_kb_counter'] - previous_statuses['network_out_kb_counter']
    network_in_kb = int(round(network_in_kb_delta * 8 / (now - previous_now)))
    network_out_kb = int(round(network_out_kb_delta * 8 / (now - previous_now)))
    container_cpu_cycles_delta = statuses['container_cpu_cycles_counter'] - previous_statuses['container_cpu_cycles_counter']
    total_cpu_cycles_delta = statuses['total_cpu_cycles_counter'] - previous_statuses['total_cpu_cycles_counter']
    cpu_percentage = round(container_cpu_cycles_delta / total_cpu_cycles_delta * 100, 2)

    output = 'OK %s: %s | traffic_in=%dKBits/s traffic_out=%dKBits/s memory_usage=%dMiB cpu_usage=%.2f%%' % (container, state, network_in_kb, network_out_kb, memory_usage_mb, cpu_percentage)

    # Dynamic list of IO counters
    for io_counter in statuses['io_kb_counters'].keys():
        # Weird stuff, new drive attached ?
        if not 'io_kb_counters' in previous_statuses or not io_counter in previous_statuses['io_kb_counters']:
            raise Exception("New IO counter %s found, creating buffer..." % io_counter)
        else:
            io_counter_delta = statuses['io_kb_counters'][io_counter] - previous_statuses['io_kb_counters'][io_counter]
            io_counter_kb = int(round(io_counter_delta / (now - previous_now)))
            output += ' %s=%sKiB/s' % (io_counter, io_counter_kb)
    print(output.strip())
    sys.exit(0)


if __name__ == "__main__":
    config = parse_args()
    debug = config.debug
    get_stats(config.socket, config.container)
