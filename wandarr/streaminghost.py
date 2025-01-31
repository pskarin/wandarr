import os
import datetime
import shutil
import traceback
from queue import Queue
from tempfile import gettempdir

import wandarr
from wandarr.base import ManagedHost, RemoteHostProperties, EncodeJob
from wandarr.utils import filter_threshold, run, get_local_os_type


class StreamingManagedHost(ManagedHost):
    """Implementation of a streaming host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue):
        super().__init__(hostname, props, queue)

    #
    # initiate tests through here to avoid a new thread
    #
    def testrun(self):
        self.go()

    #
    # normal threaded entry point
    #
    def run(self):
        if self.host_ok():
            self.go()

    def go(self):

        ssh_cmd = [wandarr.SSH, self.props.user + '@' + self.props.ip]

        #
        # Keep pulling items from the queue until done. Other threads will be pulling from the same queue
        # if multiple hosts configured on the same cluster.
        #
        while not self.queue.empty():
            try:
                job: EncodeJob = self.queue.get()
                in_path = job.in_path

                #
                # Convert escaped spaces back to normal. Typical for bash to escape spaces and special characters
                # in filenames.
                #
                in_path = in_path.replace('\\ ', ' ')

                #
                # calculate full input and output paths
                #
                remote_working_dir = self.props.working_dir
                remote_in_path = os.path.join(remote_working_dir, os.path.basename(in_path))
                namenoext = '.'.join(os.path.basename(in_path).split('.')[0:-1])
                remote_out_path = os.path.join(remote_working_dir, namenoext + '.tmp' + job.template.extension())
                infolder = os.path.dirname(in_path)
                outfolder = wandarr.OUTPUT_FOLDER
                # Determine output file
                if not outfolder:
                    outfolder = infolder
                else:
                    if not os.path.exists(outfolder):
                        os.makedirs(outfolder)

                if wandarr.OVERWRITE_SOURCE:
                    out_path = os.path.join(outfolder, namenoext+job.template.extension())
                    if os.path.exists(out_path) and wandarr.SKIP_EXISTING:
                        self.log(f'skipping existing file {out_path}')
                        continue
                else:
                    out_path = os.path.join(outfolder, namenoext+f'.wandarr-{job.template.name()}{job.template.extension()}')
                    if os.path.exists(out_path) and wandarr.SKIP_EXISTING:
                        self.log(f'skipping existing file {out_path}')
                        continue
                    cnt = 1
                    while os.path.exists(out_path):
                        out_path = os.path.join(outfolder, namenoext+f'.wandarr-{job.template.name()}-{cnt}{job.template.extension()}')
                        cnt += 1

                if out_path == in_path and not wandarr.OVERWRITE_SOURCE:
                    self.log(f'refusing to overwrite original file')
                    continue

                #
                # build remote commandline
                #
                video_options = self.video_cli.split(" ")

                stream_map = super().map_streams(job)

                cmd = ['-y', *job.template.input_options_list(), '-i', self.converted_path(remote_in_path),
                       *video_options,
                       *job.template.output_options_list(), *stream_map,
                       self.converted_path(remote_out_path)]
                cli = [*ssh_cmd, *cmd]

                basename = os.path.basename(job.in_path)

                super().dump_job_info(job, cli)

                opts_only = [*job.template.input_options_list(), *video_options,
                             *job.template.output_options_list(), *stream_map]
                print(f"{basename} -> ffmpeg {' '.join(opts_only)}")
                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                      'file': basename,
                                      'speed': '0x',
                                      'comp': '0%',
                                      'completed': 0,
                                      'status': 'Copying'})
                #
                # Copy source file to remote
                #
                target_dir = remote_working_dir
                if self.props.is_windows():
                    # trick to make scp work on the Windows side
                    target_dir = '/' + remote_working_dir

                scp = ['rsync', in_path, self.props.user + '@' + self.props.ip + ':' + target_dir]
                self.log(' '.join(scp))

                code, output = run(scp)
                if code != 0:
                    self.log('Unknown error copying source to remote - media skipped', style="magenta")
                    if wandarr.VERBOSE:
                        self.log(output)
                    continue

                basename = os.path.basename(job.in_path)

                #
                # Start remote
                #
                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                      'file': basename,
                                      'completed': 0,
                                      'status': 'Running'})
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run_remote(wandarr.SSH, self.props.user, self.props.ip, cmd,
                                              super().callback_wrapper(job))
                job_stop = datetime.datetime.now()

                #
                # copy results back to local
                #
                retrieved_copy_name = os.path.join(gettempdir(), os.path.basename(remote_out_path))
                cmd = ['scp', self.props.user + '@' + self.props.ip + ':' + remote_out_path, retrieved_copy_name]
                self.log(' '.join(cmd))

                code, output = run(cmd)

                #
                # process completed, check results and finish
                #
                if code is None:
                    # was vetoed by threshold checker, clean up
                    self.complete(in_path, (job_stop - job_start).seconds)
                    os.remove(retrieved_copy_name)
                    continue

                if code == 0:
                    if not filter_threshold(job.template, in_path, retrieved_copy_name):
#                        self.log(
#                            f'Encoding file {in_path} did not meet minimum savings threshold, skipped')
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(retrieved_copy_name)
                        continue
                    self.complete(in_path, (job_stop - job_start).seconds)

                    if wandarr.COPY_METADATA:
                        exiftool = ['exiftool', '-q', '-overwrite_original', '-tagsfromfile',
                               in_path, retrieved_copy_name]
                        self.log(' '.join(exiftool))

                        code, output = run(exiftool)
                        if code != 0:
                            self.log('Unknown error copying source to remote - media skipped', style="magenta")
                            if wandarr.VERBOSE:
                                self.log(output)
                            continue
                    if wandarr.VERBOSE:
                        self.log(f'moving media to {in_path}')
                    shutil.move(retrieved_copy_name, out_path)

                elif code is not None:
                    self.log(f'error during remote transcode of {in_path}', style="magenta")
                    self.log(f' Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')

                if self.props.is_windows():
                    remote_out_path = remote_out_path.replace("/", "\\")
                    remote_in_path = remote_in_path.replace("/", "\\")
                    if get_local_os_type() == "linux":
                        remote_out_path = remote_out_path.replace(r"\\", "\\")
                        remote_in_path = remote_in_path.replace(r"\\", "\\")
                    self.run_process([*ssh_cmd, f'del "{remote_out_path}"'])
                else:
                    self.run_process([*ssh_cmd, f'rm {remote_out_path}'])

            except Exception:
                print(traceback.format_exc())
            finally:
                self.queue.task_done()
