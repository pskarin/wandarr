#!/usr/bin/python3
import glob
import os
import sys
import signal
from typing import List
import argparse
import subprocess

import wandarr

from wandarr import __version__
from wandarr.agent import Agent
from wandarr.cluster import manage_cluster
from wandarr.config import ConfigFile
from wandarr.ffmpeg import FFmpeg
from wandarr.media import MediaInfo
from wandarr.utils import files_from_file, dump_stats

DEFAULT_CONFIG = os.path.expanduser('~/.wandarr.yml')


def install_sigint_handler():

    def signal_handler(sig, frame):
        print('Process terminated')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)


def init_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"wandarr (ver {__version__})")
    parser.add_argument(dest='files', metavar='filename', nargs='*')
    parser.add_argument('-v', dest='verbose',
                        action='store_true', help='verbose mode')
    parser.add_argument("-i", help="show technical info on files and stop",
                        action="store_true", dest="show_info")
    parser.add_argument("-l", dest="local_only",
                        action="store_true", help="Transcode on local machine only if multiples defined")
    parser.add_argument("-d", dest="output_path",
                        help="output to specified folder")
    parser.add_argument('--dry-run', dest='dry_run',
                        action='store_true', help="Test run, show steps but don't change anything")
    parser.add_argument('-y', dest='configfile_name', default=DEFAULT_CONFIG,
                        action='store', help='Full path to configuration file.  Default is ~/.wandarr.yml')
    parser.add_argument('--agent', dest='agent_mode',
                        action='store_true',
                        help="Start in agent mode on a host and listen for transcode requests from other wandarr.")
    parser.add_argument('-t', dest='template', required=False,
                        action='store', help="Template name to use for transcode jobs")
    parser.add_argument('--hosts', dest='host_override',
                        action='store', help="Only run transcode on given host(s), comma-separated")
    parser.add_argument('--from-file', dest='from_file',
                        action='store', help='Filename that contains list of full paths of files to transcode. Use - for standard input.')
    parser.add_argument("--console", dest="console", action="store_true", required=False, help=argparse.SUPPRESS)
    parser.add_argument("--ping", dest="ping", action="store_true", help="Run ping before SSH on host check")
    parser.add_argument('--overwrite_original', dest='overwrite_source',
                        action='store_true', help='overwrite source file')
    parser.add_argument('--no_skip_existing', dest='no_skip_existing',
                        action='store_true', help='do not skip existing files, instead number output')
    parser.add_argument('--metadata', dest='metadata', action='store_true',
                        help='Copy metadata (default)')
    parser.add_argument('--no-metadata', dest='metadata', action='store_false', 
                        help='Do not copy metadata')
    parser.set_defaults(metadata=True)
    return parser


def finalize_files(files: list, from_file: str):
    if len(files) == 0 and not from_file:
        print('No files - nothing to do')
        sys.exit(0)

    enriched_files = []
    for f in files:
        expanded_files: List = glob.glob(f)  # support wildcards in Windows
        for ef in expanded_files:
            enriched_files.append(ef)
    files = enriched_files

    # if os.name == "nt":
    #     expanded_files: List = glob.glob(files[0])     # handle wildcards in Windows
    #     for f in expanded_files:
    #         files.append(f)

    if from_file:
        tmpfiles = files_from_file(from_file)
        files.extend(tmpfiles)
    return files


def setup_host_override(host_override: str, local_only: bool, configfile: ConfigFile):
    if local_only:
        for config in configfile.hosts.values():
            if config.get("type") != "local":
                config["status"] = "disabled"
        return

    if host_override is not None:
        # disable all other hosts in-memory only - to force encodes to the designated host
        host_list = host_override.split(",")
        for name, this_config in configfile.hosts.items():
            if name not in host_list:
                this_config['status'] = 'disabled'


def load_config(path: str = DEFAULT_CONFIG):
    return ConfigFile(path)


def main():
    start()


def start():
    install_sigint_handler()

    parser = init_argparse()
    args = parser.parse_args()

    files: List = args.files
    wandarr.VERBOSE = args.verbose
    wandarr.SKIP_EXISTING = not args.no_skip_existing
    wandarr.DRY_RUN = args.dry_run
    wandarr.SHOW_INFO = args.show_info
    wandarr.DO_PING = args.ping
    wandarr.COPY_METADATA = args.metadata
    wandarr.OUTPUT_FOLDER = args.output_path
    wandarr.OVERWRITE_SOURCE = args.overwrite_source

    if wandarr.OVERWRITE_SOURCE:
        wandarr.SKIP_EXISTING = False

    if wandarr.SHOW_INFO:
        wandarr.DRY_RUN = True
        args.agent_mode = False

    if wandarr.COPY_METADATA:
        try:
            subprocess.run('exiftool', capture_output=True, shell=False)
        except:
            print("exiftool not found, use switch --no-metadata")
            sys.exit(1)

    if args.agent_mode:
        agent = Agent()
        agent.serve()
        sys.exit(0)

    configfile = load_config(args.configfile_name)

    if args.console:
        configfile.rich = False

    if not wandarr.COPY_METADATA and configfile.settings['metadata']: wandarr.COPY_METADATA = True

    if args.template == '?':
        print("The following templates are available: ", 
              ", ".join(list(configfile.templates.keys())))
        sys.exit(0)

    files = finalize_files(files, args.from_file)
    setup_host_override(args.host_override, args.local_only, configfile)

    if wandarr.SHOW_INFO:
        MediaInfo.show_info(configfile.rich, files, FFmpeg(configfile.ffmpeg_path))
        sys.exit(0)

    if not args.template:
        print("A template is required, use -t ? to show available templates")
        sys.exit(1)

    completed: List = manage_cluster(files, configfile, args.template)
    if len(completed) > 0:
        dump_stats(completed)
    sys.exit(0)


if __name__ == '__main__':
    start()
