# Usage
check_docker_container.py [-h] -C CONTAINER [-S SOCKET] [-D]

Check container state and perfdatas

optional arguments:
*  -h, --help            show this help message and exit
*  -C CONTAINER, --container CONTAINER  
  * Container name to request (default: None)
*  -S SOCKET, --socket SOCKET  
  * Docker daemon unix socket (default: /var/run/docker.sock)
*  -D, --debug           Debug mode: re raise Exception (do not use in production) (default: False)

# Examples

```
/usr/local/bin/check_docker_container.py --container centreon
OK centreon: Up About an hour | traffic_in=566KBits/s, traffic_out=80KBits/s, memory_usage=560MiB, cpu_usage=4.07%, read_sda=0KiB/s, write_sda=24KiB/s
```

```
/usr/local/bin/check_docker_container.py --container unexistent
CRITICAL: There's no unexistent container
```

```
/usr/local/bin/check_docker_container.py --container phpipam
CRITICAL: Container phpipam is not running: Exited (0) 4 seconds ago
```

```
/usr/local/bin/check_docker_container.py --container phpipam -S /path/to/bad/socket
UNKNOWN: Got exception while running parse_args: Docker socket file does not exist
```

# Usage in NRPE

Declare command like this
```
command[check_docker_container]=/usr/bin/sudo /usr/local/bin/check_docker_container.py --container $ARG1$
```

Of course you need the associated sudo config as well as "dont_blame_nrpe=1" in nrpe.cfg. If using Debian/Ubuntu, this setting is not sufficient, you will have to rebuild the whole NRPE package and provide an additional configure flag to allow arguments.
Otherwise you can create multiple NRPE commands with fixed container name.


# Screenshot

WIP


# TODO

There's some blkio "queued" stats that could be interesting to report as it can help figuring out if a container is stuck on disk I/O.


# Bugs

None yet but only tested on Debian Jessie backports docker servers. Please let me know.
I'd really interresting in getting confirmation it actually handle I/O against multiple disks. If you have a container with multiple volumes attached to different physical disks, please send me an example :-)
